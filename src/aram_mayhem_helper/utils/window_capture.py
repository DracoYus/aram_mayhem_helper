"""窗口截图排除（Windows）。

游戏以全屏/无边框模式占满主屏运行时，能闯进 OCR 截图的干扰窗口只有本
工具窗自己。``SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`` 让窗口
对用户照常显示，但所有屏幕截图 API（GDI BitBlt、DXGI、Windows.Graphics.
Capture）都拍不到它——截图里直接呈现它身后的游戏画面，OCR 不再受影响。

需 Windows 10 2004+；更早系统上调用失败，调用方应降级提示。
"""

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

# SetWindowDisplayAffinity 的 WDA_EXCLUDEFROMCAPTURE 标志（Win10 2004+）
_WDA_EXCLUDE_FROM_CAPTURE = 0x11
# 目标窗口不存在等错误
_ERROR_INVALID_WINDOW_HANDLE = 1400


def exclude_window_from_capture(hwnd: int) -> bool:
    """把 *hwnd* 对应的顶层窗口从所有屏幕截图中排除（窗口仍正常显示）。

    幂等；非 Windows 平台为 no-op。失败仅记录日志并返回 False（例如
    Win10 2004 之前的系统不支持该标志），不影响调用方主流程。

    :param hwnd: 顶层窗口句柄（Tk 需传 ``GetParent(root.winfo_id())`` 的结果，
        因为 ``winfo_id()`` 返回的是 Tk 内部子窗口，对其设置无效）
    :return: 设置是否成功
    """
    if sys.platform != "win32":
        return False
    # use_last_error=True：让 ctypes 捕获 GetLastError 到 thread-local，
    # 否则 get_last_error() 返回陈旧值
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDE_FROM_CAPTURE):
        logger.debug("窗口 %#x 已从屏幕截图中排除", hwnd)
        return True
    error = ctypes.get_last_error()
    if error == _ERROR_INVALID_WINDOW_HANDLE:
        logger.warning("截图排除设置失败：窗口句柄 %#x 无效", hwnd)
    else:
        logger.warning("截图排除设置失败（error=%s，需 Windows 10 2004+）", error)
    return False
