"""
Integrity tests for ang_json/.

Pytest tests (hard fail):
  python -m pytest tests/ -v

Informational coverage report vs banidb (requires local banidb):
  python tests/test_ang_json.py

banidb is local-only — coverage report is skipped if the DB is not found.
"""

import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
ANG_JSON_DIR = REPO_ROOT / "ang_json"
BANIDB_PATH = REPO_ROOT.parent / "banidb" / "sggs.db"

_UDAAT = "ੑ"  # U+0A51 — in banidb, absent from KhojGurbani (stylistic difference)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace(_UDAAT, "").strip()


def load_ang_gurmukhi(ang: int) -> set[str]:
    p = ANG_JSON_DIR / f"ang_{ang:04d}.json"
    if not p.exists():
        return set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return {norm(line["gurmukhi"]) for line in data.get("lines", [])}


def get_available_angs() -> list[int]:
    return sorted(
        int(p.stem[4:]) for p in ANG_JSON_DIR.glob("ang_*.json") if p.stem[4:].isdigit()
    )


# ---------------------------------------------------------------------------
# Structural pytest tests (no banidb needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ang", get_available_angs())
def test_structure(ang: int):
    """Verify JSON structure, required fields, and verse_id uniqueness."""
    p = ANG_JSON_DIR / f"ang_{ang:04d}.json"
    data = json.loads(p.read_text(encoding="utf-8"))

    assert data.get("ang") == ang, f"ang field mismatch: {data.get('ang')} != {ang}"

    lines = data.get("lines", [])
    assert isinstance(lines, list) and len(lines) > 0, "lines is empty"
    assert data.get("line_count") == len(lines), "line_count != len(lines)"

    required = {"index", "verse_id", "gurmukhi", "roman", "translation_ru"}
    verse_ids: set[int] = set()

    for i, line in enumerate(lines):
        missing = required - line.keys()
        assert not missing, f"line {i+1}: missing fields {missing}"

        vid = line["verse_id"]
        assert vid not in verse_ids, f"duplicate verse_id {vid}"
        verse_ids.add(vid)

        assert line["gurmukhi"].strip(), f"line {i+1}: empty gurmukhi"
        assert line["roman"].strip(), f"line {i+1}: empty roman"


# ---------------------------------------------------------------------------
# Standalone coverage report vs banidb
# ---------------------------------------------------------------------------

def _run_coverage_report() -> None:
    if not BANIDB_PATH.exists():
        print(f"banidb не найден: {BANIDB_PATH}")
        print("Coverage-отчёт недоступен (banidb — локальный ресурс).")
        return

    conn = sqlite3.connect(str(BANIDB_PATH))
    angs = get_available_angs()
    total = len(angs)
    errors: list[tuple[int, list[str]]] = []

    print(f"Проверяю {total} ангов против banidb...\n")

    for i, ang in enumerate(angs, 1):
        cur = conn.cursor()
        cur.execute("SELECT gurmukhi FROM verses WHERE ang = ? ORDER BY verse_id", (ang,))
        db_lines = [norm(row[0]) for row in cur.fetchall()]

        # Allow cross-ang attribution: check N-1, N, N+1
        our = load_ang_gurmukhi(ang - 1) | load_ang_gurmukhi(ang) | load_ang_gurmukhi(ang + 1)
        missing = [g for g in db_lines if g not in our]

        if missing:
            errors.append((ang, missing))
            print(f"  MISS  Анг {ang}: пропущено {len(missing)} строк (вероятно нет sahib_singh_pa)")
            for g in missing[:3]:
                print(f"        {g[:80]}")
        elif i % 50 == 0 or i == total:
            print(f"  OK    проверено {i}/{total} ангов")

    conn.close()
    print()

    if errors:
        total_miss = sum(len(m) for _, m in errors)
        print(f"Строк без покрытия: {total_miss} в {len(errors)} ангах")
        print("Примечание: эти строки отсутствуют в KhojGurbani или отфильтрованы")
        print("            (нет поля sahib_singh_pa — намеренный пропуск).")
    else:
        print(f"Все {total} ангов полностью покрыты.")


if __name__ == "__main__":
    _run_coverage_report()
