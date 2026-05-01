#!/usr/bin/env python3
"""
Validates ang_json/ against banidb.

Checks (in order):
  1. Missing JSON files in the given range
  2. JSON files with empty lines list
  3. verse_id coverage vs banidb (which banidb verses are absent from our data)
  4. Gurmukhi text mismatches for shared verse_ids

Usage:
  python validate_angs.py [--start 1] [--end 1430] [--banidb PATH] [--verbose]
  python validate_angs.py --no-banidb               # file-existence check only
  python validate_angs.py --missing-only            # print missing angs, one per line
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent
ANG_JSON_DIR = REPO_ROOT / "ang_json"
BANIDB_PATH = REPO_ROOT.parent / "banidb" / "sggs.db"
DARPAN_DB_PATH = REPO_ROOT / "darpan.db"
DARPAN_BASE = "https://www.gurugranthdarpan.net"

_UDAAT = "ੑ"  # U+0A51 — present in banidb, absent from KhojGurbani (stylistic)

# Stanza markers: ॥੯॥  ॥੧੦॥  ।੧।  — differ between banidb and KhojGurbani
_RE_STANZA = re.compile(r"[॥।]+\s*[\d੦-੯]+\s*[॥।]+")


def darpan_url(ang: int) -> str:
    return f"{DARPAN_BASE}/{ang:04d}.html"


def norm_gurmukhi(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace(_UDAAT, "").strip()


def norm_for_match(text: str) -> str:
    """Loose match: strip stanza-number markers before comparing."""
    return _RE_STANZA.sub("", norm_gurmukhi(text)).strip()


def is_header_line(gurmukhi: str) -> bool:
    words = gurmukhi.split()
    return len(words) <= 4 or "ਮਹਲਾ" in gurmukhi or "ਰਾਗੁ" in gurmukhi or "ਰਹਾਉ" in gurmukhi


@dataclass
class AngReport:
    ang: int
    missing: bool = False
    empty: bool = False
    our_line_count: int = 0
    db_line_count: int = 0
    uncovered_lines: list[tuple[int, str]] = field(default_factory=list)  # (verse_id, gurmukhi)
    gurmukhi_mismatches: list[tuple[int, str, str]] = field(default_factory=list)
    null_translation_lines: list[tuple[int, str]] = field(default_factory=list)   # (verse_id, gurmukhi)
    darpan_ang_mismatches:  list[tuple[int, int, str]] = field(default_factory=list)  # (verse_id, darpan_ang, gurmukhi)

    @property
    def has_issues(self) -> bool:
        return (
            self.missing
            or self.empty
            or bool(self.uncovered_lines)
            or bool(self.gurmukhi_mismatches)
            or bool(self.null_translation_lines)
            or bool(self.darpan_ang_mismatches)
        )


def load_our_ang(ang: int) -> tuple[dict[int, str], set[str]] | tuple[None, None]:
    """Returns ({verse_id: gurmukhi}, {stripped_gurmukhi}) or (None, None) if no JSON."""
    p = ANG_JSON_DIR / f"ang_{ang:04d}.json"
    if not p.exists():
        return None, None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    lines = data.get("lines", [])
    by_id: dict[int, str] = {}
    stripped: set[str] = set()
    for line in lines:
        if "verse_id" not in line:
            continue
        g = norm_gurmukhi(str(line.get("gurmukhi", "")))
        by_id[int(line["verse_id"])] = g
        stripped.add(norm_for_match(g))
    return by_id, stripped


def null_translation_lines_for_ang(ang: int) -> list[tuple[int, str]]:
    """Returns (verse_id, gurmukhi) for content lines with missing/None translation_ru."""
    p = ANG_JSON_DIR / f"ang_{ang:04d}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    result = []
    for line in data.get("lines", []):
        if "verse_id" not in line:
            continue
        ru = line.get("translation_ru", "")
        gurmukhi = str(line.get("gurmukhi", ""))
        if (not ru or ru == "None") and not is_header_line(gurmukhi):
            result.append((int(line["verse_id"]), gurmukhi))
    return result


def validate_range(
    start: int,
    end: int,
    banidb_path: Path | None,
    darpan_path: Path | None = None,
    verbose: bool = False,
) -> list[AngReport]:
    conn = None
    if banidb_path and banidb_path.exists():
        conn = sqlite3.connect(str(banidb_path))

    darpan_conn = None
    _darpan_has_ang_end = False
    if darpan_path and darpan_path.exists():
        darpan_conn = sqlite3.connect(str(darpan_path))
        cols = {r[1] for r in darpan_conn.execute("PRAGMA table_info(shabads)")}
        _darpan_has_ang_end = "ang_end" in cols

    reports: list[AngReport] = []

    for ang in range(start, end + 1):
        our_data, our_stripped = load_our_ang(ang)
        report = AngReport(ang=ang)

        if our_data is None:
            report.missing = True
            reports.append(report)
            continue

        report.our_line_count = len(our_data)

        if not our_data:
            report.empty = True
            reports.append(report)
            continue

        report.null_translation_lines = null_translation_lines_for_ang(ang)

        if darpan_conn is not None:
            dcur = darpan_conn.cursor()
            if _darpan_has_ang_end:
                _darpan_q = """SELECT s.ang, s.ang_end
                               FROM lines l JOIN shabads s ON l.shabad_id = s.id
                               WHERE l.verse_id = ? AND l.match_score = 1.0
                               LIMIT 1"""
            else:
                _darpan_q = """SELECT s.ang, s.ang
                               FROM lines l JOIN shabads s ON l.shabad_id = s.id
                               WHERE l.verse_id = ? AND l.match_score = 1.0
                               LIMIT 1"""
            for verse_id, gurmukhi in our_data.items():
                dcur.execute(_darpan_q, (verse_id,))
                row = dcur.fetchone()
                if row:
                    darpan_start, darpan_end = row
                    if not (darpan_start <= ang <= darpan_end):
                        report.darpan_ang_mismatches.append((verse_id, darpan_start, gurmukhi))

        if conn is None:
            reports.append(report)
            continue

        cur = conn.cursor()
        cur.execute(
            "SELECT verse_id, gurmukhi FROM verses WHERE ang = ? ORDER BY verse_id",
            (ang,),
        )
        db_rows = [(row[0], norm_gurmukhi(row[1])) for row in cur.fetchall()]
        report.db_line_count = len(db_rows)

        for db_vid, db_gurmukhi in db_rows:
            if db_vid in our_data:
                # Exact verse_id match: check gurmukhi (loose — strip stanza numbers)
                if norm_for_match(our_data[db_vid]) != norm_for_match(db_gurmukhi):
                    report.gurmukhi_mismatches.append((db_vid, our_data[db_vid], db_gurmukhi))
            elif norm_for_match(db_gurmukhi) in our_stripped:
                # Text matches under a different verse_id (numbering variant) — not a true miss
                pass
            else:
                report.uncovered_lines.append((db_vid, db_gurmukhi))

        reports.append(report)

    if conn:
        conn.close()
    if darpan_conn:
        darpan_conn.close()

    return reports


def find_cross_ang_duplicates(start: int, end: int) -> list[tuple[int, int, list[int]]]:
    """Find pairs of angs that share verse_ids (same shabad scraped twice).

    Returns list of (ang_a, ang_b, [shared_verse_ids]).
    Only reports pairs where shared count is significant (>= 3).
    """
    ang_to_vids: dict[int, set[int]] = {}
    for ang in range(start, end + 1):
        p = ANG_JSON_DIR / f"ang_{ang:04d}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        vids = {int(line["verse_id"]) for line in data.get("lines", []) if "verse_id" in line}
        if vids:
            ang_to_vids[ang] = vids

    duplicates: list[tuple[int, int, list[int]]] = []
    angs = sorted(ang_to_vids)
    for i, a in enumerate(angs):
        for b in angs[i + 1:]:
            if b > a + 10:  # only check nearby angs — distant ones won't share
                break
            shared = sorted(ang_to_vids[a] & ang_to_vids[b])
            if len(shared) >= 3:
                duplicates.append((a, b, shared))

    return duplicates


LOG_DB_PATH = REPO_ROOT / "validation_log.db"


def _open_log_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            ang_start INTEGER,
            ang_end   INTEGER
        );
        CREATE TABLE IF NOT EXISTS issues (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ang           INTEGER NOT NULL,
            issue_type    TEXT NOT NULL,
            detail        TEXT,
            first_seen_run INTEGER NOT NULL REFERENCES scan_runs(id),
            first_seen_ts  TEXT NOT NULL,
            resolved_run   INTEGER REFERENCES scan_runs(id),
            resolved_ts    TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_issues ON issues(ang, issue_type, detail);
    """)
    conn.commit()
    return conn


