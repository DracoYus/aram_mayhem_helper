import argparse
import logging

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.crawlers.aramkit.aramkit_crawler import AramkitCrawler
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import ocr_tool
from aram_mayhem_helper.utils.config import get_config
from aram_mayhem_helper.utils.data import get_game_data
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
    crawler.crawl()
    logger.info("英雄数据爬取完成")


def aramkit_crawler(start_id: int = 1, end_id: int = 999, dataset: str | None = None) -> None:
    """
    爬取 aramkit.com 英雄符文数据入口

    Args:
        start_id: 起始英雄ID
        end_id: 结束英雄ID
        dataset: 数据集（all 全体 / high 高分段），None 时取配置
    """
    logger.info(f"开始爬取 aramkit.com 英雄符文数据，从第{start_id}个到第{end_id}个英雄")
    crawler = AramkitCrawler(dataset=dataset)
    crawler.crawl(start_id, end_id)
    logger.info("aramkit.com 英雄符文数据爬取完成")


def main() -> None:
    """
    程序主入口，截图并推荐
    """
    logger.info("开始执行主程序")
    champion_name = get_current_champion_name()
    if not champion_name:
        logger.error("无法获取当前英雄名称")
        return

    game_data = get_game_data()
    champion_id = game_data.champion_id_by_name(champion_name)
    if not champion_id:
        logger.error(f"无法找到英雄名称 '{champion_name}' 对应的ID")
        return

    if game_data.augment_entries(champion_id) is None:
        logger.error(f"英雄ID {champion_id} 的符文数据不存在")
        return

    suggest = Suggest(champion_id, game_data, thresholds=get_config().suggest)
    arguments = ocr_tool.get_augments()
    results = suggest.suggest(arguments)
    if results:
        for result in results:
            print(result)
            logger.info(result)
    else:
        logger.warning("未能生成任何符文建议")
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

    # aramkit_crawler 命令
    aramkit_parser = subparsers.add_parser("aramkit-crawler", help="爬取 aramkit.com 英雄符文数据")
    aramkit_parser.add_argument("--start-id", type=int, default=1, help="起始英雄ID，默认1")
    aramkit_parser.add_argument("--end-id", type=int, default=999, help="结束英雄ID，默认999")
    aramkit_parser.add_argument(
        "--dataset", type=str, choices=["all", "high"], default=None, help="数据集: all(全体)/high(高分段)，默认取配置"
    )

    # main 命令
    subparsers.add_parser("main", help="执行主程序，截图并推荐")

    # web 命令
    web_parser = subparsers.add_parser("web", help="启动网页应用，浏览符文数据")
    web_parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    web_parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")

    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()
    args = parse_args()

    if args.command == "aram-augment-crawler":
        aram_augment_crawler(args.start_page, args.end_page)
    elif args.command == "champion-crawler":
        champion_crawler()
    elif args.command == "aramkit-crawler":
        aramkit_crawler(args.start_id, args.end_id, args.dataset)
    elif args.command == "main":
        main()
    elif args.command == "web":
        from aram_mayhem_helper.web import app

        logger.info(f"启动网页应用 at http://{args.host}:{args.port}")
        app.run(host=args.host, port=args.port, debug=False)
    else:
        logger.error("请指定要执行的命令")
        print("使用方法:")
        print("  python -m aram_mayhem_helper.cli aram-augment-crawler [--start-page START_PAGE] [--end-page END_PAGE]")
        print("  python -m aram_mayhem_helper.cli champion-crawler")
        print("  python -m aram_mayhem_helper.cli aramkit-crawler [--start-id START_ID] [--end-id END_ID]")
        print("                             [--dataset all|high]")
        print("  python -m aram_mayhem_helper.cli main")
        print("  python -m aram_mayhem_helper.cli web [--host HOST] [--port PORT]")
