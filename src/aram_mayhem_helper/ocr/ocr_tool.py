"""屏幕 OCR 识别工具。

PaddleOCR/PIL/screeninfo 均在方法内懒导入：模块导入本身不加载模型、
不查询屏幕（无导入期副作用），web 部署无需安装 ``[ocr]`` 依赖组。
"""

import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from aram_mayhem_helper.utils.config import get_config
from aram_mayhem_helper.utils.retry import retry_on_exception

# 失败截图文件名中 OCR 文本片段的长度上限
_MAX_NAME_LENGTH = 30


def _safe_filename(text: str, max_length: int = _MAX_NAME_LENGTH) -> str:
    """OCR 文本 → 文件名片段：替换 Windows 非法字符与空白为 "_"，截断，空则 "empty"。

    OCR 文本来自屏幕，属不可信输入，直接进文件名可能包含 ``\\/:*?"<>|``
    等非法字符或过长的空白/换行。
    """
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")
    cleaned = cleaned[:max_length].strip("_")
    return cleaned or "empty"


# 屏幕区域百分比坐标（left%, top%, right%, bottom%），对应游戏内三个符文槽位
REGIONS: list[tuple[float, float, float, float]] = [
    (0.2373, 0.386, 0.3873, 0.436),  # 第一个符文位置
    (0.4291, 0.386, 0.5791, 0.436),  # 第二个符文位置
    (0.6210, 0.386, 0.7710, 0.436),  # 第三个符文位置
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

    def __init__(
        self,
        lang: str = "ch",
        use_angle_cls: bool = False,
        use_gpu: bool = False,
        show_log: bool = False,
        debug_capture_dir: Path | None = None,
    ):
        """
        初始化 OCR 工具（不加载模型，模型在首次识别时懒加载）
        :param lang: 识别语言，默认中英文混合("ch")，英文可设为"en"
        :param use_angle_cls: 是否启用方向分类（识别旋转文本）
        :param use_gpu: 是否使用 GPU 加速
        :param show_log: 是否显示 PaddleOCR 模型加载日志
        :param debug_capture_dir: 调试模式目录；非 None 时每次识别把每个区域
            的截图保存到此目录（排查 OCR 区域坐标），None 关闭
        """
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.use_gpu = use_gpu
        self.show_log = show_log
        self.logger = logging.getLogger(__name__)
        self._ocr: Any = None
        self._ocr_lock = threading.Lock()
        self._screen_size: tuple[int, int] | None = None
        self._last_captures: list[np.ndarray[Any, Any]] = []  # 最近一次 get_augments 各区域截图，供识别失败排查
        self.debug_capture_dir = debug_capture_dir

    def _get_ocr(self) -> Any:
        """懒加载 PaddleOCR 模型实例（加锁防止预热与首次识别并发重复加载）。"""
        if self._ocr is None:
            with self._ocr_lock:
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

    def warmup(self) -> None:
        """预加载 PaddleOCR 模型（GUI 启动时后台调用，避免首次识别等待模型加载）。

        失败仅记录日志，不影响后续使用——首次识别时 `_get_ocr` 会重新加载。
        """
        try:
            self._get_ocr()
        except Exception:
            self.logger.exception("OCR 模型预热失败，首次识别时将重新加载")

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

    def _join_first_line(self, results: list[dict[str, Any]]) -> str:
        """合并识别结果中第一行文字被拆分的文本框，返回该行完整文本。

        符文名称中的全角标点（如 ``升级：中娅`` 的 ``：``、``哎哟，我的硬币！``
        的 ``，``）会造成字距断口，PaddleOCR 会把同一行文字检测成多个文本框；
        仅取第一个框会把名称截断为 ``升级：``，查表失败。以最上方文本框为锚，
        纵向与之重叠的框视为同一行，按 x 排序后拼接；卡片描述文字在下方另一行，
        纵向不重叠，不会混入名称。
        """
        boxes = [r for r in results if r.get("bbox")]
        if not boxes:
            # 无坐标信息时退回旧行为：只取第一个框
            return results[0]["text"].strip() if results else ""
        anchor = min(boxes, key=lambda r: min(p[1] for p in r["bbox"]))
        anchor_top = min(p[1] for p in anchor["bbox"])
        anchor_bottom = max(p[1] for p in anchor["bbox"])
        line_boxes = [
            r
            for r in boxes
            if min(p[1] for p in r["bbox"]) <= anchor_bottom
            and max(p[1] for p in r["bbox"]) >= anchor_top
        ]
        line_boxes.sort(key=lambda r: min(p[0] for p in r["bbox"]))
        return "".join(r["text"].strip() for r in line_boxes)

    def get_augments(self) -> list[str]:
        """
        获取当前屏幕中的符文选项，并保留各区域截图（供识别失败时保存排查）

        调试模式（debug_capture_dir 非 None）下额外把每个区域截图全部保存，
        用于排查 OCR 区域坐标是否对准游戏界面。
        :return: 获取到的符文选项列表
        """
        width, height = self.screen_size
        captures: list[np.ndarray[Any, Any]] = []
        text_list: list[str] = []
        for region in REGIONS:
            image = self.capture_screen(region_to_pixel(region, width, height))
            captures.append(image)
            results = self.recognize_text(image)
            # 合并第一行被标点断口拆开的文本框（如 "升级：中娅" → ["升级：", "中娅"]）；
            # 描述文字在下方另一行，纵向不重叠，不会混入名称（匹配为精确查表）
            text_list.append(self._join_first_line(results))
        self._last_captures = captures
        if self.debug_capture_dir is not None:
            saved = sum(
                self._save_capture(index, text, self.debug_capture_dir) is not None
                for index, text in enumerate(text_list)
            )
            self.logger.info(f"OCR 调试模式：已保存 {saved}/{len(text_list)} 张区域截图到 {self.debug_capture_dir}")
        self.logger.info(f"识别到符文选项: {text_list}")
        return text_list

    def save_failure_capture(self, index: int, ocr_text: str, directory: Path) -> Path | None:
        """保存指定区域最近一次截图的灰度图，用于排查 OCR 识别失败。

        由识别失败（符文名称未匹配）的调用方在 ``get_augments`` 之后调用；
        ``index`` 与 REGIONS 中区域一一对应。保存失败不抛异常，仅记录日志，
        不影响推荐主流程。

        Args:
            index: 区域索引（0 ~ len(REGIONS)-1）
            ocr_text: 该区域 OCR 出的原始文本（写入文件名便于辨认）
            directory: 保存目录（自动创建）

        Returns:
            保存的 PNG 路径；索引无截图或保存失败时返回 None
        """
        return self._save_capture(index, ocr_text, directory)

    def _save_capture(self, index: int, ocr_text: str, directory: Path) -> Path | None:
        """保存指定区域截图为 PNG（失败截图与调试模式共用的核心实现）。

        保存失败不抛异常，仅记录日志，不影响调用主流程。
        """
        if not (0 <= index < len(self._last_captures)):
            self.logger.warning(f"无法保存区域截图：区域索引 {index} 无对应截图")
            return None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            from PIL import Image

            # datetime.strftime 自行处理 %f，Windows 的 time.strftime 不支持微秒
            stem = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}_region{index}_{_safe_filename(ocr_text)}"
            path = directory / f"{stem}.png"
            counter = 1
            while path.exists():
                path = directory / f"{stem}_{counter}.png"
                counter += 1
            Image.fromarray(self._last_captures[index]).save(path)
        except Exception:
            self.logger.exception("保存区域截图失败")
            return None
        self.logger.info(f"已保存区域截图: {path}")
        return path


_ocr_tool_singleton: OCRTool | None = None


def get_ocr_tool() -> OCRTool:
    """懒加载 OCR 工具单例（替代旧导入期初始化 PaddleOCR 模型的副作用）。

    调试模式开关（config [ocr].debug_save_captures）在单例首次构建时读取，
    修改配置后需重启进程生效。
    """
    global _ocr_tool_singleton
    if _ocr_tool_singleton is None:
        cfg = get_config()
        _ocr_tool_singleton = OCRTool(
            debug_capture_dir=cfg.ocr_debug_dir if cfg.ocr.debug_save_captures else None,
        )
    return _ocr_tool_singleton
