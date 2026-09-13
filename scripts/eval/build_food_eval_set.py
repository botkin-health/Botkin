#!/usr/bin/env python3
"""Собирает замороженный eval-набор для парсинга еды из прод-таблицы food_interactions.

Берёт кейсы со статусом ``saved`` (пользователь подтвердил распознавание кнопкой
«Сохранить») — их ``recognized`` служит эталоном. Фото скачиваются с сервера одним
ssh-tar (fail2ban не любит серию ssh-сессий). Набор пишется в ``data/eval/food/``
(каталог ``data/`` в .gitignore — сырой текст и фото еды в репозиторий не попадают).

Запуск с мака:
    python3 scripts/eval/build_food_eval_set.py --text 40 --photo 25
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from collections import defaultdict
from pathlib import Path

SSH_HOST = "root@116.203.213.137"
PG = "docker exec healthvault_postgres psql -U healthvault -d healthvault -At -c"
CONTAINER_MEDIA_PREFIX = "/app/data/media/"
HOST_MEDIA_PREFIX = "/opt/botkin/data/media/"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "eval" / "food"

QUERY = """
SELECT json_agg(t) FROM (
  SELECT id, user_id, source, raw_text, media_path, recognized, created_at
  FROM food_interactions
  WHERE status = 'saved' AND recognized IS NOT NULL
    AND created_at > now() - interval '90 days'
  ORDER BY created_at DESC
) t;
"""

# Сообщения не про еду — проверяем, что модель их не логирует как приём пищи.
# В food_interactions таких нет по определению, поэтому добавляем руками.
NEGATIVE_CASES = [
    ("120/80 пульс 65", "bp"),
    ("Сейчас 15:07 151/92 пуль 65", "bp"),
    ("Правда ли, что 140/90 — это уже гипертония?", "other"),
    ("82.4 кг", "weight"),
    ("вес 79,8", "weight"),
    ("выпил магний и омегу", "vitamins"),
    ("талия 101 см, шея 42", "body_measurements"),
    ("Завтрак: яичница из 2 яиц с тостом. Обед: куриный суп 300г и кусок хлеба", "multi_food"),
]


def _ssh(cmd: str) -> str:
    return subprocess.run(["ssh", SSH_HOST, cmd], check=True, capture_output=True, text=True).stdout


def _fetch_rows() -> list[dict]:
    raw = _ssh(f'{PG} "{QUERY}"').strip()
    return json.loads(raw) if raw else []


def _stratified(rows: list[dict], n: int, seed: int) -> list[dict]:
    """Round-robin по пользователям, чтобы один активный юзер не забил весь набор."""
    rng = random.Random(seed)
    by_user: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_user[r["user_id"]].append(r)
    for bucket in by_user.values():
        rng.shuffle(bucket)
    picked: list[dict] = []
    while len(picked) < n and any(by_user.values()):
        for uid in list(by_user):
            if by_user[uid]:
                picked.append(by_user[uid].pop())
            if len(picked) >= n:
                break
    return picked


def _download_photos(media_paths: list[str], dest: Path) -> dict[str, str]:
    dest.mkdir(parents=True, exist_ok=True)
    host_paths = [p.replace(CONTAINER_MEDIA_PREFIX, HOST_MEDIA_PREFIX) for p in media_paths]
    tar = subprocess.run(
        ["ssh", SSH_HOST, "tar czf - " + " ".join(f"'{p}'" for p in host_paths)],
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "xzf", "-", "--strip-components=6", "-C", str(dest)], input=tar, check=True)
    return {p: str(dest / Path(p).name) for p in media_paths}


def _download_uploads(rel_files: list[str], dest: Path) -> dict[str, str]:
    """Фото из /doc: /opt/botkin/data/uploads/<user_id>/<file> → dest/<user_id>_<file>."""
    dest.mkdir(parents=True, exist_ok=True)
    tar = subprocess.run(
        ["ssh", SSH_HOST, "cd /opt/botkin/data/uploads && tar czf - " + " ".join(f"'{f}'" for f in rel_files)],
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "xzf", "-", "-C", str(dest)], input=tar, check=True)
    out = {}
    for f in rel_files:
        flat = dest / f.replace("/", "_")
        (dest / f).rename(flat)
        out[f] = str(flat)
    for d in dest.iterdir():
        if d.is_dir():
            d.rmdir()
    return out


def _to_case(r: dict, idx: int, user_alias: dict[int, str], photo_local: dict[str, str]) -> dict:
    rec = r["recognized"] or {}
    totals = rec.get("totals") or {}
    return {
        "id": f"{r['source']}-{r['id']}",
        "user": user_alias.setdefault(r["user_id"], f"u{len(user_alias) + 1}"),
        "source": r["source"],
        "text": r["raw_text"] or "",
        "photo": photo_local.get(r["media_path"]),
        "golden": {
            "type": "food",
            "calories": totals.get("calories"),
            "protein": totals.get("protein"),
            "fats": totals.get("fats"),
            "carbs": totals.get("carbs"),
            "n_items": len(rec.get("items") or []),
            "items": [i.get("product") or i.get("name") for i in rec.get("items") or []],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", type=int, default=40)
    ap.add_argument("--photo", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument(
        "--photo-ids",
        default="",
        help="явные id из food_interactions, добавить к случайной выборке (категории: карточки meal-kit, этикетки, весы)",
    )
    ap.add_argument(
        "--medical", type=Path, default=None, help="JSON {file: subtype} для фото из /doc uploads (тип medical)"
    )
    args = ap.parse_args()

    rows = _fetch_rows()
    text_rows = [r for r in rows if r["source"] == "text" and (r["raw_text"] or "").strip()]
    photo_rows = [r for r in rows if r["source"] == "photo" and r["media_path"]]
    print(f"prod: saved text={len(text_rows)} photo(with media)={len(photo_rows)}")

    text_pick = _stratified(text_rows, args.text, args.seed)
    photo_pick = _stratified(photo_rows, args.photo, args.seed)
    forced_ids = {int(x) for x in args.photo_ids.split(",") if x.strip()}
    picked_ids = {r["id"] for r in photo_pick}
    photo_pick += [r for r in photo_rows if r["id"] in forced_ids and r["id"] not in picked_ids]
    photo_local = _download_photos([r["media_path"] for r in photo_pick], OUT_DIR / "photos")

    user_alias: dict[int, str] = {}
    cases = [_to_case(r, i, user_alias, photo_local) for i, r in enumerate(text_pick + photo_pick)]
    if args.medical:
        med = json.loads(args.medical.read_text(encoding="utf-8"))
        med_local = _download_uploads(list(med), OUT_DIR / "medical")
        cases += [
            {
                "id": f"med-{Path(f).stem}",
                "user": "doc",
                "source": "photo",
                "text": "",
                "photo": med_local[f],
                "golden": {"type": "medical", "subtype": sub},
            }
            for f, sub in med.items()
        ]
    cases += [
        {"id": f"neg-{i}", "user": "synthetic", "source": "text", "text": t, "photo": None, "golden": {"type": g}}
        for i, (t, g) in enumerate(NEGATIVE_CASES)
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "cases.json"
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"wrote {len(cases)} cases → {out} (text={len(text_pick)}, photo={len(photo_pick)}, neg={len(NEGATIVE_CASES)})"
    )


if __name__ == "__main__":
    main()
