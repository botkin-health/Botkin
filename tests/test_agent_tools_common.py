"""Pin project-root resolution in agent_tools/common.py after the file moved one level deeper.

_resolve_user_kb_path builds paths from Path(__file__).resolve().parents[N]. The old
agent_tools_api.py used N=2; common.py is one directory deeper and must use N=3.
This test anchors the repo root INDEPENDENTLY (from tests/, same convention as
conftest.py) and checks a POSITIVE lookup, so an off-by-one N makes it fail.
"""

from pathlib import Path

# Independent anchor: tests/ lives directly under the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE_ID = 999999999  # no real user has this id
_MISSING_ID = 999999998


class _User:
    def __init__(self, telegram_id: int, cohort: str = "external"):
        self.telegram_id = telegram_id
        self.cohort = cohort


def test_resolve_user_kb_path_finds_kb_under_real_repo_root():
    """Positive path: a KB file placed under <repo_root>/data/kb/ must be found.

    With the wrong parents[N] the function would look under telegram-bot/data/kb/
    (or another wrong dir), not find the file, and return kb-not-available.
    """
    from webhook.agent_tools import common

    kb_dir = REPO_ROOT / "data" / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    kb_file = kb_dir / f"kb_{_PROBE_ID}.json"
    kb_file.write_text("{}", encoding="utf-8")
    try:
        path, label = common._resolve_user_kb_path(_User(_PROBE_ID))
        assert path is not None, "KB under the real repo root was not found — parents[N] is off"
        assert path.resolve() == kb_file.resolve()
        assert label == f"data/kb/kb_{_PROBE_ID}.json"
    finally:
        kb_file.unlink(missing_ok=True)


def test_resolve_user_kb_path_missing_returns_sentinel():
    """Negative path is unchanged by the move."""
    from webhook.agent_tools import common

    path, label = common._resolve_user_kb_path(_User(_MISSING_ID))
    assert path is None
    assert label == "kb-not-available"
