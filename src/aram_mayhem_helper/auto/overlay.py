"""推荐结果悬浮提示窗。

置顶无边框 Tkinter 窗口，显示推荐结果数秒后自动关闭。与 GUI 主窗共用
``exclude_window_from_capture`` 截图排除机制：悬浮窗对用户可见，但不会被
OCR 截图拍到（不干扰后续识别）。

设计要点：
- 必须运行在 Tkinter 主线程（Tk 不允许跨线程创建控件）——GUI 模式经
  ``root.after`` 把构建调度回主线程事件循环
- CLI 模式无 Tk 主循环：调用方不注入根窗口，降级为控制台打印
- 无边框 + 置顶 + 半透明，靠近屏幕右上角，不抢焦点
- 显示时长是**下限**：传入 ``keep_alive`` 判据后，只要符文选择界面还在
  显示就持续保留（判据为假的首次复查才关闭），避免用户还在挑符文时
  悬浮窗已经消失
- 同一时刻只保留一个悬浮窗：新内容到达时先关掉旧窗（reroll 会在保活期间
  触发新推荐，两窗重叠会露出旧推荐行）
"""

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import Misc

logger = logging.getLogger(__name__)

# 悬浮窗最短显示时长（毫秒）
_DISPLAY_MS = 8000
# 距屏幕右/上边缘的边距（像素）
_MARGIN = 40
# 保活复查间隔（毫秒）：到最短显示时长后按此周期询问判据是否仍在显示界面
_ALIVE_POLL_MS = 250

# 当前显示的悬浮窗（Tk 主线程独占，无需加锁；None 表示当前无窗）
_current_overlay: tk.Toplevel | None = None


def show_recommendation_overlay(
    lines: list[str],
    root: Misc | None = None,
    *,
    display_ms: int = _DISPLAY_MS,
    keep_alive: Callable[[], bool] | None = None,
) -> bool:
    """显示推荐结果悬浮窗，*display_ms* 毫秒后自动关闭。返回是否成功显示。

    Args:
        lines: 建议行（每行一条）
        root: Tk 根窗口。None 时表示非 GUI 环境，返回 False（调用方降级为
            控制台打印）。GUI 模式必须传入主窗实例。
        display_ms: 最短显示时长（毫秒）
        keep_alive: 保活判据（符文选择界面是否仍在显示）。提供时
            *display_ms* 只作为下限：到点后每 ``_ALIVE_POLL_MS`` 复查一次，
            为真则继续显示，为假的首次复查即关闭。None 时到点即关闭。
            判据在 Tk 主线程调用，实现需线程安全（watcher 的判据只读一个
            由监听线程写入的 float）。

    注意：本函数应在 Tk 主线程调用；watcher 线程经 ``root.after(0, ...)``
    调度（见 ``watcher.notify_result``）。
    """
    if not lines:
        return False
    if root is None:
        logger.debug("无 Tk 根窗口（CLI 模式），跳过悬浮窗")
        return False

    try:
        _build_overlay(root, lines, display_ms, keep_alive)
        return True
    except Exception:
        logger.exception("悬浮窗显示失败")
        return False


def _build_overlay(
    root: Misc,
    lines: list[str],
    display_ms: int,
    keep_alive: Callable[[], bool] | None,
) -> None:
    """构建并布局悬浮窗（主线程执行）。"""
    global _current_overlay

    import ctypes

    _close_current_overlay()  # 换内容前先关旧窗：置顶窗重叠会露出旧推荐行
    overlay = tk.Toplevel(root)
    _current_overlay = overlay
    overlay.overrideredirect(True)  # 无边框
    overlay.attributes("-topmost", True)
    overlay.attributes("-alpha", 0.92)

    # 内容：标题 + 建议行（按等级前缀着色：快选=绿，考虑=橙，其余=灰）
    title = tk.Label(
        overlay,
        text="符文推荐",
        font=("微软雅黑", 14, "bold"),
        bg="#1e2430",
        fg="#7dd3fc",
        padx=16,
        pady=6,
    )
    title.pack(fill=tk.X)

    body = tk.Frame(overlay, bg="#14181f")
    body.pack(fill=tk.X)
    for line in lines:
        color = "#4ade80" if line.startswith("快选") else "#fbbf24" if line.startswith("考虑") else "#94a3b8"
        tk.Label(
            body,
            text=line,
            font=("微软雅黑", 12),
            bg="#14181f",
            fg=color,
            anchor="w",
            padx=16,
            pady=3,
        ).pack(fill=tk.X)

    # 布局完成后定位到主屏右上角（需先 update_idletasks 拿到真实尺寸）
    overlay.update_idletasks()
    width = overlay.winfo_reqwidth()
    screen_w = overlay.winfo_screenwidth()
    overlay.geometry(f"+{screen_w - width - _MARGIN}+{_MARGIN}")

    # 从屏幕截图中排除（复用 GUI 主窗的机制；GetParent 取顶层包装窗口）
    from aram_mayhem_helper.utils.window_capture import exclude_window_from_capture

    exclude_window_from_capture(ctypes.windll.user32.GetParent(overlay.winfo_id()))

    overlay.after(display_ms, _close_or_keep_alive, overlay, keep_alive)


def _close_or_keep_alive(overlay: tk.Toplevel, keep_alive: Callable[[], bool] | None) -> None:
    """到达最短显示时长后的关闭判定：界面仍在则短周期复查，否则销毁。

    界面持续显示时本回调反复重排自身，因此悬浮窗可能长时间存活；复查回调
    注册在这个 Toplevel 上，但根窗口销毁（GUI 退出）或窗口被换内容关闭
    （见 ``_close_current_overlay``）后 Tcl 仍会触发已排队的回调，故先确认
    控件还在。
    """
    try:
        if not overlay.winfo_exists():
            _forget_overlay(overlay)  # 已被销毁，无窗口可关
            return
        if keep_alive is not None and _keep_alive_true(keep_alive):
            overlay.after(_ALIVE_POLL_MS, _close_or_keep_alive, overlay, keep_alive)
            return
        overlay.destroy()
        _forget_overlay(overlay)
    except tk.TclError:
        logger.debug("悬浮窗已随根窗口销毁，忽略本次关闭调度")
        _forget_overlay(overlay)


def _keep_alive_true(keep_alive: Callable[[], bool]) -> bool:
    """调用保活判据；判据异常按「界面已消失」处理（宁可关闭也不留残窗）。"""
    try:
        return bool(keep_alive())
    except Exception:
        logger.exception("悬浮窗保活判据异常，按界面已消失处理")
        return False


def _close_current_overlay() -> None:
    """关闭当前悬浮窗（若有），供新内容建窗前调用。

    只保留一个悬浮窗：reroll 会在保活期间再次触发推荐，而置顶窗按内容宽度
    右对齐，两窗宽度不同就会并排露出旧推荐行。
    """
    global _current_overlay

    overlay = _current_overlay
    _current_overlay = None
    if overlay is None:
        return
    try:
        if overlay.winfo_exists():
            overlay.destroy()
    except tk.TclError:
        logger.debug("旧悬浮窗已随根窗口销毁，忽略关闭")


def _forget_overlay(overlay: tk.Toplevel) -> None:
    """*overlay* 即当前悬浮窗时清除引用（不持有已销毁控件）。"""
    global _current_overlay
    if _current_overlay is overlay:
        _current_overlay = None
