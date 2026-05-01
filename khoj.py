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
        validate_range, find_cross_ang_duplicates, run_menu,
        BANIDB_PATH, DARPAN_DB_PATH,
    )
    banidb_path = BANIDB_PATH if BANIDB_PATH.exists() else None
    darpan_path = DARPAN_DB_PATH if DARPAN_DB_PATH.exists() else None
    print(f"\nСканирую {start}..{end}…")
    reports = validate_range(start, end, banidb_path, darpan_path=darpan_path)
    duplicates = find_cross_ang_duplicates(start, end)
    if not reports:
        print("Нет данных.")
        return
    run_menu(reports, duplicates, start, end, fix_mode=fix_mode,
             banidb_path=banidb_path, darpan_path=darpan_path)


def _print_next_steps() -> None:
    rebuilt = REPO_ROOT / "ang_json_rebuilt"
    ang_json = REPO_ROOT / "ang_json"

    rebuilt_count = len(list(rebuilt.glob("ang_*.json"))) if rebuilt.exists() else 0
    current_count = len(list(ang_json.glob("ang_*.json"))) if ang_json.exists() else 0

    print("\n══ Рекомендации для продолжения работы ══\n")

    if rebuilt.exists() and rebuilt_count > 0:
        print(f"  1. Активировать пересобранные анги ({rebuilt_count} файлов в ang_json_rebuilt/):")
        print(f"       mv ang_json ang_json_old && mv ang_json_rebuilt ang_json")
        print()

    print("  2. Перевести пропущенные стихи (5 495 строк, 188 ангов):")
    print("       Добавить режим --source darpan-db в rebuild_from_darpan.py")
    print("       Источник: darpan.db (локально, без скрапинга сайта)")
    print()
    print("  3. Стратегия генерации ангов с нуля:")
    print("       banidb  → структура (ang, verse_id, порядок)")
    print("       darpan.db → комментарий Sahib Singh (по shabad_id)")
    print("       ChatGPT  → русский перевод")
    print()
    print("  4. TODO в TECHNICAL_CONCEPT_RU.md:")
    print("       Коэффициент доверия переводу (translation_trust 0.0–1.0)")
    print("       Влияет на отображение в WordPress")
    print()


def main() -> None:
    while True:
        print("\n══ Гурбани — главное меню ══\n")
        print("  [1] Переводить / DOCX / починить roman  (меню бота)")
        print("  [2] Сканировать проблемы (banidb — устарело, + Дарпан)")
        print("  [3] Сканировать и чинить через Дарпан")
        print("  [i] Что делать дальше")
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
        elif choice == "i":
            _print_next_steps()
        else:
            print("  Неизвестный выбор.")


if __name__ == "__main__":
    main()
