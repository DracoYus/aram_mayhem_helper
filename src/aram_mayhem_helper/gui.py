import logging
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import ocr_tool
from aram_mayhem_helper.utils.data import champion_augment_data_dict, data, reload_data
from aram_mayhem_helper.utils.log_config import setup_logging

current_champion_id = None
suggest = None


# ====================== 第一步：定义日志输出函数（核心） ======================
def print_log(log_text: str, log_area: scrolledtext.ScrolledText) -> None:
    """
    向日志区域输出内容（带时间戳，自动滚动）
    :param log_text: 要打印的日志文本
    :param log_area: 日志显示区域对象
    """
    # 拼接时间戳，格式：[2026-02-20 15:30:00] 日志内容
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S] ", time.localtime())
    log_area.config(state=tk.NORMAL)  # 临时解锁日志区域，允许输入
    log_area.insert(tk.END, timestamp + log_text + "\n")  # 插入日志
    log_area.see(tk.END)  # 自动滚动到最新日志
    log_area.config(state=tk.DISABLED)  # 锁定日志区域，禁止手动编辑
    log_area.update()  # 实时刷新界面


class TkinterLogHandler(logging.Handler):
    """Logging handler that bridges log records from worker threads to the Tkinter main thread.

    Messages are pushed into a :class:`queue.Queue` and drained by
    :func:`_poll_log_queue` on the main thread via :meth:`tk.Misc.after`.
    Installed temporarily during a crawl to capture progress logs.
    """

    def __init__(self, log_queue: queue.Queue[str | None]) -> None:
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(
            logging.Formatter(
                "%(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Format *record* and push it into the queue."""
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


# ====================== 第二步：定义业务函数（绑定按钮，带日志输出） ======================
def recognize_champion(log_area: scrolledtext.ScrolledText) -> None:
    """识别当前英雄"""
    print_log("开始执行「识别当前英雄」操作...", log_area)

    global suggest
    global current_champion_id

    try:
        champion_name = get_current_champion_name()
        if not champion_name:
            print_log("无法获取当前英雄名称，请确保游戏正在运行", log_area)
            return
        current_champion_id = data.get_champion_id_by_name(champion_name)
        if not current_champion_id:
            print_log(f"无法找到英雄 '{champion_name}' 对应的ID", log_area)
            return
        if current_champion_id not in champion_augment_data_dict:
            print_log(f"英雄ID {current_champion_id} ({champion_name}) 的符文数据不存在", log_area)
            return
        champion_augment_data = champion_augment_data_dict[current_champion_id]
        suggest = Suggest(champion_augment_data)
        print_log(f"当前英雄：{champion_name}", log_area)
    except Exception as e:
        print_log(f"「识别当前英雄」操作出错：{str(e)}", log_area)


def recognize_augment(log_area: scrolledtext.ScrolledText) -> None:
    """识别符文和展示结果"""
    print_log("开始执行「识别符文」操作...", log_area)
    if suggest is None:
        print_log("请先执行「识别英雄」操作", log_area)
        return
    augments = None
    try:
        augments = ocr_tool.get_augments()
        augments_info = suggest.suggest(augments)
        for augment_info in augments_info:
            print_log(str(augment_info), log_area)
    except Exception as e:
        print_log(f"「识别符文」操作出错：{str(e)}", log_area)
        if augments is not None:
            print_log(str(augments), log_area)


# ====================== 第三步：异步爬取任务（后台线程 + 日志桥接） ======================
_crawl_in_progress = False


def _poll_log_queue(
    log_queue: queue.Queue[str | None],
    log_area: scrolledtext.ScrolledText,
    crawl_buttons: list[tk.Button],
) -> None:
    """Drain *log_queue* and display messages in *log_area* on the main thread.

    Called periodically via ``root.after()`` while a crawl is running.
    When a ``None`` sentinel is received the crawl is complete: buttons
    are re-enabled, data singletons are reloaded, and polling stops.
    """
    try:
        while True:
            try:
                msg = log_queue.get_nowait()
            except queue.Empty:
                break

            if msg is None:
                _finish_crawl(log_area, crawl_buttons)
                return

            print_log(msg, log_area)
    except Exception:
        _finish_crawl(log_area, crawl_buttons)
        print_log("日志轮询过程中发生错误，已恢复按钮状态", log_area)
        logging.getLogger(__name__).exception("日志轮询异常")
        return

    log_area.after(100, _poll_log_queue, log_queue, log_area, crawl_buttons)


def _finish_crawl(
    log_area: scrolledtext.ScrolledText,
    crawl_buttons: list[tk.Button],
) -> None:
    """Re-enable crawl buttons, reload data singletons, and reset crawl state."""
    global _crawl_in_progress
    _crawl_in_progress = False

    for btn in crawl_buttons:
        btn.config(state=tk.NORMAL)
    print_log("数据抓取完成，正在重新加载数据...", log_area)
    try:
        reload_data()
        print_log("数据已重新加载，新数据已生效", log_area)
    except Exception as e:
        print_log(f"数据重新加载失败：{e}", log_area)


def _start_crawl(
    crawl_target: Callable[[], None],
    description: str,
    log_area: scrolledtext.ScrolledText,
    crawl_buttons: list[tk.Button],
) -> None:
    """Start *crawl_target* in a daemon thread with log bridging to the GUI.

    Installs :class:`TkinterLogHandler` on the ``aram_mayhem_helper`` logger,
    disables *crawl_buttons*, starts polling the log queue, and spawns the worker.
    """
    global _crawl_in_progress
    if _crawl_in_progress:
        print_log("已有抓取任务正在执行中，请等待完成后再试", log_area)
        return
    _crawl_in_progress = True
    log_queue: queue.Queue[str | None] = queue.Queue()
    handler = TkinterLogHandler(log_queue)

    app_logger = logging.getLogger("aram_mayhem_helper")
    app_logger.addHandler(handler)

    for btn in crawl_buttons:
        btn.config(state=tk.DISABLED)

    print_log(description, log_area)
    log_area.after(100, _poll_log_queue, log_queue, log_area, crawl_buttons)

    def worker() -> None:
        try:
            crawl_target()
        except Exception as e:
            app_logger.error("抓取过程中发生未捕获的异常", exc_info=True)
            log_queue.put(f"抓取过程中发生错误：{e}")
        finally:
            log_queue.put(None)
            app_logger.removeHandler(handler)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def fetch_champion_data(
    log_area: scrolledtext.ScrolledText,
    crawl_buttons: list[tk.Button],
) -> None:
    """Fetch all champion data from Data Dragon in a background thread."""

    def _crawl() -> None:
        crawler = ChampionCrawler()
        success = crawler.crawl()
        if success:
            logging.getLogger(__name__).info("英雄数据抓取完成：成功")
        else:
            logging.getLogger(__name__).warning("英雄数据抓取完成：失败")

    _start_crawl(_crawl, "开始获取英雄数据...", log_area, crawl_buttons)


def fetch_augment_data(
    log_area: scrolledtext.ScrolledText,
    crawl_buttons: list[tk.Button],
    start_page: int,
    end_page: int,
) -> None:
    """Fetch augment data from OP.GG in a background thread."""

    def _crawl() -> None:
        crawler = AramAugmentCrawler()
        results = crawler.batch_crawl(start_page, end_page)
        success = sum(1 for v in results.values() if v)
        fail = sum(1 for v in results.values() if not v)
        msg = f"符文数据抓取完成：成功 {success}" + (f"，失败 {fail}" if fail else "")
        if fail:
            logging.getLogger(__name__).warning(msg)
        else:
            logging.getLogger(__name__).info(msg)

    _start_crawl(
        _crawl,
        f"开始获取符文数据（页范围：{start_page}-{end_page}）...",
        log_area,
        crawl_buttons,
    )


# ====================== 第四步：创建完整GUI（按钮+日志区域） ======================
def create_gui() -> None:
    # 1. 创建主窗口
    root = tk.Tk()
    root.title("LOL海克斯乱斗工具")
    root.geometry("1200x600")  # 扩大窗口，容纳日志区域
    root.resizable(False, False)

    # 2. 创建按钮框架（放置功能按钮和异步数据获取按钮）
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)  # 垂直间距10像素

    # Row 0: 识别按钮
    btn1 = tk.Button(
        btn_frame,
        text="识别英雄",
        command=lambda: recognize_champion(log_area),  # lambda传递参数给函数
        width=15,
        height=2,
        font=("微软雅黑", 12),
    )
    btn1.grid(row=0, column=0, padx=20)  # 网格布局，水平间距20

    btn2 = tk.Button(
        btn_frame,
        text="识别符文",
        command=lambda: recognize_augment(log_area),
        width=15,
        height=2,
        font=("微软雅黑", 12),
    )
    btn2.grid(row=0, column=1, padx=20)

    # Row 1: 异步数据获取按钮 + 页码输入
    crawl_section = tk.Frame(btn_frame)
    crawl_section.grid(row=1, column=0, columnspan=2, pady=10)

    btn3 = tk.Button(
        crawl_section,
        text="获取英雄数据",
        width=15,
        height=2,
        font=("微软雅黑", 12),
    )
    btn3.pack(side=tk.LEFT, padx=10)

    btn4 = tk.Button(
        crawl_section,
        text="获取符文数据",
        width=15,
        height=2,
        font=("微软雅黑", 12),
    )
    btn4.pack(side=tk.LEFT, padx=10)

    tk.Label(crawl_section, text="起始页:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=(20, 2))
    start_entry = tk.Entry(crawl_section, width=5, font=("微软雅黑", 10))
    start_entry.insert(0, "1")
    start_entry.pack(side=tk.LEFT, padx=2)

    tk.Label(crawl_section, text="结束页:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=(10, 2))
    end_entry = tk.Entry(crawl_section, width=5, font=("微软雅黑", 10))
    end_entry.insert(0, "999")
    end_entry.pack(side=tk.LEFT, padx=2)

    crawl_buttons = [btn3, btn4]

    def _on_fetch_champion() -> None:
        fetch_champion_data(log_area, crawl_buttons)

    def _on_fetch_augment() -> None:
        try:
            start = int(start_entry.get().strip()) if start_entry.get().strip() else 1
            end = int(end_entry.get().strip()) if end_entry.get().strip() else 999
        except ValueError:
            print_log("页数格式错误，使用默认值（1-999）", log_area)
            start, end = 1, 999
        fetch_augment_data(log_area, crawl_buttons, start, end)

    btn3.config(command=_on_fetch_champion)
    btn4.config(command=_on_fetch_augment)

    # 3. 创建日志输出区域（带滚动条，只读）
    log_label = tk.Label(root, text="运行日志：", font=("微软雅黑", 10))
    log_label.pack(anchor="w", padx=20)  # 左对齐，水平间距20

    log_area = scrolledtext.ScrolledText(
        root,
        width=120,  # 宽度（字符数）
        height=15,  # 高度（行数）
        font=("Consolas", 9),  # 等宽字体，适合日志
        state=tk.DISABLED,  # 初始锁定，禁止编辑
    )
    log_area.pack(padx=20, pady=5)  # 边距

    # 初始化日志
    print_log("GUI已启动，等待执行操作...", log_area)

    # 窗口关闭时清理日志 handler，避免资源泄漏
    def _on_closing() -> None:
        app_logger = logging.getLogger("aram_mayhem_helper")
        for h in list(app_logger.handlers):
            if isinstance(h, TkinterLogHandler):
                app_logger.removeHandler(h)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_closing)

    # 4. 启动主循环
    root.mainloop()


# ====================== 运行GUI ======================
if __name__ == "__main__":
    setup_logging()
    create_gui()
