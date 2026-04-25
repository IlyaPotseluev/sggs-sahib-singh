#!/usr/bin/env python3
"""
Rebuilds ang JSON files using banidb (gurmukhi) + Granth Darpan (Sahib Singh) + ChatGPT.

One command fixes everything: scans for broken angs, deletes them, rebuilds via Darpan.

Usage:
  # Fix all detected problems in the full range
  python rebuild_from_darpan.py --fix all

  # Fix only duplicates (1..1430)
  python rebuild_from_darpan.py --fix duplicate

  # Fix specific issue type in a range
  python rebuild_from_darpan.py --fix missing --start 1000 --end 1430

  # Fix specific angs by number (no scanning needed)
  python rebuild_from_darpan.py 1078 1079

Issue types for --fix:
  missing        — ang JSON file does not exist
  empty          — JSON exists but has no lines
  duplicate      — ang shares verse_ids with another ang (probing error)
  coverage_gap   — ang exists but is missing lines vs banidb
  all            — all of the above
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from playwright_stealth import Stealth

from chatgpt_khojgurbani_sahibsingh_bot import (
    BOT_PROFILE,
    DEFAULT_CHAT_URL,
    ROMANIZATION_RULES,
    RUSSIAN_GLOSSARY,
    AngTranslation,
    OutputLine,
    RuntimeConfig,
    ang_json_path,
    extract_json_candidate,
    normalize_text,
    open_chat_tab,
    repair_json_quotes,
    save_ang_json,
    send_prompt_and_get_answer,
)
from validate_angs import (
    BANIDB_PATH,
    find_cross_ang_duplicates,
    validate_range,
)

_stealth = Stealth()

REPO_ROOT = Path(__file__).parent
ANG_JSON_DIR = REPO_ROOT / "ang_json"
DARPAN_BASE = "https://www.gurugranthdarpan.net"

DARPAN_PROMPT = """\
Игнорируй весь предыдущий контекст этого чата.
Используй только текст текущего сообщения.

Тебе даны:
1. Строки анга {ang} на гурмукхи (каждая помечена своим verse_id).
2. Полный текст страницы Грантх Дарпан для этого анга.
   Грантх Дарпан — это разбор проф. Sahib Singh: гурмукхи + панджабский перевод/комментарий.

Задача: для каждой строки гурмукхи найди соответствующий панджабский перевод Sahib Singh
в тексте Дарпана и верни JSON строго между BEGIN_KG_JSON и END_KG_JSON.

Строки анга — {expected_lines} шт.:
{gurmukhi_block}

Текст Грантх Дарпан (анг {ang}):
---
{darpan_text}
---

{romanization_rules}

{russian_glossary}

Правила:
- верни ровно {expected_lines} элементов в "lines", по одному на каждую строку гурмукхи;
- для каждой строки: verse_id (integer), roman (romanization гурмукхи), translation_ru (перевод на русский);
- translation_ru НИКОГДА не должен быть пустым — для каждой строки обязателен перевод:
  а) если нашёл перевод Sahib Singh в Дарпане — используй его (приоритет);
  б) если строка не найдена в Дарпане — переведи гурмукхи напрямую с панджабского/санскрита на русский самостоятельно, сохраняя духовный стиль;
- не добавляй пояснений, markdown, code fences;
- никогда не используй ASCII-кавычки " " внутри значений — используй «ёлочки»;
- ответ строго между BEGIN_KG_JSON и END_KG_JSON.

