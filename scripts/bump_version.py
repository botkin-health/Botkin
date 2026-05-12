#!/usr/bin/env python3
"""Bump version in all the places that need it.

Usage:
    python scripts/bump_version.py 0.5.1

Обновляет:
    core/_version.py        — runtime SSOT (читает bot.py)
    pyproject.toml          — для pip/build-инструментов
    docs/landing/index.html — pill + footer

После запуска:
    git diff   — проверить
    git add core/_version.py pyproject.toml docs/landing/index.html
    git commit -m "release: v0.5.1"
    git tag -a v0.5.1 -m "..."
    git push && git push --tags
    ./deploy.sh  (для бота) + rsync лендинга
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?$")


def main() -> int:
    if len(sys.argv) != 2 or not SEMVER_RE.match(sys.argv[1]):
        print("Usage: python scripts/bump_version.py X.Y.Z")
        print("Examples: 0.5.1, 0.6.0, 1.0.0, 0.6.0-rc1")
        return 1

    new = sys.argv[1]

    # core/_version.py
    p = ROOT / "core" / "_version.py"
    p.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new}"', p.read_text()))

    # pyproject.toml — только version в [project] (не target-version в ruff)
    p = ROOT / "pyproject.toml"
    text = p.read_text()
    text = re.sub(r'(\[project\][^\[]*?\nversion = ")[^"]+(")', rf"\g<1>{new}\g<2>", text, count=1, flags=re.DOTALL)
    p.write_text(text)

    # docs/landing/index.html — все вхождения Botkin vX.Y.Z
    p = ROOT / "docs" / "landing" / "index.html"
    p.write_text(re.sub(r"Botkin v\d+\.\d+(\.\d+)?", f"Botkin v{new}", p.read_text()))

    print(f"✅ Bumped to v{new}")
    print("Дальше:")
    print("  git diff")
    print(f"  git commit -am 'release: v{new}'")
    print(f"  git tag -a v{new} -m '...'")
    print("  git push && git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
