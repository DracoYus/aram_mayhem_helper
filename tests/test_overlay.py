"""auto.overlay 悬浮窗行为测试（真实 Tk 环境验证构建/自动关闭/保活/截图排除）。"""

import tkinter as tk
from collections.abc import Iterator

import pytest

import aram_mayhem_helper.auto.overlay as overlay_module
from aram_mayhem_helper.auto.overlay import show_recommendation_overlay


@pytest.fixture
def tk_root() -> Iterator[tk.Tk]:
    """真实 Tk 根窗口（withdraw 隐藏，测试后销毁）。"""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无显示环境，跳过 Tk 悬浮窗测试")
    root.withdraw()
    # 清除上一测试遗留的窗口引用（其根窗口已销毁，控件只对旧解释器有效）
    overlay_module._current_overlay = None
    yield root
    root.destroy()


def _overlays(root: tk.Tk) -> list[tk.Misc]:
    """当前存活的悬浮窗（主窗的 Toplevel 子窗口）。"""
    return [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]


def _label_texts(widget: tk.Misc) -> list[str]:
    """递归收集控件树中的 Label 文本（用于断言悬浮窗内容）。"""
    texts = [widget.cget("text")] if isinstance(widget, tk.Label) else []
    for child in widget.winfo_children():
        texts.extend(_label_texts(child))
    return texts


def _pump(root: tk.Tk, ms: int) -> None:
    """推进 Tk 事件循环 *ms* 毫秒，让 after 定时器（自动关闭/保活复查）真实触发。"""
    root.after(ms, root.quit)
    root.mainloop()


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
        assert len(_overlays(tk_root)) == 1

    def test_overlay_auto_closes(self, tk_root: tk.Tk) -> None:
        """无保活判据时在 display_ms 后自动销毁（after 定时器正常触发）。"""
        assert show_recommendation_overlay(["快选：测试"], root=tk_root, display_ms=50) is True
        _pump(tk_root, 200)
        assert _overlays(tk_root) == []

    def test_exclude_from_capture_called(self, tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
        """悬浮窗构建时调用截图排除（复用 GUI 主窗机制）。"""
        calls: list[int] = []
        # _build_overlay 内 `from ...window_capture import exclude_window_from_capture`
        # 是函数内导入，patch 源模块属性即可生效（每次导入取自源模块命名空间）
        import aram_mayhem_helper.utils.window_capture as wc

        monkeypatch.setattr(wc, "exclude_window_from_capture", lambda hwnd: calls.append(hwnd) or True)
        assert show_recommendation_overlay(["快选：测试"], root=tk_root) is True
        assert len(calls) == 1


class TestOverlayKeepAlive:
    """保活判据：符文选择界面还在显示时，悬浮窗不按最短显示时长关闭。"""

    def test_stays_open_while_alive_then_closes(self, tk_root: tk.Tk) -> None:
        """判据为真时跨过最短时长与多个复查周期不关闭；转假后的首次复查关闭。"""
        state = {"alive": True}
        shown = show_recommendation_overlay(
            ["快选：测试"],
            root=tk_root,
            display_ms=50,
            keep_alive=lambda: state["alive"],
        )
        assert shown is True

        _pump(tk_root, 400)  # 已过 display_ms，且至少执行一次保活复查
        assert len(_overlays(tk_root)) == 1

        state["alive"] = False
        _pump(tk_root, 400)
        assert _overlays(tk_root) == []

    def test_keep_alive_exception_closes_overlay(self, tk_root: tk.Tk) -> None:
        """判据抛异常时按「界面已消失」处理，不留残窗。"""

        def boom() -> bool:
            raise RuntimeError("判据异常")

        assert show_recommendation_overlay(["快选：测试"], root=tk_root, display_ms=20, keep_alive=boom) is True
        _pump(tk_root, 200)
        assert _overlays(tk_root) == []

    def test_new_overlay_replaces_previous(self, tk_root: tk.Tk) -> None:
        """reroll 再次触发时替换旧窗（同屏两窗会并排露出旧推荐行）。"""
        assert show_recommendation_overlay(["快选：旧符文"], root=tk_root, display_ms=60_000, keep_alive=lambda: True)
        assert show_recommendation_overlay(["快选：新符文"], root=tk_root, display_ms=60_000, keep_alive=lambda: True)

        overlays = _overlays(tk_root)
        assert len(overlays) == 1
        texts = _label_texts(overlays[0])
        assert "快选：新符文" in texts
        assert "快选：旧符文" not in texts

    def test_close_check_tolerates_dead_widget(self, tk_root: tk.Tk) -> None:
        """复查回调面对已销毁控件时静默返回，且不残留引用（winfo_exists 守卫）。"""
        assert show_recommendation_overlay(["快选：测试"], root=tk_root, display_ms=60_000, keep_alive=lambda: True)
        overlay = _overlays(tk_root)[0]
        overlay.destroy()

        overlay_module._close_or_keep_alive(overlay, lambda: True)  # 不应抛 TclError

        assert overlay_module._current_overlay is None
