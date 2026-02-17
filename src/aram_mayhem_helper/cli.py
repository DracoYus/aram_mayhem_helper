from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler


def aram_augment_crawler() -> None:
    crawler = AramAugmentCrawler()
    crawler.batch_crawl(1, 151)


def chamipon_crawler() -> None:
    crawler = ChampionCrawler()
    crawler.batch_crawl()


if __name__ == "__main__":
    aram_augment_crawler()