def _collect_current_issues(
    reports: list[AngReport],
    duplicates: list[tuple[int, int, list[int]]],
) -> list[tuple[int, str, str]]:
    """Returns list of (ang, issue_type, detail) for all current issues."""
    items: list[tuple[int, str, str]] = []
    for r in reports:
        if r.missing:
            items.append((r.ang, "missing", ""))
        if r.empty:
            items.append((r.ang, "empty", ""))
        if r.uncovered_lines:
            items.append((r.ang, "coverage_gap", str(len(r.uncovered_lines))))
        if r.gurmukhi_mismatches:
            items.append((r.ang, "gurmukhi_mismatch", str(len(r.gurmukhi_mismatches))))
        if r.null_translation_lines:
            items.append((r.ang, "null_translation", str(len(r.null_translation_lines))))
        if r.darpan_ang_mismatches:
            items.append((r.ang, "darpan_ang_mismatch", str(len(r.darpan_ang_mismatches))))
    for ang_a, ang_b, shared in duplicates:
        detail = f"↔{ang_b}:{len(shared)}"
        items.append((ang_a, "duplicate", detail))
        detail_b = f"↔{ang_a}:{len(shared)}"
        items.append((ang_b, "duplicate", detail_b))
    return items


def save_scan_log(
    reports: list[AngReport],
    duplicates: list[tuple[int, int, list[int]]],
    start: int,
    end: int,
    log_path: Path = LOG_DB_PATH,
) -> tuple[int, int, int]:
    """Save scan results to log DB. Returns (new_issues, resolved, unchanged)."""
    conn = _open_log_db(log_path)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cur = conn.cursor()
    cur.execute("INSERT INTO scan_runs (ts, ang_start, ang_end) VALUES (?,?,?)", (ts, start, end))
    run_id = cur.lastrowid
    conn.commit()

    current = _collect_current_issues(reports, duplicates)
    current_set = {(ang, itype, detail) for ang, itype, detail in current}

    # Mark resolved: open issues in range that are no longer present
    cur.execute(
        "SELECT id, ang, issue_type, detail FROM issues "
        "WHERE resolved_run IS NULL AND ang >= ? AND ang <= ?",
        (start, end),
    )
    existing_open = cur.fetchall()
    resolved = 0
    for eid, ang, itype, detail in existing_open:
        if (ang, itype, detail) not in current_set:
            cur.execute(
                "UPDATE issues SET resolved_run=?, resolved_ts=? WHERE id=?",
                (run_id, ts, eid),
            )
            resolved += 1

    # Insert new issues
    cur.execute(
        "SELECT ang, issue_type, detail FROM issues WHERE resolved_run IS NULL",
    )
    still_open = {(r[0], r[1], r[2]) for r in cur.fetchall()}

    new_count = 0
    for ang, itype, detail in current:
        if (ang, itype, detail) not in still_open:
            cur.execute(
                "INSERT OR IGNORE INTO issues "
                "(ang, issue_type, detail, first_seen_run, first_seen_ts) VALUES (?,?,?,?,?)",
                (ang, itype, detail, run_id, ts),
            )
            new_count += 1

    unchanged = len(current) - new_count
    conn.commit()
    conn.close()
    return new_count, resolved, unchanged


