"""CLI integration tests for onboard_family_user.py — все компоненты замоканы."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "onboard_family_user.py"


def _run_cli(*args, env=None):
    """Запустить CLI как subprocess. Возвращает CompletedProcess."""
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))


def test_cli_help_works():
    """`--help` не падает и упоминает основные команды."""
    result = _run_cli("--help")
    assert result.returncode == 0
    out = result.stdout
    assert "--enroll" in out
    assert "--refresh-kb" in out
    assert "--refresh-prompt" in out
    assert "--unenroll" in out
    assert "--dry-run" in out


def test_cli_enroll_requires_tid():
    """--enroll без --tid должно падать."""
    result = _run_cli("--enroll")
    assert result.returncode != 0


def test_cli_dry_run_unit(monkeypatch, tmp_path):
    """Импортированный CLI в --dry-run не дёргает деструктивные операции."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SERVER_PASSWORD", "dummy")

    # Подготовить fake FamilyHealth
    fam = tmp_path / "FamilyHealth" / "Test User"
    fam.mkdir(parents=True)
    (fam / "knowledge_base.json").write_text(
        json.dumps(
            {
                "blood_tests": [{"date": "2025-01-01", "values": {"vitamin_d": 30}}],
                "diagnoses": ["J45"],
            }
        )
    )
    (fam / "PROFILE.md").write_text("Test profile")

    sys.path.insert(0, str(REPO_ROOT))
    from scripts import onboard_family_user as cli

    with (
        patch.object(cli.server_deployer, "upload_kb") as m_upload,
        patch.object(cli.server_deployer, "update_user_row") as m_update,
        patch.object(cli.welcome_sender, "send_welcome") as m_welcome,
        patch.object(cli.persona_generator, "generate_persona") as m_persona,
        patch.object(cli.server_deployer, "fetch_user_state") as m_fetch,
    ):
        m_fetch.return_value = cli.server_deployer.UserServerState(
            telegram_id=999,
            cohort="external",
            pack_name="generic",
            prompt_length=0,
            kb_on_server=False,
        )
        m_persona.return_value = cli.persona_generator.PersonaBlocks(
            framing="x",
            chronic="x",
            open_questions="x",
            therapy="x",
            focus_areas="x",
            typical_questions="x",
        )
        rc = cli.main(
            [
                "--enroll",
                "--tid",
                "999",
                "--family-folder",
                str(fam),
                "--name",
                "Test",
                "--full-name",
                "Test User",
                "--age",
                "30",
                "--birth-date",
                "1995-01-01",
                "--location",
                "Test City",
                "--cohort",
                "family",
                "--cohort-relationship",
                "test",
                "--bio-line",
                "test bio",
                "--pack",
                "generic",
                "--style",
                "ty",
                "--dry-run",
                "--yes",
                "--prompt-output",
                str(tmp_path / "test.md"),
            ]
        )
    assert rc == 0
    m_upload.assert_not_called()
    m_update.assert_not_called()
    m_welcome.assert_not_called()


def test_cli_enroll_full_flow(monkeypatch, tmp_path):
    """--enroll без --dry-run дёргает upload_kb, update_user_row, (с --send-welcome) send_welcome."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("SERVER_PASSWORD", "dummy")

    fam = tmp_path / "FamilyHealth" / "Test User"
    fam.mkdir(parents=True)
    (fam / "knowledge_base.json").write_text(
        json.dumps(
            {
                "blood_tests": [{"date": "2025-01-01", "values": {"vitamin_d": 30}}],
                "diagnoses": ["J45"],
            }
        )
    )
    (fam / "PROFILE.md").write_text("Test profile")

    sys.path.insert(0, str(REPO_ROOT))
    from scripts import onboard_family_user as cli

    with (
        patch.object(cli.server_deployer, "upload_kb") as m_upload,
        patch.object(
            cli.server_deployer, "update_user_row", return_value=cli.server_deployer.DeployResult(rows_affected=1)
        ) as m_update,
        patch.object(cli.welcome_sender, "send_welcome", return_value=123) as m_welcome,
        patch.object(cli.persona_generator, "generate_persona") as m_persona,
        patch.object(cli.server_deployer, "fetch_user_state") as m_fetch,
        patch.object(cli, "_git_commit_artifact"),
    ):
        m_fetch.side_effect = [
            cli.server_deployer.UserServerState(999, "external", "generic", 0, False),
            cli.server_deployer.UserServerState(999, "family", "generic", 5000, True),
        ]
        m_persona.return_value = cli.persona_generator.PersonaBlocks(
            framing="x",
            chronic="x",
            open_questions="x",
            therapy="x",
            focus_areas="x",
            typical_questions="x",
        )
        rc = cli.main(
            [
                "--enroll",
                "--tid",
                "999",
                "--family-folder",
                str(fam),
                "--name",
                "Test",
                "--full-name",
                "Test User",
                "--age",
                "30",
                "--birth-date",
                "1995-01-01",
                "--location",
                "Test City",
                "--cohort",
                "family",
                "--cohort-relationship",
                "test",
                "--bio-line",
                "test bio",
                "--pack",
                "generic",
                "--style",
                "ty",
                "--send-welcome",
                "--yes",
                "--no-commit",
                "--prompt-output",
                str(tmp_path / "test.md"),
            ]
        )
    assert rc == 0
    m_upload.assert_called_once()
    m_update.assert_called_once()
    m_welcome.assert_called_once()
