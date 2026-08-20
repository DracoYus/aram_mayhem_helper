"""aramkit.com 数据爬虫。

数据版本号（如 ``16.15-20260805-7e30d3443ba1``）内嵌在首页 HTML 中，无 versions API，
通过正则提取并按游戏版本号取最新。
"""

import json
import logging
import re
import time
from pathlib import Path

from aram_mayhem_helper.crawlers.base import BaseCrawler
from aram_mayhem_helper.utils.aramkit import version_sort_key
from aram_mayhem_helper.utils.config import AppConfig, get_config
from aram_mayhem_helper.utils.data import get_game_data

# 数据版本: 16.15-20260805-7e30d3443ba1（游戏版本-日期-哈希）
DATA_VERSION_RE = re.compile(r"16\.\d+-\d{8}-[a-f0-9]{12}")
# 资源版本: 16.15-459bb2367aac（与数据版本正则互斥，不会交叉误匹配）
RESOURCES_VERSION_RE = re.compile(r"16\.\d+-[a-f0-9]{12}")


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
                try:
                    self.version_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.version_file, "w", encoding="utf-8") as f:
                        json.dump(
                            {"data_version": data_version, "resources_version": resources_version},
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                except OSError as e:
                    self.logger.error(f"保存版本信息失败: {self.version_file}, 错误: {str(e)}")
                return data_version, resources_version
            self.logger.warning(
                f"首页未发现完整版本信息: data={len(data_versions)}, resources={len(resources_versions)}"
            )

        # 回退本地缓存
        if self.version_file.exists():
            try:
                with open(self.version_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                data_version = cached.get("data_version")
                resources_version = cached.get("resources_version")
                if data_version and resources_version:
                    self.logger.info(f"使用本地缓存的版本: data={data_version}, resources={resources_version}")
                    return data_version, resources_version
            except (json.JSONDecodeError, OSError) as e:
                self.logger.error(f"读取版本缓存失败: {self.version_file}, 错误: {str(e)}")
        raise RuntimeError("无法发现 aramkit 数据版本（首页抓取失败且无本地缓存）")

    def fetch_resources(self, resources_version: str) -> None:
        """
        拉取 aramkit 资源文件（augments.json / champions.json）。

        Args:
            resources_version: 资源版本号
        """
        base_url = f"{self.resources_base_url}{resources_version}/{self.language}/resources/"
        for resource_name in ("augments", "champions"):
            url = f"{base_url}{resource_name}.json"
            self.logger.info(f"开始爬取资源文件: {url}")
            data = self.fetch_json(url)
            if data is not None:
                self.save_to_file(
                    data,
                    resource_name,
                    sub_directory=Path(resources_version),
                    base_directory=self.resources_directory,
                )

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
        fail_count = 0

        champion_id_list = [int(champion_id) for champion_id in get_game_data().champion_ids()]
        for champion_id in champion_id_list:
            if champion_id < start_id or champion_id > end_id:
                continue
            url = f"{self.data_base_url}{self.data_version}/stats/{self.dataset}/champion-details/{champion_id}.json"
            filename = f"{champion_id}"
            results[filename] = self.crawl_and_save(url, filename)
            if not results[filename]:
                failed_ids.append(champion_id)
                fail_count += 1
            if fail_count >= 10:
                self.logger.warning(f"连续{fail_count}个英雄ID爬取失败，已停止爬取")
                break
            time.sleep(self.delay_second)
        self.logger.info(
            f"批量爬取完成，共成功 {len(results) - fail_count} 个英雄；共失败 {fail_count} 个英雄ID: {failed_ids}"
        )
        return results

    def crawl(self, start_id: int = 1, end_id: int = 999) -> bool:
        """
        完整爬取流程：版本发现 → 资源文件 → 批量英雄数据

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            全部成功返回True，存在失败返回False
        """
        data_version, resources_version = self.discover_versions()
        self.data_version = data_version
        self.fetch_resources(resources_version)
        results = self.batch_crawl(start_id, end_id)
        # 空结果（如英雄数据尚未抓取）不算成功：all({}) 恒为 True 会误报
        return bool(results) and all(results.values())


if __name__ == "__main__":
    crawler = AramkitCrawler()
    crawler.crawl(1, 5)
