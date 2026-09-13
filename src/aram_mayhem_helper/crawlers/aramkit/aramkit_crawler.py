"""aramkit.com 数据爬虫。

数据版本号（如 ``16.15-20260805-7e30d3443ba1``）内嵌在首页 HTML 中，无 versions API，
通过正则提取并按游戏版本号取最新。

版本状态文件 ``version.json`` 记录各数据集的完整爬取记录（``crawled`` 字段）和进行中进度
（``progress.<dataset>.completed_ids``）。服务器版本未变化且完整记录存在时跳过重复爬取；
中断后根据进度跳过已完成英雄。
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from aram_mayhem_helper.crawlers.base import BaseCrawler
from aram_mayhem_helper.utils.aramkit import version_sort_key
from aram_mayhem_helper.utils.config import AppConfig, get_config
from aram_mayhem_helper.utils.data import get_game_data

# 数据版本: 16.15-20260805-7e30d3443ba1（游戏版本-日期-哈希）
DATA_VERSION_RE = re.compile(r"\d+\.\d+-\d{8}-[a-f0-9]{12}")
# 资源版本: 16.15-459bb2367aac（游戏版本-哈希）
# 两者互斥：数据版本横杠后是 8 位日期段（凑不满 12 位哈希），资源版本横杠后
# 直接是 12 位十六进制哈希，不会交叉误匹配
RESOURCES_VERSION_RE = re.compile(r"\d+\.\d+-[a-f0-9]{12}")


class AramkitCrawler(BaseCrawler):
    """从 aramkit.com 数据接口爬取英雄数据并保存到本地。

    Args:
        dataset: 数据集（"all" 全体 / "high" 高分段），None 时取配置
        config: 应用配置，None 时取全局配置
    """

    def __init__(self, dataset: str | None = None, config: AppConfig | None = None):
        app_config = config or get_config()
        dataset = dataset or app_config.crawler.aramkit.augment.dataset
        super().__init__(
            timeout=app_config.crawler.timeout,
            delay_second=app_config.crawler.delay_second,
            save_directory=app_config.aramkit_augment_dir,
            user_agent=app_config.crawler.user_agent,
        )
        self.dataset = dataset
        self.homepage_url = app_config.crawler.aramkit.homepage_url
        self.data_base_url = app_config.crawler.aramkit.augment.data_base_url
        self.resources_base_url = app_config.crawler.aramkit.resources.resources_base_url
        self.language = app_config.crawler.aramkit.resources.language
        self.resources_directory = app_config.aramkit_resources_dir
        self.version_file = app_config.data_dir / "aramkit" / "version.json"
        self.resources_directory.mkdir(parents=True, exist_ok=True)
        self.data_version = ""
        self.resources_version = ""
        self._resume_completed_ids: set[int] | None = None
        self.logger = logging.getLogger(__name__)

    def fetch_text(self, url: str) -> str | None:
        """
        从指定URL获取文本内容（用于版本发现首页 HTML）

        Args:
            url: 目标URL

        Returns:
            文本内容，如果失败则返回None
        """
        try:
            response = self._request(url)
            return str(response.text)
        except Exception as e:
            self.logger.error(f"请求 {url} 时发生错误: {str(e)}")
            return None

    def _read_cached_versions(self) -> dict[str, Any] | None:
        """
        读取本地版本状态文件 version.json（本次运行之前的状态）

        Returns:
            状态字典（含 data_version/resources_version/crawled/progress），
            文件缺失或损坏时返回 None
        """
        if not self.version_file.exists():
            return None
        try:
            with open(self.version_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            self.logger.error(f"读取版本缓存失败: {self.version_file}, 错误: {str(e)}")
            return None
        return cached if isinstance(cached, dict) else None

    def _save_versions(
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
        cached = self._read_cached_versions() or {}
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
        temporary_file = self.version_file.with_name(f".{self.version_file.name}.tmp")
        try:
            self.version_file.parent.mkdir(parents=True, exist_ok=True)
            with open(temporary_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(temporary_file, self.version_file)
        except (OSError, TypeError, ValueError) as e:
            self.logger.error(f"保存版本信息失败: {self.version_file}, 错误: {str(e)}")
        finally:
            try:
                temporary_file.unlink(missing_ok=True)
            except OSError as e:
                self.logger.warning(f"清理版本临时文件失败: {temporary_file}, 错误: {str(e)}")

    def discover_versions(self) -> tuple[str, str]:
        """
        从首页 HTML 中发现最新数据/资源版本号，并写入 version.json。

        无 versions API，版本串内嵌在首页中（新旧版本并存），
        按 (major, minor, 日期/哈希) 取最大；抓取失败时回退本地缓存。

        Returns:
            (data_version, resources_version) 元组
        """
        html = self.fetch_text(self.homepage_url)
        if html is not None:
            data_versions = DATA_VERSION_RE.findall(html)
            resources_versions = RESOURCES_VERSION_RE.findall(html)
            if data_versions and resources_versions:
                data_version = max(set(data_versions), key=version_sort_key)
                resources_version = max(set(resources_versions), key=version_sort_key)
                self.logger.info(f"从首页发现版本: data={data_version}, resources={resources_version}")
                self._save_versions(data_version, resources_version)
                return data_version, resources_version
            self.logger.warning(
                f"首页未发现完整版本信息: data={len(data_versions)}, resources={len(resources_versions)}"
            )

        # 回退本地缓存
        cached = self._read_cached_versions()
        if cached:
            data_version = cached.get("data_version")
            resources_version = cached.get("resources_version")
            if data_version and resources_version:
                self.logger.info(f"使用本地缓存的版本: data={data_version}, resources={resources_version}")
                return data_version, resources_version
        raise RuntimeError("无法发现 aramkit 数据版本（首页抓取失败且无本地缓存）")

    def _resources_exist(self, resources_version: str) -> bool:
        """
        判断指定资源版本的资源文件是否已完整存在于本地

        Args:
            resources_version: 资源版本号

        Returns:
            augments.json 与 champions.json 均存在返回 True
        """
        version_dir = self.resources_directory / resources_version
        return all((version_dir / f"{name}.json").exists() for name in ("augments", "champions"))

    def fetch_resources(self, resources_version: str) -> bool:
        """
        拉取 aramkit 资源文件（augments.json / champions.json）。

        Args:
            resources_version: 资源版本号

        Returns:
            两个资源文件均成功保存返回 True，否则返回 False
        """
        base_url = f"{self.resources_base_url}{resources_version}/{self.language}/resources/"
        success = True
        for resource_name in ("augments", "champions"):
            url = f"{base_url}{resource_name}.json"
            self.logger.info(f"开始爬取资源文件: {url}")
            data = self.fetch_json(url)
            if data is None:
                success = False
                continue
            saved = self.save_to_file(
                data,
                resource_name,
                sub_directory=Path(resources_version),
                base_directory=self.resources_directory,
            )
            success = success and saved
        return success and self._resources_exist(resources_version)

    def _champion_ids_in_range(self, start_id: int, end_id: int) -> list[int]:
        """
        获取本地英雄元数据中位于指定范围内的全部英雄ID

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            英雄ID列表
        """
        champion_id_list = [int(champion_id) for champion_id in get_game_data().champion_ids()]
        return [champion_id for champion_id in champion_id_list if start_id <= champion_id <= end_id]

    def _completed_ids_for_progress(
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

    def _save_progress(
        self,
        data_version: str,
        resources_version: str,
        start_id: int,
        end_id: int,
        completed_ids: set[int],
    ) -> None:
        """保存当前数据集的断点续爬进度，并清除旧的完整标记。"""
        cached = self._read_cached_versions() or {}
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
        self._save_versions(data_version, resources_version, crawled=crawled, progress=progress)

    def _prepare_progress(
        self,
        data_version: str,
        resources_version: str,
        start_id: int,
        end_id: int,
        reset: bool = False,
    ) -> set[int]:
        """初始化或恢复当前数据集的断点续爬进度。"""
        completed_ids = (
            None
            if reset
            else self._completed_ids_for_progress(self._read_cached_versions(), data_version, start_id, end_id)
        )
        completed_ids = completed_ids if completed_ids is not None else set()
        self._save_progress(data_version, resources_version, start_id, end_id, completed_ids)
        return completed_ids

    def batch_crawl(self, start_id: int = 1, end_id: int = 999) -> dict[str, bool]:
        """
        批量爬取多个英雄数据

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            包含每个URL爬取结果的字典，键为英雄ID，值为爬取结果
        """
        self.logger.info(f"开始批量爬取英雄ID范围: {start_id} - {end_id}（数据集: {self.dataset}）")
        results: dict[str, bool] = {}
        failed_ids: list[int] = []
        consecutive_failures = 0
        completed_ids = set(self._resume_completed_ids or ())
        should_persist_progress = self._resume_completed_ids is not None

        for champion_id in self._champion_ids_in_range(start_id, end_id):
            url = f"{self.data_base_url}{self.data_version}/stats/{self.dataset}/champion-details/{champion_id}.json"
            filename = f"{champion_id}"
            if champion_id in completed_ids:
                results[filename] = True
                consecutive_failures = 0
                self.logger.info(f"英雄ID {champion_id} 已完成，跳过爬取")
                continue

            results[filename] = self.crawl_and_save(url, filename)
            if not results[filename]:
                failed_ids.append(champion_id)
                consecutive_failures += 1
            else:
                if should_persist_progress:
                    completed_ids.add(champion_id)
                    self._save_progress(
                        self.data_version,
                        self.resources_version,
                        start_id,
                        end_id,
                        completed_ids,
                    )
                consecutive_failures = 0
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self.logger.warning(f"连续{consecutive_failures}个英雄ID爬取失败，已停止爬取")
                break
            time.sleep(self.delay_second)
        fail_count = sum(1 for succeeded in results.values() if not succeeded)
        self.logger.info(
            f"批量爬取完成，共成功 {len(results) - fail_count} 个英雄；共失败 {fail_count} 个英雄ID: {failed_ids}"
        )
        return results

    def _stats_up_to_date(self, previous: dict[str, Any] | None, data_version: str, start_id: int, end_id: int) -> bool:
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

    def _record_crawled(self, data_version: str, resources_version: str, start_id: int, end_id: int) -> None:
        """
        记录本数据集已完成全量爬取（写入 version.json 的 crawled 字段），供下次运行跳过判断

        Args:
            data_version: 数据版本号
            resources_version: 资源版本号
            start_id: 起始英雄ID
            end_id: 结束英雄ID
        """
        cached = self._read_cached_versions() or {}
        existing = cached.get("crawled")
        crawled = dict(existing) if isinstance(existing, dict) else {}
        crawled[self.dataset] = {"start_id": start_id, "end_id": end_id}
        existing_progress = cached.get("progress")
        progress = dict(existing_progress) if isinstance(existing_progress, dict) else {}
        progress.pop(self.dataset, None)
        self._save_versions(data_version, resources_version, crawled=crawled, progress=progress)

    def crawl(self, start_id: int = 1, end_id: int = 999, *, force: bool = False) -> bool:
        """
        完整爬取流程：版本发现 → 更新检查 → 资源文件 → 批量英雄数据

        服务器数据版本与本地一致且已有同范围完整爬取记录时跳过英雄数据爬取；
        存在同范围进行中进度时恢复爬取并跳过已完成英雄；资源文件按本地是否已存在判断是否跳过。

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID
            force: 忽略更新检查，强制全量爬取

        Returns:
            全部成功（含跳过）返回True，存在失败返回False
        """
        previous = self._read_cached_versions()
        data_version, resources_version = self.discover_versions()
        self.data_version = data_version
        self.resources_version = resources_version
        has_progress = self._completed_ids_for_progress(previous, data_version, start_id, end_id) is not None
        stats_up_to_date = (
            not force and not has_progress and self._stats_up_to_date(previous, data_version, start_id, end_id)
        )

        if self._resources_exist(resources_version):
            self.logger.info(f"资源文件已存在（{resources_version}），跳过下载")
        elif not self.fetch_resources(resources_version):
            self.logger.error(f"资源文件下载不完整（{resources_version}），终止本次爬取")
            return False

        if stats_up_to_date:
            self.logger.info(f"服务器数据无更新（{data_version}），跳过英雄数据爬取")
            return True

        self._resume_completed_ids = self._prepare_progress(
            data_version, resources_version, start_id, end_id, reset=force
        )
        try:
            results = self.batch_crawl(start_id, end_id)
        finally:
            self._resume_completed_ids = None
        if results and all(results.values()):
            self._record_crawled(data_version, resources_version, start_id, end_id)
        # 空结果（如英雄数据尚未抓取）不算成功：all({}) 恒为 True 会误报
        return bool(results) and all(results.values())


if __name__ == "__main__":
    crawler = AramkitCrawler()
    crawler.crawl(1, 5)
