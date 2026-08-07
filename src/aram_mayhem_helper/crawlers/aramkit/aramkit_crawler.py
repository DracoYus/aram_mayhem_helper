"""爬虫模块，用于从 aramkit.com 数据接口获取英雄数据并保存为 JSON 格式到本地。

数据版本号（如 ``16.15-20260805-7e30d3443ba1``）内嵌在首页 HTML 中，无 versions API，
通过正则提取并按游戏版本号取最新。
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.data import get_game_data
from aram_mayhem_helper.utils.retry import retry_on_exception

# 数据版本: 16.15-20260805-7e30d3443ba1（游戏版本-日期-哈希）
DATA_VERSION_RE = re.compile(r"16\.\d+-\d{8}-[a-f0-9]{12}")
# 资源版本: 16.15-459bb2367aac（与数据版本正则互斥，不会交叉误匹配）
RESOURCES_VERSION_RE = re.compile(r"16\.\d+-[a-f0-9]{12}")


def _version_sort_key(version: str) -> tuple:
    """版本串排序键：按游戏版本号（major.minor）+ 日期/哈希取最新。"""
    parts = version.split("-")
    major_minor = parts[0].split(".")
    rest = tuple(parts[1:]) if len(parts) > 1 else ()
    return (
        int(major_minor[0]),
        int(major_minor[1]),
    ) + rest


class AramkitCrawler:
    """用于从 aramkit.com 数据接口爬取 JSON 数据并保存到本地的爬虫类。"""

    def __init__(self, dataset: Optional[str] = None):
        """
        初始化爬虫

        Args:
            dataset: 数据集（"all" 全体 / "high" 高分段），为 None 时取配置
        """
        self.timeout = config.get("crawler", "timeout", default=30)
        self.delay_second = config.get("crawler", "delay_second", default=1)
        self.homepage_url = config.get("crawler", "aramkit", "homepage_url")
        self.data_base_url = config.get("crawler", "aramkit", "aram_augment", "data_base_url")
        self.dataset = dataset or config.get("crawler", "aramkit", "aram_augment", "dataset", default="all")
        self.save_directory = (
            config.data_path / Path(config.get("crawler", "aramkit", "aram_augment", "save_directory")) / self.dataset
        )
        self.resources_base_url = config.get("crawler", "aramkit", "resources", "resources_base_url")
        self.language = config.get("crawler", "aramkit", "resources", "language", default="zh-CN")
        self.resources_directory = config.data_path / Path(
            config.get("crawler", "aramkit", "resources", "save_directory")
        )
        self.version_file = config.data_path / "aramkit" / "version.json"
        self.session = requests.Session()

        # 设置请求头
        self.session.headers.update({"User-Agent": config.get("crawler", "user_agent")})

        # 创建保存目录
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.resources_directory.mkdir(parents=True, exist_ok=True)

        # 配置日志
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    @retry_on_exception(max_retries=3, delay=1.0, backoff_factor=2.0, exceptions=(requests.RequestException,))
    def fetch_json(self, url: str) -> Optional[Dict[Any, Any]]:
        """
        从指定URL获取JSON数据

        Args:
            url: 目标URL

        Returns:
            JSON响应数据，如果失败则返回None
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()  # 检查HTTP错误
            data = response.json()
            self.logger.info(f"成功从 {url} 获取JSON数据")
            return data
        except json.JSONDecodeError:
            self.logger.error(f"无法解析 {url} 的JSON数据")
            return None
        except Exception as e:
            self.logger.error(f"请求 {url} 时发生错误: {str(e)}")
            return None

    @retry_on_exception(max_retries=3, delay=1.0, backoff_factor=2.0, exceptions=(requests.RequestException,))
    def fetch_text(self, url: str) -> Optional[str]:
        """
        从指定URL获取文本内容（用于版本发现首页 HTML）

        Args:
            url: 目标URL

        Returns:
            文本内容，如果失败则返回None
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except Exception as e:
            self.logger.error(f"请求 {url} 时发生错误: {str(e)}")
            return None

    def save_to_file(
        self,
        data: Dict[Any, Any],
        filename: str,
        sub_directory: Optional[Path] = None,
        base_directory: Optional[Path] = None,
    ) -> bool:
        """
        将数据保存到本地JSON文件

        Args:
            data: 要保存的数据
            filename: 文件名
            sub_directory: 可选子目录（相对保存目录），如资源版本目录
            base_directory: 可选基准目录，覆盖默认的英雄数据保存目录（如资源目录）

        Returns:
            保存成功返回True，否则返回False
        """
        try:
            target_dir = (
                (base_directory or self.save_directory) / sub_directory
                if sub_directory
                else (base_directory or self.save_directory)
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            filepath = target_dir / f"{filename}.json"

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"数据已保存到 {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"保存文件时发生错误: {str(e)}")
            return False

    def crawl_and_save(self, url: str, filename: str) -> bool:
        """
        爬取URL数据并保存到本地

        Args:
            url: 目标URL
            filename: 保存的文件名（不包含.json后缀）

        Returns:
            成功返回True，否则返回False
        """
        self.logger.info(f"开始爬取数据: {url}")

        # 获取数据
        data = self.fetch_json(url)

        if data is not None:
            # 保存数据
            return self.save_to_file(data, filename)
        else:
            self.logger.error(f"未能从 {url} 获取有效数据")
            return False

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
                data_version = max(set(data_versions), key=_version_sort_key)
                resources_version = max(set(resources_versions), key=_version_sort_key)
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

    def batch_crawl(self, start_id=1, end_id=999) -> Dict[str, bool]:
        """
        批量爬取多个英雄数据

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            包含每个URL爬取结果的字典，键为英雄ID，值为爬取结果
        """
        self.logger.info(f"开始批量爬取英雄ID范围: {start_id} - {end_id}（数据集: {self.dataset}）")
        results = {}
        failed_ids = []
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

    def crawl(self, start_id=1, end_id=999) -> bool:
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
        return all(results.values())


if __name__ == "__main__":
    crawler = AramkitCrawler()
    crawler.crawl(1, 5)
