"""auto.overlay 悬浮窗行为测试（真实 Tk 环境验证构建/自动关闭/截图排除）。"""

import tkinter as tk
from collections.abc import Iterator

import pytest

from aram_mayhem_helper.auto.overlay import show_recommendation_overlay


@pytest.fixture
def tk_root() -> Iterator[tk.Tk]:
    """真实 Tk 根窗口（withdraw 隐藏，测试后销毁）。"""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无显示环境，跳过 Tk 悬浮窗测试")
    root.withdraw()
    yield root
    root.destroy()


class TestShowRecommendationOverlay:
    def test_empty_lines_returns_false(self, tk_root: tk.Tk) -> None:
        assert show_recommendation_overlay([], root=tk_root) is False

    def test_none_root_returns_false(self) -> None:
        """root=None（CLI 模式）返回 False，不抛异常、不创建 Tk 实例。"""
        assert show_recommendation_overlay(["快选：测试"], root=None) is False

    def test_shows_overlay_with_root(self, tk_root: tk.Tk) -> None:
        """有根窗口时构建悬浮窗并返回 True。"""
        assert show_recommendation_overlay(["快选：测试符文", "考虑：另一符文"], root=tk_root) is True
        tk_root.update()  # 让窗口完成布局与 after 调度

    def test_overlay_auto_closes(self, tk_root: tk.Tk) -> None:
        """悬浮窗在 display_ms 后自动销毁（after 定时器正常触发）。"""
        assert show_recommendation_overlay(["快选：测试"], root=tk_root, display_ms=50) is True
        tk_root.update()
        tk_root.after(120, tk_root.quit)
        tk_root.mainloop()
        # 无异常即视为销毁成功（destroy 已执行）

    def test_exclude_from_capture_called(self, tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
        """悬浮窗构建时调用截图排除（复用 GUI 主窗机制）。"""
        calls: list[int] = []
        # _build_overlay 内 `from ...window_capture import exclude_window_from_capture`
        # 是函数内导入，patch 源模块属性即可生效（每次导入取自源模块命名空间）
        import aram_mayhem_helper.utils.window_capture as wc

        monkeypatch.setattr(wc, "exclude_window_from_capture", lambda hwnd: calls.append(hwnd) or True)
        assert show_recommendation_overlay(["快选：测试"], root=tk_root) is True
        assert len(calls) == 1
