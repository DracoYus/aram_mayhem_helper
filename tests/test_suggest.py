"""algorithm.suggest 引擎行为锁定测试（分组/打分/推荐字符串）。"""

import pytest

import aram_mayhem_helper.algorithm.suggest as suggest_mod
from aram_mayhem_helper.utils.aramkit import AramkitResources
from aram_mayhem_helper.utils.data import ChampionAugmentData


@pytest.fixture(autouse=True)
def _use_fixture_data(patch_config_data_path):
    """本模块所有测试使用 fixture 数据目录（当前数据类读 config.data_path）。"""
    return patch_config_data_path


def _patch_lookup(monkeypatch: pytest.MonkeyPatch, trans_table: dict[str, dict]) -> None:
    """用 fixture 翻译表替换 suggest 模块的源感知查找函数。"""

    resources = AramkitResources()

    def fake_info(source: str, augment_id: str) -> dict | None:
        info = trans_table.get(str(augment_id))
        if info is None and source == "aramkit":
            return resources.get_augment_info(str(augment_id))
        return info

    def fake_id(source: str, augment_name: str) -> str | None:
        for aid, info in trans_table.items():
            if info["name"] == augment_name:
                return aid
        if source == "aramkit":
            return resources.get_augment_id(augment_name)
        return None

    monkeypatch.setattr(suggest_mod, "get_augment_info_for_source", fake_info)
    monkeypatch.setattr(suggest_mod, "get_augment_id_for_source", fake_id)


def _build_suggest(monkeypatch, trans_table, champion_id: str = "103", source: str = "opgg"):
    _patch_lookup(monkeypatch, trans_table)
    return suggest_mod.Suggest(ChampionAugmentData(champion_id, source=source))


class TestSuggestInit:
    def test_groups_by_level_and_scores(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        assert {k: len(v["augments"]) for k, v in s.augment_group.items()} == {"2": 3, "1": 3}

    def test_exact_scored_items_opgg(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        items = s.augment_group["2"]["augments"]
        assert [
            (i["id"], i["rank"], i["group_size"], i["weighted_sum"], i["performance_norm"], i["popular_norm"])
            for i in items
        ] == [
            (1005, 1, 3, 0.6746, 0.7604, 0.5),
            (1001, 2, 3, 0.5, 0.8616, 0.0),
            (1004, 3, 3, 0.3538, 0.2961, 1.0),
        ]

    def test_aramkit_converted_and_fallback_lookup(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table, source="aramkit")
        assert {k: len(v["augments"]) for k, v in s.augment_group.items()} == {"2": 3, "1": 4}
        # 7777 来自 aramkit 资源回退
        fallback = [i for i in s.augment_group["1"]["augments"] if i["id"] == 7777]
        assert fallback[0]["name"] == "测试回退符文"
        assert fallback[0]["performance"] == 0.6

    def test_popular_zero_entries_are_filtered(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table, champion_id="22")
        assert s.augment_group == {}

    def test_unknown_ids_are_skipped(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        # 9999 不在翻译表 → 不入组
        assert all(i["id"] != 9999 for g in s.augment_group.values() for i in g["augments"])


class TestSuggestMethods:
    def test_get_augment_info_by_id(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        info = s.get_augment_info_by_id("1001")
        assert info is not None
        assert info["id"] == 1001
        assert info["name"] == "泰坦的坚决"
        assert s.get_augment_info_by_id("") is None
        # 特征锁定：9999 有 perf/pop 值，虽 lookup miss 不入组，但仍留在过滤后数据中
        assert s.get_augment_info_by_id("9999") == {"id": 9999, "tier": 0, "performance": 50.0, "popular": 40.0}

    def test_suggest_recommendation_strings_opgg(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        results = s.suggest(["泰坦的坚决", "尖端发明家", "不存在符文"])
        assert results == [
            "考虑符文：泰坦的坚决，可以随掉，2/3，表现: 0.8616，流行度: 0.0",
            "考虑符文：尖端发明家，暂时先别换，1/3，表现: 0.6845，流行度: 1.0",
        ]

    def test_suggest_recommendation_strings_aramkit(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table, source="aramkit")
        results = s.suggest(["泰坦的坚决", "尖端发明家"])
        assert results == [
            "垃圾符文: 泰坦的坚决，别选，太垃圾了，3/3，表现: 0.0514，流行度: 0.5",
            "考虑符文：尖端发明家，暂时先别换，2/3，表现: 0.5394，流行度: 1.0",
        ]

    def test_suggest_all_unknown_returns_empty(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        assert s.suggest(["完全不存在的符文"]) == []

    def test_get_suggest_info_threshold_boundaries(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        # group_size=10 → immediate_rank=1.0, consider_rank=3.0
        base = {
            "name": "X",
            "group_size": 10,
            "rank": 1,
            "weighted_sum": 0.3,
            "performance_norm": 0.5,
            "popular_norm": 0.5,
        }

        def msg(rank: int, ws: float) -> str:
            item = {**base, "rank": rank, "weighted_sum": ws}
            return s.get_suggest_info([item])[0]

        # rank ≤ 1 或 ws ≥ 0.70 → 快选
        assert msg(rank=1, ws=0.3).startswith("快选符文：")
        assert msg(rank=5, ws=0.75).startswith("快选符文：")
        # rank ≤ 3 或 ws ≥ 0.50 → 考虑；单元素输入时该元素即组内最高 → "暂时先别换"
        assert msg(rank=3, ws=0.3).startswith("考虑符文：")
        assert "暂时先别换" in msg(rank=4, ws=0.5)
        assert "暂时先别换" in msg(rank=4, ws=0.51)
        # 组内存在更高 ws 时 → "可以随掉"
        top = {**base, "rank": 1, "weighted_sum": 0.9}
        below = {**base, "rank": 4, "weighted_sum": 0.51}
        assert "可以随掉" in s.get_suggest_info([top, below])[1]
        # 其余 → 垃圾
        assert msg(rank=9, ws=0.2).startswith("垃圾符文:")

    def test_get_suggest_info_empty_and_missing_group_size(self, monkeypatch, fixture_trans_table) -> None:
        s = _build_suggest(monkeypatch, fixture_trans_table)
        assert s.get_suggest_info([]) == []
        assert s.get_suggest_info([{"name": "X"}]) == []
