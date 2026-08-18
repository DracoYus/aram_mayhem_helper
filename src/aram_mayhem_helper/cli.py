import argparse
import logging

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.crawlers.aramkit.aramkit_crawler import AramkitCrawler
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import get_ocr_tool, save_unrecognized_capture
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


def recommend() -> None:
    """
    截图并推荐（OCR 识别当前对局符文）
    """
    logger.info("开始执行主程序")
    try:
        champion_name = get_current_champion_name()
        if not champion_name:
            logger.error("无法获取当前英雄名称")
            return

        game_data = get_game_data()
        champion_id = game_data.champion_id_by_name(champion_name)
        if not champion_id:
            logger.error(f"无法找到英雄名称 '{champion_name}' 对应的ID")
            return

        source = game_data.available_source(champion_id)
        if source is None:
            logger.error(f"英雄ID {champion_id} ({champion_name}) 在 opgg/aramkit 数据源中都没有符文数据")
            return

        suggest = Suggest(champion_id, game_data, source=source, thresholds=get_config().suggest)
        arguments = get_ocr_tool().get_augments()
        results = suggest.suggest(arguments, on_unrecognized=save_unrecognized_capture)
        if results:
            for result in results:
                print(result)
                logger.info(result)
        else:
            logger.warning("未能生成任何符文建议")
        logger.info("主程序执行完成")
    except Exception as e:
        logger.error(f"推荐流程执行出错: {e}")
        return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    解析命令行参数

    Args:
        argv: 参数列表，None 时取 sys.argv[1:]
    """
    parser = argparse.ArgumentParser(description="ARAM Mayhem Helper 命令行工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # recommend 命令（main 为兼容别名）
    subparsers.add_parser("recommend", aliases=["main"], help="截图识别当前对局符文并给出推荐")

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

    # web 命令
    web_parser = subparsers.add_parser("web", help="启动网页应用，浏览符文数据")
    web_parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    web_parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")

    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    """CLI 分发入口（console script 指向此函数，替代旧的 __main__ 块）。

    Args:
        argv: 参数列表，None 时取 sys.argv[1:]

    Returns:
        退出码（0 成功；无命令且推荐失败时 1）
    """
    setup_logging()
    args = parse_args(argv)

    if args.command in (None, "recommend", "main"):
        # 无子命令时默认执行推荐（兼容旧 console script 直接调用的行为）
        recommend()
    elif args.command == "aram-augment-crawler":
        aram_augment_crawler(args.start_page, args.end_page)
    elif args.command == "champion-crawler":
        champion_crawler()
    elif args.command == "aramkit-crawler":
        aramkit_crawler(args.start_id, args.end_id, args.dataset)
    elif args.command == "web":
        from aram_mayhem_helper.web import create_app

        logger.info(f"启动网页应用 at http://{args.host}:{args.port}")
        create_app().run(host=args.host, port=args.port, debug=False)
    else:
        logger.error("请指定要执行的命令")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
