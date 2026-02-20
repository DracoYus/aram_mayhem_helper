import logging

from aram_mayhem_helper.utils.config import config
from aram_mayhem_helper.utils.data import ChampionAugmentData, augment_tool
from aram_mayhem_helper.utils.norm import add_normalized_attr, add_weighted_sum_attr


class Suggest:
    immediate_select_weighted_sum_threshold = config.get("suggest", "immediate_select_weighted_sum_threshold")
    immediate_select_precentage_threshold = config.get("suggest", "immediate_select_precentage_threshold")
    consider_select_weighted_sum_threshold = config.get("suggest", "consider_select_weighted_sum_threshold")
    consider_select_precentage_threshold = config.get("suggest", "consider_select_precentage_threshold")

    def __init__(self, champion_augment_data: ChampionAugmentData):
        self.logger = logging.getLogger(__name__)

        raw_champion_augment_data = champion_augment_data.get_champion_augment_data()
        self.champion_augment_data = [
            item for item in raw_champion_augment_data if (item["performance"] != 170 and item["popular"] != 0)
        ]
        self.augment_group = {}
        for item in self.champion_augment_data:
            # 根据符文级别对符文进行分组
            augment_info = augment_tool.get_augment_info(str(item["id"]))
            level = augment_info["level"]
            item["level"] = level
            item["name"] = augment_info["name"]
            if level not in self.augment_group:
                self.augment_group[level] = {}
                self.augment_group[level]["augments"] = []
            self.augment_group[level]["augments"].append(item)
        for group_level, group_data in self.augment_group.items():
            grouped_augments = group_data["augments"]
            group_size = len(grouped_augments)
            group_data["number"] = len(group_data["augments"])
            add_normalized_attr(grouped_augments, "performance", "performance_norm", "min-max", True)
            add_normalized_attr(grouped_augments, "popular", "popular_norm", "min-max", False)
            add_weighted_sum_attr(grouped_augments, "performance_norm", "popular_norm", 0.7, 0.3, "weighted_sum")
            #  对每个组进行排序，统计名次
            sorted_group_data = sorted(grouped_augments, key=lambda x: x["weighted_sum"], reverse=True)
            group_data["augments"] = sorted_group_data
            for idx, item in enumerate(sorted_group_data):
                item["rank"] = idx + 1
                item["group_size"] = group_size

    def get_augment_info_by_id(self, augment_id: str) -> dict:
        """
        使用符文id查询对应符文信息

        Args:
            augment_id (str): 符文id

        Returns:
            dict: 符文信息
        """
        for item in self.champion_augment_data:
            if str(item["id"]) == augment_id:
                return item

    def suggest(self, augments: list[str]) -> list:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[str]): 输入符文信息

        Returns:
            list: 操作推荐
        """
        augment_ids = [augment_tool.get_augment_id(augment) for augment in augments]
        augment_info = [self.get_augment_info_by_id(augment_id) for augment_id in augment_ids]
        result = self.get_suggest_info(augment_info)
        return result

    def get_suggest_info(self, augments: list[str]) -> list:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[str]): 输入符文信息

        Returns:
            list: 操作推荐
        """
        augments_num = augments[0]["group_size"]
        immediate_select_rank_threshold = augments_num * Suggest.immediate_select_precentage_threshold
        consider_select_rank_threshold = augments_num * Suggest.consider_select_precentage_threshold
        sorted_augments = sorted(augments, key=lambda x: x["weighted_sum"], reverse=True)
        result = []
        for idx, augment in enumerate(sorted_augments):
            if (
                augment["rank"] <= immediate_select_rank_threshold
                or augment["weighted_sum"] >= Suggest.immediate_select_weighted_sum_threshold
            ):
                result.append(f"快选符文：{augment['name']}，别的不用看了, {augment['rank']} / {augments_num}")
                continue
            if (
                augment["rank"] <= consider_select_rank_threshold
                or augment["weighted_sum"] >= Suggest.consider_select_weighted_sum_threshold
            ):
                if idx == 0:
                    result.append(f"考虑符文：{augment['name']}，暂时先别换{augment['rank']} / {augments_num}")
                    continue
                else:
                    result.append(f"考虑符文：{augment['name']}，可以随掉，{augment['rank']} / {augments_num}")
                    continue
            result.append(f"垃圾符文: {augment['name']}，别选，太垃圾了，{augment['rank']} / {augments_num}")

        return result


if __name__ == "__main__":
    # all_champion_data = data.get_all_champion_data()
    # chamoion_id_list = [int(champion["key"]) for champion in all_champion_data.values()]
    # chamoion_id_list.sort()
    # for champion_id in chamoion_id_list:
    #     champion_augment_data = ChampionAugmentData(champion_id)
    #     suggest = Suggest(champion_augment_data)
    #     suggest.suggest(["老练狙神", "红包", "吞噬灵魂"])
    champion_augment_data = ChampionAugmentData(99)
    suggest = Suggest(champion_augment_data)
    suggests = suggest.suggest(["老练狙神", "红包", "吞噬灵魂"])
    print(suggests)
