"""通用版本号工具测试。"""

import pytest

from aram_mayhem_helper.utils.version import latest_version, parse_version, version_sort_key


class TestVersionParsing:
    def test_parse_version_contains_all_numeric_release_components(self) -> None:
        assert parse_version("16.10.10") == ((16, 10, 10), ())

    def test_numeric_release_components_are_sorted_numerically(self) -> None:
        versions = ["16.9.9", "16.10.1", "16.10.10", "16.10.2"]
        assert max(versions, key=version_sort_key) == "16.10.10"

    def test_suffix_is_sorted_after_release_and_preserves_existing_order(self) -> None:
        versions = ["16.15-20260805-a", "16.15-20260806-c", "16.15"]
        assert max(versions, key=version_sort_key) == "16.15-20260806-c"
        assert version_sort_key("16.15") < version_sort_key("16.15-abc")

    def test_latest_version_ignores_invalid_values(self) -> None:
        assert latest_version(["not-a-version", "16.9.9", "README"]) == "16.9.9"
        assert latest_version(["not-a-version", "README"]) is None

    @pytest.mark.parametrize("value", ["", "16", "16..1", "16.x.1", "16.1-"])
    def test_invalid_version_raises_from_sort_key(self, value: str) -> None:
        with pytest.raises(ValueError, match="无效版本号"):
            version_sort_key(value)
