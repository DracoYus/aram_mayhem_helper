import ctypes
import logging
import queue
import sys
import threading
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext, ttk

from aram_mayhem_helper.algorithm.suggest import Suggest
from aram_mayhem_helper.crawlers.aramkit.aramkit_crawler import AramkitCrawler
from aram_mayhem_helper.crawlers.ddragon.champion_crawler import ChampionCrawler
from aram_mayhem_helper.crawlers.opgg.aram_augment_crawler import AramAugmentCrawler
from aram_mayhem_helper.league_client_api.live_data import get_current_champion_name
from aram_mayhem_helper.ocr.ocr_tool import get_ocr_tool
from aram_mayhem_helper.utils.config import VALID_SOURCES, get_config, set_data_source
from aram_mayhem_helper.utils.data import get_game_data
from aram_mayhem_helper.utils.log_config import setup_logging


# ====================== 第一步：定义日志输出函数（核心） ======================
def print_log(log_text: str, log_area: scrolledtext.ScrolledText) -> None:
    """
    向日志区域输出内容（带时间戳，自动滚动）
    :param log_text: 要打印的日志文本
    :param log_area: 日志显示区域对象
    """
    # 拼接时间戳，格式：[15:30:00] 日志内容
    timestamp = time.strftime("[%H:%M:%S] ", time.localtime())
    log_area.config(state=tk.NORMAL)  # 临时解锁日志区域，允许输入
    log_area.insert(tk.END, timestamp + log_text + "\n")  # 插入日志
    log_area.see(tk.END)  # 自动滚动到最新日志
    log_area.config(state=tk.DISABLED)  # 锁定日志区域，禁止手动编辑
    log_area.update()  # 实时刷新界面


