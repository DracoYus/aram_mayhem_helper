"""屏幕 OCR 识别工具。

PaddleOCR/PIL/screeninfo 均在方法内懒导入：模块导入本身不加载模型、
不查询屏幕（无导入期副作用），web 部署无需安装 ``[ocr]`` 依赖组。
"""

import logging
from typing import Any

import numpy as np

from aram_mayhem_helper.utils.retry import retry_on_exception

# 屏幕区域百分比坐标（left%, top%, right%, bottom%），对应游戏内三个符文槽位
REGIONS: list[tuple[float, float, float, float]] = [
    (0.24, 0.37, 0.39, 0.42),  # 第一个符文位置
    (0.42, 0.37, 0.57, 0.42),  # 第二个符文位置
    (0.61, 0.37, 0.76, 0.42),  # 第三个符文位置
]


def region_to_pixel(
    region: tuple[float, float, float, float],
    screen_width: int,
    screen_height: int,
) -> tuple[int, int, int, int]:
    """百分比区域 → 像素坐标 (left, top, right, bottom)。"""
    return (
        int(region[0] * screen_width),
        int(region[1] * screen_height),
        int(region[2] * screen_width),
        int(region[3] * screen_height),
    )


class OCRTool:
    """
    屏幕指定区域 OCR 识别工具类
    支持截图、识别一体化操作，也可单独识别本地图片
    """

    def __init__(self, lang: str = "ch", use_angle_cls: bool = False, use_gpu: bool = False, show_log: bool = False):
        """
        初始化 OCR 工具（不加载模型，模型在首次识别时懒加载）
        :param lang: 识别语言，默认中英文混合("ch")，英文可设为"en"
        :param use_angle_cls: 是否启用方向分类（识别旋转文本）
        :param use_gpu: 是否使用 GPU 加速
        :param show_log: 是否显示 PaddleOCR 模型加载日志
        """
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.use_gpu = use_gpu
        self.show_log = show_log
        self.logger = logging.getLogger(__name__)
        self._ocr: Any = None
        self._screen_size: tuple[int, int] | None = None

    def _get_ocr(self) -> Any:
        """懒加载 PaddleOCR 模型实例。"""
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                show_log=self.show_log,
                use_gpu=self.use_gpu,
                det_db_thresh=0.2,
                det_db_box_thresh=0.3,
                det_db_unclip_ratio=2.0,
                det_db_score_mode="fast",  # 加快检测速度，不影响合并
            )
        return self._ocr

    @property
    def screen_size(self) -> tuple[int, int]:
        """主显示器尺寸 (width, height)，懒查询。"""
        if self._screen_size is None:
            from screeninfo import get_monitors

            monitor = get_monitors()[0]
            self._screen_size = (monitor.width, monitor.height)
        return self._screen_size

    def capture_screen(self, bbox: tuple[int, int, int, int]) -> np.ndarray[Any, Any]:
        """
        截取屏幕指定区域
        :param bbox: 屏幕区域坐标 (left, top, right, bottom)
        :return: 截图的 numpy 数组（灰度）
        """
        from PIL import ImageGrab

        try:
            screenshot = ImageGrab.grab(bbox).convert("L")
            return np.array(screenshot)
        except Exception as e:
            raise RuntimeError(f"屏幕截图失败: {str(e)}")

    @retry_on_exception(max_retries=2, delay=0.5, backoff_factor=1.5, exceptions=(RuntimeError,))
    def recognize_text(self, image: np.ndarray[Any, Any] | str) -> list[dict[str, Any]]:
        """
        识别图像中的文本
        :param image: 图像输入，支持 numpy 数组（截图结果）或 本地图片路径
        :return: 识别结果列表，每个元素为 {"text": "文本", "confidence": 置信度, "bbox": 坐标}
        """
        try:
            result = self._get_ocr().ocr(image, cls=self.use_angle_cls)
        except Exception as e:
            raise RuntimeError(f"OCR 识别失败: {str(e)}")

        # 解析结果为结构化数据
        parsed_result = []
        if result and result[0]:
            for line in result[0]:
                parsed_result.append(
                    {
                        "text": line[1][0],
                        "confidence": float(line[1][1]),
                        "bbox": line[0],  # 文本区域坐标 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    }
                )
        return parsed_result

    def capture_and_recognize(self, bbox: tuple[int, int, int, int]) -> str:
        """
        截取屏幕指定区域并识别文本（一体化方法）
        :param bbox: 屏幕区域坐标 (left, top, right, bottom)
        :return: 区域内所有识别文本拼接后的完整字符串
        """
        img_array = self.capture_screen(bbox)
        results = self.recognize_text(img_array)
        texts = [item["text"].strip() for item in results]
        return "".join(texts)

    def get_augments(self) -> list[str]:
        """
        获取当前屏幕中的符文选项
        :return: 获取到的符文选项列表
        """
        width, height = self.screen_size
        text_list = [self.capture_and_recognize(region_to_pixel(region, width, height)) for region in REGIONS]
        self.logger.info(f"识别到符文选项: {text_list}")
        return text_list


_ocr_tool_singleton: OCRTool | None = None


def get_ocr_tool() -> OCRTool:
    """懒加载 OCR 工具单例（替代旧导入期初始化 PaddleOCR 模型的副作用）。"""
    global _ocr_tool_singleton
    if _ocr_tool_singleton is None:
        _ocr_tool_singleton = OCRTool()
    return _ocr_tool_singleton
