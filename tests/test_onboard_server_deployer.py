"""Server deployer — scp KB на Hetzner + psql UPDATE."""

import subprocess
from unittest.mock import patch

import pytest

from scripts.onboard.server_deployer import (
    ServerConfig,
    upload_kb,
    update_user_row,
    fetch_user_state,
    remove_kb,
)


@pytest.fixture
def cfg():
    return ServerConfig(
        host="116.203.213.137",
        user="root",
        deploy_path="/opt/healthvault",
    )


def test_upload_kb_runs_atomic_scp(cfg, tmp_path):
    kb = tmp_path / "kb_999.json"
    kb.write_text('{"blood_tests":[]}')
    runs: list[list[str]] = []

    def fake_run(cmd, **kw):
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        upload_kb(kb_path=kb, telegram_id=999, cfg=cfg)

    # Должно быть: 1) scp в .tmp 2) ssh mv .tmp → финальный путь
    assert any("scp" in " ".join(c) for c in runs)
    assert any("kb_999.json.tmp" in " ".join(c) for c in runs)
    assert any("mv " in " ".join(c) for c in runs)


def test_upload_kb_raises_on_scp_failure(cfg, tmp_path):
    kb = tmp_path / "kb_999.json"
    kb.write_text('{"blood_tests":[]}')

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="permission denied")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError) as exc:
            upload_kb(kb_path=kb, telegram_id=999, cfg=cfg)
    assert "permission denied" in str(exc.value)


