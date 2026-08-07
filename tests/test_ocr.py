"""ocr 区域换算与识别解析行为锁定测试（不初始化 PaddleOCR）。"""

import logging

import pytest

from aram_mayhem_helper.ocr.ocr_tool import REGIONS, OCRTool, region_to_pixel


def _make_ocr() -> OCRTool:
    """绕过 __init__ 构造（避免加载 PaddleOCR 模型与屏幕查询）。"""
    tool = object.__new__(OCRTool)
    tool.use_angle_cls = False
    tool.logger = logging.getLogger("test_ocr")
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
        tool.capture_and_recognize = lambda bbox: captured.append(bbox) or "x"  # type: ignore[method-assign]
        assert tool.get_augments() == ["x", "x", "x"]
        assert captured == [
            (460, 399, 748, 453),
            (806, 399, 1094, 453),
            (1171, 399, 1459, 453),
        ]


class TestModuleImportIsLight:
    def test_import_does_not_build_ocr(self) -> None:
        # 导入模块本身不应加载 PaddleOCR（无导入期副作用）
        import aram_mayhem_helper.ocr.ocr_tool as mod

        assert mod.get_ocr_tool() is mod.get_ocr_tool()  # 懒单例缓存
