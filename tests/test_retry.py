"""utils.retry 重试装饰器行为锁定测试。"""

import time

import pytest

from aram_mayhem_helper.utils.retry import retry_on_exception


class TestRetryOnException:
    def test_success_on_first_attempt_returns_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        @retry_on_exception(max_retries=2, delay=1.0, backoff_factor=2.0, exceptions=(ValueError,))
        def ok() -> str:
            return "done"

        assert ok() == "done"
        assert sleeps == []

    def test_retries_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        @retry_on_exception(max_retries=3, delay=1.0, backoff_factor=2.0, exceptions=(ValueError,))
        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("boom")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 3
        assert sleeps == [1.0, 2.0]  # 指数退避

    def test_exhausts_retries_and_reraises_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)

        @retry_on_exception(max_retries=2, delay=1.0, backoff_factor=2.0, exceptions=(ValueError,))
        def always_fails() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            always_fails()

    def test_unmatched_exception_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: None)
        calls = {"n": 0}

        @retry_on_exception(max_retries=3, delay=1.0, backoff_factor=2.0, exceptions=(KeyError,))
        def raises_type_error() -> None:
            calls["n"] += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError, match="not retried"):
            raises_type_error()
        assert calls["n"] == 1
