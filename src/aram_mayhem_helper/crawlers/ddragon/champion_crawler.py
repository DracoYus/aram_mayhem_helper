"""Data Dragon 英雄数据爬虫。"""

import logging

import requests

from aram_mayhem_helper.crawlers.base import BaseCrawler
from aram_mayhem_helper.utils.config import AppConfig, get_config
from aram_mayhem_helper.utils.version import latest_version

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
        """从 Data Dragon versions API 获取语义版本号最高的版本。"""
        response = self._request(DDragon_VERSIONS_URL)
        try:
            payload = response.json()
        except ValueError as e:
            raise ValueError("Data Dragon 版本接口返回的 JSON 无法解析") from e
        if not isinstance(payload, list):
            raise ValueError("Data Dragon 版本接口返回格式错误")

        versions = [version for version in payload if isinstance(version, str)]
        latest = latest_version(versions)
        if latest is None:
            raise ValueError("Data Dragon 版本接口未返回有效版本号")
        return latest

    def crawl(self) -> bool:
        """获取最新版本的英雄数据并保存到本地。

        Returns:
            成功返回 ``True``，否则返回 ``False``。
        """
        self.logger.info("开始爬取英雄数据")
        try:
            game_version = self.get_latest_ddragon_version()
        except (requests.RequestException, ValueError) as e:
            self.logger.error(f"获取 Data Dragon 版本失败: {str(e)}")
            return False
        url = self.base_url.format(game_version)
        filename = f"{game_version}"
        return self.crawl_and_save(url, filename)


if __name__ == "__main__":
    crawler = ChampionCrawler()
    crawler.crawl()
