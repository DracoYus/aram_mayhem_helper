import logging

import aram_mayhem_helper.gui as gui


class FakeButton:
    def __init__(self) -> None:
        self.states: list[str] = []

    def config(self, *, state: str) -> None:
        self.states.append(state)


class FakeLogArea:
    def __init__(self) -> None:
        self.entries: list[str] = []
        self.callbacks: list[tuple[object, tuple[object, ...]]] = []

    def config(self, **_kwargs: object) -> None:
        pass

    def insert(self, _index: str, text: str) -> None:
        self.entries.append(text)

    def see(self, _index: str) -> None:
        pass

    def update(self) -> None:
        pass

    def after(self, _delay: int, callback: object, *args: object) -> None:
        self.callbacks.append((callback, args))


class ImmediateThread:
    def __init__(self, *, target: object, daemon: bool) -> None:
        assert daemon is True
        self.target = target

    def start(self) -> None:
        self.target()  # type: ignore[operator]


def test_background_task_does_not_bridge_crawler_progress_logs(monkeypatch) -> None:
    log_area = FakeLogArea()
    button = FakeButton()
    crawler_logger = logging.getLogger("aram_mayhem_helper.crawlers.test")
    monkeypatch.setattr(gui.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(gui.logger, "level", logging.DEBUG)
    monkeypatch.setattr(crawler_logger, "level", logging.DEBUG)
    gui._active_tasks.clear()
    gui._pending_reload_callbacks.clear()

    def task() -> None:
        gui.logger.info("GUI 状态消息")
        crawler_logger.info("爬虫逐条进度消息")
        crawler_logger.warning("爬虫警告消息")

    gui._run_in_background(task, "开始任务", log_area, [button], task_name="recognize")
    callback, args = log_area.callbacks[0]
    callback(*args)  # type: ignore[operator]

    rendered = "".join(log_area.entries)
    assert "开始任务" in rendered
    assert "GUI 状态消息" in rendered
    assert "爬虫逐条进度消息" not in rendered
    assert "爬虫警告消息" in rendered
    assert button.states == ["disabled", "normal"]


def test_recognize_and_crawl_tasks_can_run_at_the_same_time(monkeypatch) -> None:
    log_area = FakeLogArea()
    recognize_button = FakeButton()
    crawl_button = FakeButton()
    started: list[str] = []
    gui._active_tasks.clear()
    gui._pending_reload_callbacks.clear()
    monkeypatch.setattr(gui.threading, "Thread", ImmediateThread)

    gui._run_in_background(
        lambda: started.append("recognize"),
        "开始识别",
        log_area,
        [recognize_button],
        task_name="recognize",
    )
    gui._run_in_background(
        lambda: started.append("crawl"),
        "开始爬取",
        log_area,
        [crawl_button],
        task_name="crawl",
    )

    assert started == ["recognize", "crawl"]
    assert recognize_button.states == ["disabled"]
    assert crawl_button.states == ["disabled"]

    for callback, args in log_area.callbacks:
        callback(*args)  # type: ignore[operator]

    assert recognize_button.states == ["disabled", "normal"]
    assert crawl_button.states == ["disabled", "normal"]


def test_same_task_type_is_rejected_while_running(monkeypatch) -> None:
    log_area = FakeLogArea()
    button = FakeButton()
    started: list[str] = []
    gui._active_tasks.clear()
    gui._pending_reload_callbacks.clear()
    monkeypatch.setattr(gui.threading, "Thread", ImmediateThread)

    gui._run_in_background(
        lambda: started.append("first"),
        "开始爬取",
        log_area,
        [button],
        task_name="crawl",
    )
    gui._run_in_background(
        lambda: started.append("second"),
        "不应启动",
        log_area,
        [button],
        task_name="crawl",
    )

    assert started == ["first"]
    assert "已有爬取任务正在执行中，请等待完成后再试" in "".join(log_area.entries)

    callback, args = log_area.callbacks[0]
    callback(*args)  # type: ignore[operator]


def test_crawl_reload_waits_for_recognition_to_finish() -> None:
    log_area = FakeLogArea()
    recognize_button = FakeButton()
    crawl_button = FakeButton()
    reloads: list[str] = []
    gui._active_tasks.clear()
    gui._pending_reload_callbacks.clear()

    gui._active_tasks.update({"recognize", "crawl"})
    gui._finish_task(
        log_area,
        [crawl_button],
        lambda: reloads.append("reload"),
        "crawl",
    )

    assert reloads == []
    assert gui._active_tasks == {"recognize"}

    gui._finish_task(log_area, [recognize_button], None, "recognize")

    assert reloads == ["reload"]
    assert gui._active_tasks == set()
