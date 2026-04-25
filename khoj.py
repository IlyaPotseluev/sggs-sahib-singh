#!/usr/bin/env python3
"""
Точка входа. python khoj.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
PYTHON = sys.executable


def _ask_range(default_start: int = 1, default_end: int = 1430) -> tuple[int, int]:
    print(f"\nДиапазон ангов (по умолчанию {default_start}..{default_end})")
    try:
        raw = input(f"  С анга [{default_start}]: ").strip()
        start = int(raw) if raw else default_start
        raw = input(f"  По анг [{default_end}]: ").strip()
        end = int(raw) if raw else default_end
    except (EOFError, KeyboardInterrupt, ValueError):
        start, end = default_start, default_end
    return max(1, min(start, 1430)), max(start, min(end, 1430))


def _run_bot_menu() -> None:
    subprocess.run([PYTHON, str(REPO_ROOT / "chatgpt_khojgurbani_sahibsingh_bot.py"), "--menu"])


def _run_scan(start: int, end: int, fix_mode: bool = False) -> None:
    from validate_angs import (
        validate_range, find_cross_ang_duplicates, run_menu, BANIDB_PATH,
    )
    banidb_path = BANIDB_PATH if BANIDB_PATH.exists() else None
    print(f"\nСканирую {start}..{end}…")
    reports = validate_range(start, end, banidb_path)
    duplicates = find_cross_ang_duplicates(start, end)
    if not reports:
        print("Нет данных.")
        return
    run_menu(reports, duplicates, start, end, fix_mode=fix_mode, banidb_path=banidb_path)


def main() -> None:
    while True:
        print("\n══ Гурбани — главное меню ══\n")
        print("  [1] Переводить / DOCX / починить roman  (меню бота)")
        print("  [2] Сканировать проблемы vs banidb")
        print("  [3] Сканировать и чинить через Дарпан")
        print("  [q] Выйти")
        try:
            choice = input("\n  Выбор: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "q":
            break
        elif choice == "1":
            _run_bot_menu()
        elif choice in ("2", "3"):
            start, end = _ask_range()
            _run_scan(start, end, fix_mode=(choice == "3"))
        else:
            print("  Неизвестный выбор.")


if __name__ == "__main__":
    main()
