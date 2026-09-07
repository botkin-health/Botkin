"""Pin project-root resolution in agent_tools/common.py after the file moved one level deeper."""

from pathlib import Path


def test_resolve_user_kb_path_sees_real_project_root():
    from webhook.agent_tools import common

    # The project root must contain these top-level dirs; telegram-bot/ (the wrong
    # answer after the move) contains neither.
    root = Path(common.__file__).resolve().parents[3]
    assert (root / "config").is_dir(), f"expected repo root, got {root}"
    assert (root / "database").is_dir(), f"expected repo root, got {root}"

    # And the function itself must build paths under that same root.
    class _U:
        telegram_id = 999999999  # no KB file exists for this id
        cohort = "external"

    path, label = common._resolve_user_kb_path(_U())
    assert path is None
    assert label == "kb-not-available"
