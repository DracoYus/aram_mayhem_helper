"""符文选择阶段检测：像素判别 + 去抖状态机（纯逻辑，无 I/O）。

实测依据（2026-09，4K 主屏，海克斯乱斗 KIWI 模式）：
- Live Client Data API 无符文选择事件（官方 EventName 清单仅战斗类），事件路径不可用；
- 选择阶段 gameTime 照常推进，冻结假设不成立；
- 选择界面三个 OCR 区域呈「暗背景 + 高对比白字」特征
  （mean ≈ 31~42, std ≈ 52~65, min/max ≈ 8/231），
  游戏内同区域为地图像素（mean ≈ 99~132, std ≈ 25~32, 无极端值），
  mean/std 双判据在两组样本间均有 2~4 倍间隔。

reroll（刷新符文）处理：reroll 后选择界面仍停留在屏幕上（信号不消失），
状态机在 TRIGGERED 状态下对区域截图做内容指纹（亮像素降采样二值向量），
指纹连续 2 次显著变化 → 判定为 reroll 换卡，重新触发识别。
"""

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from numpy.typing import NDArray

# 默认判别阈值（实测两组样本间隔中点，可被配置覆盖）
DEFAULT_MEAN_THRESHOLD = 60.0
DEFAULT_STD_THRESHOLD = 40.0
# 指纹差异阈值：汉明距离/总位数 超过此值视为内容变化（reroll 换卡）
DEFAULT_FINGERPRINT_CHANGE_RATIO = 0.10
# 指纹降采样网格（每区域缩到 grid × grid 二值图）
_FINGERPRINT_GRID = 16


@dataclass(frozen=True)
class DetectionThresholds:
    """选择界面像素判别阈值（灰度统计特征）。

    判据：区域灰度 mean < mean_threshold 且 std > std_threshold
    （暗背景 + 高对比文字）。两个条件在实测样本间均有数倍间隔，
    双条件与运算进一步压缩误判空间。
    """

    mean_threshold: float = DEFAULT_MEAN_THRESHOLD
    std_threshold: float = DEFAULT_STD_THRESHOLD


def looks_like_selection_ui(image: NDArray[np.uint8], thresholds: DetectionThresholds) -> bool:
    """判断单个区域灰度截图是否符合符文选择界面特征。

    Args:
        image: 灰度截图（2D uint8 数组）
        thresholds: 判别阈值
    """
    if image.size == 0:
        return False
    mean = float(image.mean())
    std = float(image.std())
    return mean < thresholds.mean_threshold and std > thresholds.std_threshold


def looks_like_selection_ui_stats(stats: list[tuple[float, float]], thresholds: DetectionThresholds) -> bool:
    """按已计算的 (mean, std) 统计判断是否为选择界面（任一区域命中即算）。

    多区域取「任一命中」而非「全部命中」：游戏内三个区域都是地图像素，
    全部不命中；选择界面三个区域都是卡片文字，全部命中。取任一是为了
    容忍单个区域被遮挡/描述文字覆盖导致的特征偏移。
    """
    return any(mean < thresholds.mean_threshold and std > thresholds.std_threshold for mean, std in stats)


