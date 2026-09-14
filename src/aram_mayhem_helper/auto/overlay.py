"""推荐结果悬浮提示窗。

置顶无边框 Tkinter 窗口，显示推荐结果数秒后自动关闭。与 GUI 主窗共用
``exclude_window_from_capture`` 截图排除机制：悬浮窗对用户可见，但不会被
OCR 截图拍到（不干扰后续识别）。

设计要点：
- 必须运行在 Tkinter 主线程（Tk 不允许跨线程创建控件）——GUI 模式经
  ``root.after`` 把构建调度回主线程事件循环
- CLI 模式无 Tk 主循环：调用方不注入根窗口，降级为控制台打印
- 无边框 + 置顶 + 半透明，靠近屏幕右上角，不抢焦点
"""

import logging
import tkinter as tk
from tkinter import Misc

logger = logging.getLogger(__name__)

# 悬浮窗显示时长（毫秒）
_DISPLAY_MS = 8000
# 距屏幕右/上边缘的边距（像素）
_MARGIN = 40


def show_recommendation_overlay(lines: list[str], root: Misc | None = None, *, display_ms: int = _DISPLAY_MS) -> bool:
    """显示推荐结果悬浮窗，*display_ms* 毫秒后自动关闭。返回是否成功显示。

    Args:
        lines: 建议行（每行一条）
        root: Tk 根窗口。None 时表示非 GUI 环境，返回 False（调用方降级为
            控制台打印）。GUI 模式必须传入主窗实例。
        display_ms: 显示时长（毫秒）

    注意：本函数应在 Tk 主线程调用；watcher 线程经 ``root.after(0, ...)``
    调度（见 ``watcher.notify_result``）。
    """
    if not lines:
        return False
    if root is None:
        logger.debug("无 Tk 根窗口（CLI 模式），跳过悬浮窗")
        return False

    try:
        _build_overlay(root, lines, display_ms)
        return True
    except Exception:
        logger.exception("悬浮窗显示失败")
        return False


def _build_overlay(root: Misc, lines: list[str], display_ms: int) -> None:
    """构建并布局悬浮窗（主线程执行）。"""
    import ctypes

    overlay = tk.Toplevel(root)
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

    overlay.after(display_ms, overlay.destroy)
