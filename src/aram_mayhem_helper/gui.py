import ctypes
import logging
import queue
import sys
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


def _enable_dpi_awareness() -> None:
    """Enable system DPI awareness on Windows to prevent blurry bitmap scaling.

    Must be called **before** ``tk.Tk()`` is created.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _scaled(value: int, factor: float) -> int:
    """Scale *value* by *factor*, minimum 1."""
    return max(1, round(value * factor))


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
    _enable_dpi_awareness()

    root = tk.Tk()
    root.title("LOL海克斯乱斗工具")

    # --- DPI-aware sizing ---
    dpi = root.winfo_fpixels("1i")
    scale = dpi / 96.0

    phys_w = root.winfo_screenwidth()
    phys_h = root.winfo_screenheight()
    eff_w = int(phys_w / scale)
    eff_h = int(phys_h / scale)

    # Window size: proportional to effective screen, with bounds
    win_w = max(600, min(int(eff_w * 0.40), 1000))
    win_h = max(400, min(int(eff_h * 0.38), 650))
    x = (phys_w - win_w) // 2
    y = (phys_h - win_h) // 2
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    root.minsize(520, 340)

    # Font sizes
    btn_font = ("微软雅黑", max(9, min(round(12 * scale), 16)))
    label_font = ("微软雅黑", max(8, min(round(10 * scale), 14)))
    log_font = ("Consolas", max(8, min(round(9 * scale), 12)))

    # Padding
    pad_lg = _scaled(20, scale)
    pad_md = _scaled(10, scale)
    pad_sm = _scaled(5, scale)
    pad_xs = _scaled(2, scale)

    # --- Control area: two side-by-side groups ---
    control_frame = tk.Frame(root)
    control_frame.pack(pady=(pad_md, 0), padx=pad_lg, fill=tk.X)
    control_frame.grid_columnconfigure(0, weight=1)
    control_frame.grid_columnconfigure(1, weight=1)

    # Left group: game actions
    action_group = tk.LabelFrame(control_frame, text="游戏操作", font=label_font)
    action_group.grid(row=0, column=0, padx=(0, pad_sm), pady=pad_sm, sticky="nsew")

    btn1 = tk.Button(
        action_group,
        text="识别英雄",
        command=lambda: recognize_champion(log_area),
        font=btn_font,
    )
    btn1.pack(fill=tk.X, padx=pad_sm, pady=pad_xs)

    btn2 = tk.Button(
        action_group,
        text="识别符文",
        command=lambda: recognize_augment(log_area),
        font=btn_font,
    )
    btn2.pack(fill=tk.X, padx=pad_sm, pady=pad_xs)

    # Right group: data crawling
    data_group = tk.LabelFrame(control_frame, text="数据抓取", font=label_font)
    data_group.grid(row=0, column=1, padx=(pad_sm, 0), pady=pad_sm, sticky="nsew")

    btn3 = tk.Button(
        data_group,
        text="获取英雄数据",
        font=btn_font,
    )
    btn3.pack(fill=tk.X, padx=pad_sm, pady=pad_xs)

    btn4 = tk.Button(
        data_group,
        text="获取符文数据",
        font=btn_font,
    )
    btn4.pack(fill=tk.X, padx=pad_sm, pady=pad_xs)

    # Page range inputs at bottom of data group
    page_row = tk.Frame(data_group)
    page_row.pack(fill=tk.X, padx=pad_sm, pady=pad_xs)

    tk.Label(page_row, text="起始页:", font=label_font).pack(side=tk.LEFT, padx=(0, pad_xs))
    start_entry = tk.Entry(page_row, width=5, font=label_font)
    start_entry.insert(0, "1")
    start_entry.pack(side=tk.LEFT, padx=(0, pad_sm))

    tk.Label(page_row, text="结束页:", font=label_font).pack(side=tk.LEFT, padx=(0, pad_xs))
    end_entry = tk.Entry(page_row, width=5, font=label_font)
    end_entry.insert(0, "999")
    end_entry.pack(side=tk.LEFT)

    crawl_buttons = [btn3, btn4]

    # --- Separator between controls and log ---
    separator = tk.Frame(root, height=_scaled(2, scale), bd=1, relief=tk.SUNKEN)
    separator.pack(fill=tk.X, padx=pad_lg, pady=(pad_md, 0))

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

    # 3. 日志输出区域（带滚动条，只读，填充剩余空间）
    log_label = tk.Label(root, text="运行日志：", font=label_font)
    log_label.pack(anchor="w", padx=pad_lg, pady=(pad_sm, 0))

    log_area = scrolledtext.ScrolledText(
        root,
        font=log_font,
        state=tk.DISABLED,
    )
    log_area.pack(padx=pad_lg, pady=pad_sm, fill=tk.BOTH, expand=True)

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
