"""aramkit.com 数据爬虫。

数据版本号（如 ``16.15-20260805-7e30d3443ba1``）内嵌在首页 HTML 中，无 versions API，
通过正则提取并按游戏版本号取最新。

版本状态（version.json 的读取/写入、断点续爬进度、跳过判断）由
``version_state.VersionState`` 负责；本类只保留 HTTP 爬取与文件保存逻辑。
"""

import logging
import re
from pathlib import Path

from aram_mayhem_helper.crawlers.aramkit.version_state import VersionState
from aram_mayhem_helper.crawlers.base import BaseCrawler
from aram_mayhem_helper.utils.aramkit import version_sort_key
from aram_mayhem_helper.utils.config import AppConfig, get_config
from aram_mayhem_helper.utils.data import get_game_data
from aram_mayhem_helper.utils.update_check import UpdateState, UpdateStatus

# 数据版本: 16.15-20260805-7e30d3443ba1（游戏版本-日期-哈希）
DATA_VERSION_RE = re.compile(r"\d+\.\d+-\d{8}-[a-f0-9]{12}")
# 资源版本: 16.15-459bb2367aac（游戏版本-哈希）
# 两者互斥：数据版本横杠后是 8 位日期段（凑不满 12 位哈希），资源版本横杠后
# 直接是 12 位十六进制哈希，不会交叉误匹配
RESOURCES_VERSION_RE = re.compile(r"\d+\.\d+-[a-f0-9]{12}")