def test_update_user_row_builds_correct_sql(cfg):
    captured_sql = []

    def fake_run(cmd, **kw):
        captured_sql.append(" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="UPDATE 1\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        result = update_user_row(
            telegram_id=830908046,
            cohort="family",
            pack_name="respiratory_allergic",
            agent_system_prompt="hello",
            cfg=cfg,
        )

    joined = " ".join(captured_sql)
    assert "830908046" in joined
    assert "family" in joined
    assert "respiratory_allergic" in joined
    assert result.rows_affected == 1


def test_update_user_row_raises_when_zero_rows(cfg):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="UPDATE 0\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError) as exc:
            update_user_row(
                telegram_id=999999,
                cohort="family",
                pack_name="generic",
                agent_system_prompt="x",
                cfg=cfg,
            )
    assert "0 rows" in str(exc.value).lower() or "not found" in str(exc.value).lower()


def test_fetch_user_state_parses_psql_output(cfg):
    # First call: psql SELECT returns pipe-separated row
    # Second call: ssh test -f returns "t\n"
    psql_result = subprocess.CompletedProcess([], 0, stdout="830908046|external|generic|0\n", stderr="")
    ssh_result = subprocess.CompletedProcess([], 0, stdout="f\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=[psql_result, ssh_result]):
        state = fetch_user_state(telegram_id=830908046, cfg=cfg)

    assert state.cohort == "external"
    assert state.pack_name == "generic"
    assert state.prompt_length == 0
    assert state.kb_on_server is False


def test_remove_kb_runs_ssh_rm(cfg):
    runs = []

    def fake_run(cmd, **kw):
        runs.append(" ".join(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        remove_kb(telegram_id=999, cfg=cfg)

    joined = " ".join(runs)
    assert "rm" in joined
    assert "kb_999.json" in joined


def test_update_user_row_escapes_sql_injection_in_cohort(cfg):
    """SQL injection через cohort должна быть нейтрализована удвоением кавычек."""
    captured_sql: list[str] = []

    def fake_psql(cfg_arg, sql: str) -> subprocess.CompletedProcess:
        captured_sql.append(sql)
        return subprocess.CompletedProcess([], 0, stdout="UPDATE 1\n", stderr="")

    with patch("scripts.onboard.server_deployer._psql", side_effect=fake_psql):
        update_user_row(
            telegram_id=999,
            cohort="x'; DROP TABLE users;--",
            pack_name="generic",
            agent_system_prompt="ok",
            cfg=cfg,
        )
    assert len(captured_sql) == 1
    sql = captured_sql[0]
    # Escaped form: single quote doubled → x'' must appear in raw SQL
    assert "x''" in sql
    # The original unescaped injection sequence must NOT appear
    assert "x'; DROP" not in sql


def test_fetch_user_state_user_not_found_raises_specific_error(cfg):
    """Пустой результат → UserNotFoundError, не RuntimeError."""
    from scripts.onboard.server_deployer import UserNotFoundError

    psql_result = subprocess.CompletedProcess([], 0, stdout="\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", return_value=psql_result):
        with pytest.raises(UserNotFoundError) as exc:
            fetch_user_state(telegram_id=999999, cfg=cfg)
    assert "999999" in str(exc.value)


def test_fetch_user_state_psql_failure_raises_psql_error(cfg):
    """psql ошибка инфраструктуры → PsqlError, не UserNotFoundError."""
    from scripts.onboard.server_deployer import PsqlError

    psql_fail = subprocess.CompletedProcess([], 2, stdout="", stderr="container not running")

    with patch("scripts.onboard.server_deployer.subprocess.run", return_value=psql_fail):
        with pytest.raises(PsqlError) as exc:
            fetch_user_state(telegram_id=999, cfg=cfg)
    assert "container not running" in str(exc.value)


def test_update_user_row_zero_rows_raises_user_not_found(cfg):
    """rows=0 → UserNotFoundError (специфичный класс, не общий RuntimeError)."""
    from scripts.onboard.server_deployer import UserNotFoundError

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="UPDATE 0\n", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(UserNotFoundError) as exc:
            update_user_row(
                telegram_id=999999,
                cohort="family",
                pack_name="generic",
                agent_system_prompt="x",
                cfg=cfg,
            )
    assert "999999" in str(exc.value)


def test_upload_kb_rejects_invalid_json_on_server(cfg, tmp_path):
    """Если post-upload JSON-валидация на сервере падает — RuntimeError + cleanup."""
    kb = tmp_path / "kb_999.json"
    kb.write_text('{"blood_tests":[]}')

    call_count = {"n": 0}

    def fake_run(cmd, **kw):
        call_count["n"] += 1
        # Call sequence: mkdir (1) → scp (2) → mv (3) → python json.load (4, fails) → rm (5)
        if call_count["n"] == 4:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="json.decoder.JSONDecodeError")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError) as exc:
            upload_kb(kb_path=kb, telegram_id=999, cfg=cfg)
    assert "JSON" in str(exc.value) or "json" in str(exc.value)


def test_fetch_agent_system_prompt_returns_text(cfg):
    """Возвращает текст промпта из psql output."""
    from scripts.onboard.server_deployer import fetch_agent_system_prompt

    psql_result = subprocess.CompletedProcess([], 0, stdout="some prompt text\n", stderr="")
    with patch("scripts.onboard.server_deployer.subprocess.run", return_value=psql_result):
        prompt = fetch_agent_system_prompt(telegram_id=999, cfg=cfg)
    assert "some prompt text" in prompt


def test_upload_kb_rollback_tmp_on_mv_failure(cfg, tmp_path):
    """Если mv падает — должен быть вызван rm на .tmp файл."""
    kb = tmp_path / "kb_999.json"
    kb.write_text('{"blood_tests":[]}')

    call_count = {"n": 0}
    captured = []

    def fake_run(cmd, **kw):
        call_count["n"] += 1
        captured.append(" ".join(cmd))
        # Call sequence: mkdir (1) → scp (2) → mv (3, fails) → rm rollback (4)
        if call_count["n"] == 3:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="mv failed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("scripts.onboard.server_deployer.subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError):
            upload_kb(kb_path=kb, telegram_id=999, cfg=cfg)
    # 4-й вызов — rm -f .tmp rollback после провала mv
    assert "rm -f" in captured[3]
    assert "kb_999.json.tmp" in captured[3]
