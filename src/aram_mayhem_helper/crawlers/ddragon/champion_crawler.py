"""Data Dragon 英雄数据爬虫。"""

import logging

import requests

from aram_mayhem_helper.crawlers.base import BaseCrawler
from aram_mayhem_helper.utils.config import AppConfig, get_config

DDragon_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"


class ChampionCrawler(BaseCrawler):
    """获取最新版本的英雄数据并保存到本地。"""

    def __init__(self, config: AppConfig | None = None):
        """
        Args:
            config: 应用配置，None 时取全局配置
        """
        app_config = config or get_config()
        super().__init__(
            timeout=app_config.crawler.timeout,
            delay_second=app_config.crawler.delay_second,
            save_directory=app_config.champion_dir,
            base_url=app_config.crawler.ddragon_champion.base_url,
            user_agent=app_config.crawler.user_agent,
        )
        self.logger = logging.getLogger(__name__)

    def get_latest_ddragon_version(self) -> str:
        """获取 Data Dragon 最新版本号（versions API 首元素）。"""
        response = requests.get(DDragon_VERSIONS_URL)
        versions = response.json()
        return str(versions[0])

    def crawl(self) -> bool:
        """获取最新版本的英雄数据并保存到本地。

        Returns:
            成功返回 ``True``，否则返回 ``False``。
        """
        self.logger.info("开始爬取英雄数据")
        game_version = self.get_latest_ddragon_version()
        url = self.base_url.format(game_version)
        filename = f"{game_version}"
        return self.crawl_and_save(url, filename)


if __name__ == "__main__":
    crawler = ChampionCrawler()
    crawler.crawl()
