from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import ocr_tool
from aram_mayhem_helper.utils.data import champion_augment_data_dict, data
from aram_mayhem_helper.utils.log_config import setup_logging


def aram_augment_crawler() -> None:
    """
    爬取英雄符文数据入口
    """
    crawler = AramAugmentCrawler()
    crawler.batch_crawl(0, 999)


def chamipon_crawler() -> None:
    """
    爬取英雄数据入口
    """
    crawler = ChampionCrawler()
    crawler.batch_crawl()


def main() -> None:
    """
    程序主入口，截图并推荐
    """
    champion_name = get_current_champion_name()
    champion_id = data.get_champion_id_by_name(champion_name)
    champion_augment_data = champion_augment_data_dict[champion_id]
    suggest = Suggest(champion_augment_data)
    arguments = ocr_tool.get_augments()
    suggest.suggest(arguments)


if __name__ == "__main__":
    setup_logging()
    main()
    # aram_augment_crawler()
