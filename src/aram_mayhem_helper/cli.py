import argparse
import logging

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import ocr_tool
from aram_mayhem_helper.utils.data import champion_augment_data_dict, data
from aram_mayhem_helper.utils.log_config import setup_logging

logger = logging.getLogger(__name__)


def aram_augment_crawler(start_page: int = 1, end_page: int = 999) -> None:
    """
    爬取英雄符文数据入口
    """
    logger.info(f"开始爬取英雄符文数据，从第{start_page}页到第{end_page}页")
    crawler = AramAugmentCrawler()
    crawler.batch_crawl(start_page, end_page)
    logger.info("英雄符文数据爬取完成")


def champion_crawler() -> None:
    """
    爬取英雄数据入口
    """
    logger.info("开始爬取英雄数据")
    crawler = ChampionCrawler()
    crawler.batch_crawl()
    logger.info("英雄数据爬取完成")


def main() -> None:
    """
    程序主入口，截图并推荐
    """
    logger.info("开始执行主程序")
    champion_name = get_current_champion_name()
    if not champion_name:
        logger.error("无法获取当前英雄名称")
        return

    champion_id = data.get_champion_id_by_name(champion_name)
    if not champion_id:
        logger.error(f"无法找到英雄名称 '{champion_name}' 对应的ID")
        return

    if champion_id not in champion_augment_data_dict:
        logger.error(f"英雄ID {champion_id} 的符文数据不存在")
        return

    champion_augment_data = champion_augment_data_dict[champion_id]
    suggest = Suggest(champion_augment_data)
    arguments = ocr_tool.get_augments()
    suggest.suggest(arguments)
    logger.info("主程序执行完成")


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数
    """
    parser = argparse.ArgumentParser(description="ARAM Mayhem Helper 命令行工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # aram_augment_crawler 命令
    aram_augment_parser = subparsers.add_parser("aram-augment-crawler", help="爬取英雄符文数据")
    aram_augment_parser.add_argument("--start-page", type=int, default=1, help="开始页码，默认1")
    aram_augment_parser.add_argument("--end-page", type=int, default=999, help="结束页码，默认999")

    # champion_crawler 命令
    subparsers.add_parser("champion-crawler", help="爬取英雄数据")

    # main 命令
    subparsers.add_parser("main", help="执行主程序，截图并推荐")

    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()
    args = parse_args()

    if args.command == "aram-augment-crawler":
        aram_augment_crawler(args.start_page, args.end_page)
    elif args.command == "champion-crawler":
        champion_crawler()
    elif args.command == "main":
        main()
    else:
        logger.error("请指定要执行的命令")
        print("使用方法:")
        print("  python -m aram_mayhem_helper.cli aram-augment-crawler [--start-page START_PAGE] [--end-page END_PAGE]")
        print("  python -m aram_mayhem_helper.cli champion-crawler")
        print("  python -m aram_mayhem_helper.cli main")
