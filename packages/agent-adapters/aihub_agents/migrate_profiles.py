"""Prepare or apply migration of account-owned Claude profiles."""

from __future__ import annotations

import argparse
from pathlib import Path

from .worker import _build_claude_overlay, _ensure_codex_profile_overlay


def migrate_profiles(home: Path, *, dry_run: bool) -> None:
    accounts = home / ".aihub" / "accounts"
    profiles = sorted(
        ((account / engine, engine) for account in accounts.iterdir()
         if account.is_dir()
         for engine in ("claude", "codex")
         if (account / engine).is_dir()),
        key=lambda item: (item[0].parent.name, item[1]),
    ) if accounts.is_dir() else []
    # Dry-run must model the plan as if earlier profiles had already been
    # applied.  Otherwise every profile independently sees an empty real
    # ~/.claude and would incorrectly plan `move` for the same filename.
    virtual_base: set[str] | None = set() if dry_run else None
    for profile, engine in profiles:
        print(f"profile: {profile.parent.name}/{engine}")
        if engine == "claude":
            _build_claude_overlay(
                profile,
                home / ".claude",
                dry_run=dry_run,
                virtual_base=virtual_base,
                allow_legacy_migration=True,
            )
        else:
            _ensure_codex_profile_overlay(
                profile,
                home / ".codex",
                allow_legacy_migration=True,
                dry_run=dry_run,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate AI Hub Claude account profiles")
    parser.add_argument("--dry-run", action="store_true", help="print the name-only migration plan")
    parser.add_argument("--home", type=Path, help="HOME root to inspect (default: current HOME)")
    args = parser.parse_args()
    migrate_profiles((args.home or Path.home()).expanduser(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
