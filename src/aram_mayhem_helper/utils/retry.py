import logging
import time
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_T = TypeVar("_T")


def retry_on_exception(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    """
    重试装饰器，当函数抛出指定异常时自动重试

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 延迟时间增长因子
        exceptions: 需要重试的异常类型元组
    """

    def decorator(func: Callable[_P, _T]) -> Callable[_P, _T]:
        @wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            current_delay = delay
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} 执行失败（第{attempt + 1}次尝试），"
                            f"错误: {str(e)}，{current_delay:.1f}秒后重试..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(f"{func.__name__} 执行失败，已达到最大重试次数（{max_retries}次），错误: {str(e)}")

            assert last_exception is not None
            raise last_exception

        return wrapper

    return decorator