def print_log_history(log_path: Path = LOG_DB_PATH, limit: int = 20) -> None:
    if not log_path.exists():
        print("Лог-файл не найден.")
        return
    conn = sqlite3.connect(str(log_path))
    cur = conn.cursor()

    cur.execute("SELECT id, ts, ang_start, ang_end FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,))
    runs = cur.fetchall()
    print(f"Последние {len(runs)} скана:")
    for rid, ts, a, b in runs:
        cur.execute("SELECT COUNT(*) FROM issues WHERE first_seen_run=?", (rid,))
        new = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM issues WHERE resolved_run=?", (rid,))
        fixed = cur.fetchone()[0]
        print(f"  #{rid:4d}  {ts}  анги {a}..{b}  +{new} новых  -{fixed} исправлено")

    print()
    cur.execute("SELECT COUNT(*) FROM issues WHERE resolved_run IS NULL")
    open_total = cur.fetchone()[0]
    print(f"Открытых проблем всего: {open_total}")

    cur.execute(
        "SELECT issue_type, COUNT(*) FROM issues WHERE resolved_run IS NULL GROUP BY issue_type"
    )
    for itype, cnt in cur.fetchall():
        print(f"  {itype}: {cnt}")

    conn.close()


def print_report(
    reports: list[AngReport],
    duplicates: list[tuple[int, int, list[int]]],
    verbose: bool = False,
) -> None:
    total = len(reports)
    missing_angs = [r for r in reports if r.missing]
    empty_angs = [r for r in reports if r.empty]
    coverage_gaps = [r for r in reports if r.uncovered_lines]
    mismatches = [r for r in reports if r.gurmukhi_mismatches]
    dup_angs = {a for a, b, _ in duplicates} | {b for a, b, _ in duplicates}
    ok_count = sum(1 for r in reports if not r.has_issues and r.ang not in dup_angs)

    print(f"\n══ Validation: анги {reports[0].ang}..{reports[-1].ang} ({total} шт.) ══\n")

    if missing_angs:
        print(f"Отсутствующие JSON ({len(missing_angs)}):")
        for r in missing_angs:
            print(f"  Анг {r.ang:4d}  →  {darpan_url(r.ang)}")
        print()

    if empty_angs:
        print(f"Пустые JSON — нет строк ({len(empty_angs)}):")
        for r in empty_angs:
            print(f"  Анг {r.ang:4d}  →  {darpan_url(r.ang)}")
        print()

    if coverage_gaps:
        total_missing = sum(len(r.uncovered_lines) for r in coverage_gaps)
        print(f"Неполное покрытие vs banidb ({len(coverage_gaps)} ангов, {total_missing} строк):")
        for r in coverage_gaps:
            lines = r.uncovered_lines
            print(f"  Анг {r.ang:4d}: {r.our_line_count} строк (banidb: {r.db_line_count}), "
                  f"пропущено {len(lines)}  →  {darpan_url(r.ang)}")
            if verbose:
                for vid, gurmukhi in lines:
                    print(f"    [{vid:5d}] {gurmukhi}")
        print()

    if duplicates:
        print(f"Дублирование verse_id между ангами ({len(duplicates)} пар) — один шабад засчитан дважды:")
        for ang_a, ang_b, shared in duplicates:
            pct = len(shared) * 100 // max(1, len(shared))
            print(f"  Анг {ang_a:4d} ↔ Анг {ang_b:4d}: {len(shared)} общих verse_id")
            if verbose:
                short = ", ".join(str(v) for v in shared[:6])
                suffix = f" … ещё {len(shared) - 6}" if len(shared) > 6 else ""
                print(f"    verse_ids: [{short}{suffix}]")
                print(f"    {darpan_url(ang_a)}")
                print(f"    {darpan_url(ang_b)}")
        print()

    if mismatches:
        total_mm = sum(len(r.gurmukhi_mismatches) for r in mismatches)
        print(f"Несовпадение гурмукхи ({len(mismatches)} ангов, {total_mm} строк):")
        for r in mismatches:
            print(f"  Анг {r.ang:4d} ({len(r.gurmukhi_mismatches)} строк)  →  {darpan_url(r.ang)}")
            if verbose:
                for vid, our, db in r.gurmukhi_mismatches[:2]:
                    print(f"    verse_id {vid}:")
                    print(f"      Наш:    {our[:80]}")
                    print(f"      banidb: {db[:80]}")
        print()

    darp_mm = [r for r in reports if r.darpan_ang_mismatches]
    if darp_mm:
        total_dm = sum(len(r.darpan_ang_mismatches) for r in darp_mm)
        print(f"Неправильный анг по Дарпану ({len(darp_mm)} ангов, {total_dm} строк):")
        for r in darp_mm:
            print(f"  Анг {r.ang:4d} ({len(r.darpan_ang_mismatches)} строк)  →  {darpan_url(r.ang)}")
            if verbose:
                for vid, dang, g in r.darpan_ang_mismatches[:3]:
                    print(f"    [{vid:5d}] Дарпан: анг {dang}  |  {g[:70]}")
        print()

    print("Итого:")
    print(f"  Проверено:               {total}")
    print(f"  OK:                      {ok_count}")
    if missing_angs:
        print(f"  Отсутствуют:             {len(missing_angs)}")
    if empty_angs:
        print(f"  Пустые:                  {len(empty_angs)}")
    if duplicates:
        print(f"  Дублированные пары:      {len(duplicates)}")
    if coverage_gaps:
        print(f"  Неполное покрытие:       {len(coverage_gaps)}")
    if mismatches:
        print(f"  Несовпадение гурмукхи:   {len(mismatches)}")
    if darp_mm:
        print(f"  Неправильный анг (Дарп): {len(darp_mm)}")


def _ask_range(default_start: int = 1, default_end: int = 1430) -> tuple[int, int]:
    print(f"\nДиапазон ангов для сканирования (по умолчанию {default_start}..{default_end})")
    try:
        raw = input(f"  С анга [{default_start}]: ").strip()
        start = int(raw) if raw else default_start
        raw = input(f"  По анг [{default_end}]: ").strip()
        end = int(raw) if raw else default_end
    except (EOFError, KeyboardInterrupt, ValueError):
        start, end = default_start, default_end
    start = max(1, min(start, 1430))
    end = max(start, min(end, 1430))
    return start, end


ISSUE_LABELS = {
    "missing":              "Отсутствует файл",
    "empty":                "Пустой файл (нет строк)",
    "coverage_gap":         "Неполное покрытие vs banidb",
    "duplicate":            "Дубль шабада (два анга — один контент)",
    "gurmukhi_mismatch":    "Несовпадение текста гурмукхи",
    "null_translation":     "Пустой перевод (нет translation_ru)",
    "darpan_ang_mismatch":  "Неправильный анг (не совпадает с Дарпаном)",
}


def _menu_summary(
    reports: list[AngReport],
    duplicates: list[tuple[int, int, list[int]]],
    start: int,
    end: int,
) -> None:
    missing  = [r for r in reports if r.missing]
    empty    = [r for r in reports if r.empty]
    gaps     = [r for r in reports if r.uncovered_lines]
    mm       = [r for r in reports if r.gurmukhi_mismatches]
    null_tr  = [r for r in reports if r.null_translation_lines]
    darp_mm  = [r for r in reports if r.darpan_ang_mismatches]
    dup_angs = {a for a, b, _ in duplicates} | {b for a, b, _ in duplicates}
    ok = sum(1 for r in reports if not r.has_issues and r.ang not in dup_angs)
    problem_angs = len(missing) + len(empty) + len(gaps) + len(mm) + len(dup_angs) + len(null_tr) + len(darp_mm)

    print(f"\n══ Сканирование ангов {start}..{end} ({len(reports)} шт.) ══\n")
    print(f"  OK: {ok}   Проблемных: {problem_angs}\n")
    print("  Категории проблем:")
    rows = [
        ("1", "missing",           f"{len(missing)} анг(ов)", ""),
        ("2", "empty",             f"{len(empty)} анг(ов)", ""),
        ("3", "coverage_gap",
            f"{len(gaps)} анг(ов)",
            f"({sum(len(r.uncovered_lines) for r in gaps)} строк)" if gaps else ""),
        ("4", "duplicate",
            f"{len(duplicates)} пар(ы)",
            f"({len(dup_angs)} анга)" if duplicates else ""),
        ("5", "gurmukhi_mismatch",
            f"{len(mm)} анг(ов)",
            f"({sum(len(r.gurmukhi_mismatches) for r in mm)} строк)" if mm else ""),
        ("6", "null_translation",
            f"{len(null_tr)} анг(ов)",
            f"({sum(len(r.null_translation_lines) for r in null_tr)} строк)" if null_tr else ""),
        ("7", "darpan_ang_mismatch",
            f"{len(darp_mm)} анг(ов)",
            f"({sum(len(r.darpan_ang_mismatches) for r in darp_mm)} строк)" if darp_mm else ""),
    ]
    for num, key, count, extra in rows:
        label = ISSUE_LABELS[key]
        has_issue = bool({
            "missing": missing, "empty": empty, "coverage_gap": gaps,
            "duplicate": duplicates, "gurmukhi_mismatch": mm,
            "null_translation": null_tr, "darpan_ang_mismatch": darp_mm,
        }[key])
        marker = "! " if has_issue else "  "
        print(f"    [{num}] {marker}{label:<45}  {count} {extra}")
    print()


def _menu_detail_missing(reports: list[AngReport]) -> None:
    items = [r for r in reports if r.missing]
    if not items:
        print("  Нет отсутствующих ангов.")
        return
    print(f"\n── Отсутствует файл ({len(items)} анг(ов)) ──\n")
    for r in items:
        print(f"  Анг {r.ang:4d}   {darpan_url(r.ang)}")


def _menu_detail_empty(reports: list[AngReport]) -> None:
    items = [r for r in reports if r.empty]
    if not items:
        print("  Нет пустых ангов.")
        return
    print(f"\n── Пустой файл ({len(items)} анг(ов)) ──\n")
    for r in items:
        print(f"  Анг {r.ang:4d}   {darpan_url(r.ang)}")


def _menu_detail_gaps(reports: list[AngReport], verbose: bool) -> None:
    items = [r for r in reports if r.uncovered_lines]
    if not items:
        print("  Нет ангов с неполным покрытием.")
        return
    total_lines = sum(len(r.uncovered_lines) for r in items)
    print(f"\n── Неполное покрытие ({len(items)} анг(ов), {total_lines} строк) ──\n")
    for r in items:
        print(f"  Анг {r.ang:4d}  наших {r.our_line_count} / banidb {r.db_line_count} "
              f"— пропущено {len(r.uncovered_lines):3d}   {darpan_url(r.ang)}")
        if verbose:
            for vid, g in r.uncovered_lines[:5]:
                print(f"      [{vid:5d}] {g[:90]}")
            if len(r.uncovered_lines) > 5:
                print(f"      … ещё {len(r.uncovered_lines) - 5}")


def _menu_detail_duplicates(
    duplicates: list[tuple[int, int, list[int]]],
    verbose: bool,
) -> None:
    if not duplicates:
        print("  Дублей не обнаружено.")
        return
    print(f"\n── Дубль шабада ({len(duplicates)} пар(ы)) ──\n")
    for ang_a, ang_b, shared in duplicates:
        print(f"  Анг {ang_a:4d} ↔ Анг {ang_b:4d}   {len(shared)} общих verse_id")
        if verbose:
            s = ", ".join(str(v) for v in shared[:8])
            sfx = f" … ещё {len(shared)-8}" if len(shared) > 8 else ""
            print(f"      verse_ids: [{s}{sfx}]")
        print(f"      {darpan_url(ang_a)}")
        print(f"      {darpan_url(ang_b)}")


def _menu_detail_mismatches(reports: list[AngReport], verbose: bool) -> None:
    items = [r for r in reports if r.gurmukhi_mismatches]
    if not items:
        print("  Нет несовпадений гурмукхи.")
        return
    total = sum(len(r.gurmukhi_mismatches) for r in items)
    print(f"\n── Несовпадение гурмукхи ({len(items)} анг(ов), {total} строк) ──\n")
    for r in items:
        print(f"  Анг {r.ang:4d}  {len(r.gurmukhi_mismatches)} строк   {darpan_url(r.ang)}")
        if verbose:
            for vid, our, db in r.gurmukhi_mismatches[:2]:
                print(f"      verse_id {vid}:")
                print(f"        наш:    {our[:80]}")
                print(f"        banidb: {db[:80]}")


def _menu_detail_null_translations(reports: list[AngReport], verbose: bool) -> None:
    items = [r for r in reports if r.null_translation_lines]
    if not items:
        print("  Нет ангов с пустыми переводами.")
        return
    total = sum(len(r.null_translation_lines) for r in items)
    print(f"\n── Пустой перевод ({len(items)} анг(ов), {total} строк) ──\n")
    for r in items:
        print(f"  Анг {r.ang:4d}  {len(r.null_translation_lines)} строк   {darpan_url(r.ang)}")
        if verbose:
            for vid, g in r.null_translation_lines[:3]:
                print(f"      [{vid:5d}] {g[:80]}")
            if len(r.null_translation_lines) > 3:
                print(f"      … ещё {len(r.null_translation_lines) - 3}")


def _menu_detail_darpan_mismatches(reports: list[AngReport], verbose: bool) -> None:
    items = [r for r in reports if r.darpan_ang_mismatches]
    if not items:
        print("  Нет несовпадений с Дарпаном.")
        return
    total = sum(len(r.darpan_ang_mismatches) for r in items)
    print(f"\n── Неправильный анг по Дарпану ({len(items)} анг(ов), {total} строк) ──\n")
    for r in items:
        print(f"  Анг {r.ang:4d}  {len(r.darpan_ang_mismatches)} строк   {darpan_url(r.ang)}")
        if verbose:
            for vid, darpan_ang, g in r.darpan_ang_mismatches[:5]:
                print(f"      [{vid:5d}] Дарпан: анг {darpan_ang}  |  {g[:70]}")
            if len(r.darpan_ang_mismatches) > 5:
                print(f"      … ещё {len(r.darpan_ang_mismatches) - 5}")


_FIX_TYPE = {
    "1": "missing",
    "2": "empty",
    "3": "coverage_gap",
    "4": "duplicate",
    "5": "gurmukhi_mismatch",
    "6": "null_translation",
    "7": "darpan_ang_mismatch",
}


def _run_fix(
    fix_type: str,
    start: int,
    end: int,
    reports: list[AngReport],
) -> None:
    import subprocess as _sp
    fix_script = REPO_ROOT / "rebuild_from_darpan.py"
    if not fix_script.exists():
        print("  rebuild_from_darpan.py не найден.")
        return

    if fix_type == "gurmukhi_mismatch":
        angs = [str(r.ang) for r in reports if r.gurmukhi_mismatches]
        if not angs:
            print("  Нет ангов для починки.")
            return
        cmd = [__import__("sys").executable, str(fix_script)] + angs
    elif fix_type == "null_translation":
        angs = [str(r.ang) for r in reports if r.null_translation_lines]
        if not angs:
            print("  Нет ангов для починки.")
            return
        cmd = [__import__("sys").executable, str(fix_script)] + angs
    else:
        cmd = [
            __import__("sys").executable, str(fix_script),
            "--fix", fix_type,
            "--start", str(start), "--end", str(end),
        ]

    print(f"\n  → {' '.join(cmd[2:])}\n")
    _sp.run(cmd)


def run_menu(
    reports: list[AngReport],
    duplicates: list[tuple[int, int, list[int]]],
    start: int,
    end: int,
    fix_mode: bool = False,
    banidb_path: Path | None = None,
    darpan_path: Path | None = None,
) -> None:
    verbose = False
    while True:
        _menu_summary(reports, duplicates, start, end)

        if fix_mode:
            print("  [v] детали строк  [f+номер] починить категорию (напр. f4)  [q] выйти")
        else:
            print("  [v] переключить детали строк  [q] выйти")
        print()
        try:
            choice = input("  Выбери категорию [1-7 / v / q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "q":
            break

        if choice == "v":
            verbose = not verbose
            print(f"  → детали {'включены' if verbose else 'выключены'}\n")
            continue

        # Fix command: f1..f6
        if fix_mode and len(choice) == 2 and choice[0] == "f" and choice[1] in _FIX_TYPE:
            fix_type = _FIX_TYPE[choice[1]]
            _run_fix(fix_type, start, end, reports)
            print(f"\n  Пересканирую {start}..{end}…")
            reports = validate_range(start, end, banidb_path, darpan_path=darpan_path)
            duplicates = find_cross_ang_duplicates(start, end)
            continue

        if choice == "1":
            _menu_detail_missing(reports)
        elif choice == "2":
            _menu_detail_empty(reports)
        elif choice == "3":
            _menu_detail_gaps(reports, verbose)
        elif choice == "4":
            _menu_detail_duplicates(duplicates, verbose)
        elif choice == "5":
            _menu_detail_mismatches(reports, verbose)
        elif choice == "6":
            _menu_detail_null_translations(reports, verbose)
        elif choice == "7":
            _menu_detail_darpan_mismatches(reports, verbose)
        else:
            print("  Неизвестный выбор.")
            continue

        print()
        try:
            input("  [Enter] — вернуться в меню…")
        except (EOFError, KeyboardInterrupt):
            print()
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate ang_json/ against banidb")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1430)
    parser.add_argument("--banidb", type=str, default=str(BANIDB_PATH))
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Показывать детали несовпадений (только в режиме --plain)")
    parser.add_argument("--plain", action="store_true",
                        help="Без меню: вывести полный отчёт и выйти")
    parser.add_argument("--no-banidb", action="store_true",
                        help="Только проверять наличие файлов, без сравнения содержимого")
    parser.add_argument("--missing-only", action="store_true",
                        help="Вывести только список отсутствующих ангов (один на строку)")
    parser.add_argument("--darpan", type=str, default=str(DARPAN_DB_PATH),
                        help="Путь к darpan.db для проверки ang-принадлежности Гурбани")
    parser.add_argument("--no-darpan", action="store_true",
                        help="Не использовать darpan.db")
    parser.add_argument("--save-log", action="store_true",
                        help="Сохранить результаты скана в validation_log.db")
    parser.add_argument("--show-log", action="store_true",
                        help="Показать историю сканов из validation_log.db и выйти")
    args = parser.parse_args()

    if args.show_log:
        print_log_history()
        return

    if args.missing_only:
        for ang in range(args.start, args.end + 1):
            p = ANG_JSON_DIR / f"ang_{ang:04d}.json"
            if not p.exists():
                print(ang)
        return

    banidb_path: Path | None = None
    if not args.no_banidb:
        banidb_path = Path(args.banidb)
        if not banidb_path.exists():
            print(f"banidb не найден: {banidb_path}")
            print("Проверяю только наличие файлов.\n")
            banidb_path = None

    darpan_path: Path | None = None
    if not args.no_darpan:
        darpan_path = Path(args.darpan)
        if not darpan_path.exists():
            darpan_path = None

    if args.plain:
        start, end = args.start, args.end
    else:
        start, end = _ask_range(args.start, args.end)

    print(f"Сканирую {start}..{end}…")
    reports = validate_range(start, end, banidb_path, darpan_path=darpan_path, verbose=args.verbose)
    duplicates = find_cross_ang_duplicates(start, end)

    if not reports:
        print("Нет данных для проверки.")
        return

    if args.plain:
        print_report(reports, duplicates, verbose=args.verbose)
    else:
        run_menu(reports, duplicates, start, end, banidb_path=banidb_path, darpan_path=darpan_path)

    if args.save_log:
        new_c, resolved, _ = save_scan_log(reports, duplicates, start, end)
        print(f"\nЛог сохранён → {LOG_DB_PATH.name}: +{new_c} новых, -{resolved} исправлено")


if __name__ == "__main__":
    main()
