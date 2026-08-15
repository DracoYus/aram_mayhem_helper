"""algorithm.suggest 引擎测试（分组/打分/推荐字符串，基于 GameData 注入）。"""

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.utils.config import get_config


def _build_suggest(game_data, champion_id: str = "103", source: str = "opgg") -> Suggest:
    return Suggest(
        champion_id,
        game_data,
        source=source,
        thresholds=get_config().suggest,
    )


class TestSuggestInit:
    def test_groups_by_level_and_scores(self, game_data) -> None:
        s = _build_suggest(game_data)
        assert {k: len(v["augments"]) for k, v in s.augment_group.items()} == {"2": 3, "1": 3}

    def test_exact_scored_items_opgg(self, game_data) -> None:
        s = _build_suggest(game_data)
        items = s.augment_group["2"]["augments"]
        assert [
            (i["id"], i["rank"], i["group_size"], i["weighted_sum"], i["performance_norm"], i["popular_norm"])
            for i in items
        ] == [
            (1005, 1, 3, 0.6746, 0.7604, 0.5),
            (1001, 2, 3, 0.5, 0.8616, 0.0),
            (1004, 3, 3, 0.3538, 0.2961, 1.0),
        ]

    def test_aramkit_converted_and_fallback_lookup(self, game_data) -> None:
        s = _build_suggest(game_data, source="aramkit")
        assert {k: len(v["augments"]) for k, v in s.augment_group.items()} == {"2": 3, "1": 4}
        # 7777 来自 aramkit 资源回退
        fallback = [i for i in s.augment_group["1"]["augments"] if i["id"] == 7777]
        assert fallback[0]["name"] == "测试回退符文"
        assert fallback[0]["performance"] == 0.6

    def test_popular_zero_entries_are_filtered(self, game_data) -> None:
        s = _build_suggest(game_data, champion_id="22")
        assert s.augment_group == {}

    def test_unknown_ids_are_skipped(self, game_data) -> None:
        s = _build_suggest(game_data)
        # 9999 不在翻译表 → 不入组（统一后的行为：也不保留在 champion_augment_data）
        assert all(i["id"] != 9999 for g in s.augment_group.values() for i in g["augments"])
        assert s.get_augment_info_by_id("9999") is None

    def test_unknown_champion_initializes_empty(self, game_data) -> None:
        s = _build_suggest(game_data, champion_id="999")
        assert s.augment_group == {}
        assert s.champion_augment_data == []

    def test_single_item_group_does_not_crash(self, game_data, fixture_data_dir) -> None:
        # 单元素 level 组方差为 0：统一后容错跳过打分（旧 Suggest 会抛 ValueError）
        import json

        entries = game_data.augment_entries("103", "opgg")
        single = [e for e in entries if e["id"] == 1002]
        (fixture_data_dir / "opgg" / "aram_augments" / "103.json").write_text(
            json.dumps({"data": single}), encoding="utf-8"
        )
        game_data.reload()
        s = _build_suggest(game_data)
        assert "1" in s.augment_group  # 组保留（无分数）

    def test_default_source_used_when_omitted(self, game_data) -> None:
        s = _build_suggest(game_data, source=None)
        assert s.source == game_data.default_source()


class TestSuggestMethods:
    def test_get_augment_info_by_id(self, game_data) -> None:
        s = _build_suggest(game_data)
        info = s.get_augment_info_by_id("1001")
        assert info is not None
        assert info["id"] == 1001
        assert info["name"] == "泰坦的坚决"
        assert s.get_augment_info_by_id("") is None

    def test_suggest_recommendation_strings_opgg(self, game_data) -> None:
        s = _build_suggest(game_data)
        results = s.suggest(["泰坦的坚决", "尖端发明家", "不存在符文"])
        assert results == [
            "考虑符文：泰坦的坚决，2/3，表现: 0.8616，流行度: 0.0",
            "考虑符文：尖端发明家，1/3，表现: 0.6845，流行度: 1.0",
        ]

    def test_suggest_recommendation_strings_aramkit(self, game_data) -> None:
        s = _build_suggest(game_data, source="aramkit")
        results = s.suggest(["泰坦的坚决", "尖端发明家"])
        assert results == [
            "垃圾符文: 泰坦的坚决，3/3，表现: 0.0514，流行度: 0.5",
            "考虑符文：尖端发明家，2/3，表现: 0.5394，流行度: 1.0",
        ]

    def test_suggest_all_unknown_returns_empty(self, game_data) -> None:
        s = _build_suggest(game_data)
        assert s.suggest(["完全不存在的符文"]) == []

    def test_get_suggest_info_threshold_boundaries(self, game_data) -> None:
        s = _build_suggest(game_data)
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
        # rank ≤ 3 或 ws ≥ 0.50 → 考虑
        assert msg(rank=3, ws=0.3).startswith("考虑符文：")
        assert msg(rank=4, ws=0.5) == "考虑符文：X，4/10，表现: 0.5，流行度: 0.5"
        assert msg(rank=4, ws=0.51) == "考虑符文：X，4/10，表现: 0.5，流行度: 0.5"
        # 组内存在更高 ws 时仍为考虑
        top = {**base, "rank": 1, "weighted_sum": 0.9}
        below = {**base, "rank": 4, "weighted_sum": 0.51}
        assert s.get_suggest_info([top, below])[1].startswith("考虑符文：")
        # 其余 → 垃圾
        assert msg(rank=9, ws=0.2).startswith("垃圾符文:")

    def test_get_suggest_info_empty_and_missing_group_size(self, game_data) -> None:
        s = _build_suggest(game_data)
        assert s.get_suggest_info([]) == []
        assert s.get_suggest_info([{"name": "X"}]) == []


class TestSuggestOnUnrecognized:
    def test_callback_fires_with_index_and_text_for_unmatched(self, game_data) -> None:
        s = _build_suggest(game_data)
        calls: list[tuple[int, str]] = []
        results = s.suggest(
            ["泰坦的坚决", "不存在符文", "另一个不存在"], on_unrecognized=lambda i, t: calls.append((i, t))
        )
        assert calls == [(1, "不存在符文"), (2, "另一个不存在")]  # 索引与输入位置一一对应
        assert len(results) == 1  # 匹配的照常推荐

    def test_callback_not_fired_when_all_matched(self, game_data) -> None:
        s = _build_suggest(game_data)
        calls: list[tuple[int, str]] = []
        s.suggest(["泰坦的坚决", "尖端发明家"], on_unrecognized=lambda i, t: calls.append((i, t)))
        assert calls == []

    def test_default_none_keeps_behavior(self, game_data) -> None:
        s = _build_suggest(game_data)
        assert s.suggest(["完全不存在的符文"]) == []  # 默认参数路径不变
