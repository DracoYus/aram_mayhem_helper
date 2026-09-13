"""aramkit version.json 状态操作（爬虫断点续爬与跳过判断的状态层）。

状态文件 ``version.json`` 记录各数据集的完整爬取记录（``crawled`` 字段）和进行中进度
（``progress.<dataset>.completed_ids``）。服务器版本未变化且完整记录存在时跳过重复爬取；
中断后根据进度跳过已完成英雄。
"""

import json
import logging
import os
from pathlib import Path
from typing import Any


class VersionState:
    """version.json 的读取/写入与数据集级状态查询（与 HTTP 爬取逻辑解耦）。

    Args:
        file_path: 状态文件路径（``<data_dir>/aramkit/version.json``）
        dataset: 数据集（"all"/"high"），数据集级查询与写入使用
        logger: 日志器，None 时取模块 logger
    """

    def __init__(self, file_path: Path, dataset: str, logger: logging.Logger | None = None):
        self.file_path = file_path
        self.dataset = dataset
        self.logger = logger or logging.getLogger(__name__)

    def read(self) -> dict[str, Any] | None:
        """
        读取本地版本状态文件 version.json（本次运行之前的状态）

        Returns:
            状态字典（含 data_version/resources_version/crawled/progress），
            文件缺失或损坏时返回 None
        """
        if not self.file_path.exists():
            return None
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self.logger.error(f"读取版本缓存失败: {self.file_path}, 错误: {str(e)}")
            return None
        return cached if isinstance(cached, dict) else None

    def save(
        self,
        data_version: str,
        resources_version: str,
        crawled: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
    ) -> None:
        """
        写入版本状态文件 version.json。

        Args:
            data_version: 数据版本号
            resources_version: 资源版本号
            crawled: 各数据集的完整爬取记录；None 时保留同一数据版本的已有记录
            progress: 各数据集的断点续爬记录；None 时保留同一数据版本的已有记录
        """
        cached = self.read() or {}
        same_data_version = cached.get("data_version") == data_version
        if crawled is None:
            existing = cached.get("crawled")
            crawled = existing if same_data_version and isinstance(existing, dict) else {}
        if progress is None:
            existing = cached.get("progress")
            progress = existing if same_data_version and isinstance(existing, dict) else {}
        state = {
            "data_version": data_version,
            "resources_version": resources_version,
            "crawled": crawled,
            "progress": progress,
        }
        temporary_file = self.file_path.with_name(f".{self.file_path.name}.tmp")
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(temporary_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(temporary_file, self.file_path)
        except (OSError, TypeError, ValueError) as e:
            self.logger.error(f"保存版本信息失败: {self.file_path}, 错误: {str(e)}")
        finally:
            try:
                temporary_file.unlink(missing_ok=True)
            except OSError as e:
                self.logger.warning(f"清理版本临时文件失败: {temporary_file}, 错误: {str(e)}")

    def completed_ids_for(
        self, cached: dict[str, Any] | None, data_version: str, start_id: int, end_id: int
    ) -> set[int] | None:
        """读取与当前数据版本、数据集和范围匹配的已完成英雄 ID。"""
        if not cached or cached.get("data_version") != data_version:
            return None
        progress = cached.get("progress")
        if not isinstance(progress, dict):
            return None
        record = progress.get(self.dataset)
        if not isinstance(record, dict):
            return None
        if record.get("data_version") != data_version:
            return None
        if record.get("start_id") != start_id or record.get("end_id") != end_id:
            return None
        completed_ids = record.get("completed_ids")
        if not isinstance(completed_ids, list):
            return set()
        return {
            completed_id
            for completed_id in completed_ids
            if isinstance(completed_id, int) and not isinstance(completed_id, bool)
        }

    def save_progress(
        self,
        data_version: str,
        resources_version: str,
        start_id: int,
        end_id: int,
        completed_ids: set[int],
    ) -> None:
        """保存当前数据集的断点续爬进度，并清除旧的完整标记。"""
        cached = self.read() or {}
        same_data_version = cached.get("data_version") == data_version
        existing_progress = cached.get("progress")
        progress = dict(existing_progress) if same_data_version and isinstance(existing_progress, dict) else {}
        progress[self.dataset] = {
            "data_version": data_version,
            "start_id": start_id,
            "end_id": end_id,
            "completed_ids": sorted(completed_ids),
        }
        existing_crawled = cached.get("crawled")
        crawled = dict(existing_crawled) if same_data_version and isinstance(existing_crawled, dict) else {}
        crawled.pop(self.dataset, None)
        self.save(data_version, resources_version, crawled=crawled, progress=progress)

    def prepare_progress(
        self,
        data_version: str,
        resources_version: str,
        start_id: int,
        end_id: int,
        reset: bool = False,
    ) -> set[int]:
        """初始化或恢复当前数据集的断点续爬进度。"""
        completed_ids = None if reset else self.completed_ids_for(self.read(), data_version, start_id, end_id)
        completed_ids = completed_ids if completed_ids is not None else set()
        self.save_progress(data_version, resources_version, start_id, end_id, completed_ids)
        return completed_ids

    def stats_up_to_date(self, previous: dict[str, Any] | None, data_version: str, start_id: int, end_id: int) -> bool:
        """
        判断本地英雄数据是否已覆盖当前服务器版本及请求范围

        Args:
            previous: 本次运行前的 version.json 状态（None 表示无记录）
            data_version: 服务器当前数据版本号
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            版本一致且本数据集已有相同范围的爬取记录时返回 True
        """
        if not previous or previous.get("data_version") != data_version:
            return False
        crawled = previous.get("crawled")
        if not isinstance(crawled, dict):
            return False
        record = crawled.get(self.dataset)
        return isinstance(record, dict) and record.get("start_id") == start_id and record.get("end_id") == end_id

    def record_crawled(self, data_version: str, resources_version: str, start_id: int, end_id: int) -> None:
        """
        记录本数据集已完成全量爬取（写入 version.json 的 crawled 字段），供下次运行跳过判断

        Args:
            data_version: 数据版本号
            resources_version: 资源版本号
            start_id: 起始英雄ID
            end_id: 结束英雄ID
        """
        cached = self.read() or {}
        existing = cached.get("crawled")
        crawled = dict(existing) if isinstance(existing, dict) else {}
        crawled[self.dataset] = {"start_id": start_id, "end_id": end_id}
        existing_progress = cached.get("progress")
        progress = dict(existing_progress) if isinstance(existing_progress, dict) else {}
        progress.pop(self.dataset, None)
        self.save(data_version, resources_version, crawled=crawled, progress=progress)
