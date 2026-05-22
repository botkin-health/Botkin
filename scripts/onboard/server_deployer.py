"""Server deployer — scp KB + psql UPDATE с атомарностью и rollback."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ServerConfig:
    host: str
    user: str
    password: str
    deploy_path: str
    sshpass_path: str = "/opt/homebrew/bin/sshpass"


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


def _sshpass_args(cfg: ServerConfig) -> list[str]:
    return [cfg.sshpass_path, "-p", cfg.password]


def _ssh(cfg: ServerConfig, remote_cmd: str) -> subprocess.CompletedProcess:
    cmd = _sshpass_args(cfg) + [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        f"{cfg.user}@{cfg.host}",
        remote_cmd,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _scp(cfg: ServerConfig, local_path: Path, remote_path: str) -> subprocess.CompletedProcess:
    cmd = _sshpass_args(cfg) + [
        "scp",
        "-o",
        "StrictHostKeyChecking=no",
        str(local_path),
        f"{cfg.user}@{cfg.host}:{remote_path}",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _psql(cfg: ServerConfig, sql: str) -> subprocess.CompletedProcess:
    """Запустить psql -t -c <sql> через docker exec на сервере."""
    docker_cmd = f"docker exec healthvault_postgres psql -U healthvault -d healthvault -t -A -c {shlex.quote(sql)}"
    return _ssh(cfg, docker_cmd)


def upload_kb(*, kb_path: Path, telegram_id: int, cfg: ServerConfig) -> None:
    """Залить kb_<tid>.json на сервер atomic'ом: scp в .tmp + mv."""
    tmp_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json.tmp"
    final_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json"

    scp = _scp(cfg, kb_path, tmp_remote)
    if scp.returncode != 0:
        raise RuntimeError(f"scp failed: {scp.stderr or scp.stdout}")

    mv = _ssh(cfg, f"mv {shlex.quote(tmp_remote)} {shlex.quote(final_remote)}")
    if mv.returncode != 0:
        # rollback .tmp
        _ssh(cfg, f"rm -f {shlex.quote(tmp_remote)}")
        raise RuntimeError(f"ssh mv failed: {mv.stderr or mv.stdout}")


def remove_kb(*, telegram_id: int, cfg: ServerConfig) -> None:
    """Удалить kb_<tid>.json с сервера (для rollback / --unenroll)."""
    final_remote = f"{cfg.deploy_path}/kb_{telegram_id}.json"
    _ssh(cfg, f"rm -f {shlex.quote(final_remote)}")


def update_user_row(
    *,
    telegram_id: int,
    cohort: str,
    pack_name: str,
    agent_system_prompt: str,
    cfg: ServerConfig,
) -> DeployResult:
    """UPDATE users SET cohort, pack_name, agent_system_prompt WHERE telegram_id."""
    # Escape single quotes in prompt for SQL
    prompt_escaped = agent_system_prompt.replace("'", "''")
    sql = (
        f"UPDATE users SET cohort='{cohort}', pack_name='{pack_name}', "
        f"agent_system_prompt='{prompt_escaped}' "
        f"WHERE telegram_id={telegram_id};"
    )
    result = _psql(cfg, sql)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr or result.stdout}")

    out = result.stdout.strip()
    # Last non-empty line is "UPDATE N"
    last_lines = [line for line in out.splitlines() if line.strip()]
    if not last_lines:
        raise RuntimeError(f"psql gave no output for UPDATE: {out!r}")
    last = last_lines[-1]
    rows = int(last.split()[-1]) if last.upper().startswith("UPDATE") else 0
    if rows == 0:
        raise RuntimeError(f"UPDATE matched 0 rows — user telegram_id={telegram_id} not found")
    return DeployResult(rows_affected=rows)


def fetch_user_state(*, telegram_id: int, cfg: ServerConfig) -> UserServerState:
    """SELECT текущего состояния юзера + проверка наличия kb-файла."""
    sql = (
        f"SELECT telegram_id, cohort, pack_name, "
        f"COALESCE(LENGTH(agent_system_prompt), 0) "
        f"FROM users WHERE telegram_id={telegram_id};"
    )
    result = _psql(cfg, sql)
    if result.returncode != 0:
        raise RuntimeError(f"psql SELECT failed: {result.stderr or result.stdout}")
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"User telegram_id={telegram_id} not found in users table")
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
