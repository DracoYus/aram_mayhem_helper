"""自动监听器：轮询游戏窗口像素特征，检测到符文选择界面时自动触发推荐。

检测原理见 ``detection.py`` 模块注释。本模块负责 I/O 部分：
- 游戏窗口定位（EnumWindows 按标题精确匹配，客户区坐标下按百分比截区域——
  比按主屏尺寸截更稳，副屏/窗口化都能对准）
- 两级检测：像素判据 < 5ms 廉价预筛 → OCR 文本查表内容确认
- 状态机推进 + 触发 ``run_recommend`` + 结果展示（悬浮窗/控制台）
"""

import ctypes
import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from ctypes import wintypes

from aram_mayhem_helper.algorithm.recommend_flow import RecommendOutcome, run_recommend
from aram_mayhem_helper.auto.detection import (
    DetectionThresholds,
    SelectionDetector,
    looks_like_selection_ui_stats,
)
from aram_mayhem_helper.ocr.ocr_tool import REGIONS
from aram_mayhem_helper.utils.config import get_config

logger = logging.getLogger(__name__)

# League 游戏进程窗口标题（EnumWindows 实测；RCLIENT 客户端窗口标题为
# "League of Legends"（无此后缀），不会误匹配）
_GAME_WINDOW_TITLE = "League of Legends (TM) Client"
# 默认轮询间隔（秒）：1s 平衡及时性与开销（选择阶段每轮含一次 OCR ~0.3s）
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
# 推荐结果展示的标题（悬浮窗/控制台共用）
_RESULT_TITLE = "符文推荐"
# 悬浮窗队列轮询间隔（毫秒）
_OVERLAY_POLL_MS = 200

user32 = ctypes.WinDLL("user32", use_last_error=True)

