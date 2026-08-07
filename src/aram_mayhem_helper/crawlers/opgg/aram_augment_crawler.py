"""OP.GG 英雄符文数据爬虫。"""

import logging
import time

from aram_mayhem_helper.crawlers.base import BaseCrawler
from aram_mayhem_helper.utils.config import AppConfig, get_config
from aram_mayhem_helper.utils.data import get_game_data


class AramAugmentCrawler(BaseCrawler):
    """从 OP.GG API 爬取各英雄的 aram-augments 数据。"""

    def __init__(self, config: AppConfig | None = None):
        """
        Args:
            config: 应用配置，None 时取全局配置
        """
        app_config = config or get_config()
        super().__init__(
            timeout=app_config.crawler.timeout,
            delay_second=app_config.crawler.delay_second,
            save_directory=app_config.opgg_augment_dir,
            base_url=app_config.crawler.opgg_augment.base_url,
            user_agent=app_config.crawler.user_agent,
        )
        self.logger = logging.getLogger(__name__)

    def batch_crawl(self, start_id: int = 1, end_id: int = 999) -> dict[str, bool]:
        """
        批量爬取多个英雄的符文数据。

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            包含每个英雄爬取结果的字典，键为英雄ID，值为爬取结果
        """
        self.logger.info(f"开始批量爬取英雄ID范围: {start_id} - {end_id}")
        results: dict[str, bool] = {}
        failed_ids: list[int] = []
        fail_count = 0

        champion_id_list = [int(champion_id) for champion_id in get_game_data().champion_ids()]
        for champion_id in champion_id_list:
            if champion_id < start_id or champion_id > end_id:
                continue
            url = self.base_url.format(champion_id)
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


if __name__ == "__main__":
    crawler = AramAugmentCrawler()
    crawler.batch_crawl(151, 999)
