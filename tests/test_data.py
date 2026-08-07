"""utils.data 数据层行为锁定测试（Data / ChampionAugmentData / AugmentTool / 模块函数）。"""

import json

import pytest

import aram_mayhem_helper.utils.data as data_mod
from aram_mayhem_helper.utils.aramkit import AramkitResources
from aram_mayhem_helper.utils.data import (
    AugmentTool,
    ChampionAugmentData,
    Data,
    get_augment_id_for_source,
    get_augment_info_for_source,
    get_default_source,
)


class TestData:
    def test_get_champion_id_by_name(self, patch_config_data_path) -> None:
        data = Data()
        assert data.get_champion_id_by_name("Ahri") == "103"
        assert data.get_champion_id_by_name("ahri") == "103"  # 不区分大小写
        assert data.get_champion_id_by_name("不存在") is None

    def test_get_champion_name_by_id(self, patch_config_data_path) -> None:
        data = Data()
        assert data.get_champion_name_by_id("103") == "Ahri"
        assert data.get_champion_name_by_id("999") is None

    def test_get_all_champion_data_picks_latest_file(self, patch_config_data_path) -> None:
        data = Data()
        assert set(data.get_all_champion_data()) == {"Ahri", "Aatrox", "Ashe"}


class TestChampionAugmentData:
    def test_opgg_reads_data_field(self, patch_config_data_path) -> None:
        cad = ChampionAugmentData("103", source="opgg")
        entries = cad.get_champion_augment_data()
        assert entries[0] == {"id": 1001, "tier": 0, "performance": 80.0, "popular": 10.0}
        assert len(entries) == 7

    def test_opgg_missing_data_field_returns_empty(self, patch_config_data_path) -> None:
        (patch_config_data_path / "opgg" / "aram_augments" / "42.json").write_text(
            json.dumps({"foo": "bar"}), encoding="utf-8"
        )
        cad = ChampionAugmentData("42", source="opgg")
        assert cad.get_champion_augment_data() == []

    def test_aramkit_reads_dataset_subdir_and_converts(self, patch_config_data_path) -> None:
        cad = ChampionAugmentData("103", source="aramkit")
        entries = cad.get_champion_augment_data()
        assert entries[0] == {
            "id": 1001,
            "performance": 0.55,
            "popular": 0.1,
            "rank": 1,
            "sampleCount": 1000,
        }
        assert len(entries) == 7

    def test_missing_file_raises_file_not_found(self, patch_config_data_path) -> None:
        cad = ChampionAugmentData("999", source="opgg")
        with pytest.raises(FileNotFoundError):
            cad.get_champion_augment_data()

    def test_corrupt_json_raises_json_decode_error(self, patch_config_data_path) -> None:
        (patch_config_data_path / "opgg" / "aram_augments" / "42.json").write_text("{not json", encoding="utf-8")
        cad = ChampionAugmentData("42", source="opgg")
        with pytest.raises(json.JSONDecodeError):
            cad.get_champion_augment_data()

    def test_result_is_cached(self, patch_config_data_path) -> None:
        cad = ChampionAugmentData("103", source="opgg")
        first = cad.get_champion_augment_data()
        # 缓存后修改文件不应影响已缓存结果
        (patch_config_data_path / "opgg" / "aram_augments" / "103.json").write_text(
            json.dumps({"data": []}), encoding="utf-8"
        )
        assert cad.get_champion_augment_data() is first


class TestAugmentTool:
    def test_loads_translation_table(self, patch_config_data_path) -> None:
        tool = AugmentTool()
        assert tool.get_augment_info("1001") == {"name": "泰坦的坚决", "level": "2"}

    def test_get_augment_id_exact_match(self, patch_config_data_path) -> None:
        tool = AugmentTool()
        assert tool.get_augment_id("泰坦的坚决") == "1001"

    def test_get_augment_id_normalized_match(self, patch_config_data_path) -> None:
        tool = AugmentTool()
        assert tool.get_augment_id("泰坦的 坚决") == "1001"  # 空白变体
        # 名字本身含连字符时，OCR 横线误读变体可匹配
        assert tool.get_augment_id("测试—符文") == "3001"
        assert tool.get_augment_id("测试一符文") == "3001"
        # 名字不含连字符时，横线变体不匹配（当前行为）
        assert tool.get_augment_id("泰坦的一坚决") is None

    def test_get_augment_id_unknown_returns_none(self, patch_config_data_path) -> None:
        tool = AugmentTool()
        assert tool.get_augment_id("不存在的符文") is None

    def test_missing_trans_file_initializes_empty(self, tmp_path, monkeypatch) -> None:
        from aram_mayhem_helper.utils.config import config

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch.setattr(config, "data_path", data_dir)
        tool = AugmentTool()
        assert tool.get_augment_info("1001") is None


class TestModuleFunctions:
    def test_get_default_source_returns_config_value(self) -> None:
        assert get_default_source() in ("opgg", "aramkit")

    def test_get_augment_info_for_source_translation_first(self, patch_config_data_path, monkeypatch) -> None:
        monkeypatch.setattr(data_mod, "augment_tool", AugmentTool())
        assert get_augment_info_for_source("opgg", "1001") == {"name": "泰坦的坚决", "level": "2"}

    def test_get_augment_info_for_source_aramkit_fallback(self, patch_config_data_path, monkeypatch) -> None:
        monkeypatch.setattr(data_mod, "augment_tool", AugmentTool())
        monkeypatch.setattr(data_mod, "aramkit_resources", AramkitResources())
        assert get_augment_info_for_source("aramkit", "7777") == {"name": "测试回退符文", "level": "1"}
        assert get_augment_info_for_source("opgg", "7777") is None  # opgg 不回退

    def test_get_augment_id_for_source_aramkit_fallback(self, patch_config_data_path, monkeypatch) -> None:
        monkeypatch.setattr(data_mod, "augment_tool", AugmentTool())
        monkeypatch.setattr(data_mod, "aramkit_resources", AramkitResources())
        assert get_augment_id_for_source("aramkit", "测试回退符文") == "7777"
        assert get_augment_id_for_source("opgg", "测试回退符文") is None
