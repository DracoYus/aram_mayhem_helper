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
    monkeypatch.setattr(gui, "_task_in_progress", False)
    monkeypatch.setattr(gui.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(gui.logger, "level", logging.DEBUG)
    monkeypatch.setattr(crawler_logger, "level", logging.DEBUG)

    def task() -> None:
        gui.logger.info("GUI 状态消息")
        crawler_logger.info("爬虫逐条进度消息")
        crawler_logger.warning("爬虫警告消息")

    gui._run_in_background(task, "开始任务", log_area, [button])
    callback, args = log_area.callbacks[0]
    callback(*args)  # type: ignore[operator]

    rendered = "".join(log_area.entries)
    assert "开始任务" in rendered
    assert "GUI 状态消息" in rendered
    assert "爬虫逐条进度消息" not in rendered
    assert "爬虫警告消息" in rendered
    assert button.states == ["disabled", "normal"]