BEGIN_KG_JSON
{{
  "ang": {ang},
  "lines": [
    {{
      "verse_id": 123,
      "roman": "...",
      "translation_ru": "..."
    }}
  ]
}}
END_KG_JSON
"""


# ---------------------------------------------------------------------------
# TODO marking for header lines
# ---------------------------------------------------------------------------

def _is_header_line(gurmukhi: str) -> bool:
    words = gurmukhi.split()
    return len(words) <= 4 or "ਮਹਲਾ" in gurmukhi or "ਰਾਗੁ" in gurmukhi or "ਰਹਾਉ" in gurmukhi


def mark_todos(json_dir: Path, start: int, end: int) -> tuple[int, int]:
    """Mark empty translation_ru in header lines as 'TODO'.

    Returns (angs_changed, lines_marked).
    """
    angs_changed = 0
    lines_marked = 0

    for ang in range(start, end + 1):
        p = json_dir / f"ang_{ang:04d}.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        changed = False
        for line in data.get("lines", []):
            if not line.get("translation_ru", "").strip() and _is_header_line(
                line.get("gurmukhi", "")
            ):
                line["translation_ru"] = "TODO"
                lines_marked += 1
                changed = True
        if changed:
            p.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            angs_changed += 1

    return angs_changed, lines_marked


# ---------------------------------------------------------------------------
# banidb helpers
# ---------------------------------------------------------------------------

def banidb_lines_for_ang(banidb_path: Path, ang: int) -> list[dict]:
    """Returns [{verse_id, gurmukhi}] from banidb for the given ang."""
    import sqlite3
    conn = sqlite3.connect(str(banidb_path))
    cur = conn.cursor()
    cur.execute("SELECT verse_id, gurmukhi FROM verses WHERE ang=? ORDER BY verse_id", (ang,))
    rows = [{"verse_id": r[0], "gurmukhi": r[1]} for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Granth Darpan scraping
# ---------------------------------------------------------------------------

def scrape_darpan(context, ang: int, page_timeout_ms: int) -> str:
    url = f"{DARPAN_BASE}/{ang:04d}.html"
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=page_timeout_ms)
        page.wait_for_timeout(1500)
        for selector in ["#content", "main", "article", ".entry-content", "body"]:
            try:
                el = page.locator(selector).first
                if el.count() > 0:
                    text = normalize_text(el.inner_text())
                    if len(text) > 300:
                        return text
            except Exception:
                continue
        return normalize_text(page.locator("body").inner_text())
    except PWTimeout:
        print(f"    ⚠ Таймаут загрузки Дарпана для анга {ang}")
        return ""
    except Exception as exc:
        print(f"    ⚠ Ошибка Дарпана: {exc}")
        return ""
    finally:
        page.close()


# ---------------------------------------------------------------------------
# Prompt + parse
# ---------------------------------------------------------------------------

def build_prompt(ang: int, banidb_rows: list[dict], darpan_text: str) -> str:
    gurmukhi_block = "\n".join(f"[{r['verse_id']}] {r['gurmukhi']}" for r in banidb_rows)
    # Cap darpan_text to avoid token overflow; 12k chars ≈ 3k tokens
    return DARPAN_PROMPT.format(
        ang=ang,
        expected_lines=len(banidb_rows),
        gurmukhi_block=gurmukhi_block,
        darpan_text=darpan_text[:20_000],
        romanization_rules=ROMANIZATION_RULES,
        russian_glossary=RUSSIAN_GLOSSARY,
    )


def parse_answer(answer: str, ang: int, banidb_rows: list[dict]) -> AngTranslation | None:
    candidate = extract_json_candidate(answer)
    if not candidate:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            data = json.loads(repair_json_quotes(candidate))
        except json.JSONDecodeError:
            return None

    lines_raw = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(lines_raw, list) or not lines_raw:
        return None

    vid_to_gurmukhi = {r["verse_id"]: r["gurmukhi"] for r in banidb_rows}
    out: list[OutputLine] = []
    for i, item in enumerate(lines_raw):
        if not isinstance(item, dict):
            continue
        try:
            verse_id = int(item["verse_id"])
        except Exception:
            continue
        out.append(OutputLine(
            index=i + 1,
            verse_id=verse_id,
            shabad_num=0,
            shabad_id=None,
            gurmukhi=vid_to_gurmukhi.get(verse_id, ""),
            site_roman="",
            sahib_singh_pa="",
            roman=normalize_text(str(item.get("roman", ""))),
            translation_ru=normalize_text(str(item.get("translation_ru", ""))),
        ))

    return AngTranslation(ang=ang, lines=out) if out else None


# ---------------------------------------------------------------------------
# Core rebuild for one ang
# ---------------------------------------------------------------------------

def rebuild_one(ang: int, context, chat_url: str, cfg: RuntimeConfig, banidb_path: Path) -> bool:
    banidb_rows = banidb_lines_for_ang(banidb_path, ang)
    if not banidb_rows:
        print(f"  ✗ banidb: нет строк для анга {ang}")
        return False
    print(f"  → banidb: {len(banidb_rows)} строк")

    print(f"  → Загружаю Грантх Дарпан…")
    darpan_text = scrape_darpan(context, ang, cfg.page_timeout_ms)
    if darpan_text:
        print(f"  → Дарпан: {len(darpan_text)} символов")
    else:
        print(f"  ⚠ Дарпан недоступен — отправлю без него (только гурмукхи)")

    prompt = build_prompt(ang, banidb_rows, darpan_text)

    chat_page = open_chat_tab(context, chat_url, cfg.page_timeout_ms)
    chat_page.bring_to_front()
    result = None
    try:
        for attempt in range(1, cfg.max_retries + 1):
            print(f"  → Попытка {attempt}/{cfg.max_retries} (ChatGPT)…")
            answer = send_prompt_and_get_answer(chat_page, prompt, cfg)
            if answer:
                result = parse_answer(answer, ang, banidb_rows)
                if result:
                    print(f"  ✓ Распознано: {len(result.lines)} строк")
                    break
                print("  ⚠ Ответ не прошёл разбор")
            else:
                print("  ⚠ Пустой ответ")
            if attempt < cfg.max_retries:
                time.sleep(cfg.retry_delay_s)
    finally:
        if not cfg.keep_chat_tabs:
            try:
                chat_page.close()
            except Exception:
                pass

    if result is None:
        print(f"  ✗ Не удалось пересобрать анг {ang}")
        return False

    json_path = save_ang_json(ANG_JSON_DIR, result)
    print(f"  ✓ Сохранён: {json_path.name}")
    return True


# ---------------------------------------------------------------------------
# Scan-based target collection
# ---------------------------------------------------------------------------

def collect_targets(
    fix_types: set[str],
    start: int,
    end: int,
    banidb_path: Path | None,
) -> tuple[list[int], list[int]]:
    """Returns (angs_to_delete, angs_to_rebuild).

    For duplicates: both angs in the pair are deleted and rebuilt.
    For others: the affected ang is deleted and rebuilt.
    """
    print(f"Сканирую анги {start}..{end}…")
    reports = validate_range(start, end, banidb_path)
    duplicates = find_cross_ang_duplicates(start, end)

    to_delete: set[int] = set()
    to_rebuild: set[int] = set()

    if "missing" in fix_types or "all" in fix_types:
        for r in reports:
            if r.missing:
                to_rebuild.add(r.ang)

    if "empty" in fix_types or "all" in fix_types:
        for r in reports:
            if r.empty:
                to_delete.add(r.ang)
                to_rebuild.add(r.ang)

    if "duplicate" in fix_types or "all" in fix_types:
        for ang_a, ang_b, _ in duplicates:
            to_delete.add(ang_a)
            to_delete.add(ang_b)
            to_rebuild.add(ang_a)
            to_rebuild.add(ang_b)

    if "coverage_gap" in fix_types or "all" in fix_types:
        for r in reports:
            if r.uncovered_lines:
                to_delete.add(r.ang)
                to_rebuild.add(r.ang)

    return sorted(to_delete), sorted(to_rebuild)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild ang JSON via banidb + Granth Darpan + ChatGPT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "angs", nargs="*", type=int,
        help="Конкретные анги (без сканирования)",
    )
    parser.add_argument(
        "--fix",
        choices=["missing", "empty", "duplicate", "coverage_gap", "all"],
        help="Тип проблемы для автофикса (сканирует диапазон и чинит)",
    )
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1430)
    parser.add_argument("--banidb", type=str, default=str(BANIDB_PATH))
    parser.add_argument("--chat-url", type=str, default=DEFAULT_CHAT_URL)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument("--page-timeout", type=int, default=30)
    parser.add_argument("--response-timeout", type=int, default=300)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Не спрашивать подтверждение")
    parser.add_argument("--mark-todos", action="store_true",
                        help="Пометить пустые translation_ru в заголовочных строках как TODO, без GPT")
    args = parser.parse_args()

    if args.mark_todos:
        print(f"Помечаю заголовки как TODO (анги {args.start}..{args.end})…")
        angs_changed, lines_marked = mark_todos(ANG_JSON_DIR, args.start, args.end)
        print(f"Готово: {lines_marked} строк в {angs_changed} ангах помечены как TODO")
        sys.exit(0)

    banidb_path = Path(args.banidb)
    if not banidb_path.exists():
        print(f"banidb не найден: {banidb_path}")
        sys.exit(1)

    cfg = RuntimeConfig(
        page_timeout_ms=args.page_timeout * 1000,
        input_timeout_ms=15_000,
        response_timeout_ms=args.response_timeout * 1000,
        new_message_timeout_ms=30_000,
        max_retries=args.max_retries,
        retry_delay_s=args.retry_delay,
        raw_log_dir=None,
        json_dir=ANG_JSON_DIR,
        keep_chat_tabs=False,
    )

    # Determine target angs
    if args.angs:
        # Explicit list — no scanning
        to_delete = [a for a in args.angs if ang_json_path(ANG_JSON_DIR, a).exists()]
        to_rebuild = list(args.angs)
    elif args.fix:
        to_delete, to_rebuild = collect_targets(
            {args.fix}, args.start, args.end, banidb_path
        )
    else:
        parser.print_help()
        sys.exit(0)

    if not to_rebuild:
        print("Нет ангов для пересборки.")
        sys.exit(0)

    # Show plan and confirm
    if to_delete:
        print(f"\nБудут удалены JSON ({len(to_delete)}): {to_delete}")
    print(f"Будут пересобраны ({len(to_rebuild)}): {to_rebuild}")
    print()
    if not args.yes:
        ans = input("Продолжить? [y/N] ").strip().lower()
        if ans != "y":
            print("Отменено.")
            sys.exit(0)

    # Delete broken JSONs
    for ang in to_delete:
        p = ang_json_path(ANG_JSON_DIR, ang)
        if p.exists():
            p.unlink()
            print(f"  ✗ Удалён {p.name}")

    # Open browser and rebuild
    BOT_PROFILE.mkdir(exist_ok=True)
    first_run = not (BOT_PROFILE / "Default").exists()

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(BOT_PROFILE),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        _stealth.apply_stealth_sync(context.pages[0] if context.pages else context.new_page())

        if first_run:
            page = open_chat_tab(context, args.chat_url, cfg.page_timeout_ms)
            input("\n>> Войди в ChatGPT и нажми ENTER…\n")
            page.close()

        ok, fail = 0, 0
        for i, ang in enumerate(to_rebuild):
            print(f"\n══ Анг {ang} ({i+1}/{len(to_rebuild)}) ══")
            if rebuild_one(ang, context, args.chat_url, cfg, banidb_path):
                ok += 1
            else:
                fail += 1
            if i < len(to_rebuild) - 1:
                time.sleep(args.delay)

        context.close()

    print(f"\n✓ Готово: {ok} успешно, {fail} не удалось")


if __name__ == "__main__":
    main()
