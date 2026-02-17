"""爬虫模块，用于从指定URL获取数据并保存为JSON格式到本地."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from aram_mayhem_helper.utils.config import config


class ChampionCrawler:
    """用于从指定URL爬取JSON数据并保存到本地的爬虫类."""

    def __init__(self):
        """
        初始化爬虫

        Args:
            save_directory: 保存数据的目录，默认为'data'
        """
        self.timeout = config.get("crawler", "timeout", 30)
        self.delay_second = config.get("crawler", "delay_second", 1)
        self.save_directory = config.data_path / Path(config.get("crawler", "ddragon", "champion", "save_directory"))
        self.base_url = config.get("crawler", "ddragon", "champion", "base_url")
        # self.game_version = config.get("crawler", "ddragon", "champion", "game_version")
        self.session = requests.Session()

        # 设置请求头
        self.session.headers.update({"User-Agent": config.get("crawler", "user_agent")})

        # 创建保存目录
        self.save_directory.mkdir(parents=True, exist_ok=True)

        # 配置日志
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def fetch_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[Any, Any]]:
        """
        从指定URL获取JSON数据

        Args:
            url: 目标URL
            params: 请求参数

        Returns:
            JSON响应数据，如果失败则返回None
        """
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()  # 检查HTTP错误

            # 尝试解析JSON
            data = response.json()
            self.logger.info(f"成功从 {url} 获取JSON数据")
            return data
        except json.JSONDecodeError:
            self.logger.error(f"无法解析 {url} 的JSON数据")
            return None
        except Exception as e:
            self.logger.error(f"请求 {url} 时发生错误: {str(e)}")
            return None

    def save_to_file(self, data: Dict[Any, Any], filename: str) -> bool:
        """
        将数据保存到本地JSON文件

        Args:
            data: 要保存的数据
            filename: 文件名

        Returns:
            保存成功返回True，否则返回False
        """
        try:
            filepath = self.save_directory / f"{filename}.json"

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"数据已保存到 {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"保存文件时发生错误: {str(e)}")
            return False

    def crawl_and_save(self, url: str, filename: str, params: Optional[Dict[str, Any]] = None) -> bool:
        """
        爬取URL数据并保存到本地

        Args:
            url: 目标URL
            filename: 保存的文件名（不包含.json后缀）
            params: 请求参数

        Returns:
            成功返回True，否则返回False
        """
        self.logger.info(f"开始爬取数据: {url}")

        # 获取数据
        data = self.fetch_json(url, params)

        if data is not None:
            # 保存数据
            self.save_to_file(data, filename)
        else:
            self.logger.error(f"未能从 {url} 获取有效数据")
        return data

    def get_latest_ddragon_version(self) -> str:
        url = "https://ddragon.leagueoflegends.com/api/versions.json"
        response = requests.get(url)
        versions = response.json()
        return versions[0]  # 第一个元素是最新版本

    def batch_crawl(self) -> Dict[str, bool]:
        """
        批量爬取多个URL

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            包含每个URL爬取结果的字典，键为英雄ID，值为爬取结果
        """
        self.logger.info("开始批量爬取英雄ID数据")

        self.game_version = self.get_latest_ddragon_version()
        url = self.base_url.format(self.game_version)
        filename = f"{self.game_version}"
        results = self.crawl_and_save(url, filename)

        return results


if __name__ == "__main__":
    crawler = ChampionCrawler()
    crawler.batch_crawl()
