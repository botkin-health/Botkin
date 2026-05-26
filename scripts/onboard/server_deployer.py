"""Server deployer — scp KB + psql UPDATE с атомарностью и rollback."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class PsqlError(RuntimeError):
    """psql command failed (infrastructure error: container down, network, etc)."""


class UserNotFoundError(RuntimeError):
    """User with given telegram_id does not exist in users table."""


@dataclass(frozen=True)
class ServerConfig:
    host: str
    user: str
    deploy_path: str
    timeout: int = 60  # seconds for ssh/scp commands


SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]


@dataclass(frozen=True)
class DeployResult:
    rows_affected: int


@dataclass(frozen=True)
class UserServerState:
    telegram_id: int
    cohort: str
    pack_name: str
    prompt_length: int
    kb_on_server: bool


def _ssh(cfg: ServerConfig, remote_cmd: str) -> subprocess.CompletedProcess:
    cmd = [
        "ssh",
        *SSH_OPTS,
        f"{cfg.user}@{cfg.host}",
        remote_cmd,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.timeout)


def _scp(cfg: ServerConfig, local_path: Path, remote_path: str) -> subprocess.CompletedProcess:
    cmd = [
        "scp",
        *SSH_OPTS,
        str(local_path),
        f"{cfg.user}@{cfg.host}:{remote_path}",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.timeout)


def _psql(cfg: ServerConfig, sql: str) -> subprocess.CompletedProcess:
    """Запустить psql -t -c <sql> через docker exec на сервере."""
    docker_cmd = f"docker exec healthvault_postgres psql -U healthvault -d healthvault -t -A -c {shlex.quote(sql)}"
    return _ssh(cfg, docker_cmd)


def _kb_remote_path(cfg: ServerConfig, telegram_id: int) -> str:
    """Layout: ``<deploy_path>/data/kb/kb_<tid>.json``. Auto-synced into the
    bot container via the existing ``./data:/app/data`` bind-mount. New users
    no longer require per-file entries in docker-compose.prod.yml."""
    return f"{cfg.deploy_path}/data/kb/kb_{telegram_id}.json"


def upload_kb(*, kb_path: Path, telegram_id: int, cfg: ServerConfig) -> None:
    """Залить kb_<tid>.json на сервер atomic'ом: mkdir + scp в .tmp + mv."""
    final_remote = _kb_remote_path(cfg, telegram_id)
    tmp_remote = f"{final_remote}.tmp"
    kb_dir = final_remote.rsplit("/", 1)[0]

    # Ensure target directory exists (idempotent).
    mkdir = _ssh(cfg, f"mkdir -p {shlex.quote(kb_dir)}")
    if mkdir.returncode != 0:
        raise RuntimeError(f"mkdir failed: {mkdir.stderr or mkdir.stdout}")

    scp = _scp(cfg, kb_path, tmp_remote)
    if scp.returncode != 0:
        raise RuntimeError(f"scp failed: {scp.stderr or scp.stdout}")

    mv = _ssh(cfg, f"mv {shlex.quote(tmp_remote)} {shlex.quote(final_remote)}")
    if mv.returncode != 0:
        # rollback .tmp
        _ssh(cfg, f"rm -f {shlex.quote(tmp_remote)}")
        raise RuntimeError(f"ssh mv failed: {mv.stderr or mv.stdout}")

    # Verify the uploaded file is valid JSON on the server
    check_cmd = f"python3 -c 'import json,sys; json.load(open(sys.argv[1]))' {shlex.quote(final_remote)}"
    verify = _ssh(cfg, check_cmd)
    if verify.returncode != 0:
        # Roll back the broken file
        _ssh(cfg, f"rm -f {shlex.quote(final_remote)}")
        raise RuntimeError(f"Uploaded KB is not valid JSON on server: {verify.stderr or verify.stdout}")


def remove_kb(*, telegram_id: int, cfg: ServerConfig) -> None:
    """Удалить kb_<tid>.json с сервера (для rollback / --unenroll).

    Also cleans up legacy location at deploy_path root if it exists — covers
    the 2026-05-22→05-24 transition when files briefly lived in both spots.
    """
    final_remote = _kb_remote_path(cfg, telegram_id)
    legacy_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json"
    _ssh(cfg, f"rm -f {shlex.quote(final_remote)} {shlex.quote(legacy_remote)}")


def update_user_row(
    *,
    telegram_id: int,
    cohort: str,
    pack_name: str,
    agent_system_prompt: str,
    cfg: ServerConfig,
) -> DeployResult:
    """UPDATE users SET cohort, pack_name, agent_system_prompt WHERE telegram_id."""
    # Escape single quotes in all string fields for SQL
    cohort_escaped = cohort.replace("'", "''")
    pack_escaped = pack_name.replace("'", "''")
    prompt_escaped = agent_system_prompt.replace("'", "''")
    sql = (
        f"UPDATE users SET cohort='{cohort_escaped}', pack_name='{pack_escaped}', "
        f"agent_system_prompt='{prompt_escaped}' "
        f"WHERE telegram_id={telegram_id};"
    )
    result = _psql(cfg, sql)
    if result.returncode != 0:
        raise PsqlError(f"psql failed: {result.stderr or result.stdout}")

    out = result.stdout.strip()
    # Last non-empty line is "UPDATE N"
    last_lines = [line for line in out.splitlines() if line.strip()]
    if not last_lines:
        raise PsqlError(f"psql gave no output for UPDATE: {out!r}")
    last = last_lines[-1]
    rows = int(last.split()[-1]) if last.upper().startswith("UPDATE") else 0
    if rows == 0:
        raise UserNotFoundError(f"UPDATE matched 0 rows — user telegram_id={telegram_id} not found")
    return DeployResult(rows_affected=rows)


def fetch_agent_system_prompt(*, telegram_id: int, cfg: ServerConfig) -> str:
    """Получить полный текст agent_system_prompt из БД. Empty string if NULL."""
    sql = f"SELECT COALESCE(agent_system_prompt, '') FROM users WHERE telegram_id={telegram_id};"
    result = _psql(cfg, sql)
    if result.returncode != 0:
        raise PsqlError(f"psql SELECT prompt failed: {result.stderr or result.stdout}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise UserNotFoundError(f"User telegram_id={telegram_id} not found")
    # psql -t -A returns the value; if prompt has newlines they'll be in the lines
    # But COALESCE ensures we always get at least an empty marker
    return "\n".join(lines)


def fetch_user_state(*, telegram_id: int, cfg: ServerConfig) -> UserServerState:
    """SELECT текущего состояния юзера + проверка наличия kb-файла."""
    sql = (
        f"SELECT telegram_id, cohort, pack_name, "
        f"COALESCE(LENGTH(agent_system_prompt), 0) "
        f"FROM users WHERE telegram_id={telegram_id};"
    )
    result = _psql(cfg, sql)
    if result.returncode != 0:
        raise PsqlError(f"psql SELECT failed: {result.stderr or result.stdout}")
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise UserNotFoundError(f"User telegram_id={telegram_id} not found in users table")
    line = lines[0]
    tid, cohort, pack, prompt_len = line.split("|")

    # Проверка файла на сервере через ssh test -f
    check = _ssh(cfg, f"test -f {shlex.quote(cfg.deploy_path)}/kb_{telegram_id}.json && echo t || echo f")
    kb_on_server = check.stdout.strip() == "t"

    return UserServerState(
        telegram_id=int(tid),
        cohort=cohort,
        pack_name=pack,
        prompt_length=int(prompt_len),
        kb_on_server=kb_on_server,
    )
