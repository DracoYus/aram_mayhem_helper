import requests
import urllib3

# 禁用 SSL 警告（游戏客户端用自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_current_champion_name():
    """
    获取正在运行的对局中自己的英雄 ID 和名称
    :return: champion_name 或 None
    """
    # Live Client Data API 地址（固定端口 2999）
    base_url = "https://127.0.0.1:2999/liveclientdata/allgamedata"

    try:
        # 1. 获取当前活跃玩家数据
        active_player_resp = requests.get(
            base_url,
            verify=False,  # 忽略证书验证
            timeout=2,
        )
        active_player_resp.raise_for_status()  # 检查请求是否成功
        all_data = active_player_resp.json()

        # 2. 提取用户riotId（召唤师名称）
        riotId = all_data.get("activePlayer").get("riotId")
        if not riotId:
            print("未获取到riotId")
            return None

        raw_champion_name = None
        # 3.找到自己的英雄名称（通过 summonerName 匹配）
        all_players = all_data.get("allPlayers")
        for player in all_players:
            if player.get("riotId") == riotId:
                raw_champion_name = player.get("rawChampionName")
                break

        champion_name = raw_champion_name and raw_champion_name.split("_")[-1]
        return champion_name

    except requests.exceptions.ConnectionError:
        print("无法连接到游戏客户端，请确保：\n1. 已进入对局\n2. 已开启“允许第三方应用访问游戏数据”")
        return None
    except Exception as e:
        print(f"获取数据失败: {str(e)}")
        return None


# ================= 调用示例 =================
if __name__ == "__main__":
    champ_name = get_current_champion_name()
    print(f"当前英雄名称: {champ_name}")
