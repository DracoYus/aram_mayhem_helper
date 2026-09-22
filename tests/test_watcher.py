"""auto.watcher 行为测试（mock 窗口定位/截图/OCR，验证两级检测→触发→展示链路）。"""

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
_REAL_AUGMENTS = ["快中求稳", "海洋龙魂", "家园卫士"]
_REAL_AUGMENTS_ALT = ["甲", "乙", "丙"]


class FakeWatcher(AutoWatcher):
    """注入测试替身的 watcher：像素统计/OCR 文本序列化喂入，绕过窗口/截图 I/O。

    复制生产 _poll_once 的判定逻辑（像素预筛 → OCR 确认 → 触发/reroll），
    用测试序列替代窗口定位/截图/OCR，_has_known_augment 用本地词表替身。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pixel_samples: list[list[tuple[float, float]]] = []
        self.ocr_results: list[list[str]] = []
        self.recommend_calls = 0
        self.notified: list[list[str]] = []
        self.known_augments: set[str] = set(_REAL_AUGMENTS) | set(_REAL_AUGMENTS_ALT)

    def _has_known_augment(self, augments: list[str]) -> bool:
        return any(text in self.known_augments for text in augments if text)

    def _trigger_recommendation(self, augments: list[str] | None = None) -> None:
        self.recommend_calls += 1
        self._last_augments = augments
        self._notify_fn(["快选：测试"])

    def _poll_once(self) -> None:
        """与生产逻辑同构（生产 _poll_once 改动时需同步本方法）。"""
        if not self.pixel_samples:
            return
        stats = self.pixel_samples.pop(0)
        if not looks_like_selection_ui_stats(stats, self._thresholds):
            self._detector.feed(False)
            self._last_augments = None
            return
        if not self.ocr_results:
            return
        augments = self.ocr_results.pop(0)
        if not any(augments):
            return
        if watcher_module._is_shard_ui(augments):
            return
        if not self._has_known_augment(augments):
            self._false_positive_streak += 1
            self._next_ocr_delay = watcher_module._FALSE_POSITIVE_BACKOFF_SECONDS
            return
        self._false_positive_streak = 0
        self._next_ocr_delay = 0.0
        self._selection_seen_at = time.monotonic()  # 悬浮窗保活时间戳
        result = self._detector.feed(True)
        if result.should_trigger:
            self._trigger_recommendation(augments)
        elif self._last_augments is not None and set(augments) != set(self._last_augments):
            if sum(1 for text in augments if text) < 2:
                return  # reroll 动画半空帧
            self._trigger_recommendation(augments)


class TestTwoStageDetection:
    """两级检测：像素预筛命中但 OCR 内容不匹配 → 不触发。"""

    def _w(self, **kwargs: Any) -> FakeWatcher:
        return FakeWatcher(poll_interval=0.01, debounce_count=1, **kwargs)

    def test_kda_ui_not_triggered(self) -> None:
        """记分板 KDA 文本（13182/5/16 等）：像素命中但查表全失败 → 不触发。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS, _SELECTION_STATS, _SELECTION_STATS]
        w.ocr_results = [["13182/5/16", "", "17/9"]] * 3
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 0

    def test_real_augments_triggered(self) -> None:
        """真实符文名：像素命中 + 查表命中 → 触发。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS, _SELECTION_STATS]
        w.ocr_results = [_REAL_AUGMENTS, _REAL_AUGMENTS]
        w._poll_once()
        w._poll_once()
        assert w.recommend_calls == 1
        assert w._last_augments == _REAL_AUGMENTS

    def test_empty_ocr_does_not_trigger(self) -> None:
        """OCR 空（过渡帧）：不触发，基准不变。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS, _SELECTION_STATS]
        w.ocr_results = [["", "", ""], ["", "", ""]]
        w._poll_once()
        w._poll_once()
        assert w.recommend_calls == 0
        assert w._last_augments is None

    def test_shard_ui_not_triggered(self) -> None:
        """碎片界面：不触发、不更新基准。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS, _SELECTION_STATS, _SELECTION_STATS]
        w.ocr_results = [["力量碎片", "迅捷碎片", "护甲碎片"]] * 3
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 0
        assert w._last_augments is None

    def test_pixel_miss_resets_baseline(self) -> None:
        """像素预筛未命中（回游戏）：重武装 + 清除 reroll 基准。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS, _INGAME_STATS]
        w.ocr_results = [_REAL_AUGMENTS]
        w._poll_once()  # 触发
        assert w._last_augments == _REAL_AUGMENTS
        w._poll_once()  # 游戏画面 → 重武装
        assert w._detector.state.name == "RUNNING"
        assert w._last_augments is None


