"""utils.aramkit 适配层行为锁定测试（convert_augment_records / version_sort_key / AramkitResources）。"""

import json
import shutil

from aram_mayhem_helper.utils.aramkit import (
    RARITY_TO_LEVEL,
    AramkitResources,
    convert_augment_records,
    version_sort_key,
)


class TestRarityToLevel:
    def test_mapping(self) -> None:
        assert RARITY_TO_LEVEL == {"prismatic": "2", "gold": "1", "silver": "0"}


class TestConvertAugmentRecords:
    def test_converts_winrate_pickrate(self) -> None:
        records = convert_augment_records(
            [{"id": 1001, "rank": 1, "sampleCount": 100, "pickRate": 0.1, "winRate": 0.55}]
        )
        assert records == [
            {
                "id": 1001,
                "performance": 0.55,
                "popular": 0.1,
                "sampleCount": 100,
                "rank": 1,
            }
        ]

    def test_skips_records_missing_id_or_rates(self) -> None:
        records = convert_augment_records(
            [
                {"id": 1, "pickRate": 0.1, "winRate": 0.5},  # 缺字段的正常项
                {"pickRate": 0.1, "winRate": 0.5},  # 缺 id
                {"id": 2, "winRate": 0.5},  # 缺 pickRate
                {"id": 3, "pickRate": 0.1},  # 缺 winRate
            ]
        )
        assert records == [{"id": 1, "performance": 0.5, "popular": 0.1}]

    def test_preserves_optional_fields_when_present(self) -> None:
        records = convert_augment_records(
            [
                {
                    "id": 1,
                    "pickRate": 0.1,
                    "winRate": 0.5,
                    "sampleCount": 9,
                    "rank": 2,
                    "stageAgnostic": False,
                    "availableStages": [1, 2],
                }
            ]
        )
        assert records[0]["stageAgnostic"] is False
        assert records[0]["availableStages"] == [1, 2]

    def test_empty_list(self) -> None:
        assert convert_augment_records([]) == []


class TestVersionSortKey:
    def test_orders_by_major_minor_then_rest(self) -> None:
        versions = ["16.14-20260805-a", "16.15-20260805-b", "16.15-20260806-c"]
        assert max(versions, key=version_sort_key) == "16.15-20260806-c"

    def test_version_without_suffix_sorts_before_with_suffix(self) -> None:
        assert version_sort_key("16.15") < version_sort_key("16.15-abc")


class TestAramkitResources:
    def test_loads_latest_version_dir_and_looks_up(self, fixture_data_dir) -> None:
        resources = AramkitResources(fixture_data_dir / "aramkit" / "resources")
        assert resources.get_augment_info("7777") == {"name": "测试回退符文", "level": "1"}
        assert resources.get_augment_id("测试回退符文") == "7777"
        # 特征锁定：与 AugmentLookup 同套 OCR 容错归一化（空格差异可匹配）
        assert resources.get_augment_id("测试回退 符文") == "7777"
        assert resources.get_augment_info("9999") is None
        assert resources.get_augment_id("不存在符文") is None

    def test_picks_highest_semantic_version_dir(self, fixture_data_dir) -> None:
        res_dir = fixture_data_dir / "aramkit" / "resources"
        shutil.copytree(
            res_dir / "16.0.1-abc123456789",
            res_dir / "16.0.2-def123456789",
        )
        (res_dir / "16.0.2-def123456789" / "augments.json").write_text(
            json.dumps({"8888": {"name": "新版符文", "rarity": "silver"}}), encoding="utf-8"
        )
        resources = AramkitResources(fixture_data_dir / "aramkit" / "resources")
        assert resources.get_augment_info("8888") == {"name": "新版符文", "level": "0"}
        assert resources.get_augment_info("7777") is None  # 旧版目录不再被选中

    def test_ignores_invalid_version_directories(self, fixture_data_dir) -> None:
        res_dir = fixture_data_dir / "aramkit" / "resources"
        invalid_dir = res_dir / "temporary"
        shutil.copytree(res_dir / "16.0.1-abc123456789", invalid_dir)
        (invalid_dir / "augments.json").write_text(
            json.dumps({"8888": {"name": "无效目录符文", "rarity": "silver"}}), encoding="utf-8"
        )

        resources = AramkitResources(res_dir)

        assert resources.get_augment_info("7777") is not None
        assert resources.get_augment_info("8888") is None

    def test_reload_clears_and_repopulates(self, fixture_data_dir) -> None:
        resources = AramkitResources(fixture_data_dir / "aramkit" / "resources")
        assert resources.get_augment_info("7777") is not None
        resources.reload()
        assert resources.get_augment_info("7777") is not None  # 重新加载后仍可查

    def test_missing_directory_loads_empty(self, fixture_data_dir) -> None:
        shutil.rmtree(fixture_data_dir / "aramkit" / "resources")
        resources = AramkitResources(fixture_data_dir / "aramkit" / "resources")
        assert resources.get_augment_info("7777") is None
