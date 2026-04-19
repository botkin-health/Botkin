"""Tests for webapp static auto-versioning.

Goal: verify that `/webapp/` serves index.html with a cache-busting hash
substituted into `{{V}}` placeholders, and that the hash changes when
any of the tracked files (day.js, api.js, day.css) is modified.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from fastapi.testclient import TestClient


def test_index_substitutes_version_placeholder():
    """{{V}} in index.html must be replaced with an 8-char hex hash."""
    from webhook import apple_health

    client = TestClient(apple_health.app)
    r = client.get("/webapp/")
    assert r.status_code == 200
    body = r.text
    # Placeholder must be gone
    assert "{{V}}" not in body
    # Tracked assets must include ?v=<hash>
    import re

    matches = re.findall(r"(?:day\.js|api\.js|day\.css)\?v=([0-9a-f]+)", body)
    assert matches, f"no versioned assets found in body: {body[:500]}"
    # All versions in one response must be the same hash
    assert len(set(matches)) == 1
    assert len(matches[0]) == 8


def test_index_cache_control_is_no_cache():
    """HTML itself must not be cached — only the referenced JS/CSS are cached via ?v=."""
    from webhook import apple_health

    client = TestClient(apple_health.app)
    r = client.get("/webapp/")
    assert "no-cache" in r.headers.get("cache-control", "").lower()


def test_version_changes_when_file_mtime_changes(tmp_path, monkeypatch):
    """Touching day.js must produce a new version hash."""
    # Create a fake webapp dir
    webapp = tmp_path / "webapp"
    webapp.mkdir()
    (webapp / "day.js").write_text("// v1")
    (webapp / "api.js").write_text("// a")
    (webapp / "day.css").write_text("/* c */")
    (webapp / "index.html").write_text('<script src="day.js?v={{V}}"></script>')

    from webhook import apple_health

    monkeypatch.setattr(apple_health, "_webapp_dir", webapp)

    v1 = apple_health._webapp_version()
    # Bump mtime on day.js by rewriting it
    import time as _time

    _time.sleep(0.01)  # ensure mtime_ns is different
    (webapp / "day.js").write_text("// v2")
    v2 = apple_health._webapp_version()

    assert v1 != v2, "version must change when day.js is modified"
    assert len(v1) == len(v2) == 8


# ── JS static analysis ────────────────────────────────────────────────────────


def _extract_nutri_refs(js_text: str) -> list[str]:
    """Extract identifier names from window.__nutri = { a, b, c } or { a: b, ... }."""
    import re

    m = re.search(r"window\.__nutri\s*=\s*\{([^}]+)\}", js_text)
    if not m:
        return []
    body = m.group(1)
    # Each entry is either `name` (shorthand) or `key: name`
    names = []
    for entry in body.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            names.append(entry.split(":")[1].strip())
        else:
            names.append(entry)
    return names


def _is_defined_in_js(name: str, js_text: str) -> bool:
    """Return True if `name` looks like it's defined (const/let/var/function) in the file."""
    import re

    patterns = [
        rf"\bconst\s+{re.escape(name)}\b",
        rf"\blet\s+{re.escape(name)}\b",
        rf"\bvar\s+{re.escape(name)}\b",
        rf"\bfunction\s+{re.escape(name)}\b",
        rf"\basync\s+function\s+{re.escape(name)}\b",
    ]
    return any(re.search(p, js_text) for p in patterns)


def test_nutri_debug_object_references_defined_names():
    """Regression: window.__nutri = { ... } must only reference names defined in day.js.

    This caught the bug where `api` was left in __nutri after being renamed to `API`,
    causing a ReferenceError that silently crashed the IIFE on first load.
    """
    day_js = Path(__file__).resolve().parent.parent / "telegram-bot" / "webapp" / "day.js"
    js_text = day_js.read_text(encoding="utf-8")

    refs = _extract_nutri_refs(js_text)
    assert refs, "window.__nutri not found in day.js — update test if intentionally removed"

    undefined = [name for name in refs if not _is_defined_in_js(name, js_text)]
    assert not undefined, (
        f"window.__nutri references name(s) not defined in day.js: {undefined}. "
        "This causes ReferenceError on first load."
    )