class AramkitCrawler(BaseCrawler):
    """从 aramkit.com 数据接口爬取英雄数据并保存到本地。

    Args:
        dataset: 数据集（"all" 全体 / "high" 高分段），None 时取配置
        config: 应用配置，None 时取全局配置
    """

    def __init__(self, dataset: str | None = None, config: AppConfig | None = None):
        app_config = config or get_config()
        dataset = dataset or app_config.crawler.aramkit.augment.dataset
        super().__init__(
            timeout=app_config.crawler.timeout,
            delay_second=app_config.crawler.delay_second,
            save_directory=app_config.aramkit_augment_dir,
            user_agent=app_config.crawler.user_agent,
        )
        self.dataset = dataset
        self.homepage_url = app_config.crawler.aramkit.homepage_url
        self.data_base_url = app_config.crawler.aramkit.augment.data_base_url
        self.resources_base_url = app_config.crawler.aramkit.resources.resources_base_url
        self.language = app_config.crawler.aramkit.resources.language
        self.resources_directory = app_config.aramkit_resources_dir
        self.version_file = app_config.data_dir / "aramkit" / "version.json"
        self.resources_directory.mkdir(parents=True, exist_ok=True)
        self.data_version = ""
        self.resources_version = ""
        self._resume_completed_ids: set[int] | None = None
        self._state = VersionState(self.version_file, self.dataset, logging.getLogger(__name__))
        self.logger = logging.getLogger(__name__)

    def fetch_text(self, url: str) -> str | None:
        """
        从指定URL获取文本内容（用于版本发现首页 HTML）

        Args:
            url: 目标URL

        Returns:
            文本内容，如果失败则返回None
        """
        try:
            response = self._request(url)
            return str(response.text)
        except Exception as e:
            self.logger.error(f"请求 {url} 时发生错误: {str(e)}")
            return None

    def fetch_remote_versions(self) -> tuple[str, str] | None:
        """从首页 HTML 解析最新数据/资源版本号（纯读取，不写 version.json）。

        供 ``discover_versions``（爬取前写盘）与 ``check_update``（只读比较）
        共用；首页抓取失败或未发现完整版本信息时返回 None。

        Returns:
            (data_version, resources_version) 元组，失败时 None
        """
        html = self.fetch_text(self.homepage_url)
        if html is None:
            return None
        data_versions = DATA_VERSION_RE.findall(html)
        resources_versions = RESOURCES_VERSION_RE.findall(html)
        if not (data_versions and resources_versions):
            self.logger.warning(
                f"首页未发现完整版本信息: data={len(data_versions)}, resources={len(resources_versions)}"
            )
            return None
        data_version = max(set(data_versions), key=version_sort_key)
        resources_version = max(set(resources_versions), key=version_sort_key)
        self.logger.info(f"从首页发现版本: data={data_version}, resources={resources_version}")
        return data_version, resources_version

    def discover_versions(self) -> tuple[str, str]:
        """
        从首页 HTML 中发现最新数据/资源版本号，并写入 version.json。

        无 versions API，版本串内嵌在首页中（新旧版本并存），
        按 (major, minor, 日期/哈希) 取最大；抓取失败时回退本地缓存。

        Returns:
            (data_version, resources_version) 元组
        """
        remote = self.fetch_remote_versions()
        if remote is not None:
            data_version, resources_version = remote
            self._state.save(data_version, resources_version)
            return data_version, resources_version

        # 回退本地缓存
        cached = self._state.read()
        if cached:
            fallback_data = cached.get("data_version")
            fallback_resources = cached.get("resources_version")
            if fallback_data and fallback_resources:
                self.logger.info(f"使用本地缓存的版本: data={fallback_data}, resources={fallback_resources}")
                return str(fallback_data), str(fallback_resources)
        raise RuntimeError("无法发现 aramkit 数据版本（首页抓取失败且无本地缓存）")

    def check_update(self) -> UpdateStatus:
        """只读更新检查：比较首页最新数据版本与本地 version.json 记录。

        不写任何状态文件（区别于 ``discover_versions``），首页抓取失败时
        返回 unknown，绝不误报"已是最新"。

        Returns:
            检查结果（见 :class:`UpdateStatus`）
        """
        remote = self.fetch_remote_versions()
        if remote is None:
            return UpdateStatus(source="aramkit", state="unknown", error="无法获取远端版本")
        remote_version = remote[0]
        cached = self._state.read()
        local_version = cached.get("data_version") if cached else None
        if not local_version:
            return UpdateStatus(source="aramkit", state="no_local_data", remote_version=remote_version)
        state: UpdateState = "update_available"
        if local_version == remote_version:
            state = "up_to_date"
        return UpdateStatus(source="aramkit", state=state, local_version=local_version, remote_version=remote_version)

    def _resources_exist(self, resources_version: str) -> bool:
        """
        判断指定资源版本的资源文件是否已完整存在于本地

        Args:
            resources_version: 资源版本号

        Returns:
            augments.json 与 champions.json 均存在返回 True
        """
        version_dir = self.resources_directory / resources_version
        return all((version_dir / f"{name}.json").exists() for name in ("augments", "champions"))

    def fetch_resources(self, resources_version: str) -> bool:
        """
        拉取 aramkit 资源文件（augments.json / champions.json）。

        Args:
            resources_version: 资源版本号

        Returns:
            两个资源文件均成功保存返回 True，否则返回 False
        """
        base_url = f"{self.resources_base_url}{resources_version}/{self.language}/resources/"
        success = True
        for resource_name in ("augments", "champions"):
            url = f"{base_url}{resource_name}.json"
            self.logger.info(f"开始爬取资源文件: {url}")
            data = self.fetch_json(url)
            if data is None:
                success = False
                continue
            saved = self.save_to_file(
                data,
                resource_name,
                sub_directory=Path(resources_version),
                base_directory=self.resources_directory,
            )
            success = success and saved
        return success and self._resources_exist(resources_version)

    def _champion_ids_in_range(self, start_id: int, end_id: int) -> list[int]:
        """
        获取本地英雄元数据中位于指定范围内的全部英雄ID

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            英雄ID列表
        """
        champion_id_list = [int(champion_id) for champion_id in get_game_data().champion_ids()]
        return [champion_id for champion_id in champion_id_list if start_id <= champion_id <= end_id]

    def batch_crawl(self, start_id: int = 1, end_id: int = 999) -> dict[str, bool]:
        """
        批量爬取多个英雄数据

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID

        Returns:
            包含每个URL爬取结果的字典，键为英雄ID，值为爬取结果
        """
        self.logger.info(f"开始批量爬取英雄ID范围: {start_id} - {end_id}（数据集: {self.dataset}）")
        completed_ids = set(self._resume_completed_ids or ())
        should_persist_progress = self._resume_completed_ids is not None
        champion_ids = self._champion_ids_in_range(start_id, end_id)
        # 断点续爬：已完成的英雄不再请求，但结果计为 True（crawl 依赖
        # all(results.values()) 判断全量成功并写入 crawled 完整标记）
        pending: list[int] = []
        for champion_id in champion_ids:
            if champion_id in completed_ids:
                self.logger.info(f"英雄ID {champion_id} 已完成，跳过爬取")
            else:
                pending.append(champion_id)

        def _on_success(champion_id: int) -> None:
            if should_persist_progress:
                completed_ids.add(champion_id)
                self._state.save_progress(self.data_version, self.resources_version, start_id, end_id, completed_ids)

        results = self.batch_crawl_ids(
            pending,
            url_for=lambda champion_id: (
                f"{self.data_base_url}{self.data_version}/stats/{self.dataset}/champion-details/{champion_id}.json"
            ),
            on_success=_on_success,
        )
        for champion_id in champion_ids:
            if champion_id in completed_ids:
                results[str(champion_id)] = True
        return results

    def crawl(self, start_id: int = 1, end_id: int = 999, *, force: bool = False) -> bool:
        """
        完整爬取流程：版本发现 → 更新检查 → 资源文件 → 批量英雄数据

        服务器数据版本与本地一致且已有同范围完整爬取记录时跳过英雄数据爬取；
        存在同范围进行中进度时恢复爬取并跳过已完成英雄；资源文件按本地是否已存在判断是否跳过。

        Args:
            start_id: 起始英雄ID
            end_id: 结束英雄ID
            force: 忽略更新检查，强制全量爬取

        Returns:
            全部成功（含跳过）返回True，存在失败返回False
        """
        previous = self._state.read()
        data_version, resources_version = self.discover_versions()
        self.data_version = data_version
        self.resources_version = resources_version
        has_progress = self._state.completed_ids_for(previous, data_version, start_id, end_id) is not None
        stats_up_to_date = (
            not force and not has_progress and self._state.stats_up_to_date(previous, data_version, start_id, end_id)
        )

        if self._resources_exist(resources_version):
            self.logger.info(f"资源文件已存在（{resources_version}），跳过下载")
        elif not self.fetch_resources(resources_version):
            self.logger.error(f"资源文件下载不完整（{resources_version}），终止本次爬取")
            return False

        if stats_up_to_date:
            self.logger.info(f"服务器数据无更新（{data_version}），跳过英雄数据爬取")
            return True

        self._resume_completed_ids = self._state.prepare_progress(
            data_version, resources_version, start_id, end_id, reset=force
        )
        try:
            results = self.batch_crawl(start_id, end_id)
        finally:
            self._resume_completed_ids = None
        if results and all(results.values()):
            self._state.record_crawled(data_version, resources_version, start_id, end_id)
        # 空结果（如英雄数据尚未抓取）不算成功：all({}) 恒为 True 会误报
        return bool(results) and all(results.values())


if __name__ == "__main__":
    crawler = AramkitCrawler()
    crawler.crawl(1, 5)
