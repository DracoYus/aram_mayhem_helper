import logging
import sys

from aram_mayhem_helper.utils.config import config


def setup_logging(
    level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    log_file: str = "app.log",
):
    """
    配置项目全局日志（只需在主入口调用一次）
    :param level: 根 logger 的最低级别
    :param console_level: 控制台输出的级别
    :param file_level: 文件输出的级别
    :param log_file: 日志文件名
    """
    # 1. 获取根 logger
    root_logger = logging.getLogger("aram_mayhem_helper")
    root_logger.setLevel(level)
    root_logger.propagate = False  # 避免重复输出到系统默认 logger

    # 2. 清空已有的 Handler（防止重复配置）
    root_logger.handlers.clear()

    # 3. 配置控制台 Handler（输出 INFO 及以上）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 4. 配置文件 Handler（输出 DEBUG 及以上，保存到 logs 目录）
    log_dir = config.base_dir / "logs"
    log_dir.mkdir(exist_ok=True)  # 自动创建 logs 目录
    file_handler = logging.FileHandler(log_dir / log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