# 显式 logger 名而非 __name__：用户启动器以直接脚本方式运行 gui.py 时
# __name__ == "__main__"，日志会绕过 "aram_mayhem_helper" 的处理器而全部丢失
logger = logging.getLogger("aram_mayhem_helper.gui")


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
        # 只桥接消息本体：GUI 日志区的时间戳由 print_log 统一添加，
        # 完整格式（时间/logger 名/级别/文件名:行号）由文件日志（log_config.py）保留
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Format *record* and push it into the queue."""
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


# ====================== 第二步：业务函数（绑定按钮，带日志输出） ======================
def recognize_augment(
    log_area: scrolledtext.ScrolledText,
    buttons: list[tk.Button],
    source: str,
) -> None:
    """识别符文和展示结果（后台线程执行，避免阻塞 Tkinter 主线程）。

    使用 GUI 选择的数据源作为首选数据源。
    """
    _run_in_background(
        lambda: _recognize_worker(source),
        "开始执行「识别符文」操作...",
        log_area,
        buttons,
    )


def _save_unrecognized_capture(index: int, text: str) -> None:
    """符文名称识别失败时保存对应区域截图，便于后期排查 OCR 问题。

    OCR 工具的 info 日志经 ``aram_mayhem_helper`` 根 logger 桥接到 GUI 日志区。
    """
    get_ocr_tool().save_failure_capture(index, text, get_config().ocr_failure_dir)


def _recognize_worker(source: str) -> None:
    """后台执行：识别当前英雄 → OCR 读取符文 → 生成推荐。

    不变式：本函数内的数据源一律显式传入（available_source 的 preferred /
    Suggest.source），不依赖 default_source() —— 写回配置后 GameData 持有的
    旧配置引用已过期，默认源可能不是 GUI 当前选择。
    """
    game_data = get_game_data()

    try:
        champion_name = get_current_champion_name()
        if not champion_name:
            logger.error("无法获取当前英雄名称，请确保游戏正在运行")
            return
        champion_id = game_data.champion_id_by_name(champion_name)
        if not champion_id:
            logger.error(f"无法找到英雄 '{champion_name}' 对应的ID")
            return
        resolved = game_data.available_source(champion_id, preferred=source)
        if resolved is None:
            logger.error(f"英雄ID {champion_id} ({champion_name}) 在数据源 {source} 与另一源中都没有符文数据")
            return
        if resolved != source:
            logger.warning(f"数据源 {source} 无该英雄的符文数据，已回退使用 {resolved}")
        suggest = Suggest(champion_id, game_data, source=resolved, thresholds=get_config().suggest)
        logger.info(f"当前英雄：{champion_name}（数据源: {resolved}）")
    except Exception as e:
        logger.error(f"识别英雄出错：{str(e)}")
        return

    augments = None
    try:
        augments = get_ocr_tool().get_augments()
        augments_info = suggest.suggest(augments, on_unrecognized=_save_unrecognized_capture)
        if augments_info:
            for augment_info in augments_info:
                logger.info(str(augment_info))
        else:
            logger.warning("未能生成任何符文建议（OCR 名称未匹配到当前英雄的符文数据）")
    except Exception as e:
        logger.error(f"「识别符文」操作出错：{str(e)}")
        if augments is not None:
            logger.info(str(augments))


def _warmup_ocr() -> None:
    """后台线程预热 OCR 模型（静默执行：失败也不影响，首次识别时 OCRTool 会重新加载）。"""
    get_ocr_tool().warmup()


# ====================== 第三步：后台任务（后台线程 + 日志桥接） ======================
_task_in_progress = False


def _poll_log_queue(
    log_queue: queue.Queue[str | None],
    log_area: scrolledtext.ScrolledText,
    buttons: list[tk.Button],
    on_done: Callable[[], None] | None,
) -> None:
    """Drain *log_queue* and display messages in *log_area* on the main thread.

    Called periodically via ``root.after()`` while a background task is running.
    When a ``None`` sentinel is received the task is complete: buttons
    are re-enabled, *on_done* is invoked, and polling stops.
    """
    try:
        while True:
            try:
                msg = log_queue.get_nowait()
            except queue.Empty:
                break

            if msg is None:
                _finish_task(log_area, buttons, on_done)
                return

            print_log(msg, log_area)
    except Exception:
        _finish_task(log_area, buttons, on_done)
        print_log("日志轮询过程中发生错误，已恢复按钮状态", log_area)
        logger.exception("日志轮询异常")
        return

    log_area.after(100, _poll_log_queue, log_queue, log_area, buttons, on_done)


def _finish_task(
    log_area: scrolledtext.ScrolledText,
    buttons: list[tk.Button],
    on_done: Callable[[], None] | None,
) -> None:
    """Re-enable buttons, run *on_done* (e.g. reload data), and reset task state."""
    global _task_in_progress
    _task_in_progress = False

    for btn in buttons:
        btn.config(state=tk.NORMAL)
    if on_done is not None:
        on_done()


def _run_in_background(
    target: Callable[[], None],
    description: str,
    log_area: scrolledtext.ScrolledText,
    buttons: list[tk.Button],
    on_done: Callable[[], None] | None = None,
) -> None:
    """Start *target* in a daemon thread with log bridging to the GUI.

    Installs :class:`TkinterLogHandler` on the ``aram_mayhem_helper`` logger,
    disables *buttons*, starts polling the log queue, and spawns the worker.
    A single ``_task_in_progress`` guard prevents concurrent tasks.
    """
    global _task_in_progress
    if _task_in_progress:
        print_log("已有任务正在执行中，请等待完成后再试", log_area)
        return
    _task_in_progress = True
    log_queue: queue.Queue[str | None] = queue.Queue()
    handler = TkinterLogHandler(log_queue)

    app_logger = logging.getLogger("aram_mayhem_helper")
    app_logger.addHandler(handler)

    for btn in buttons:
        btn.config(state=tk.DISABLED)

    print_log(description, log_area)
    log_area.after(100, _poll_log_queue, log_queue, log_area, buttons, on_done)

    def worker() -> None:
        try:
            target()
        except Exception as e:
            app_logger.error("任务执行过程中发生未捕获的异常", exc_info=True)
            log_queue.put(f"任务执行过程中发生错误：{e}")
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
            logger.info("英雄数据抓取完成：成功")
        else:
            logger.warning("英雄数据抓取完成：失败")

    _run_in_background(
        _crawl,
        "开始获取英雄数据...",
        log_area,
        crawl_buttons,
        on_done=_reload_data_after_crawl(log_area),
    )


def _reload_data_after_crawl(log_area: scrolledtext.ScrolledText) -> Callable[[], None]:
    """爬取完成后在主线程刷新数据缓存。"""

    def _reload() -> None:
        print_log("数据抓取完成，正在重新加载数据...", log_area)
        try:
            get_game_data().reload()
            print_log("数据已重新加载，新数据已生效", log_area)
        except Exception as e:
            print_log(f"数据重新加载失败：{e}", log_area)

    return _reload


def fetch_augment_data(
    log_area: scrolledtext.ScrolledText,
    crawl_buttons: list[tk.Button],
    start_page: int,
    end_page: int,
    source: str,
) -> None:
    """Fetch augment data from the selected source in a background thread.

    aramkit 走完整爬取流程（版本发现 + 资源文件 + 批量英雄数据）；
    opgg 走批量英雄数据抓取。
    """

    def _crawl() -> None:
        if source == "aramkit":
            try:
                success = AramkitCrawler().crawl(start_page, end_page)
            except RuntimeError as e:  # 版本发现失败（首页抓取失败且无本地缓存）
                logger.error(f"aramkit 符文数据抓取失败：{e}")
                return
            if success:
                logger.info("符文数据抓取完成（aramkit）：全部英雄成功")
            else:
                logger.warning("符文数据抓取完成（aramkit）：部分英雄失败")
        else:
            crawler = AramAugmentCrawler()
            results = crawler.batch_crawl(start_page, end_page)
            success_count = sum(1 for v in results.values() if v)
            fail_count = sum(1 for v in results.values() if not v)
            msg = f"符文数据抓取完成（opgg）：成功 {success_count}" + (f"，失败 {fail_count}" if fail_count else "")
            if fail_count:
                logger.warning(msg)
            else:
                logger.info(msg)

    _run_in_background(
        _crawl,
        f"开始获取符文数据（数据源: {source}，页范围：{start_page}-{end_page}）...",
        log_area,
        crawl_buttons,
        on_done=_reload_data_after_crawl(log_area),
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

    # Use the smaller screen dimension as the reference to keep consistent
    # visual proportions regardless of aspect ratio.
    ref_dim = min(phys_w, phys_h)

    # Window size: scale a base 800×520 design (at 96 DPI, ~1080p screen)
    # so the window occupies a similar fraction of the screen at any DPI.
    base_w, base_h = 600, 380
    size_scale = ref_dim / 1080  # 1080 is the reference shorter-side at FHD
    win_w = int(base_w * size_scale)
    win_h = int(base_h * size_scale)

    # Clamp: never smaller than the base design, never larger than 85 % of screen
    win_w = max(_scaled(600, scale), min(win_w, int(phys_w * 0.85)))
    win_h = max(_scaled(300, scale), min(win_h, int(phys_h * 0.85)))

    x = (phys_w - win_w) // 2
    y = (phys_h - win_h) // 2
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")
    root.minsize(_scaled(600, scale), _scaled(300, scale))

    # Font sizes: 基础值按 1080p（100% 缩放）下的可读字号设定，
    # scale 继续按 DPI 放大高分辨率屏幕的字号。
    btn_font = ("微软雅黑", max(9, min(round(10 * scale), 16)))
    label_font = ("微软雅黑", max(8, min(round(9 * scale), 14)))
    log_font = ("Consolas", max(9, min(round(10 * scale), 16)))

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

    # 顶部：数据源选择（跨两列），识别符文与数据抓取共用所选数据源
    source_row = tk.Frame(control_frame)
    source_row.grid(row=0, column=0, columnspan=2, padx=pad_sm, pady=(pad_sm, 0), sticky="ew")

    tk.Label(source_row, text="数据源:", font=label_font).pack(side=tk.LEFT)
    source_var = tk.StringVar(value=get_config().data_source.source)
    source_combo = ttk.Combobox(
        source_row,
        textvariable=source_var,
        values=VALID_SOURCES,
        state="readonly",
        width=10,
    )
    source_combo.pack(side=tk.LEFT, padx=(pad_xs, 0))

    def _on_source_changed(_event: object) -> None:
        """主线程回调：写回 config.toml 并重建配置单例；失败时回滚下拉框显示。"""
        new_source = source_var.get()
        try:
            set_data_source(new_source)
            print_log(f"数据源已切换并持久化: {new_source}", log_area)
        except (ValueError, OSError) as e:
            print_log(f"数据源切换失败: {e}（已恢复原设置）", log_area)
            source_var.set(get_config().data_source.source)  # 失败时单例未重建，仍是旧值

    source_combo.bind("<<ComboboxSelected>>", _on_source_changed)

    # Left group: game actions
    action_group = tk.LabelFrame(control_frame, text="游戏操作", font=label_font)
    action_group.grid(row=1, column=0, padx=(0, pad_sm), pady=pad_sm, sticky="nsew")

    btn2 = tk.Button(
        action_group,
        text="识别符文",
        command=lambda: recognize_augment(log_area, all_buttons, source_var.get()),
        font=btn_font,
    )
    btn2.pack(fill=tk.X, padx=pad_sm, pady=pad_xs)

    # Right group: data crawling
    data_group = tk.LabelFrame(control_frame, text="数据抓取", font=label_font)
    data_group.grid(row=1, column=1, padx=(pad_sm, 0), pady=pad_sm, sticky="nsew")

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

    all_buttons = [btn2, btn3, btn4]

    def _on_fetch_champion() -> None:
        fetch_champion_data(log_area, all_buttons)

    def _on_fetch_augment() -> None:
        try:
            start = int(start_entry.get().strip()) if start_entry.get().strip() else 1
            end = int(end_entry.get().strip()) if end_entry.get().strip() else 999
        except ValueError:
            print_log("页数格式错误，使用默认值（1-999）", log_area)
            start, end = 1, 999
        fetch_augment_data(log_area, all_buttons, start, end, source_var.get())

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

    # 后台预热 PaddleOCR 模型：首次初始化需数秒，预热后首次识别不再卡顿（静默执行）
    threading.Thread(target=_warmup_ocr, daemon=True).start()

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
