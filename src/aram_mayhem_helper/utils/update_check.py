"""数据源更新检查：状态模型与用户提示文案。

检查逻辑本身挂在各爬虫的 ``check_update()`` 方法上（复用其会话与版本发现），
本模块只定义不可变的结果模型，供 GUI/CLI 直接展示，不含任何网络或文件操作。
"""

from dataclasses import dataclass
from typing import Literal

UpdateState = Literal["up_to_date", "update_available", "no_local_data", "unknown"]

_SOURCE_LABELS = {"ddragon": "英雄数据", "aramkit": "aramkit 符文数据"}


@dataclass(frozen=True)
class UpdateStatus:
    """一次更新检查的结果。

    Attributes:
        source: 数据源标识（"ddragon"/"aramkit"）
        state: 检查结论（见 :data:`UpdateState`）
        local_version: 本地版本号，无本地数据时为 None
        remote_version: 远端版本号，远端不可达时为 None
        error: state 为 "unknown" 时的失败原因
    """

    source: str
    state: UpdateState
    local_version: str | None = None
    remote_version: str | None = None
    error: str | None = None

    @property
    def message(self) -> str:
        """用户可读的检查结论（中文，供日志区展示）。"""
        label = _SOURCE_LABELS.get(self.source, self.source)
        if self.state == "update_available":
            return f"{label}有新版本（{self.local_version} → {self.remote_version}），请执行数据抓取更新"
        if self.state == "up_to_date":
            return f"{label}已是最新（{self.local_version}）"
        if self.state == "no_local_data":
            return f"本地暂无{label}，请先执行数据抓取"
        detail = f"：{self.error}" if self.error else ""
        return f"{label}更新检查失败{detail}，不影响本地数据使用"
