"""打分函数测试：algorithm.scoring 的缩放与贝叶斯-sigmoid 打分行为（自 utils.norm 迁移）。"""

import pytest

from aram_mayhem_helper.algorithm.scoring import add_bayesian_sigmoid_score_attr, add_unit_scale_attr


def _sample_group() -> list[dict]:
    return [
        {"id": "a", "performance": 0.55, "popular": 0.1},
        {"id": "b", "performance": 0.52, "popular": 0.2},
        {"id": "c", "performance": 0.60, "popular": 0.05},
        {"id": "d", "performance": 0.40, "popular": 0.01},
    ]


class TestAddUnitScaleAttr:
    def test_min_max_scales_perf_and_pop_to_unit(self) -> None:
        items = _sample_group()
        add_unit_scale_attr(items)
        assert [(i["performance_unit"], i["popular_unit"]) for i in items] == [
            (0.75, 0.4737),
            (0.6, 1.0),
            (1.0, 0.2105),
            (0.0, 0.0),
        ]
        # 原始字段不被覆盖
        assert [i["performance"] for i in items] == [0.55, 0.52, 0.60, 0.40]

    def test_all_equal_values_map_to_zero(self) -> None:
        items = [{"id": "x", "performance": 5, "popular": 2}, {"id": "y", "performance": 5, "popular": 2}]
        add_unit_scale_attr(items)
        assert [(i["performance_unit"], i["popular_unit"]) for i in items] == [(0.0, 0.0), (0.0, 0.0)]

    def test_empty_list_is_noop(self) -> None:
        add_unit_scale_attr([])  # 不应抛异常

    def test_missing_key_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            add_unit_scale_attr([{"id": "a", "popular": 1.0}])


class TestAddBayesianSigmoidScoreAttr:
    def test_exact_scores_on_sample_group(self) -> None:
        items = _sample_group()
        add_unit_scale_attr(items)
        add_bayesian_sigmoid_score_attr(
            items,
            perf_attr="performance_unit",
            pop_attr="popular_unit",
            new_attr="weighted_sum",
            tau_factor=0.5,
            sigmoid_steepness=1.0,
            perf_display_attr="performance_norm",
            pop_display_attr="popular_norm",
        )
        assert [(i["weighted_sum"], i["performance_norm"], i["popular_norm"]) for i in items] == [
            (0.5717, 0.6066, 0.6667),
            (0.364, 0.3339, 1.0),
            (0.7474, 0.9093, 0.3333),
            (0.5, 0.0056, 0.0),
        ]

    def test_popular_percentile_most_popular_is_1(self) -> None:
        items = _sample_group()
        add_unit_scale_attr(items)
        add_bayesian_sigmoid_score_attr(
            items,
            perf_attr="performance_unit",
            pop_attr="popular_unit",
            perf_display_attr="performance_norm",
            pop_display_attr="popular_norm",
        )
        assert items[1]["popular_norm"] == 1.0  # popular_unit 最高者

    def test_empty_list_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="data_list is empty"):
            add_bayesian_sigmoid_score_attr([])

    def test_missing_key_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            add_bayesian_sigmoid_score_attr([{"performance": 0.5}])

    def test_zero_perf_variance_raises_value_error(self) -> None:
        items = [
            {"performance": 0.5, "popular": 1.0},
            {"performance": 0.5, "popular": 2.0},
            {"performance": 0.5, "popular": 3.0},
        ]
        with pytest.raises(ValueError, match="performance std is 0"):
            add_bayesian_sigmoid_score_attr(items)
