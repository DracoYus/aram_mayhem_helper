import logging
from typing import List, Optional, Tuple, Union

import numpy as np
from paddleocr import PaddleOCR
from PIL import ImageGrab


class OCRTool:
    """
    屏幕指定区域 OCR 识别工具类
    支持截图、识别一体化操作，也可单独识别本地图片
    """

    def __init__(self, lang: str = "ch", use_angle_cls: bool = False, use_gpu: bool = False, show_log: bool = False):
        """
        初始化 OCR 工具
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

        # 初始化 PaddleOCR 模型（懒加载，首次调用时才真正加载）
        self._ocr: Optional[PaddleOCR] = PaddleOCR(
            use_angle_cls=self.use_angle_cls,
            lang=self.lang,
            show_log=self.show_log,
            use_gpu=self.use_gpu,
            det_db_thresh=0.2,
            det_db_box_thresh=0.3,
            det_db_unclip_ratio=2.0,
            det_db_score_mode="fast",  # 加快检测速度，不影响合并
        )

    def capture_screen(self, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        """
        截取屏幕指定区域
        :param bbox: 屏幕区域坐标 (left, top, right, bottom)
        :return: 截图的 numpy 数组（RGB 格式）
        """
        try:
            screenshot = ImageGrab.grab(bbox).convert("L")
            return np.array(screenshot)
        except Exception as e:
            raise RuntimeError(f"屏幕截图失败: {str(e)}")

    def recognize_text(self, image: Union[np.ndarray, str]) -> List[dict]:
        """
        识别图像中的文本
        :param image: 图像输入，支持 numpy 数组（截图结果）或 本地图片路径
        :return: 识别结果列表，每个元素为 {"text": "文本", "confidence": 置信度, "bbox": 坐标}
        """

        try:
            result = self._ocr.ocr(image, cls=self.use_angle_cls)
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

    def capture_and_recognize(self, bbox: Tuple[int, int, int, int]) -> List[dict]:
        """
        截取屏幕指定区域并识别文本（一体化方法）
        :param bbox: 屏幕区域坐标 (left, top, right, bottom)
        :return: 识别结果列表，格式同 recognize_text()
        """
        img_array = self.capture_screen(bbox)
        return self.recognize_text(img_array)

    def get_augments(self) -> List[str]:
        """
        获取当前屏幕中的符文选项
        :return: 获取到的符文选项列表
        """
        result = []
        result.extend(self.capture_and_recognize((940, 835, 1475, 895)))
        result.extend(self.capture_and_recognize((1645, 835, 2180, 895)))
        result.extend(self.capture_and_recognize((2355, 835, 2890, 895)))
        text_list = [item["text"].strip() for item in result]
        self.logger.info(f"识别到符文选项: {text_list}")
        return text_list


ocr_tool = OCRTool()

if __name__ == "__main__":
    result = ocr_tool.get_augments()
    print(result)
