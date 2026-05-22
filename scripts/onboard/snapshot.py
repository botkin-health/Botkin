"""Snapshot состояния юзера в БД до изменений — для rollback'а."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Default — относительно корня проекта; CLI/тесты могут переопределить.
DEFAULT_SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "onboarding_snapshots"


@dataclass(frozen=True)
class UserSnapshot:
    telegram_id: int
    cohort: str
    pack_name: str
    agent_system_prompt: str
    kb_existed_on_server: bool


def save_snapshot(snap: UserSnapshot, *, snapshots_dir: Optional[Path] = None) -> Path:
    """Записать snapshot. Имя файла: <tid>_<isoformat>.json (sortable)."""
    snapshots_dir = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = snapshots_dir / f"{snap.telegram_id}_{timestamp}.json"
    payload = asdict(snap)
    payload["timestamp"] = timestamp
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def load_latest_snapshot(*, telegram_id: int, snapshots_dir: Optional[Path] = None) -> Optional[UserSnapshot]:
    """Вернуть самый свежий snapshot для юзера, либо None если нет."""
    snapshots_dir = snapshots_dir or DEFAULT_SNAPSHOTS_DIR
    if not snapshots_dir.exists():
        return None
    candidates = sorted(snapshots_dir.glob(f"{telegram_id}_*.json"))
    if not candidates:
        return None
    data = json.loads(candidates[-1].read_text())
    data.pop("timestamp", None)
    return UserSnapshot(**data)
