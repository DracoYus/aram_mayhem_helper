"""爬虫模块，用于从指定URL获取数据并保存为JSON格式到本地."""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.data import data


class AramAugmentCrawler:
    """用于从指定URL爬取JSON数据并保存到本地的爬虫类."""

    def __init__(self):
        """
        初始化爬虫

        Args:
            save_directory: 保存数据的目录，默认为'data'
        """
        self.timeout = config.get("crawler", "timeout", default=30)
        self.delay_second = config.get("crawler", "delay_second", default=1)
        self.save_directory = config.data_path / Path(config.get("crawler", "opgg", "aram_augment", "save_directory"))
        self.base_url = config.get("crawler", "opgg", "aram_augment", "base_url")
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
            return self.save_to_file(data, filename)
        else:
            self.logger.error(f"未能从 {url} 获取有效数据")
            return False

    def batch_crawl(self, start_id=1, end_id=999) -> Dict[str, bool]:
        """
        批量爬取多个URL

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            包含每个URL爬取结果的字典，键为英雄ID，值为爬取结果
        """
        self.logger.info(f"开始批量爬取英雄ID范围: {start_id} - {end_id}")
        results = {}
        failed_ids = []
        fail_count = 0

        all_champion_data = data.get_all_champion_data()
        chamoion_id_list = [int(champion["key"]) for champion in all_champion_data.values()]
        chamoion_id_list.sort()
        for chamoion_id in chamoion_id_list:
            if chamoion_id < start_id or chamoion_id > end_id:
                continue
            url = self.base_url.format(chamoion_id)
            filename = f"{chamoion_id}"
            results[filename] = self.crawl_and_save(url, filename)
            if not results[filename]:
                failed_ids.append(chamoion_id)
                fail_count += 1
            if fail_count >= 10:
                self.logger.warning(f"连续{fail_count}个英雄ID爬取失败，已停止爬取")
                break
            time.sleep(self.delay_second)
        self.logger.info(
            f"批量爬取完成，共成功 {len(results) - fail_count} 个英雄；共失败 {fail_count} 个英雄ID: {failed_ids}"
        )
        return results


if __name__ == "__main__":
    crawler = AramAugmentCrawler()
    crawler.batch_crawl(151, 999)
