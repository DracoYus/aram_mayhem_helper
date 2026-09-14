"""auto.detection 像素判别与状态机行为测试。"""

import numpy as np
import pytest

from aram_mayhem_helper.auto.detection import (
    DEFAULT_MEAN_THRESHOLD,
    DEFAULT_STD_THRESHOLD,
    DetectionResult,
    DetectionThresholds,
    SelectionDetector,
    SelectionState,
    looks_like_selection_ui,
    looks_like_selection_ui_stats,
)

# 实测样本（选择界面 / 游戏内，见 detection.py 模块注释）
_SELECTION_STATS = [(31.5, 51.6), (32.8, 53.6), (41.5, 65.3)]
_INGAME_STATS = [(106.7, 24.6), (99.1, 31.8), (132.3, 28.1)]


class TestLooksLikeSelectionUi:
    def test_selection_like_image_passes(self) -> None:
        # 暗背景 + 高对比白字：模拟选择界面卡片
        image = np.full((108, 576), 20, dtype=np.uint8)
        image[40:70, 100:400] = 230
        assert looks_like_selection_ui(image, DetectionThresholds()) is True

    def test_bright_low_contrast_image_fails(self) -> None:
        # 游戏内地图像素：亮且对比低
        image = np.full((108, 576), 110, dtype=np.uint8)
        image[40:70, 100:400] = 140
        assert looks_like_selection_ui(image, DetectionThresholds()) is False

    def test_dark_but_flat_image_fails(self) -> None:
        # 纯黑画面（如加载黑屏）：mean 命中但 std 不命中
        image = np.zeros((108, 576), dtype=np.uint8)
        assert looks_like_selection_ui(image, DetectionThresholds()) is False

    def test_empty_image_fails(self) -> None:
        image = np.zeros((0, 0), dtype=np.uint8)
        assert looks_like_selection_ui(image, DetectionThresholds()) is False


class TestLooksLikeSelectionUiStats:
    def test_measured_selection_stats_pass(self) -> None:
        assert looks_like_selection_ui_stats(_SELECTION_STATS, DetectionThresholds()) is True

    def test_measured_ingame_stats_fail(self) -> None:
        assert looks_like_selection_ui_stats(_INGAME_STATS, DetectionThresholds()) is False

    def test_any_region_hit_counts(self) -> None:
        # 单个区域命中即算（容忍单区域被遮挡导致的特征偏移）
        mixed = [(110.0, 20.0), (35.0, 55.0), (120.0, 25.0)]
        assert looks_like_selection_ui_stats(mixed, DetectionThresholds()) is True

    def test_empty_stats_fail(self) -> None:
        assert looks_like_selection_ui_stats([], DetectionThresholds()) is False

    def test_custom_thresholds(self) -> None:
        strict = DetectionThresholds(mean_threshold=10.0, std_threshold=100.0)
        assert looks_like_selection_ui_stats(_SELECTION_STATS, strict) is False


class TestSelectionDetector:
    def test_initial_state_is_running(self) -> None:
        detector = SelectionDetector()
        assert detector.state is SelectionState.RUNNING

    def test_no_trigger_below_debounce(self) -> None:
        detector = SelectionDetector(debounce_count=3)
        assert detector.feed(True).should_trigger is False
        assert detector.feed(True).should_trigger is False
        assert detector.state is SelectionState.RUNNING

    def test_triggers_after_consecutive_hits(self) -> None:
        detector = SelectionDetector(debounce_count=2)
        assert detector.feed(True).should_trigger is False
        result = detector.feed(True)
        assert result.should_trigger is True
        assert result.state is SelectionState.TRIGGERED

    def test_single_miss_resets_counter(self) -> None:
        detector = SelectionDetector(debounce_count=2)
        detector.feed(True)
        detector.feed(False)  # 断开连续性
        assert detector.feed(True).should_trigger is False

    def test_no_repeat_trigger_while_in_selection(self) -> None:
        detector = SelectionDetector(debounce_count=1)
        assert detector.feed(True).should_trigger is True
        # 仍在选择界面时保持 TRIGGERED，不重复触发
        assert detector.feed(True).should_trigger is False
        assert detector.feed(True).should_trigger is False

    def test_rearms_after_signal_disappears(self) -> None:
        detector = SelectionDetector(debounce_count=1)
        detector.feed(True)  # 触发
        detector.feed(False)  # 选择结束 → 重新武装
        assert detector.state is SelectionState.RUNNING
        # 重新武装后可再次触发（一局多次选择阶段）
        assert detector.feed(True).should_trigger is True

    def test_reset_returns_to_running(self) -> None:
        detector = SelectionDetector(debounce_count=2)
        detector.feed(True)  # 计数 1/2
        detector.reset()
        assert detector.state is SelectionState.RUNNING
        assert detector.feed(True).should_trigger is False  # 计数已清零，需重新累计
        assert detector.feed(True).should_trigger is True

    def test_debounce_count_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="debounce_count"):
            SelectionDetector(debounce_count=0)

    def test_result_is_frozen_dataclass(self) -> None:
        result = DetectionResult(state=SelectionState.RUNNING, should_trigger=False)
        with pytest.raises(Exception):
            result.should_trigger = True  # type: ignore[misc]

    def test_default_thresholds_values(self) -> None:
        assert DEFAULT_MEAN_THRESHOLD == 60.0
        assert DEFAULT_STD_THRESHOLD == 40.0
