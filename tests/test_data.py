"""utils.data 数据层测试（GameData 仓储 / AugmentLookup 翻译表）。"""

import json

import pytest

from aram_mayhem_helper.utils.data import AugmentLookup


class TestGameDataChampions:
    def test_champion_id_by_name(self, game_data) -> None:
        assert game_data.champion_id_by_name("Ahri") == "103"
        assert game_data.champion_id_by_name("ahri") == "103"  # 不区分大小写
        assert game_data.champion_id_by_name("不存在") is None

    def test_champion_name_by_id(self, game_data) -> None:
        assert game_data.champion_name("103") == "Ahri"
        assert game_data.champion_name("999") is None

    def test_champion_ids_sorted(self, game_data) -> None:
        assert game_data.champion_ids() == ["22", "103", "266"]

    def test_default_source_from_config(self, game_data) -> None:
        assert game_data.default_source() in ("opgg", "aramkit")


class TestGameDataAugmentEntries:
    def test_opgg_reads_data_field(self, game_data) -> None:
        entries = game_data.augment_entries("103", "opgg")
        assert entries is not None
        assert entries[0] == {"id": 1001, "tier": 0, "performance": 80.0, "popular": 10.0}
        assert len(entries) == 7

    def test_opgg_missing_data_field_returns_empty(self, game_data, fixture_data_dir) -> None:
        (fixture_data_dir / "opgg" / "aram_augments" / "266.json").write_text(
            json.dumps({"foo": "bar"}), encoding="utf-8"
        )
        assert game_data.augment_entries("266", "opgg") == []

    def test_aramkit_reads_dataset_subdir_and_converts(self, game_data) -> None:
        entries = game_data.augment_entries("103", "aramkit")
        assert entries is not None
        assert entries[0] == {
            "id": 1001,
            "performance": 0.55,
            "popular": 0.1,
            "rank": 1,
            "sampleCount": 1000,
        }
        assert len(entries) == 7

    def test_unknown_champion_returns_none(self, game_data) -> None:
        assert game_data.augment_entries("999", "opgg") is None

    def test_known_champion_missing_file_raises(self, game_data) -> None:
        # 266 在 ddragon fixture 中，但无 opgg 数据文件
        with pytest.raises(FileNotFoundError):
            game_data.augment_entries("266", "opgg")

    def test_corrupt_json_raises_json_decode_error(self, game_data, fixture_data_dir) -> None:
        (fixture_data_dir / "opgg" / "aram_augments" / "266.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            game_data.augment_entries("266", "opgg")

    def test_result_is_cached(self, game_data, fixture_data_dir) -> None:
        first = game_data.augment_entries("103", "opgg")
        # 缓存后修改文件不应影响已缓存结果
        (fixture_data_dir / "opgg" / "aram_augments" / "103.json").write_text(
            json.dumps({"data": []}), encoding="utf-8"
        )
        assert game_data.augment_entries("103", "opgg") is first

    def test_augment_entries_all_raises_on_missing_file(self, game_data) -> None:
        # 266 在 ddragon fixture 中但无 opgg 文件 → FileNotFoundError 向上传播（web 调用方负责捕获）
        with pytest.raises(FileNotFoundError):
            game_data.augment_entries_all("opgg")


class TestGameDataAvailableSource:
    """推荐流程的数据源解析：默认源缺数据时回退另一源（修复默认源切换后部分英雄硬中断）。"""

    def test_prefers_default_source_when_both_exist(self, game_data) -> None:
        # 103 在 opgg 与 aramkit 都有数据
        assert game_data.available_source("103", preferred="aramkit") == "aramkit"
        assert game_data.available_source("103", preferred="opgg") == "opgg"

    def test_falls_back_to_other_source_when_default_missing(self, game_data) -> None:
        # 22 只有 opgg 数据：默认 aramkit 缺失时回退 opgg
        assert game_data.available_source("22", preferred="aramkit") == "opgg"

    def test_returns_none_when_no_source_has_data(self, game_data) -> None:
        # 266 在两个数据源都没有文件
        assert game_data.available_source("266", preferred="aramkit") is None

    def test_no_preferred_uses_config_default(self, game_data) -> None:
        assert game_data.available_source("103") == game_data.default_source()

    def test_fallback_does_not_raise_on_corrupt_file(self, game_data, fixture_data_dir) -> None:
        # 默认源文件损坏时静默跳过，回退到另一源
        (fixture_data_dir / "aramkit" / "aram_augments" / "all" / "103.json").write_text(
            "{not json", encoding="utf-8"
        )
        assert game_data.available_source("103", preferred="aramkit") == "opgg"


class TestGameDataLookup:
    def test_augment_info_translation_first(self, game_data) -> None:
        assert game_data.augment_info("1001", "opgg") == {"name": "泰坦的坚决", "level": "2"}

    def test_augment_info_aramkit_fallback(self, game_data) -> None:
        assert game_data.augment_info("7777", "aramkit") == {"name": "测试回退符文", "level": "1"}
        assert game_data.augment_info("7777", "opgg") is None  # opgg 不回退

    def test_augment_id_normalized_match(self, game_data) -> None:
        assert game_data.augment_id("泰坦的 坚决", "opgg") == "1001"
        assert game_data.augment_id("测试—符文", "opgg") == "3001"  # 连字符变体
        assert game_data.augment_id("不存在符文", "opgg") is None

    def test_augment_id_aramkit_fallback(self, game_data) -> None:
        assert game_data.augment_id("测试回退符文", "aramkit") == "7777"
        assert game_data.augment_id("测试回退符文", "opgg") is None


class TestGameDataReload:
    def test_reload_refreshes_augment_entries(self, game_data, fixture_data_dir) -> None:
        assert len(game_data.augment_entries("103", "opgg")) == 7
        (fixture_data_dir / "opgg" / "aram_augments" / "103.json").write_text(
            json.dumps({"data": [{"id": 1, "performance": 1.0, "popular": 1.0}]}), encoding="utf-8"
        )
        game_data.reload()
        assert len(game_data.augment_entries("103", "opgg")) == 1

    def test_reload_refreshes_translation_table(self, game_data, fixture_data_dir) -> None:
        assert game_data.augment_id("泰坦的坚决", "opgg") == "1001"
        (fixture_data_dir / "augment_trans.json").write_text(
            json.dumps({"1001": {"name": "泰坦的坚决", "level": "2"}}), encoding="utf-8"
        )
        game_data.reload()
        assert game_data.augment_id("泰坦的坚决", "opgg") == "1001"

    def test_reload_refreshes_aramkit_resources(self, game_data, fixture_data_dir) -> None:
        assert game_data.augment_info("7777", "aramkit") is not None
        (fixture_data_dir / "aramkit" / "resources" / "16.0.1-abc123456789" / "augments.json").write_text(
            json.dumps({}), encoding="utf-8"
        )
        game_data.reload()
        assert game_data.augment_info("7777", "aramkit") is None


class TestAugmentLookup:
    def test_missing_trans_file_initializes_empty(self, tmp_path) -> None:
        lookup = AugmentLookup(tmp_path / "nope.json")
        assert lookup.get_augment_info("1001") is None
        assert lookup.get_augment_id("泰坦的坚决") is None

    def test_exact_and_normalized_lookup(self, game_data) -> None:
        lookup = game_data._lookup_impl()
        assert lookup.get_augment_id("泰坦的坚决") == "1001"
        assert lookup.get_augment_id("泰坦的 坚决") == "1001"
        assert lookup.get_augment_info("1001") == {"name": "泰坦的坚决", "level": "2"}
