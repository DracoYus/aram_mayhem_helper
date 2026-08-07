"""utils.text_normalization 行为锁定测试。"""

from aram_mayhem_helper.utils.text_normalization import DEFAULT_RULES, normalize_for_lookup, normalize_text


class TestNormalizeText:
    def test_default_rules_replace_common_misreads(self) -> None:
        assert normalize_text("进击") == "迸击"
        assert normalize_text("鸣人") == "呜人"
        assert normalize_text("堂控") == "掌控"

    def test_rules_replace_all_occurrences(self) -> None:
        assert normalize_text("进进出出进") == "迸迸出出迸"

    def test_custom_rules_override_defaults(self) -> None:
        assert normalize_text("进击", rules=[("进", "X")]) == "X击"

    def test_empty_text_returns_unchanged(self) -> None:
        assert normalize_text("") == ""
        assert normalize_text(None) is None  # type: ignore[arg-type]

    def test_rules_are_ordered_pairs(self) -> None:
        assert all(isinstance(a, str) and isinstance(b, str) for a, b in DEFAULT_RULES)


class TestNormalizeForLookup:
    def test_dash_variants_unify_to_ascii_dash(self) -> None:
        assert normalize_for_lookup("泰坦的—坚决") == "泰坦的-坚决"
        assert normalize_for_lookup("泰坦的–坚决") == "泰坦的-坚决"
        assert normalize_for_lookup("泰坦的－坚决") == "泰坦的-坚决"
        assert normalize_for_lookup("泰坦的-坚决") == "泰坦的-坚决"

    def test_cjk_horizontal_line_misread_becomes_dash(self) -> None:
        # 一 (U+4E00) 被视为 OCR 横线误读 → ASCII '-'
        assert normalize_for_lookup("泰坦的一坚决") == "泰坦的-坚决"

    def test_whitespace_is_dropped(self) -> None:
        assert normalize_for_lookup("泰坦的 坚决") == "泰坦的坚决"
        assert normalize_for_lookup("泰坦的\t坚决") == "泰坦的坚决"

    def test_control_chars_are_dropped(self) -> None:
        assert normalize_for_lookup("泰坦的\x00坚决") == "泰坦的坚决"

    def test_semantic_misreads_still_applied(self) -> None:
        assert normalize_for_lookup("进击的鸣人") == "迸击的呜人"

    def test_empty_text_returns_unchanged(self) -> None:
        assert normalize_for_lookup("") == ""