def content_fingerprint(image: NDArray[np.uint8], grid: int = _FINGERPRINT_GRID) -> NDArray[np.float64]:
    """区域灰度图 → 内容指纹（grid × grid 降采样二值向量）。

    分块均值降采样后，亮于块均值的格子记 1（文字所在格），其余记 0。
    对亮度整体偏移（动画光效）不敏感，只反映文字布局——同一卡片重复
    采样指纹稳定，reroll 换卡后文字布局变化 → 指纹显著变化。
    """
    if image.size == 0:
        return np.zeros(grid * grid, dtype=np.float64)
    h, w = image.shape[:2]
    blocks = [
        image[r * h // grid : (r + 1) * h // grid, c * w // grid : (c + 1) * w // grid].mean()
        for r in range(grid)
        for c in range(grid)
    ]
    resized = np.array(blocks, dtype=np.float64).reshape(grid, grid)
    binary: NDArray[np.float64] = (resized > resized.mean()).astype(np.float64)
    return binary.ravel()


def fingerprint_changed(a: NDArray[np.float64], b: NDArray[np.float64], ratio: float) -> bool:
    """两个指纹的汉明距离占比是否超过 *ratio*（内容显著变化）。"""
    if a.shape != b.shape or a.size == 0:
        return False
    return float(np.mean(a != b)) > ratio


class SelectionState(Enum):
    """选择阶段检测状态机的状态。"""

    RUNNING = auto()  # 游戏中，未在选择界面
    TRIGGERED = auto()  # 已触发本次推荐，等待选择界面消失后重新武装


@dataclass(frozen=True)
class DetectionResult:
    """状态机单步推进的结果。"""

    state: SelectionState
    should_trigger: bool  # 触发瞬间为 True（首次进入选择界面，或 reroll 换卡）


class SelectionDetector:
    """选择阶段检测状态机：连续 N 次命中判据后触发一次，信号消失后重新武装。

    去抖（连续 N 次）用于过滤游戏过渡帧（回城特效、死亡灰屏等短暂暗画面）。

    reroll 支持：TRIGGERED 状态下若界面内容指纹连续 2 次显著变化
    （刷新符文换卡），重新触发识别并更新快照。
    """

    def __init__(
        self,
        debounce_count: int = 2,
        fingerprint_change_ratio: float = DEFAULT_FINGERPRINT_CHANGE_RATIO,
    ) -> None:
        if debounce_count < 1:
            raise ValueError(f"debounce_count 必须 >= 1，收到 {debounce_count}")
        self._debounce_count = debounce_count
        self._fingerprint_ratio = fingerprint_change_ratio
        self._consecutive_hits = 0
        self._state = SelectionState.RUNNING
        self._fingerprint: NDArray[np.float64] | None = None  # 已识别界面的内容快照
        self._change_streak = 0  # 连续指纹变化计数（去抖 reroll 瞬间动画）

    @property
    def state(self) -> SelectionState:
        return self._state

    def reset(self) -> None:
        """回到初始状态（RUNNING，计数清零，指纹清空）。"""
        self._consecutive_hits = 0
        self._change_streak = 0
        self._fingerprint = None
        self._state = SelectionState.RUNNING

    def feed(self, is_selection_ui: bool, fingerprint: NDArray[np.float64] | None = None) -> DetectionResult:
        """输入一次判别结果（TRIGGERED 状态下附内容指纹），推进状态机。

        RUNNING 触发时若带指纹则记录为快照；TRIGGERED 下指纹连续 2 次
        显著变化 → reroll 重触发并更新快照。
        """
        if self._state is SelectionState.TRIGGERED:
            if not is_selection_ui:
                # 选择界面消失 → 重新武装
                self._state = SelectionState.RUNNING
                self._consecutive_hits = 0
                self._change_streak = 0
                self._fingerprint = None
                return DetectionResult(state=self._state, should_trigger=False)

            # 仍在选择界面：检查内容是否变化（reroll 换卡）
            if fingerprint is None:
                return DetectionResult(state=self._state, should_trigger=False)
            changed = self._fingerprint is not None and fingerprint_changed(
                self._fingerprint, fingerprint, self._fingerprint_ratio
            )
            self._change_streak = self._change_streak + 1 if changed else 0
            if self._change_streak >= 2:
                # reroll：更新快照并重新触发
                self._fingerprint = fingerprint
                self._change_streak = 0
                return DetectionResult(state=self._state, should_trigger=True)
            if self._fingerprint is None:
                self._fingerprint = fingerprint
            return DetectionResult(state=self._state, should_trigger=False)

        # RUNNING 状态
        if not is_selection_ui:
            self._consecutive_hits = 0
            return DetectionResult(state=self._state, should_trigger=False)

        self._consecutive_hits += 1
        if self._consecutive_hits >= self._debounce_count:
            self._state = SelectionState.TRIGGERED
            if fingerprint is not None:
                self._fingerprint = fingerprint
            return DetectionResult(state=self._state, should_trigger=True)
        return DetectionResult(state=self._state, should_trigger=False)
