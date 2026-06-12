"""Security + характеризующий тест создания бэкапа БД (pg_dump).

Сейчас бэкап строится как `/bin/sh -c "PGPASSWORD='{pw}' pg_dump ... > '{path}'"`
— пароль интерполируется в shell-строку (инъекция при кавычке/$() в пароле).

Характеризующий: при успешном pg_dump эндпоинт возвращает 200 и имя файла.
Security: пароль со spec-символами не попадает в shell-строку; вызов не через
/bin/sh. RED сейчас → GREEN после фикса (subprocess списком аргументов + env).
"""

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

MALICIOUS_PW = "p'; rm -rf / #$(whoami)"


@pytest.fixture
def admin_client(monkeypatch, tmp_path):
    from webhook import admin

    monkeypatch.setattr(admin, "BACKUPS_DIR", tmp_path)
    monkeypatch.setenv("POSTGRES_PASSWORD", MALICIOUS_PW)

    captured = {"calls": []}

    def fake_run(cmd, *args, **kwargs):
        captured["calls"].append({"cmd": cmd, "kwargs": kwargs})
        # Симулируем успешный pg_dump: создаём непустой файл-результат.
        for token in cmd if isinstance(cmd, (list, tuple)) else [cmd]:
            if isinstance(token, str) and token.endswith(".sql.gz"):
                Path(token).write_bytes(b"\x1f\x8b\x08fake-gzip")
        # Если фикс стримит stdout pg_dump в gzip сам — отдадим байты и нулевой код.
        out = tmp_path  # noqa: F841
        for f in tmp_path.iterdir():
            pass
        return subprocess.CompletedProcess(cmd, 0, stdout=b"PGDUMP-BYTES", stderr=b"")

    monkeypatch.setattr(admin.subprocess, "run", fake_run)
    monkeypatch.setattr(admin, "_human", lambda n: f"{n}B", raising=False)

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_auth] = lambda: "admin"
    client = TestClient(app)
    client._captured = captured
    return client


def test_backup_success_returns_filename(admin_client):
    """Характеризующий: успешный бэкап → 200 и .sql.gz имя файла."""
    r = admin_client.post("/admin/api/backups")
    assert r.status_code == 200, r.text
    body = r.json()
    fname = body.get("filename") or body.get("name") or str(body)
    assert ".sql.gz" in str(body) or ".sql.gz" in str(fname)


def test_password_not_interpolated_into_shell(admin_client):
    """Security: пароль со spec-символами НЕ попадает в shell-командную строку,
    и вызов не идёт через /bin/sh -c."""
    admin_client.post("/admin/api/backups")
    calls = admin_client._captured["calls"]
    assert calls, "subprocess.run не вызывался"

    for call in calls:
        cmd = call["cmd"]
        # 1) Не shell-обёртка
        if isinstance(cmd, (list, tuple)):
            assert cmd[0] != "/bin/sh", "бэкап всё ещё запускается через /bin/sh -c"
            # 2) Пароль не сконкатенирован в строку аргумента вместе с pg_dump
            joined = " ".join(str(t) for t in cmd)
        else:
            joined = str(cmd)
        assert MALICIOUS_PW not in joined, "пароль интерполирован в команду (shell injection)"

    # 3) Пароль передаётся через env, а не argv (если фикс использует env)
    env_used = any((call["kwargs"].get("env") or {}).get("PGPASSWORD") == MALICIOUS_PW for call in calls)
    argv_clean = all(
        MALICIOUS_PW
        not in " ".join(str(t) for t in (call["cmd"] if isinstance(call["cmd"], (list, tuple)) else [call["cmd"]]))
        for call in calls
    )
    assert env_used or argv_clean
