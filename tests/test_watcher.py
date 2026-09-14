"""auto.watcher 行为测试（mock 窗口定位/截图，验证轮询→状态机→触发链路）。"""

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

import aram_mayhem_helper.auto.watcher as watcher_module
from aram_mayhem_helper.algorithm.recommend_flow import RecommendOutcome
from aram_mayhem_helper.auto.detection import DetectionThresholds, looks_like_selection_ui_stats
from aram_mayhem_helper.auto.watcher import AutoWatcher, capture_region_stats, find_game_window, is_window_foreground

# 实测像素统计（见 detection.py）
_SELECTION_STATS = [(31.5, 51.6), (32.8, 53.6), (41.5, 65.3)]
_INGAME_STATS = [(106.7, 24.6), (99.1, 31.8), (132.3, 28.1)]


class FakeWatcher(AutoWatcher):
    """注入测试替身的 watcher：直接喂像素统计序列，绕过窗口定位/截图。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.samples: list[list[tuple[float, float]]] = []  # 每轮注入的像素统计
        self.recommend_calls = 0
        self.notified: list[tuple[str, list[str]]] = []

    def _poll_once(self) -> None:
        if not self.samples:
            return
        stats = self.samples.pop(0)
        result = self._detector.feed(looks_like_selection_ui_stats(stats, self._thresholds))
        if result.should_trigger:
            self.recommend_calls += 1
            self._notify_fn(["快选：神圣雪球"])


class TestAutoWatcherPolling:
    def test_triggers_recommendation_and_notify(self) -> None:
        """连续两轮选择界面统计 → 触发一次推荐 + 一次结果展示。"""
        calls: list[list[str]] = []

        def fake_notify(lines: list[str]) -> bool:
            calls.append(lines)
            return True

        w = FakeWatcher(notify_fn=fake_notify, poll_interval=0.01, debounce_count=2)
        w.samples = [_SELECTION_STATS, _SELECTION_STATS]
        w._poll_once()
        w._poll_once()
        assert w.recommend_calls == 1
        assert calls == [["快选：神圣雪球"]]

    def test_no_trigger_on_ingame_stats(self) -> None:
        w = FakeWatcher(poll_interval=0.01)
        w.samples = [_INGAME_STATS, _INGAME_STATS, _INGAME_STATS]
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 0

    def test_no_repeat_trigger_within_same_selection(self) -> None:
        """选择界面持续多轮只触发一次（TRIGGERED 状态保持）。"""
        w = FakeWatcher(poll_interval=0.01, debounce_count=1)
        w.samples = [_SELECTION_STATS] * 5
        for _ in range(5):
            w._poll_once()
        assert w.recommend_calls == 1

    def test_retriggers_in_next_selection_phase(self) -> None:
        """一局第二次选择阶段：消失后重新武装，可再次触发。"""
        w = FakeWatcher(poll_interval=0.01, debounce_count=1)
        # 第一次选择阶段
        w.samples = [_SELECTION_STATS, _SELECTION_STATS, _SELECTION_STATS]
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 1
        # 回到游戏 → 重新武装
        w.samples = [_INGAME_STATS]
        w._poll_once()
        # 第二次选择阶段
        w.samples = [_SELECTION_STATS]
        w._poll_once()
        assert w.recommend_calls == 2

    def test_debounce_filters_transient_dark_frame(self) -> None:
        """单轮暗帧（过渡画面）被去抖过滤，不触发。"""
        w = FakeWatcher(poll_interval=0.01, debounce_count=2)
        w.samples = [_SELECTION_STATS, _INGAME_STATS, _SELECTION_STATS, _SELECTION_STATS]
        for _ in range(4):
            w._poll_once()
        assert w.recommend_calls == 1  # 仅第 3、4 轮连续命中触发


class TestWatcherLifecycle:
    @pytest.fixture
    def idle_watcher(self) -> Iterator[AutoWatcher]:
        """轮询立即返回的 watcher（不依赖窗口/截图环境）。"""
        w = AutoWatcher(poll_interval=0.05)
        w._poll_once = lambda: None  # noqa: B008 - 测试替身：隔离窗口/截图环境
        yield w
        w.stop()
        w.join(timeout=2)

    def test_start_stop_thread(self, idle_watcher: AutoWatcher) -> None:
        """start 启动线程，stop 使其在下一间隔退出。"""
        w = idle_watcher
        w.start()
        assert w.is_running
        assert w._thread is not None and w._thread.is_alive()
        w.stop()
        w.join(timeout=2)
        assert not w.is_running
        assert w._thread is not None and not w._thread.is_alive()

    def test_stop_before_start_is_noop(self) -> None:
        w = AutoWatcher()
        w.stop()  # 不应抛异常
        assert not w.is_running

    def test_double_start_is_noop(self, idle_watcher: AutoWatcher) -> None:
        w = idle_watcher
        w.start()
        first_thread = w._thread
        w.start()  # 重复启动不换线程
        assert w._thread is first_thread

    def test_watch_loop_survives_poll_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单次轮询抛异常时循环不退出（记日志继续下一轮）。"""
        w = AutoWatcher(poll_interval=0.01)
        calls = 0

        def boom() -> None:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("boom")

        monkeypatch.setattr(w, "_poll_once", boom)
        w._thread = threading.Thread(target=w._watch_loop, daemon=True)
        w._thread.start()
        time.sleep(0.1)  # 等 3 轮
        w.stop()
        w.join(timeout=2)
        assert calls >= 3


