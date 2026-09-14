"""auto.watcher 行为测试（mock 窗口定位/截图，验证轮询→状态机→触发链路）。"""

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

import aram_mayhem_helper.auto.watcher as watcher_module
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
