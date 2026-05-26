#!/usr/bin/env python3
"""onboard_family_user.py — CLI оркестратор подключения семейного юзера к BotkinClaw.

Examples:
  # Полный onboarding Игоря (dry-run):
  python3 scripts/onboard_family_user.py --enroll \\
      --tid REDACTED_ID \\
      --family-folder "$HOME/Library/CloudStorage/.../FamilyHealth/Игорь Лысковский — Здоровье" \\
      --name "Игорь" --full-name "Лысковский Игорь Александрович" \\
      --age "21 год" --birth-date "2004-08-15" --location "Москва" \\
      --cohort family --cohort-relationship "сын Александра" \\
      --bio-line "Студент. Аллергия на пыль, поллиноз." \\
      --pack respiratory_allergic --style ty \\
      --dry-run

  # Реальный enroll + welcome:
  python3 scripts/onboard_family_user.py --enroll ... --send-welcome --yes

  # Только обновить промпт:
  python3 scripts/onboard_family_user.py --refresh-prompt --tid REDACTED_ID \\
      --from-file scripts/server/agent_prompts/igor.md

  # Отозвать:
  python3 scripts/onboard_family_user.py --unenroll --tid REDACTED_ID

См. design: docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.onboard import (
    kb_validator,
    persona_generator,
    server_deployer,
    snapshot,
    welcome_sender,
)
from core.packs import get_pack

TEMPLATE_PATH = REPO_ROOT / "scripts" / "server" / "agent_prompts" / "templates" / "family_active_coach.md"
PROMPT_DIR = REPO_ROOT / "scripts" / "server" / "agent_prompts"


def _server_config() -> server_deployer.ServerConfig:
    return server_deployer.ServerConfig(
        host=os.environ.get("SERVER_HOST", "116.203.213.137"),
        user=os.environ.get("SERVER_USER", "root"),
        deploy_path=os.environ.get("SERVER_DEPLOY_PATH", "/opt/healthvault"),
    )


def _git_commit_artifact(prompt_path: Path, telegram_id: int, pack_name: str) -> None:
    """Stage the prompt artifact and commit. Warn (don't raise) on failure."""
    msg = f"agent: onboard telegram_id={telegram_id} — {pack_name}"
    add = subprocess.run(["git", "add", str(prompt_path)], capture_output=True, text=True, cwd=REPO_ROOT)
    if add.returncode != 0:
        print(f"  ⚠ git add failed (rc={add.returncode}): {add.stderr.strip()}")
        return
    commit = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True, cwd=REPO_ROOT)
    if commit.returncode != 0:
        # Could be "nothing to commit" — not fatal
        print(f"  ⚠ git commit returned rc={commit.returncode}: {commit.stdout.strip() or commit.stderr.strip()}")