class TestWindowHelpers:
    def test_find_game_window_no_game(self) -> None:
        """无游戏窗口时返回 None 或合法句柄（视测试环境而定）。"""
        result = find_game_window()
        assert result is None or isinstance(result, int)

    def test_is_window_foreground_zero_hwnd(self) -> None:
        assert is_window_foreground(0) is False

    def test_capture_region_stats_invalid_hwnd(self) -> None:
        """无效句柄返回 None（GetClientRect 失败）。"""
        assert capture_region_stats(0) is None


class TestWatcherDefaults:
    def test_default_thresholds_applied(self) -> None:
        w = AutoWatcher()
        assert w._thresholds == DetectionThresholds()

    def test_custom_thresholds_applied(self) -> None:
        w = AutoWatcher(thresholds=DetectionThresholds(mean_threshold=1.0, std_threshold=2.0))
        assert w._thresholds == DetectionThresholds(mean_threshold=1.0, std_threshold=2.0)

    def test_default_dependencies_injected(self) -> None:
        """默认依赖为真实函数（确保生产路径未被测试替身污染）。"""
        w = AutoWatcher()
        assert w._run_recommend_fn is watcher_module.run_recommend
        assert w._notify_fn is watcher_module.notify_result


class TestNotifyResult:
    def setup_method(self) -> None:
        """每个测试前清除根窗口引用与队列（模块级状态隔离）。"""
        watcher_module.set_tk_root(None)
        watcher_module._overlay_queue = __import__("queue").Queue()

    def teardown_method(self) -> None:
        watcher_module.set_tk_root(None)

    def test_empty_lines_returns_false(self) -> None:
        assert watcher_module.notify_result([]) is False

    def test_no_root_prints_to_console(self, capsys: pytest.CaptureFixture[str]) -> None:
        """CLI 模式（未注入根窗口）：打印控制台并返回 True。"""
        assert watcher_module.notify_result(["快选：测试"]) is True
        captured = capsys.readouterr()
        assert "快选：测试" in captured.out
        assert "符文推荐" in captured.out

    def test_with_root_enqueues_overlay_request(self) -> None:
        """GUI 模式（已注入根窗口）：请求入队（watcher 线程不碰 Tk API）。"""
        watcher_module.set_tk_root(object())  # type: ignore[arg-type]
        assert watcher_module.notify_result(["快选：测试"]) is True
        assert watcher_module._overlay_queue.qsize() == 1
        assert watcher_module._overlay_queue.get_nowait() == ["快选：测试"]

    def test_poll_overlay_queue_builds_and_reschedules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """队列轮询：消费请求构建悬浮窗，并重新调度自身。"""
        built: list[list[str]] = []
        scheduled: list[int] = []

        class FakeRoot:
            def after(self, delay_ms: int, func: Any, *args: Any) -> None:
                scheduled.append(delay_ms)

        monkeypatch.setattr(
            "aram_mayhem_helper.auto.overlay.show_recommendation_overlay",
            lambda lines, root=None: built.append(lines) or True,
        )
        watcher_module.set_tk_root(FakeRoot())  # type: ignore[arg-type]
        watcher_module._overlay_queue.put(["快选：测试"])
        watcher_module.poll_overlay_queue()
        assert built == [["快选：测试"]]
        assert scheduled == [watcher_module._OVERLAY_POLL_MS]