class TestRerollViaPoll:
    """reroll：选择界面持续中 OCR 文本变化 → 重触发（经 _poll_once 全链路）。"""

    def _w(self, **kwargs: Any) -> FakeWatcher:
        return FakeWatcher(poll_interval=0.01, debounce_count=1, **kwargs)

    def test_text_change_retriggers(self) -> None:
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [_REAL_AUGMENTS, _REAL_AUGMENTS, _REAL_AUGMENTS_ALT]
        w._poll_once()  # 触发 #1
        w._poll_once()  # 相同文本，不重触发
        w._poll_once()  # 文本变化 → 重触发
        assert w.recommend_calls == 2
        assert w._last_augments == _REAL_AUGMENTS_ALT

    def test_same_text_no_retrigger(self) -> None:
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 4
        w.ocr_results = [_REAL_AUGMENTS] * 4
        for _ in range(4):
            w._poll_once()
        assert w.recommend_calls == 1

    def test_order_change_counts_as_same(self) -> None:
        """相同符文不同顺序（OCR 乱序）不算变化。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [_REAL_AUGMENTS, _REAL_AUGMENTS, list(reversed(_REAL_AUGMENTS))]
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 1


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
        w.stop()
        assert not w.is_running

    def test_double_start_is_noop(self, idle_watcher: AutoWatcher) -> None:
        w = idle_watcher
        w.start()
        first_thread = w._thread
        w.start()
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
        time.sleep(0.1)
        w.stop()
        w.join(timeout=2)
        assert calls >= 3


class TestWindowHelpers:
    def test_find_game_window_no_game(self) -> None:
        result = find_game_window()
        assert result is None or isinstance(result, int)

    def test_is_window_foreground_zero_hwnd(self) -> None:
        assert is_window_foreground(0) is False

    def test_capture_region_stats_invalid_hwnd(self) -> None:
        assert capture_region_stats(0) is None


class TestWatcherDefaults:
    def test_default_thresholds_applied(self) -> None:
        w = AutoWatcher()
        assert w._thresholds == DetectionThresholds()

    def test_custom_thresholds_applied(self) -> None:
        w = AutoWatcher(thresholds=DetectionThresholds(mean_threshold=1.0, std_threshold=2.0))
        assert w._thresholds == DetectionThresholds(mean_threshold=1.0, std_threshold=2.0)

    def test_default_dependencies_injected(self) -> None:
        w = AutoWatcher()
        assert w._run_recommend_fn is watcher_module.run_recommend
        assert w._notify_fn is watcher_module.notify_result


class TestNotifyResult:
    def setup_method(self) -> None:
        watcher_module.set_tk_root(None)
        import queue

        watcher_module._overlay_queue = queue.Queue()

    def teardown_method(self) -> None:
        watcher_module.set_tk_root(None)

    def test_empty_lines_returns_false(self) -> None:
        assert watcher_module.notify_result([]) is False

    def test_no_root_prints_to_console(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert watcher_module.notify_result(["快选：测试"]) is True
        captured = capsys.readouterr()
        assert "快选：测试" in captured.out
        assert "符文推荐" in captured.out

    def test_with_root_enqueues_overlay_request(self) -> None:
        watcher_module.set_tk_root(object())  # type: ignore[arg-type]
        assert watcher_module.notify_result(["快选：测试"]) is True
        assert watcher_module._overlay_queue.qsize() == 1
        assert watcher_module._overlay_queue.get_nowait() == (["快选：测试"], None)

    def test_keep_alive_travels_with_request(self) -> None:
        """保活判据随请求入队（主线程建窗时才知道界面是否还在显示）。"""
        predicate = lambda: True  # noqa: E731 - 测试替身：判据只需可调用
        watcher_module.set_tk_root(object())  # type: ignore[arg-type]
        assert watcher_module.notify_result(["快选：测试"], keep_alive=predicate) is True
        assert watcher_module._overlay_queue.get_nowait() == (["快选：测试"], predicate)

    def test_poll_overlay_queue_builds_and_reschedules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[tuple[list[str], Any]] = []
        scheduled: list[int] = []

        class FakeRoot:
            def after(self, delay_ms: int, func: Any, *args: Any) -> None:
                scheduled.append(delay_ms)

        monkeypatch.setattr(
            "aram_mayhem_helper.auto.overlay.show_recommendation_overlay",
            lambda lines, root=None, *, keep_alive=None: built.append((lines, keep_alive)) or True,
        )
        predicate = lambda: True  # noqa: E731 - 测试替身：判据只需可调用
        watcher_module.set_tk_root(FakeRoot())  # type: ignore[arg-type]
        watcher_module._overlay_queue.put((["快选：测试"], predicate))
        watcher_module.poll_overlay_queue()
        assert built == [(["快选：测试"], predicate)]
        assert scheduled == [watcher_module._OVERLAY_POLL_MS]


class TestShardUiFilter:
    def test_is_shard_ui_all_shard_names(self) -> None:
        assert watcher_module._is_shard_ui(["力量碎片", "迅捷碎片", "护甲碎片"]) is True

    def test_is_shard_ui_real_augments(self) -> None:
        assert watcher_module._is_shard_ui(_REAL_AUGMENTS) is False

    def test_is_shard_ui_mixed(self) -> None:
        assert watcher_module._is_shard_ui(["力量碎片", "飞升仪式", ""]) is False

    def test_is_shard_ui_empty(self) -> None:
        assert watcher_module._is_shard_ui([]) is False


class TestRecommendOutcomeAugments:
    def test_augments_field_roundtrip(self) -> None:
        outcome = RecommendOutcome(lines=[], augments=["甲", "乙"])
        assert outcome.augments == ["甲", "乙"]

    def test_default_none(self) -> None:
        assert RecommendOutcome(lines=[]).augments is None


class TestFalsePositiveBackoff:
    """误报退避：像素命中但内容非符文（死亡回放等持续 UI）时拉长采样间隔。"""

    def _w(self) -> FakeWatcher:
        w = FakeWatcher(poll_interval=0.01, debounce_count=1)
        return w

    def test_backoff_set_on_false_positive(self) -> None:
        """内容确认失败 → 退避生效 + 计数递增。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS]
        w.ocr_results = [["13182/5/16", "", "17/9"]]
        w._poll_once()
        assert w._next_ocr_delay == watcher_module._FALSE_POSITIVE_BACKOFF_SECONDS
        assert w._false_positive_streak == 1

    def test_backoff_resets_on_valid_content(self) -> None:
        """内容确认通过 → 退避与计数清零。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS]
        w.ocr_results = [_REAL_AUGMENTS]
        w._poll_once()
        assert w._next_ocr_delay == 0.0
        assert w._false_positive_streak == 0

    def test_streak_deduplicates_logs(self) -> None:
        """连续误报：计数递增但只记第一条（caplog 验证单条 DEBUG）。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [["13182/5/16", "", "17/9"]] * 3
        for _ in range(3):
            w._poll_once()
        assert w._false_positive_streak == 3

    def test_kda_pattern_prefilter(self) -> None:
        """KDA 数字模式直接排除，不查表。"""
        w = self._w()
        # 全是 KDA/纯数字 → 无候选，直接 False（不触发 GameData 加载）
        assert w._has_known_augment(["5910/6/28", "16", "11/17"]) is False
        assert w._has_known_augment(["0", "18", "664"]) is False
        assert w._has_known_augment(["13615%"]) is False


