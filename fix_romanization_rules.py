#!/usr/bin/env python3
"""Targeted fixes for project romanization rules in ang_json.

Default mode is a dry run. Use --apply to write changes.

Rules:
  1. Gurmukhi dulavan (ੈ) is rendered as ē, not ai, for Russian readers.
     Example: ਮਿਲੈ -> milē, ਕੈ -> kē.
  2. Final sihari (ਿ) marks no pronounced final vowel in project romanization.
     Example: ਹਰਿ -> har, ਮੁਕਤਿ -> mukt, not hari/mukat.
  3. Final onkar (ੁ) in multi-letter words is dropped.
     Example: ਕਰਹੁ -> karah, ਨਾਮੁ -> nām.
  4. Mukta schwa deletion is context-sensitive. The script can audit likely
     consonant-pair candidates, but does not broadly auto-apply them.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).parent
ANG_JSON_DIR = REPO_ROOT / "ang_json"

_DULAVAN = "\u0A48"  # ੈ
_SIHARI = "\u0A3F"  # ਿ
_ONKAR = "\u0A41"  # ੁ
_GURMUKHI_CONSONANTS = set("ਕਖਗਘਙਚਛਜਝਞਟਠਡਢਣਤਥਦਧਨਪਫਬਭਮਯਰਲਵਸਹੜ")
_GURMUKHI_WORD_RE = re.compile(r"[\u0A00-\u0A7F]+")
_ROMAN_WORD_RE = re.compile(r"[A-Za-zĀāĒēĪīŌōŪūṄṅÑñṬṭḌḍṆṇŚśṢṣḤḥṚṛḶḷ]+")
_CONSONANT_LATIN = {
    "ਕ": "k", "ਖ": "kh", "ਗ": "g", "ਘ": "gh", "ਙ": "ṅ",
    "ਚ": "ch", "ਛ": "chh", "ਜ": "j", "ਝ": "jh", "ਞ": "ñ",
    "ਟ": "ṭ", "ਠ": "ṭh", "ਡ": "ḍ", "ਢ": "ḍh", "ਣ": "ṇ",
    "ਤ": "t", "ਥ": "th", "ਦ": "d", "ਧ": "dh", "ਨ": "n",
    "ਪ": "p", "ਫ": "ph", "ਬ": "b", "ਭ": "bh", "ਮ": "m",
    "ਯ": "y", "ਰ": "r", "ਲ": "l", "ਵ": "v", "ਸ": "s",
    "ਹ": "h", "ੜ": "ṛ",
}
_INDEPENDENT_VOWEL_LATIN = {
    "ਅ": "a", "ਆ": "ā", "ਇ": "i", "ਈ": "ī", "ਉ": "u",
    "ਊ": "ū", "ਏ": "e", "ਐ": "ē", "ਓ": "o", "ਔ": "au",
}
_DEPENDENT_VOWEL_LATIN = {
    "ਾ": "ā", "ਿ": "i", "ੀ": "ī", "ੁ": "u", "ੂ": "ū",
    "ੇ": "e", "ੈ": "ē", "ੋ": "o", "ੌ": "au",
}
_DEPENDENT_VOWELS = set("ਾਿੀੁੂੇੈੋੌ")
_SCHWA_OVERRIDES = {
    "ਮੁਕਤਿ": {"mukat": "mukt", "mukati": "mukt"},
}


@dataclass
class RomanFix:
    ang: int
    line_index: int
    verse_id: int | None
    gurmukhi: str
    before: str
    after: str
    rules: list[str]


@dataclass
class SchwaCandidate:
    ang: int
    line_index: int
    verse_id: int | None
    gurmukhi_word: str
    roman_word: str
    pair: str
    roman_pattern: str


def _replace_ai_for_dulavan(gurmukhi: str, roman: str) -> tuple[str, bool]:
    """Replace ai with ē when the Gurmukhi line contains dulavan.

    The project romanization is for Russian readers; "ai" is read as two
    sounds in Russian, while dulavan should be displayed as an "э"-like sound.
    """
    if _DULAVAN not in gurmukhi or "ai" not in roman.lower():
        return roman, False

    result = roman.replace("ai", "ē").replace("Ai", "Ē")
    result = result.replace("AI", "Ē").replace("aI", "ē")
    return result, result != roman


def _replace_word_at_span(text: str, span: tuple[int, int], replacement: str) -> str:
    start, end = span
    return text[:start] + replacement + text[end:]


def _base_consonant_count(gurmukhi_word: str) -> int:
    return sum(1 for ch in gurmukhi_word if ch in _GURMUKHI_CONSONANTS)


def _drop_final_vowel_sound(roman_word: str, vowels: tuple[str, ...]) -> str:
    lower = roman_word.lower()
    for vowel in vowels:
        if lower.endswith(vowel):
            return roman_word[: -len(vowel)]
    return roman_word


def _rough_roman_for_gurmukhi_word(gurmukhi_word: str) -> str:
    result: list[str] = []
    chars = list(gurmukhi_word)
    i = 0
    while i < len(chars):
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""

        if ch in _INDEPENDENT_VOWEL_LATIN:
            result.append(_INDEPENDENT_VOWEL_LATIN[ch])
        elif ch in _CONSONANT_LATIN:
            result.append(_CONSONANT_LATIN[ch])
            if nxt in _DEPENDENT_VOWEL_LATIN:
                result.append(_DEPENDENT_VOWEL_LATIN[nxt])
                i += 1
            elif nxt == "੍":
                i += 1
            elif nxt and nxt in _GURMUKHI_CONSONANTS:
                result.append("a")
        elif ch == "ੰ" or ch == "ਂ":
            result.append("ṃ")
        i += 1
    return "".join(result)


def _final_onkar_roman_targets(g_words: list[str]) -> set[str]:
    targets: set[str] = set()
    for word in g_words:
        if not (word.endswith(_ONKAR) and _base_consonant_count(word) > 1):
            continue
        rough = _rough_roman_for_gurmukhi_word(word).lower()
        if rough.endswith("u") and len(rough) > 2:
            targets.add(rough)
    return targets


def _drop_short_u_from_roman_words(roman: str, targets: set[str]) -> tuple[str, int]:
    """Drop final short u from likely multi-letter roman words.

    This is used as a fallback for final Gurmukhi onkar when Gurmukhi and
    roman token counts do not align. It intentionally does not drop long ū.
    """
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        word = match.group(0)
        if word.lower() not in targets:
            return word
        changed += 1
        return word[:-1]

    return _ROMAN_WORD_RE.sub(repl, roman), changed


def _fix_final_sihari_and_onkar(gurmukhi: str, roman: str) -> tuple[str, list[str]]:
    """Apply project pronunciation fixes for final sihari/onkar words."""
    g_words = [m.group(0) for m in _GURMUKHI_WORD_RE.finditer(gurmukhi)]
    r_matches = list(_ROMAN_WORD_RE.finditer(roman))
    if not g_words or len(g_words) != len(r_matches):
        targets = _final_onkar_roman_targets(g_words)
        if targets:
            fixed, changed = _drop_short_u_from_roman_words(roman, targets)
            if changed:
                return fixed, ["final-onkar-drop-u-fallback"] * changed
        return roman, []

    result = roman
    offset = 0
    rules: list[str] = []
    for g_word, r_match in zip(g_words, r_matches):
        r_word = r_match.group(0)
        fixed = r_word
        word_rules: list[str] = []

        overrides = _SCHWA_OVERRIDES.get(g_word)
        if overrides:
            override = overrides.get(fixed.lower())
            if override:
                fixed = override
                word_rules.append("schwa-override")

        if g_word.endswith(_SIHARI):
            fixed_after_i = _drop_final_vowel_sound(fixed, ("i", "ī"))
            if fixed_after_i != fixed:
                fixed = fixed_after_i
                word_rules.append("final-sihari-drop-i")

        if g_word.endswith(_ONKAR) and _base_consonant_count(g_word) > 1:
            fixed_after_u = _drop_final_vowel_sound(fixed, ("u",))
            if fixed_after_u != fixed:
                fixed = fixed_after_u
                word_rules.append("final-onkar-drop-u")

        if fixed == r_word:
            continue

        start, end = r_match.span()
        start += offset
        end += offset
        result = _replace_word_at_span(result, (start, end), fixed)
        offset += len(fixed) - len(r_word)
        rules.extend(word_rules)

    return result, rules


def _bare_consonant_pairs(g_word: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    chars = list(g_word)
    consonants: list[tuple[str, bool]] = []
    for i, ch in enumerate(chars):
        if ch not in _GURMUKHI_CONSONANTS:
            continue
        has_explicit_vowel = i + 1 < len(chars) and chars[i + 1] in _DEPENDENT_VOWELS
        consonants.append((ch, has_explicit_vowel))

    for (left, left_has_vowel), (right, _right_has_vowel) in zip(consonants, consonants[1:]):
        if not left_has_vowel:
            pairs.append((left, right))
    return pairs


def _schwa_candidates_for_line(
    ang: int,
    line: dict,
    gurmukhi: str,
    roman: str,
) -> list[SchwaCandidate]:
    g_words = [m.group(0) for m in _GURMUKHI_WORD_RE.finditer(gurmukhi)]
    r_matches = list(_ROMAN_WORD_RE.finditer(roman))
    if len(g_words) != len(r_matches):
        return []

    candidates: list[SchwaCandidate] = []
    for g_word, r_match in zip(g_words, r_matches):
        r_word = r_match.group(0)
        r_lower = r_word.lower()
        for left, right in _bare_consonant_pairs(g_word):
            left_r = _CONSONANT_LATIN.get(left)
            right_r = _CONSONANT_LATIN.get(right)
            if not left_r or not right_r:
                continue
            pattern = f"{left_r}a{right_r}"
            if pattern in r_lower:
                candidates.append(
                    SchwaCandidate(
                        ang=ang,
                        line_index=int(line.get("index", 0)),
                        verse_id=line.get("verse_id"),
                        gurmukhi_word=g_word,
                        roman_word=r_word,
                        pair=f"{left}{right}",
                        roman_pattern=pattern,
                    )
                )
    return candidates


def fix_roman_line(gurmukhi: str, roman: str) -> tuple[str, list[str]]:
    """Return fixed roman text and the rule ids that changed it."""
    rules: list[str] = []

    new_roman, changed = _replace_ai_for_dulavan(gurmukhi, roman)
    if changed:
        roman = new_roman
        rules.append("dulavan-ai-to-e")

    new_roman, changed_rules = _fix_final_sihari_and_onkar(gurmukhi, roman)
    if changed_rules:
        roman = new_roman
        rules.extend(changed_rules)

    return roman, rules


def scan_ang(path: Path) -> list[RomanFix]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ang = int(data.get("ang", path.stem[4:]))
    fixes: list[RomanFix] = []

    for line in data.get("lines", []):
        gurmukhi = str(line.get("gurmukhi", ""))
        roman = str(line.get("roman", ""))
        fixed, rules = fix_roman_line(gurmukhi, roman)
        if fixed != roman:
            fixes.append(
                RomanFix(
                    ang=ang,
                    line_index=int(line.get("index", 0)),
                    verse_id=line.get("verse_id"),
                    gurmukhi=gurmukhi,
                    before=roman,
                    after=fixed,
                    rules=rules,
                )
            )

    return fixes


def scan_schwa_candidates(path: Path) -> list[SchwaCandidate]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ang = int(data.get("ang", path.stem[4:]))
    candidates: list[SchwaCandidate] = []

    for line in data.get("lines", []):
        candidates.extend(
            _schwa_candidates_for_line(
                ang=ang,
                line=line,
                gurmukhi=str(line.get("gurmukhi", "")),
                roman=str(line.get("roman", "")),
            )
        )

    return candidates


def apply_ang(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0

    for line in data.get("lines", []):
        gurmukhi = str(line.get("gurmukhi", ""))
        roman = str(line.get("roman", ""))
        fixed, _rules = fix_roman_line(gurmukhi, roman)
        if fixed != roman:
            line["roman"] = fixed
            changed += 1

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return changed


def _ang_paths(json_dir: Path, start: int, end: int) -> list[Path]:
    return [
        json_dir / f"ang_{ang:04d}.json"
        for ang in range(start, end + 1)
        if (json_dir / f"ang_{ang:04d}.json").exists()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1430)
    parser.add_argument("--json-dir", type=Path, default=ANG_JSON_DIR)
    parser.add_argument("--apply", action="store_true", help="Write changes to ang_json")
    parser.add_argument(
        "--schwa-candidates",
        action="store_true",
        help="Show likely mukta schwa-deletion candidates by consonant pairs; does not apply",
    )
    parser.add_argument("--limit", type=int, default=40, help="Max preview lines in dry-run output")
    args = parser.parse_args()

    paths = _ang_paths(args.json_dir, args.start, args.end)
    if args.schwa_candidates:
        candidates: list[SchwaCandidate] = []
        for path in paths:
            candidates.extend(scan_schwa_candidates(path))
        print(f"Schwa candidate audit: {len(candidates)} candidates in {args.start}..{args.end}.")
        pair_counts = Counter(c.pair for c in candidates)
        for pair, count in pair_counts.most_common(20):
            print(f"  {pair}: {count}")
        for cand in candidates[: args.limit]:
            print(
                f"\nAng {cand.ang:04d}, line {cand.line_index}, verse {cand.verse_id}: "
                f"{cand.gurmukhi_word} / {cand.roman_word}"
            )
            print(f"  pair {cand.pair}, roman pattern '{cand.roman_pattern}'")
        if len(candidates) > args.limit:
            print(f"\n... {len(candidates) - args.limit} more. Use --limit to show more.")
        return

    all_fixes: list[RomanFix] = []
    for path in paths:
        all_fixes.extend(scan_ang(path))

    if not all_fixes:
        print(f"No romanization fixes found in {args.start}..{args.end}.")
        return

    if args.apply:
        changed_lines = 0
        changed_angs = 0
        for path in paths:
            changed = apply_ang(path)
            if changed:
                changed_angs += 1
                changed_lines += changed
        print(f"Applied {changed_lines} romanization fixes in {changed_angs} ang file(s).")
        return

    print(f"Dry run: {len(all_fixes)} romanization fixes in {args.start}..{args.end}.")
    rule_counts = Counter(rule for fix in all_fixes for rule in fix.rules)
    for rule, count in sorted(rule_counts.items()):
        print(f"  {rule}: {count}")
    for fix in all_fixes[: args.limit]:
        rule_list = ", ".join(fix.rules)
        print(f"\nAng {fix.ang:04d}, line {fix.line_index}, verse {fix.verse_id} [{rule_list}]")
        print(f"  G: {fix.gurmukhi}")
        print(f"  - {fix.before}")
        print(f"  + {fix.after}")
    if len(all_fixes) > args.limit:
        print(f"\n... {len(all_fixes) - args.limit} more. Use --limit to show more.")
    print("\nRun again with --apply to write changes.")


if __name__ == "__main__":
    main()