def _confirm(message: str, *, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    print(message)
    return input("Продолжить? [y/N] ").strip().lower() == "y"


def _short_name_from_full(name: str) -> str:
    """Транслитерация Cyrillic → latin для имени файла. Soft/hard signs дропаются."""
    digraphs = [
        ("ж", "zh"),
        ("Ж", "Zh"),
        ("ч", "ch"),
        ("Ч", "Ch"),
        ("ш", "sh"),
        ("Ш", "Sh"),
        ("щ", "shch"),
        ("Щ", "Shch"),
        ("ю", "yu"),
        ("Ю", "Yu"),
        ("я", "ya"),
        ("Я", "Ya"),
        ("ё", "yo"),
        ("Ё", "Yo"),
    ]
    for src, dst in digraphs:
        name = name.replace(src, dst)
    # Single-char map — same length on both sides
    single = str.maketrans(
        "абвгдезийклмнопрстуфхцыэАБВГДЕЗИЙКЛМНОПРСТУФХЦЫЭ",
        "abvgdeziyklmnoprstufhcyeABVGDEZIYKLMNOPRSTUFHCYE",
    )
    name = name.translate(single)
    # Drop soft and hard signs entirely (no underscore replacement)
    name = name.replace("ь", "").replace("Ь", "").replace("ъ", "").replace("Ъ", "")
    return name.lower().replace(" ", "_").strip("_")


def cmd_enroll(args) -> int:
    ENROLL_REQUIRED = (
        "family_folder",
        "name",
        "full_name",
        "age",
        "birth_date",
        "location",
        "cohort",
        "cohort_relationship",
        "bio_line",
        "pack",
    )
    missing = [f"--{f.replace('_', '-')}" for f in ENROLL_REQUIRED if getattr(args, f) is None]
    if missing:
        print(f"❌ --enroll requires: {', '.join(missing)}")
        return 1
    fam_folder = Path(args.family_folder)
    kb_path = fam_folder / "knowledge_base.json"
    profile_path = fam_folder / "PROFILE.md"

    print("== Pre-flight checks ==")
    kb_summary = kb_validator.validate_kb(kb_path)
    print(f"  KB ok: {kb_summary.blood_tests_count} blood_tests, {kb_summary.size_bytes} bytes")
    pack = get_pack(args.pack)
    print(f"  Pack ok: {pack.name} — {pack.description}")

    cfg = _server_config()
    state_before = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    print(
        f"  Current server state: cohort={state_before.cohort}, "
        f"pack={state_before.pack_name}, prompt_len={state_before.prompt_length}, "
        f"kb_on_server={state_before.kb_on_server}"
    )
    already_enrolled = state_before.prompt_length > 0 and state_before.kb_on_server
    if already_enrolled and not args.force:
        print(
            f"❌ User {args.tid} уже enrolled. --force для перезаписи или "
            "--refresh-prompt / --refresh-kb для частичного обновления."
        )
        return 1

    # When re-enrolling (--force), capture the prior prompt for full rollback.
    prior_prompt = ""
    if already_enrolled:
        prior_prompt = server_deployer.fetch_agent_system_prompt(telegram_id=args.tid, cfg=cfg)
    snap = snapshot.UserSnapshot(
        telegram_id=args.tid,
        cohort=state_before.cohort,
        pack_name=state_before.pack_name,
        agent_system_prompt=prior_prompt,
        kb_existed_on_server=state_before.kb_on_server,
    )
    snapshot_path = snapshot.save_snapshot(snap)
    print(f"  Snapshot saved: {snapshot_path}")

    print("== Generating persona via Claude ==")
    profile_md = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    kb_data = json.loads(kb_path.read_text(encoding="utf-8"))
    inp = persona_generator.PersonaInput(
        name=args.name,
        full_name=args.full_name,
        age=args.age,
        birth_date=args.birth_date,
        location=args.location,
        cohort=args.cohort,
        cohort_relationship=args.cohort_relationship,
        pack_name=args.pack,
        bio_line=args.bio_line,
        kb_json=kb_data,
        profile_md=profile_md,
        style=args.style,
    )
    if args.from_file:
        print(f"  Using prompt from file: {args.from_file} (skipping LLM call)")
        prompt_text = Path(args.from_file).read_text(encoding="utf-8")
    else:
        blocks = persona_generator.generate_persona(inp)
        prompt_text = persona_generator.render_prompt(inp, blocks, template_path=TEMPLATE_PATH)

    if args.prompt_output:
        prompt_path = Path(args.prompt_output)
    else:
        prompt_path = PROMPT_DIR / f"{_short_name_from_full(args.name)}.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text, encoding="utf-8")
    print(f"  Prompt artifact saved: {prompt_path} ({len(prompt_text)} chars)")

    print("\n== Plan ==")
    print(f"  KB: scp {kb_path} → {cfg.deploy_path}/data/kb/kb_{args.tid}.json")
    print(
        f"  DB: UPDATE users SET cohort='{args.cohort}', pack_name='{args.pack}', "
        f"agent_system_prompt=<{len(prompt_text)} chars> WHERE telegram_id={args.tid}"
    )
    if args.send_welcome:
        print(f"  Welcome: Bot API sendMessage chat_id={args.tid}")
    print(f"  Prompt preview (first 500 chars):\n---\n{prompt_text[:500]}\n---")

    if args.dry_run:
        print("\n💡 --dry-run: ничего не применяется. Запусти без --dry-run.")
        return 0
    if not _confirm("\nПрименить изменения?", auto_yes=args.yes):
        print("Отменено пользователем.")
        return 1

    print("\n== Applying ==")
    try:
        server_deployer.upload_kb(kb_path=kb_path, telegram_id=args.tid, cfg=cfg)
        print("  ✓ KB uploaded")
    except Exception as e:
        print(f"❌ KB upload failed: {e}")
        return 2

    try:
        result = server_deployer.update_user_row(
            telegram_id=args.tid,
            cohort=args.cohort,
            pack_name=args.pack,
            agent_system_prompt=prompt_text,
            cfg=cfg,
        )
        print(f"  ✓ DB updated ({result.rows_affected} row)")
    except Exception as e:
        print(f"❌ DB update failed: {e}")
        print("  Rollback: removing KB from server")
        try:
            server_deployer.remove_kb(telegram_id=args.tid, cfg=cfg)
        except Exception as rb:
            print(f"  ⚠ Rollback also failed: {rb}")
        return 3

    print("\n== Post-flight verify ==")
    state_after = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    print(
        f"  cohort={state_after.cohort}, pack={state_after.pack_name}, "
        f"prompt_len={state_after.prompt_length}, kb_on_server={state_after.kb_on_server}"
    )
    if (
        state_after.cohort != args.cohort
        or state_after.pack_name != args.pack
        or state_after.prompt_length < len(prompt_text) - 10
        or not state_after.kb_on_server
    ):
        print("❌ Post-flight verify mismatch — investigate before celebrating.")
        return 4
    print("  ✓ Verified")

    if args.send_welcome:
        text = welcome_sender.build_welcome_text(
            name=args.name,
            style=args.style,
            inviter_name="Александр",
        )
        msg_id = welcome_sender.send_welcome(chat_id=args.tid, text=text)
        print(f"  ✓ Welcome sent (message_id={msg_id})")

    if not args.no_commit:
        _git_commit_artifact(prompt_path, args.tid, args.pack)
        print("  ✓ Git commit created locally (запушь когда готов)")
    else:
        print(f"  ⚠ --no-commit: артефакт {prompt_path} НЕ закоммичен")

    print(f"\n✅ Onboarding {args.name} (telegram_id={args.tid}) завершён.")
    return 0


def cmd_unenroll(args) -> int:
    cfg = _server_config()
    state_before = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    print(
        f"Current: cohort={state_before.cohort}, pack={state_before.pack_name}, "
        f"prompt_len={state_before.prompt_length}, kb_on_server={state_before.kb_on_server}"
    )
    if args.dry_run:
        print("💡 --dry-run: ничего не применяется.")
        return 0
    if not _confirm(f"Отозвать enrollment у telegram_id={args.tid}?", auto_yes=args.yes):
        return 1
    try:
        server_deployer.update_user_row(
            telegram_id=args.tid,
            cohort="external",
            pack_name="generic",
            agent_system_prompt="",
            cfg=cfg,
        )
        server_deployer.remove_kb(telegram_id=args.tid, cfg=cfg)
    except server_deployer.UserNotFoundError as e:
        print(f"❌ {e}")
        return 2
    except Exception as e:
        print(f"❌ Unenroll failed: {e}")
        return 3
    print(f"✅ Unenrolled telegram_id={args.tid}")
    return 0


def cmd_refresh_kb(args) -> int:
    if not args.family_folder:
        print("❌ --family-folder обязателен для --refresh-kb")
        return 1
    kb_path = Path(args.family_folder) / "knowledge_base.json"
    kb_validator.validate_kb(kb_path)
    cfg = _server_config()
    if args.dry_run:
        print(f"💡 --dry-run: scp {kb_path} → {cfg.deploy_path}/data/kb/kb_{args.tid}.json")
        return 0
    server_deployer.upload_kb(kb_path=kb_path, telegram_id=args.tid, cfg=cfg)
    print(f"✅ KB refreshed for telegram_id={args.tid}")
    return 0


def cmd_refresh_prompt(args) -> int:
    if not args.from_file:
        REFRESH_PROMPT_REQUIRED = (
            "family_folder",
            "name",
            "full_name",
            "age",
            "birth_date",
            "location",
            "cohort",
            "cohort_relationship",
            "bio_line",
            "pack",
        )
        missing = [f"--{f.replace('_', '-')}" for f in REFRESH_PROMPT_REQUIRED if getattr(args, f) is None]
        if missing:
            print(f"❌ --refresh-prompt without --from-file requires: {', '.join(missing)}")
            return 1
    cfg = _server_config()
    if args.from_file:
        prompt_text = Path(args.from_file).read_text(encoding="utf-8")
        print(f"Using prompt from {args.from_file} ({len(prompt_text)} chars)")
    else:
        fam_folder = Path(args.family_folder)
        kb_data = json.loads((fam_folder / "knowledge_base.json").read_text(encoding="utf-8"))
        profile_path = fam_folder / "PROFILE.md"
        profile_md = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
        inp = persona_generator.PersonaInput(
            name=args.name,
            full_name=args.full_name,
            age=args.age,
            birth_date=args.birth_date,
            location=args.location,
            cohort=args.cohort,
            cohort_relationship=args.cohort_relationship,
            pack_name=args.pack,
            bio_line=args.bio_line,
            kb_json=kb_data,
            profile_md=profile_md,
            style=args.style,
        )
        blocks = persona_generator.generate_persona(inp)
        prompt_text = persona_generator.render_prompt(inp, blocks, template_path=TEMPLATE_PATH)

    if args.dry_run:
        print(f"💡 --dry-run: would UPDATE prompt_len={len(prompt_text)} for tid={args.tid}")
        return 0

    state = server_deployer.fetch_user_state(telegram_id=args.tid, cfg=cfg)
    server_deployer.update_user_row(
        telegram_id=args.tid,
        cohort=state.cohort,
        pack_name=state.pack_name,
        agent_system_prompt=prompt_text,
        cfg=cfg,
    )
    print(f"✅ Prompt refreshed for telegram_id={args.tid}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Onboard a family user to BotkinClaw (KB + prompt + welcome).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    cmd = p.add_mutually_exclusive_group(required=True)
    cmd.add_argument("--enroll", action="store_true")
    cmd.add_argument("--unenroll", action="store_true")
    cmd.add_argument("--refresh-kb", action="store_true", dest="refresh_kb")
    cmd.add_argument("--refresh-prompt", action="store_true", dest="refresh_prompt")

    p.add_argument("--tid", type=int, required=True, help="Telegram ID of the user")
    p.add_argument("--family-folder", help="Path to FamilyHealth/<name> folder")
    p.add_argument("--name", help="Short name, e.g. 'Игорь'")
    p.add_argument("--full-name", help="Full name")
    p.add_argument("--age", help="Age as words, e.g. '21 год'")
    p.add_argument("--birth-date", help="YYYY-MM-DD")
    p.add_argument("--location", help="City")
    p.add_argument("--cohort", choices=["owner", "family", "early_user", "external"])
    p.add_argument("--cohort-relationship", help="e.g. 'сын Александра'")
    p.add_argument("--bio-line", help="One-line bio")
    p.add_argument("--pack", help="Pack name from core/packs.py")
    p.add_argument("--style", choices=["ty", "vy"], default="ty")
    p.add_argument("--from-file", help="Use prompt from file instead of generating")
    p.add_argument("--prompt-output", help="Override where to save prompt artifact")

    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Overwrite existing enrollment")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    p.add_argument("--send-welcome", action="store_true")
    p.add_argument("--no-commit", action="store_true", help="Don't git commit the artifact")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.enroll:
        return cmd_enroll(args)
    if args.unenroll:
        return cmd_unenroll(args)
    if args.refresh_kb:
        return cmd_refresh_kb(args)
    if args.refresh_prompt:
        return cmd_refresh_prompt(args)
    parser.error("No command specified")
    return 2


if __name__ == "__main__":
    sys.exit(main())