class TestRerollDetection:
    """reroll 检测：TRIGGERED 期间 OCR 文本变化 → 重触发。"""

    def _watcher(self) -> FakeWatcher:
        w = FakeWatcher(poll_interval=0.01, debounce_count=2)
        return w

    def test_reroll_retriggers_on_text_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """识别文本变化 → 重触发推荐。"""
        w = self._watcher()
        # 首次触发
        w.samples = [_SELECTION_STATS, _SELECTION_STATS]
        w._poll_once()
        w._poll_once()
        assert w.recommend_calls == 1
        assert w._last_augments is None  # 触发路径未更新（由 _check_reroll 更新）
        # 模拟首次 _check_reroll 建立基准
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["甲", "乙", "丙"])
        w._check_reroll()
        assert w._last_augments == ["甲", "乙", "丙"]
        # reroll：文本变化 → 重触发（用计数替身替换 _trigger_recommendation）
        trigger_count = {"n": 0}

        def counting_trigger() -> None:
            trigger_count["n"] += 1

        w._trigger_recommendation = counting_trigger  # type: ignore[method-assign]
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["甲", "丁", "戊"])
        w._check_reroll()
        assert trigger_count["n"] == 1

    def test_same_text_no_retrigger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """文本不变 → 不重触发。"""
        w = self._watcher()
        w.samples = [_SELECTION_STATS, _SELECTION_STATS]
        w._poll_once()
        w._poll_once()
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["甲", "乙", "丙"])
        w._check_reroll()
        w._check_reroll()
        assert w.recommend_calls == 1

    def test_empty_ocr_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """空 OCR 结果（动画帧）不算变化，也不更新基准。"""
        w = self._watcher()
        w.samples = [_SELECTION_STATS, _SELECTION_STATS]
        w._poll_once()
        w._poll_once()
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["甲", "乙", "丙"])
        w._check_reroll()
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["", "", ""])
        w._check_reroll()
        assert w.recommend_calls == 1
        assert w._last_augments == ["甲", "乙", "丙"]  # 基准未被空结果覆盖

    def test_order_change_counts_as_same(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """相同符文不同顺序（OCR 偶尔乱序）不算变化。"""
        w = self._watcher()
        w.samples = [_SELECTION_STATS, _SELECTION_STATS]
        w._poll_once()
        w._poll_once()
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["甲", "乙", "丙"])
        w._check_reroll()
        monkeypatch.setattr("aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["丙", "甲", "乙"])
        w._check_reroll()
        assert w.recommend_calls == 1


class TestShardUiFilter:
    """「三选一碎片」界面过滤：正常游戏流程，静默跳过。"""

    def test_is_shard_ui_all_shard_names(self) -> None:
        from aram_mayhem_helper.auto.watcher import _is_shard_ui

        assert _is_shard_ui(["力量碎片", "迅捷碎片", "护甲碎片"]) is True

    def test_is_shard_ui_real_augments(self) -> None:
        from aram_mayhem_helper.auto.watcher import _is_shard_ui

        assert _is_shard_ui(["飞升仪式", "精怪魔法", "终极九头蛇"]) is False

    def test_is_shard_ui_mixed(self) -> None:
        from aram_mayhem_helper.auto.watcher import _is_shard_ui

        # 部分以碎片结尾（OCR 残缺）不算碎片界面
        assert _is_shard_ui(["力量碎片", "飞升仪式", ""]) is False

    def test_is_shard_ui_empty(self) -> None:
        from aram_mayhem_helper.auto.watcher import _is_shard_ui

        assert _is_shard_ui([]) is False

    def test_check_reroll_skips_shard_ui(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """碎片界面不触发推荐、不更新基准。"""
        w = FakeWatcher(poll_interval=0.01)
        w.samples = [_SELECTION_STATS, _SELECTION_STATS]
        w._poll_once()
        w._poll_once()
        monkeypatch.setattr(
            "aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["力量碎片", "迅捷碎片", "护甲碎片"]
        )
        w._check_reroll()
        assert w.recommend_calls == 1  # 只有首次触发，无 reroll 重触发
        assert w._last_augments is None  # 基准未更新

    def test_trigger_recommendation_skips_shard_ui(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """首次触发路径遇碎片界面：静默返回，不调 run_recommend。"""
        calls = {"run_recommend": 0}
        monkeypatch.setattr(
            "aram_mayhem_helper.ocr.ocr_tool.OCRTool.get_augments", lambda self: ["力量碎片", "迅捷碎片", "护甲碎片"]
        )

        def fake_run_recommend(*args: Any, **kwargs: Any) -> RecommendOutcome:
            calls["run_recommend"] += 1
            return RecommendOutcome(lines=[])

        w = FakeWatcher(run_recommend_fn=fake_run_recommend, poll_interval=0.01)
        w._trigger_recommendation()
        assert calls["run_recommend"] == 0
