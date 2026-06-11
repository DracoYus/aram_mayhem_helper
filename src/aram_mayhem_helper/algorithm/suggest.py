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
        filtered_data = []
        for item in raw_champion_augment_data:
            perf = item.get("performance")
            pop = item.get("popular")
            if perf is None or pop is None:
                self.logger.warning(
                    f"英雄id:{champion_augment_data.champion_id}，符文数据项缺少 performance/popular 字段: {item}"
                )
                continue
            if perf == 170 and pop == 0:
                continue
            filtered_data.append(item)
        self.champion_augment_data = filtered_data
        self.augment_group = {}
        for item in self.champion_augment_data:
            # 根据符文级别对符文进行分组
            item_id = item.get("id")
            if item_id is None:
                self.logger.warning(f"英雄id:{champion_augment_data.champion_id}，符文数据项缺少 'id' 字段: {item}")
                continue
            augment_info = augment_tool.get_augment_info(str(item_id))
            if not augment_info:
                self.logger.warning(
                    f"英雄id:{champion_augment_data.champion_id}，翻译文件中未找到符文 ID {item_id} 的翻译: {item}"
                )
                continue
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

    def get_augment_info_by_id(self, augment_id: str) -> dict | None:
        """
        使用符文id查询对应符文信息

        Args:
            augment_id (str): 符文id

        Returns:
            dict | None: 符文信息，未找到时返回 None
        """
        if not augment_id:
            return None
        for item in self.champion_augment_data:
            item_id = item.get("id")
            if item_id is not None and str(item_id) == augment_id:
                return item
        return None

    def suggest(self, augments: list[str]) -> list:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[str]): 输入符文信息

        Returns:
            list: 操作推荐
        """
        augment_info = []
        for augment in augments:
            augment_id = augment_tool.get_augment_id(augment)
            if not augment_id:
                self.logger.warning(f"无法识别符文名称 '{augment}'，翻译文件中未找到匹配")
                continue
            info = self.get_augment_info_by_id(augment_id)
            if not info:
                self.logger.warning(f"符文 ID {augment_id} (OCR名称: '{augment}') 在当前英雄数据中未找到")
                continue
            augment_info.append(info)
        if not augment_info:
            self.logger.warning("没有有效的符文信息可供建议")
            return []
        result = self.get_suggest_info(augment_info)
        return result

    def get_suggest_info(self, augments: list[dict]) -> list:
        """
        根据输入符文信息，给出操作推荐

        Args:
            augments (list[dict]): 输入符文信息

        Returns:
            list: 操作推荐
        """
        if not augments:
            return []
        first = augments[0]
        if first is None:
            self.logger.warning("符文信息列表首元素为 None，无法生成建议")
            return []
        augments_num = first.get("group_size")
        if augments_num is None:
            self.logger.warning("符文数据缺少 'group_size' 字段，无法生成建议")
            return []
        immediate_select_rank_threshold = augments_num * Suggest.immediate_select_precentage_threshold
        consider_select_rank_threshold = augments_num * Suggest.consider_select_precentage_threshold
        max_weighted_sum = max(item.get("weighted_sum", 0) for item in augments if item is not None)
        result = []
        for augment in augments:
            if augment is None:
                continue
            name = augment.get("name", "未知")
            rank = augment.get("rank", augments_num)
            ws = augment.get("weighted_sum", 0)
            perf_norm = augment.get("performance_norm", "N/A")
            pop_norm = augment.get("popular_norm", "N/A")
            message = None
            if rank <= immediate_select_rank_threshold or ws >= Suggest.immediate_select_weighted_sum_threshold:
                message = f"快选符文：{name}，别的不用看了"
            elif rank <= consider_select_rank_threshold or ws >= Suggest.consider_select_weighted_sum_threshold:
                if max_weighted_sum == ws:
                    message = f"考虑符文：{name}，暂时先别换"
                else:
                    message = f"考虑符文：{name}，可以随掉"
            else:
                message = f"垃圾符文: {name}，别选，太垃圾了"
            message += f"，{rank}/{augments_num}，表现: {perf_norm}，流行度: {pop_norm}"
            result.append(message)

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