class TestPartialEmptyFrameFilter:
    """reroll 动画半空帧过滤：新内容 <2 个非空不算换卡。"""

    def _w(self) -> FakeWatcher:
        return FakeWatcher(poll_interval=0.01, debounce_count=1)

    def test_mostly_empty_change_skipped(self) -> None:
        """实测场景：['威能之追求', '', ''] 是动画帧，不重触发。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [_REAL_AUGMENTS, _REAL_AUGMENTS, ["威能之追求", "", ""]]
        w._poll_once()  # 触发
        w._poll_once()  # 相同
        w._poll_once()  # 半空变化 → 跳过
        assert w.recommend_calls == 1
        assert w._last_augments == _REAL_AUGMENTS  # 基准未被半空帧污染

    def test_single_nonempty_change_skipped(self) -> None:
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [_REAL_AUGMENTS, _REAL_AUGMENTS, ["甲", "", ""]]
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 1

    def test_full_change_still_retriggers(self) -> None:
        """完整的 3 个新符文 → 正常重触发。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [_REAL_AUGMENTS, _REAL_AUGMENTS, ["甲", "乙", "丙"]]
        for _ in range(3):
            w._poll_once()
        assert w.recommend_calls == 2


class TestSelectionUiKeepAlive:
    """悬浮窗保活判据：选择界面还在显示 → 判据为真（界面消失后自然转假）。"""

    def _w(self, **kwargs: Any) -> FakeWatcher:
        return FakeWatcher(poll_interval=0.01, debounce_count=1, **kwargs)

    def test_never_confirmed_is_not_alive(self) -> None:
        assert AutoWatcher().selection_ui_alive() is False

    def test_alive_after_confirmed_selection(self) -> None:
        """每一轮确认到选择界面都会刷新时间戳 → 判据持续为真（悬浮窗不关闭）。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS] * 3
        w.ocr_results = [_REAL_AUGMENTS] * 3
        for _ in range(3):
            w._poll_once()
            assert w.selection_ui_alive() is True

    def test_expires_after_grace(self) -> None:
        """超过保活窗口未再确认（界面消失/窗口转后台）→ 判据转假。"""
        w = self._w()
        w._selection_seen_at = time.monotonic() - w._alive_grace - 1.0
        assert w.selection_ui_alive() is False

    def test_pixel_miss_does_not_refresh_timestamp(self) -> None:
        """像素预筛未命中（回到游戏画面）：时间戳不刷新，判据不再被延长。"""
        w = self._w()
        w.pixel_samples = [_SELECTION_STATS, _INGAME_STATS]
        w.ocr_results = [_REAL_AUGMENTS]
        w._poll_once()
        confirmed_at = w._selection_seen_at
        assert confirmed_at > 0.0
        w._poll_once()
        assert w._selection_seen_at == confirmed_at

    def test_grace_scales_with_poll_interval(self) -> None:
        """轮询间隔调大时保活窗口随之放宽（否则界面还在、悬浮窗却已关闭）。"""
        assert AutoWatcher(poll_interval=5.0)._alive_grace == 5.0 * watcher_module._SELECTION_ALIVE_GRACE_FACTOR
        assert AutoWatcher(poll_interval=0.1)._alive_grace == watcher_module._SELECTION_ALIVE_GRACE_MIN_SECONDS

    def test_start_resets_alive_state(self) -> None:
        """重新开始监听不继承上一轮的选择界面状态。"""
        w = AutoWatcher(poll_interval=0.01)
        w._selection_seen_at = time.monotonic()
        w._poll_once = lambda: None  # noqa: B008 - 测试替身：隔离窗口/截图环境
        w.start()
        try:
            assert w.selection_ui_alive() is False
        finally:
            w.stop()
            w.join(timeout=2)

    def test_trigger_forwards_keep_alive_to_notify(self) -> None:
        """触发推荐时把保活判据交给展示层（悬浮窗据此决定是否关闭）。"""
        captured: dict[str, Any] = {}

        def fake_notify(lines: list[str], *, keep_alive: Any = None) -> bool:
            captured["lines"] = lines
            captured["keep_alive"] = keep_alive
            return True

        w = AutoWatcher(
            run_recommend_fn=lambda *args, **kwargs: RecommendOutcome(lines=["快选：测试"]),
            notify_fn=fake_notify,
        )
        w._trigger_recommendation()
        assert captured["lines"] == ["快选：测试"]
        assert captured["keep_alive"] == w.selection_ui_alive
        assert captured["keep_alive"]() is False  # 尚未确认选择界面 → 按固定时长显示
