"""进程 DPI 感知统一管理（Windows）。

进程的 DPI 感知级别决定系统如何虚拟化屏幕坐标与缩放窗口：

- unaware：系统把高 DPI 屏虚拟化成低分辨率，整窗位图拉伸（文字模糊）；
- system aware：按主屏 DPI 缩放，跨屏错乱；
- per-monitor V2：进程按每台显示器的真实 DPI 渲染，文字清晰。

第三方库（如 screeninfo 的 Windows 枚举器）会在运行中途调用
``SetProcessDpiAwareness(2)`` 抢改进程感知级别，导致已显示的窗口突然
"缩回"物理像素尺寸。因此感知级别必须由本应用在创建任何窗口之前主动
声明——先到先得，之后第三方库的同类调用只会失败（已设置），不再有副作用。
"""

import ctypes
import sys

_ensured = False


def ensure_per_monitor_dpi_awareness() -> None:
    """把进程 DPI 感知提升为 Per-Monitor V2（幂等；非 Windows 为 no-op）。

    必须在创建 Tk 窗口之前调用；重复调用无副作用。
    """
    global _ensured
    if _ensured or sys.platform != "win32":
        return
    _ensured = True
    user32 = ctypes.windll.user32
    # 首选 DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2（-4，Win10 1703+）：
    # 非客户区（标题栏等）也按每屏 DPI 缩放。
    try:
        if hasattr(user32, "SetProcessDpiAwarenessContext") and user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        ):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Win 8.1+，Per-Monitor
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()  # Vista+ 兜底（system aware）
    except Exception:
        pass
