"""
Integration tests for Row Level Security (RLS) isolation.

Tests verify that hv_app role can only see rows for the user set in
the session variable app.user_id. Requires HV_APP_DB_PASSWORD env var.

PostgreSQL container is NOT exposed externally. We open an SSH tunnel
using the system `ssh` binary (subprocess) through the server, forwarding
to the Docker-internal healthvault_postgres container.

Run:
    HV_APP_DB_PASSWORD=$(grep '^HV_APP_DB_PASSWORD=' .env | cut -d= -f2) \\
      pytest tests/integration/test_rls_isolation.py -m integration -v
"""

import pytest
import os
import socket
import subprocess
import time
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.integration


def _get_postgres_internal_ip():
    """Get the Docker-internal IP of healthvault_postgres container."""
    result = subprocess.run(
        "ssh root@116.203.213.137 \"docker inspect healthvault_postgres --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'\"",
        shell=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    ip = result.stdout.strip()
    if not ip:
        raise RuntimeError(f"Could not get postgres IP. stderr: {result.stderr}")
    return ip


def _find_free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def ssh_tunnel():
    """Open SSH port-forward tunnel: localhost:local_port -> postgres_container:5432."""
    postgres_ip = _get_postgres_internal_ip()
    local_port = _find_free_port()
    proc = subprocess.Popen(
        [
            "ssh",
            "-N",
            "-L",
            f"{local_port}:{postgres_ip}:5432",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ExitOnForwardFailure=yes",
            "root@116.203.213.137",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait briefly for tunnel to establish
    time.sleep(2)
    if proc.poll() is not None:
        raise RuntimeError(f"SSH tunnel process exited early (rc={proc.returncode})")
    yield local_port
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="module")
def hv_app_engine(ssh_tunnel):
    """SQLAlchemy engine connected as hv_app role — RLS-restricted.

    Note: do NOT use isolation_level='AUTOCOMMIT'. SET LOCAL requires a real
    transaction (BEGIN/COMMIT), which conn.begin() provides in default mode.
    """
    pwd = os.environ["HV_APP_DB_PASSWORD"]
    url = f"postgresql://hv_app:{pwd}@127.0.0.1:{ssh_tunnel}/healthvault"
    engine = create_engine(url)
    yield engine
    engine.dispose()


def test_rls_blocks_other_users_meals(hv_app_engine):
    """When session.app.user_id = Sasha (895655), can't see Nika's (485132) nutrition_log rows."""
    with hv_app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_id = '895655'"))
            rows = conn.execute(text("SELECT user_id FROM nutrition_log WHERE user_id = 485132 LIMIT 5")).fetchall()
    assert len(rows) == 0, "Sasha's session shouldn't see Nika's nutrition rows"


def test_rls_allows_own_user_meals(hv_app_engine):
    """When session.app.user_id = Sasha, can see Sasha's nutrition_log rows.

    Requires user 895655 to have at least one row in nutrition_log.
    This is always true in production but may fail in empty test DBs.
    """
    with hv_app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_id = '895655'"))
            rows = conn.execute(text("SELECT user_id FROM nutrition_log WHERE user_id = 895655 LIMIT 5")).fetchall()
    assert len(rows) > 0, (
        "Sasha's session should see her own rows. If this fails, user 895655 has no nutrition_log rows in this DB."
    )


def test_rls_no_session_var_returns_nothing(hv_app_engine):
    """Without setting app.user_id, hv_app should see no rows (NULL bigint cast → no match)."""
    with hv_app_engine.connect() as conn:
        with conn.begin():
            rows = conn.execute(text("SELECT user_id FROM nutrition_log LIMIT 5")).fetchall()
    assert len(rows) == 0, "Without session var, hv_app should see no rows at all"


def test_rls_supplements_blocks_cross_user(hv_app_engine):
    """RLS on supplements_log: Sasha's session can't see other users' rows."""
    with hv_app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET LOCAL app.user_id = '895655'"))
            rows = conn.execute(text("SELECT user_id FROM supplements_log WHERE user_id != 895655 LIMIT 5")).fetchall()
    assert len(rows) == 0, "Sasha's session shouldn't see other users' supplements"
