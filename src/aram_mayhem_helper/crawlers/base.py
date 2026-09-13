"""爬虫基类：共享 HTTP 会话、JSON 拉取与本地保存样板（消除三爬虫的复制粘贴）。"""

import json
import logging
import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import requests

from aram_mayhem_helper.utils.retry import retry_on_exception

# 批量爬取时连续失败的最大英雄数（达到即中止，避免盲目请求）
MAX_CONSECUTIVE_FAILURES = 10


class BaseCrawler:
    """共享爬虫样板：会话、JSON 拉取、文件保存。

    Args:
        timeout: 请求超时（秒）
        delay_second: 批量爬取间隔（秒）
        save_directory: 默认保存目录
        base_url: URL 模板（子类可自行管理 URL）
        user_agent: 请求 UA
    """

    def __init__(
        self,
        *,
        timeout: int,
        delay_second: float,
        save_directory: Path,
        base_url: str = "",
        user_agent: str = "",
    ) -> None:
        self.timeout = timeout
        self.delay_second = delay_second
        self.save_directory = save_directory
        self.base_url = base_url
        self.session = requests.Session()
        if user_agent:
            self.session.headers.update({"User-Agent": user_agent})
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    @retry_on_exception(max_retries=3, delay=1.0, backoff_factor=2.0, exceptions=(requests.RequestException,))
    def _request(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        """发送 HTTP 请求；请求异常交由重试装饰器处理。"""
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response

    def fetch_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """从指定 URL 获取 JSON 数据，失败返回 None。"""
        try:
            response = self._request(url, params)
            data: dict[str, Any] = response.json()
            self.logger.info(f"成功从 {url} 获取JSON数据")
            return data
        except json.JSONDecodeError:
            self.logger.error(f"无法解析 {url} 的JSON数据")
            return None
        except Exception as e:
            self.logger.error(f"请求 {url} 时发生错误: {str(e)}")
            return None

    def save_to_file(
        self,
        data: dict[str, Any],
        filename: str,
        sub_directory: Path | None = None,
        base_directory: Path | None = None,
    ) -> bool:
        """将数据保存到本地 JSON 文件。

        Args:
            data: 要保存的数据
            filename: 文件名（不含 .json 后缀）
            sub_directory: 可选子目录（相对基准目录），如 aramkit 资源版本目录
            base_directory: 可选基准目录，覆盖默认保存目录

        Returns:
            保存成功返回 True，否则返回 False
        """
        temporary_file: Path | None = None
        try:
            target_dir = base_directory or self.save_directory
            if sub_directory:
                target_dir = target_dir / sub_directory
            target_dir.mkdir(parents=True, exist_ok=True)
            filepath = target_dir / f"{filename}.json"
            temporary_file = filepath.with_name(f".{filepath.name}.tmp")
            with open(temporary_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temporary_file, filepath)
            self.logger.info(f"数据已保存到 {filepath}")
            return True
        except Exception as e:
            self.logger.error(f"保存文件时发生错误: {str(e)}")
            return False
        finally:
            if temporary_file is not None:
                try:
                    temporary_file.unlink(missing_ok=True)
                except OSError as e:
                    self.logger.warning(f"清理临时文件失败: {temporary_file}, 错误: {str(e)}")

    def crawl_and_save(self, url: str, filename: str, params: dict[str, Any] | None = None) -> bool:
        """拉取 URL 数据并保存到本地。

        Args:
            url: 目标 URL
            filename: 保存的文件名（不含 .json 后缀）
            params: 请求参数

        Returns:
            成功返回 True，否则返回 False
        """
        self.logger.info(f"开始爬取数据: {url}")
        data = self.fetch_json(url, params)
        if data is not None:
            return self.save_to_file(data, filename)
        self.logger.error(f"未能从 {url} 获取有效数据")
        return False

    def batch_crawl_ids(
        self,
        champion_ids: Sequence[int],
        *,
        url_for: Callable[[int], str],
        on_success: Callable[[int], None] | None = None,
    ) -> dict[str, bool]:
        """按英雄 ID 顺序批量爬取，连续失败达到阈值即中止。

        opgg/aramkit 两个爬虫共享的循环骨架：逐个英雄请求并保存，成功时
        重置连续失败计数并触发 ``on_success`` 回调（aramkit 用它持久化
        断点续爬进度），连续失败达到 :data:`MAX_CONSECUTIVE_FAILURES` 记
        WARNING 并停止。

        Args:
            champion_ids: 按序爬取的英雄 ID 列表
            url_for: 英雄 ID → 目标 URL
            on_success: 单个英雄成功后的回调（可选）

        Returns:
            键为英雄 ID 字符串、值为爬取结果的字典
        """
        results: dict[str, bool] = {}
        failed_ids: list[int] = []
        consecutive_failures = 0
        for champion_id in champion_ids:
            filename = str(champion_id)
            results[filename] = self.crawl_and_save(url_for(champion_id), filename)
            if results[filename]:
                if on_success is not None:
                    on_success(champion_id)
                consecutive_failures = 0
            else:
                failed_ids.append(champion_id)
                consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self.logger.warning(f"连续{consecutive_failures}个英雄ID爬取失败，已停止爬取")
                break
            time.sleep(self.delay_second)
        fail_count = len(failed_ids)
        self.logger.info(
            f"批量爬取完成，共成功 {len(results) - fail_count} 个英雄；共失败 {fail_count} 个英雄ID: {failed_ids}"
        )
        return results