# EnumWindows 回调签名
_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_game_window() -> int | None:
    """查找 League 游戏窗口句柄（按标题精确匹配顶层可见窗口），未找到返回 None。"""
    result: list[int] = []

    def _on_window(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length == len(_GAME_WINDOW_TITLE):
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == _GAME_WINDOW_TITLE and user32.IsWindowVisible(hwnd):
                result.append(hwnd)
                return False  # 找到即停止枚举
        return True

    user32.EnumWindows(_ENUM_PROC(_on_window), 0)
    return result[0] if result else None


def is_window_foreground(hwnd: int) -> bool:
    """判断 *hwnd* 是否为当前前台窗口（被遮挡/最小化时截图不可信，采样方应跳过）。"""
    return bool(user32.GetForegroundWindow() == hwnd)


def capture_region_stats(hwnd: int) -> list[tuple[float, float]] | None:
    """按游戏窗口客户区百分比坐标截取 REGIONS 区域，返回各区域灰度 (mean, std)。

    窗口不可用（句柄失效/客户区为空）时返回 None。
    """
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    # 客户区左上角的屏幕坐标（窗口可能带边框/标题栏偏移）
    point = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    origin_x, origin_y = point.x, point.y

    from PIL import ImageGrab

    stats: list[tuple[float, float]] = []
    for region in REGIONS:
        left = origin_x + int(region[0] * width)
        top = origin_y + int(region[1] * height)
        right = origin_x + int(region[2] * width)
        bottom = origin_y + int(region[3] * height)
        image = ImageGrab.grab((left, top, right, bottom)).convert("L")
        stats.append(_gray_stats(image))
    return stats


def _gray_stats(image: object) -> tuple[float, float]:
    """PIL 灰度图 → (mean, std)（经 numpy 转换，项目已依赖 numpy）。"""
    import numpy as np

    arr = np.asarray(image)
    return float(arr.mean()), float(arr.std())


def notify_result(lines: list[str]) -> bool:
    """展示推荐结果：GUI 运行中把悬浮窗请求放入队列（主线程轮询消费），
    否则打印控制台。返回是否成功受理。

    watcher 线程不能调用 Tk API（``root.after`` 也非线程安全，实测抛
    ``RuntimeError: main thread is not in main loop``）。GUI 模式沿用
    ``TkinterLogHandler`` 的队列桥接模式：watcher 线程只 put，GUI 主线程
    的轮询循环 drain 并构建悬浮窗。
    """
    if not lines:
        return False

    if _tk_root_ref is not None:
        _overlay_queue.put(lines)
        return True

    # CLI 模式：无 Tk 主循环，直接打印
    print(f"=== {_RESULT_TITLE} ===")
    for line in lines:
        print(line)
    return True


# GUI 主窗引用（gui.py 创建窗口后注入；None 表示 CLI 模式）
_tk_root_ref: tk.Misc | None = None
# 悬浮窗请求队列：watcher 线程 → Tk 主线程（与 GUI 日志桥接同模式）
_overlay_queue: queue.Queue[list[str]] = queue.Queue()


def set_tk_root(root: tk.Misc | None) -> None:
    """注入/清除 Tk 根窗口引用（GUI 启动时调用；线程安全性由调用方保证）。"""
    global _tk_root_ref
    _tk_root_ref = root


def poll_overlay_queue() -> None:
    """主线程轮询悬浮窗请求队列（GUI 经 ``root.after`` 周期调用）。

    有请求则构建悬浮窗；无请求时仅重新调度自身。GUI 关闭后轮询自然停止
    （不再有 after 调度）。
    """
    from aram_mayhem_helper.auto.overlay import show_recommendation_overlay

    try:
        while True:
            lines = _overlay_queue.get_nowait()
            show_recommendation_overlay(lines, root=_tk_root_ref)
    except queue.Empty:
        pass
    if _tk_root_ref is not None:
        _tk_root_ref.after(_OVERLAY_POLL_MS, poll_overlay_queue)


# 游戏内「三选一碎片」界面的 OCR 文本全部以「碎片」结尾（如 力量碎片/迅捷碎片），
# 真实符文名（221 个）中无此前缀——以此区分碎片界面与符文选择界面
_SHARD_SUFFIX = "碎片"


def _is_shard_ui(augments: list[str]) -> bool:
    """OCR 结果是否为游戏内「三选一碎片」界面（全部以「碎片」结尾）。"""
    return bool(augments) and all(text.endswith(_SHARD_SUFFIX) for text in augments if text)


class AutoWatcher:
    """自动监听器：像素预筛 → OCR 内容确认 → 触发推荐 → 展示结果。

    Args:
        run_recommend_fn: 推荐流程函数（默认 ``run_recommend``，测试注入替身）
        notify_fn: 结果展示函数 ``(lines) -> bool``（默认 ``notify_result``，
            GUI 模式显示悬浮窗、CLI 打印控制台；测试注入替身）
        poll_interval: 轮询间隔秒数
        thresholds: 像素判别阈值（None 取默认）
        debounce_count: 状态机去抖次数
    """

    def __init__(
        self,
        run_recommend_fn: Callable[..., RecommendOutcome] = run_recommend,
        notify_fn: Callable[..., bool] | None = None,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        thresholds: DetectionThresholds | None = None,
        debounce_count: int = 2,
    ) -> None:
        self._run_recommend_fn = run_recommend_fn
        self._notify_fn = notify_fn or notify_result
        self._poll_interval = poll_interval
        self._thresholds = thresholds or DetectionThresholds()
        self._detector = SelectionDetector(debounce_count=debounce_count)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_augments: list[str] | None = None  # 上次 OCR 识别文本（reroll 比对基准）

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set() and self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """请求停止轮询（线程安全；轮询线程在下一间隔退出）。"""
        self._stop_event.set()

    def start(self) -> None:
        """启动监听线程（daemon；重复启动无操作）。"""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("自动监听已在运行中")
            return
        self._stop_event.clear()
        self._detector.reset()
        self._last_augments = None
        self._thread = threading.Thread(target=self._watch_loop, name="auto-watcher", daemon=True)
        self._thread.start()
        logger.info("自动监听已启动（每 %.0f 秒检测一次符文选择界面）", self._poll_interval)

    def join(self, timeout: float | None = None) -> None:
        """等待监听线程退出（测试用）。"""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _watch_loop(self) -> None:
        """轮询主循环：窗口定位 → 像素预筛 → OCR 确认 → 触发。"""
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                logger.exception("自动监听单次轮询异常，继续下一轮")
            self._stop_event.wait(self._poll_interval)

    def _poll_once(self) -> None:
        """单次轮询：像素预筛 → OCR 内容确认 → 触发 / reroll 检测。

        两级检测：像素判据 < 5ms 廉价预筛（记分板/死亡回放等暗色 UI 也会命中）；
        预筛命中才跑 OCR，内容查表确认（至少一个匹配已知符文名）才算选择界面。
        """
        hwnd = find_game_window()
        if hwnd is None:
            # 游戏未运行：静默跳过（状态机保持原状，进对局后自然恢复）
            return
        if not is_window_foreground(hwnd):
            # 游戏被遮挡/最小化：截图不可信，跳过本次采样
            logger.debug("游戏窗口不在前台，跳过本次采样")
            return

        stats = capture_region_stats(hwnd)
        if stats is None:
            return
        if not looks_like_selection_ui_stats(stats, self._thresholds):
            # 像素预筛未命中（游戏画面）：重武装并清除 reroll 基准
            self._detector.feed(False)
            self._last_augments = None
            return

        # 像素预筛命中：OCR 确认内容
        from aram_mayhem_helper.ocr.ocr_tool import get_ocr_tool

        augments = get_ocr_tool().get_augments()
        if not any(augments):
            # 动画帧/过渡画面：OCR 空，按非选择界面处理（不触发不更新基准）
            logger.debug("OCR 结果为空（过渡帧），跳过")
            return
        if _is_shard_ui(augments):
            logger.debug("碎片界面（正常游戏流程），跳过")
            return
        if not self._has_known_augment(augments):
            # 记分板 KDA / 其他暗色 UI：OCR 文本查表全部失败 → 非符文选择界面
            logger.debug("OCR 文本均非已知符文（%s），判定为其他 UI，跳过", augments)
            return

        result = self._detector.feed(True)
        if result.should_trigger:
            self._trigger_recommendation(augments)
        elif self._last_augments is not None and set(augments) != set(self._last_augments):
            # 选择界面持续中且内容变化 → reroll 重触发（基准在触发时更新）
            logger.info("检测到符文变更（reroll）: %s -> %s", self._last_augments, augments)
            self._trigger_recommendation(augments)

    def _has_known_augment(self, augments: list[str]) -> bool:
        """OCR 文本中是否至少一个能匹配已知符文名（内容级确认）。"""
        from aram_mayhem_helper.utils.data import get_game_data

        game_data = get_game_data()
        return any(game_data.augment_id(text) is not None for text in augments if text)

    def _trigger_recommendation(self, augments: list[str] | None = None) -> None:
        """触发推荐并展示结果（悬浮窗/控制台）。

        Args:
            augments: 预筛阶段已完成的 OCR 结果（复用，避免重复截图识别）；
                None 时基准取 run_recommend 返回的识别文本。
        """
        logger.info("检测到符文选择界面，自动执行推荐...")
        from aram_mayhem_helper.ocr.ocr_tool import get_ocr_tool
        from aram_mayhem_helper.utils.data import get_game_data

        outcome = self._run_recommend_fn(
            get_game_data(), get_ocr_tool(), preferred_source=get_config().data_source.source
        )
        # reroll 比对基准：优先用预筛 OCR 结果（与触发判定一致），否则取推荐流程的识别文本
        self._last_augments = augments if augments is not None else outcome.augments
        if outcome.lines:
            send_ok = self._notify_fn(outcome.lines)
            logger.info("推荐结果展示%s", "成功" if send_ok else "失败")
        else:
            logger.warning("自动推荐未产生建议（OCR 未匹配或数据缺失）")
