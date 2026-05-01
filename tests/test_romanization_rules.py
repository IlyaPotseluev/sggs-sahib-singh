from fix_romanization_rules import fix_roman_line, scan_schwa_candidates


def test_dulavan_uses_e_for_russian_readers():
    fixed, rules = fix_roman_line("ਮਿਲੈ", "milai")

    assert fixed == "milē"
    assert rules == ["dulavan-ai-to-e"]


def test_dulavan_changes_common_particles():
    fixed, rules = fix_roman_line("ਕੈ ਹੈ", "kai hai")

    assert fixed == "kē hē"
    assert rules == ["dulavan-ai-to-e"]


def test_final_sihari_mukti_drops_schwa():
    fixed, rules = fix_roman_line("ਮੁਕਤਿ", "mukat")

    assert fixed == "mukt"
    assert rules == ["schwa-override"]


def test_final_sihari_mukti_handles_kati():
    fixed, rules = fix_roman_line("ਮੁਕਤਿ", "mukati")

    assert fixed == "mukt"
    assert rules == ["schwa-override"]


def test_final_sihari_general_words_drop_i():
    fixed, rules = fix_roman_line("ਹਰਿ ਮਨਿ ਜਪਿ", "hari mani japi")

    assert fixed == "har man jap"
    assert rules == [
        "final-sihari-drop-i",
        "final-sihari-drop-i",
        "final-sihari-drop-i",
    ]


def test_final_onkar_multi_letter_words_drop_short_u():
    fixed, rules = fix_roman_line("ਕਰਹੁ ਨਾਮੁ ਪ੍ਰਭੁ", "karahu nāmu prabhu")

    assert fixed == "karah nām prabh"
    assert rules == [
        "final-onkar-drop-u",
        "final-onkar-drop-u",
        "final-onkar-drop-u",
    ]


def test_final_onkar_does_not_drop_long_u():
    fixed, rules = fix_roman_line("ਕਰਹੁ", "karahū")

    assert fixed == "karahū"
    assert rules == []


def test_final_onkar_fallback_when_token_counts_do_not_align():
    fixed, rules = fix_roman_line("ਦਇਆਲ ਕਰਹੁ ॥੧॥", "daiāl karahu 1")

    assert fixed == "daiāl karah 1"
    assert rules == ["final-onkar-drop-u-fallback"]


def test_final_onkar_fallback_does_not_drop_non_onkar_au_words():
    fixed, rules = fix_roman_line("ਨਾਮੁ ਨਿਰਭਉ ਰਹਾਉ ॥੧॥", "nāmu nirbhau rahāu 1")

    assert fixed == "nām nirbhau rahāu 1"
    assert rules == ["final-onkar-drop-u-fallback"]


def test_final_onkar_short_one_consonant_word_is_left_alone():
    fixed, rules = fix_roman_line("ਤੁ", "tu")

    assert fixed == "tu"
    assert rules == []


def test_schwa_candidates_audit_reports_bare_consonant_pair(tmp_path):
    path = tmp_path / "ang_0001.json"
    path.write_text(
        """
{
  "ang": 1,
  "lines": [
    {
      "index": 1,
      "verse_id": 1,
      "gurmukhi": "ਮੁਕਤਿ ਭਗਤਿ",
      "roman": "mukat bhagat"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    candidates = scan_schwa_candidates(path)

    assert [(c.gurmukhi_word, c.roman_word, c.pair) for c in candidates] == [
        ("ਮੁਕਤਿ", "mukat", "ਕਤ"),
        ("ਭਗਤਿ", "bhagat", "ਭਗ"),
        ("ਭਗਤਿ", "bhagat", "ਗਤ"),
    ]


def test_unrelated_ai_is_not_changed_without_dulavan():
    fixed, rules = fix_roman_line("ਆਇਆ", "āiā")

    assert fixed == "āiā"
    assert rules == []
