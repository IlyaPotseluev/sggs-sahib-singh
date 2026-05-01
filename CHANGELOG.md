# Changelog

## 2026-05-01 — Romanization fixes for Russian readers

Added and applied a targeted romanization normalization pass for `ang_json/*.json`.

### What changed

- Gurmukhi dulavan `ੈ` is rendered as `ē`, not `ai`, in project `roman`.
  - Rationale: Russian readers read `ai` as two sounds, "а-и"; the intended reading is closer to "э/е".
  - Examples:
    - `ਮਿਲੈ`: `milai` -> `milē`
    - `ਹੈ`: `hai` -> `hē`
    - `ਕੈ`: `kai` -> `kē`
- Final Gurmukhi onkar `ੁ` after a consonant is dropped in multi-consonant words.
  - Examples:
    - `ਕਰਹੁ`: `karahu` -> `karah`
    - `ਨਾਮੁ`: `nāmu` -> `nām`
    - `ਪ੍ਰਭੁ`: `prabhu` -> `prabh`
  - Important distinction: do not drop vowel-final forms that are not final onkar after a consonant.
    - Keep `ਨਿਰਭਉ` as `nirbhau`
    - Keep `ਰਹਾਉ` as `rahāu`
    - Keep `ਜਿਉ` as `jiu`
    - Keep `ਸਿਉ` as `siu`
- Confirmed narrow schwa override:
  - `ਮੁਕਤਿ`: `mukat` / `mukati` -> `mukt`
- Added an audit mode for broader mukta/schwa deletion candidates.
  - Broad schwa deletion is context-sensitive and must not be applied blindly.
  - The audit reports candidate consonant pairs for manual review.

### Tooling

New script:

```bash
python3 fix_romanization_rules.py --start 1 --end 1430
```

Default mode is dry-run. Apply mode:

```bash
python3 fix_romanization_rules.py --start 1 --end 1430 --apply
```

Audit likely mukta/schwa-deletion candidates:

```bash
python3 fix_romanization_rules.py --start 1 --end 1430 --schwa-candidates --limit 50
```

### Tests

Added tests in `tests/test_romanization_rules.py`.

Verification commands used:

```bash
python3 -m pytest tests/test_romanization_rules.py -q
python3 validate_angs.py --plain --no-darpan
python3 fix_romanization_rules.py --start 1 --end 1430 --limit 10
```

Expected current results:

- `pytest`: 12 tests passed.
- `validate_angs.py --plain --no-darpan`: 1430/1430 OK.
- romanization fixer dry-run after applying: no remaining fixes found.

### Git

Committed and pushed:

- `4d2f74b Normalize ang romanization rules`

