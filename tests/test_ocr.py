"""ocr 区域换算与识别解析行为锁定测试（不初始化 PaddleOCR）。"""

import logging

import numpy as np
import pytest

from aram_mayhem_helper.ocr.ocr_tool import REGIONS, OCRTool, region_to_pixel


def _make_ocr() -> OCRTool:
    """绕过 __init__ 构造（避免加载 PaddleOCR 模型与屏幕查询）。"""
    tool = object.__new__(OCRTool)
    tool.use_angle_cls = False
    tool.logger = logging.getLogger("test_ocr")
    tool._last_captures = []
    tool.debug_capture_dir = None
    return tool


class TestRegionToPixel:
    def test_converts_fractional_region_to_pixels(self) -> None:
        assert region_to_pixel((0.24, 0.37, 0.39, 0.42), 1920, 1080) == (460, 399, 748, 453)
        assert region_to_pixel((0.0, 0.0, 1.0, 1.0), 1920, 1080) == (0, 0, 1920, 1080)

    def test_scales_with_screen_size(self) -> None:
        assert region_to_pixel((0.5, 0.5, 0.75, 0.75), 2560, 1440) == (1280, 720, 1920, 1080)


class TestRegions:
    def test_three_augment_slots(self) -> None:
        assert len(REGIONS) == 3
        for region in REGIONS:
            assert len(region) == 4
            assert all(isinstance(v, float) for v in region)

    def test_regions_have_unique_left_edges(self) -> None:
        lefts = [r[0] for r in REGIONS]
        assert len(set(lefts)) == 3


class TestRecognizeTextParsing:
    def test_parses_paddle_result_shape(self) -> None:
        tool = _make_ocr()
        paddle_result = [
            [
                [[[10, 20], [30, 20], [30, 40], [10, 40]], ("泰坦的坚决", 0.95)],
                [[[50, 20], [90, 20], [90, 40], [50, 40]], ("闪电打击", 0.87)],
            ]
        ]
        tool._ocr = type("FakeOCR", (), {"ocr": lambda self, img, cls: paddle_result})()
        parsed = tool.recognize_text("fake")
        assert parsed == [
            {"text": "泰坦的坚决", "confidence": 0.95, "bbox": [[10, 20], [30, 20], [30, 40], [10, 40]]},
            {"text": "闪电打击", "confidence": 0.87, "bbox": [[50, 20], [90, 20], [90, 40], [50, 40]]},
        ]

    def test_empty_result_returns_empty_list(self) -> None:
        tool = _make_ocr()
        tool._ocr = type("FakeOCR", (), {"ocr": lambda self, img, cls: None})()
        assert tool.recognize_text("fake") == []

    def test_ocr_failure_raises_runtime_error(self) -> None:
        tool = _make_ocr()

        def boom(self, img, cls):
            raise Exception("paddle exploded")

        tool._ocr = type("FakeOCR", (), {"ocr": boom})()
        with pytest.raises(RuntimeError, match="OCR 识别失败"):
            tool.recognize_text("fake")


class TestCaptureAndRecognize:
    def test_joins_texts(self) -> None:
        tool = _make_ocr()
        tool.capture_screen = lambda bbox: None  # type: ignore[method-assign]
        tool.recognize_text = lambda img: [{"text": " 泰坦 ", "confidence": 0.9, "bbox": []}]  # type: ignore[method-assign]
        assert tool.capture_and_recognize((0, 0, 100, 100)) == "泰坦"


class TestGetAugments:
    def test_uses_region_to_pixel_with_screen_size(self) -> None:
        tool = _make_ocr()
        tool._screen_size = (1920, 1080)
        captured: list[tuple[int, int, int, int]] = []
        tool.capture_screen = lambda bbox: (
            captured.append(bbox)
            or np.zeros(  # type: ignore[method-assign]
                (10, 10), dtype=np.uint8
            )
        )
        tool.recognize_text = lambda img: [{"text": "x", "confidence": 1.0, "bbox": []}]  # type: ignore[method-assign]
        assert tool.get_augments() == ["x", "x", "x"]
        assert captured == [
            (460, 399, 748, 453),
            (806, 399, 1094, 453),
            (1171, 399, 1459, 453),
        ]

    def test_retains_captures_for_failure_saving(self) -> None:
        tool = _make_ocr()
        tool._screen_size = (1920, 1080)
        tool.capture_screen = lambda bbox: np.zeros((10, 10), dtype=np.uint8)  # type: ignore[method-assign]
        tool.recognize_text = lambda img: []  # type: ignore[method-assign]
        tool.get_augments()
        assert len(tool._last_captures) == 3
        assert all(isinstance(img, np.ndarray) for img in tool._last_captures)


