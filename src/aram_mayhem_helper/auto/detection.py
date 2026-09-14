"""符文选择阶段检测：像素判别 + 去抖状态机（纯逻辑，无 I/O）。

实测依据（2026-09，4K 主屏，海克斯乱斗 KIWI 模式）：
- Live Client Data API 无符文选择事件（官方 EventName 清单仅战斗类），事件路径不可用；
- 选择阶段 gameTime 照常推进，冻结假设不成立；
- 选择界面三个 OCR 区域呈「暗背景 + 高对比白字」特征
  （mean ≈ 31~42, std ≈ 52~65, min/max ≈ 8/231），
  游戏内同区域为地图像素（mean ≈ 99~132, std ≈ 25~32, 无极端值），
  mean/std 双判据在两组样本间均有 2~4 倍间隔。

reroll（刷新符文）检测不用像素指纹：16×16 降采样后不同符文名的
「白字居中」布局几乎相同，指纹差异达不到阈值（实测失效）。
reroll 检测在 watcher 中用 OCR 文本比对实现（见 watcher._check_reroll）。
"""

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from numpy.typing import NDArray

# 默认判别阈值（实测两组样本间隔中点，可被配置覆盖）
DEFAULT_MEAN_THRESHOLD = 60.0
DEFAULT_STD_THRESHOLD = 40.0


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


class SelectionState(Enum):
    """选择阶段检测状态机的状态。"""

    RUNNING = auto()  # 游戏中，未在选择界面
    TRIGGERED = auto()  # 已触发本次推荐，等待选择界面消失后重新武装


@dataclass(frozen=True)
class DetectionResult:
    """状态机单步推进的结果。"""

    state: SelectionState
    should_trigger: bool  # 仅在 RUNNING → 触发的跳变瞬间为 True


class SelectionDetector:
    """选择阶段检测状态机：连续 N 次命中判据后触发一次，信号消失后重新武装。

    去抖（连续 N 次）用于过滤游戏过渡帧（回城特效、死亡灰屏等短暂暗画面）。
    reroll 重触发不在此处（像素指纹不可靠），由 watcher 用 OCR 文本比对实现。
    """

    def __init__(self, debounce_count: int = 2) -> None:
        if debounce_count < 1:
            raise ValueError(f"debounce_count 必须 >= 1，收到 {debounce_count}")
        self._debounce_count = debounce_count
        self._consecutive_hits = 0
        self._state = SelectionState.RUNNING

    @property
    def state(self) -> SelectionState:
        return self._state

    def reset(self) -> None:
        """回到初始状态（RUNNING，计数清零）。"""
        self._consecutive_hits = 0
        self._state = SelectionState.RUNNING

    def feed(self, is_selection_ui: bool) -> DetectionResult:
        """输入一次判别结果，推进状态机。"""
        if self._state is SelectionState.TRIGGERED:
            if is_selection_ui:
                # 仍在选择界面（reroll 检测由 watcher 负责），保持 TRIGGERED
                self._consecutive_hits = 0
                return DetectionResult(state=self._state, should_trigger=False)
            # 选择界面消失 → 重新武装
            self._state = SelectionState.RUNNING
            self._consecutive_hits = 0
            return DetectionResult(state=self._state, should_trigger=False)

        # RUNNING 状态
        if not is_selection_ui:
            self._consecutive_hits = 0
            return DetectionResult(state=self._state, should_trigger=False)

        self._consecutive_hits += 1
        if self._consecutive_hits >= self._debounce_count:
            self._state = SelectionState.TRIGGERED
            return DetectionResult(state=self._state, should_trigger=True)
        return DetectionResult(state=self._state, should_trigger=False)