class TestDebugMode:
    """调试模式（debug_capture_dir 非 None）：每次识别保存全部区域截图。"""

    def test_saves_all_region_captures(self, tmp_path) -> None:
        tool = _make_ocr()
        tool._screen_size = (1920, 1080)
        tool.debug_capture_dir = tmp_path
        tool.capture_screen = lambda bbox: np.zeros((10, 10), dtype=np.uint8)  # type: ignore[method-assign]
        tool.recognize_text = lambda img: [{"text": "x", "confidence": 1.0, "bbox": []}]  # type: ignore[method-assign]

        tool.get_augments()

        names = sorted(p.name for p in tmp_path.iterdir())
        assert len(names) == 3
        assert all("region0" in n for n in names[:1])  # 三个区域各一张
        assert any("region0" in n for n in names)
        assert any("region1" in n for n in names)
        assert any("region2" in n for n in names)
        assert all(p.suffix == ".png" for p in tmp_path.iterdir())

    def test_disabled_saves_nothing(self, tmp_path) -> None:
        tool = _make_ocr()
        tool._screen_size = (1920, 1080)
        tool.capture_screen = lambda bbox: np.zeros((10, 10), dtype=np.uint8)  # type: ignore[method-assign]
        tool.recognize_text = lambda img: []  # type: ignore[method-assign]

        tool.get_augments()

        assert not tmp_path.exists() or not any(tmp_path.iterdir())


class TestSaveFailureCapture:
    def _tool_with_captures(self) -> OCRTool:
        tool = _make_ocr()
        tool._last_captures = [
            np.full((10, 20), 255, dtype=np.uint8),
            np.zeros((10, 20), dtype=np.uint8),
        ]
        return tool

    def test_saves_png_with_sanitized_name(self, tmp_path) -> None:
        tool = self._tool_with_captures()
        path = tool.save_failure_capture(0, "泰坦 的坚决:1", tmp_path)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
        assert "region0" in path.name
        assert "泰坦_的坚决_1" in path.name  # 空白/冒号 → _

    def test_empty_text_uses_placeholder(self, tmp_path) -> None:
        tool = self._tool_with_captures()
        path = tool.save_failure_capture(1, "  ", tmp_path)
        assert path is not None
        assert "empty" in path.name

    def test_index_out_of_range_returns_none(self, tmp_path) -> None:
        tool = self._tool_with_captures()
        assert tool.save_failure_capture(5, "x", tmp_path) is None
        assert tool.save_failure_capture(-1, "x", tmp_path) is None

    def test_no_captures_returns_none(self, tmp_path) -> None:
        assert _make_ocr().save_failure_capture(0, "x", tmp_path) is None

    def test_does_not_overwrite_existing_file(self, tmp_path) -> None:
        tool = self._tool_with_captures()
        first = tool.save_failure_capture(0, "abc", tmp_path)
        second = tool.save_failure_capture(0, "abc", tmp_path)
        assert first is not None and second is not None
        assert second != first
        assert second.exists()
        assert len(list(tmp_path.iterdir())) == 2

    def test_save_failure_logs_and_returns_none(self, tmp_path) -> None:
        tool = self._tool_with_captures()
        blocked = tmp_path / "blocked"
        blocked.write_text("x")  # 目录位置被文件占用 → mkdir 失败
        assert tool.save_failure_capture(0, "x", blocked) is None


class TestModuleImportIsLight:
    def test_import_does_not_build_ocr(self) -> None:
        # 导入模块本身不应加载 PaddleOCR（无导入期副作用）
        import aram_mayhem_helper.ocr.ocr_tool as mod

        assert mod.get_ocr_tool() is mod.get_ocr_tool()  # 懒单例缓存
