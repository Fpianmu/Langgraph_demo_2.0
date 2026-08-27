from __future__ import annotations

from functools import wraps
import logging
from time import perf_counter
from typing import Any, Callable, TypeVar


T = TypeVar("T")
LOGGER = logging.getLogger("agent.node_runtime")
LOGGER.setLevel(logging.INFO)


def log_node_runtime(node_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            _ensure_default_logging()
            started_at = perf_counter()
            state_keys = _state_keys(args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                duration = perf_counter() - started_at
                LOGGER.error(
                    "node=%s duration=%.4fs status=error error_type=%s state_keys=%s",
                    node_name,
                    duration,
                    exc.__class__.__name__,
                    state_keys,
                    exc_info=True,
                )
                raise
            duration = perf_counter() - started_at
            LOGGER.info(
                "node=%s duration=%.4fs status=success state_keys=%s output_keys=%s goto=%s",
                node_name,
                duration,
                state_keys,
                _output_keys(result),
                _goto_value(result),
            )
            return result

        return wrapper

    return decorator


def _ensure_default_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _state_keys(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    state = args[0] if args else kwargs.get("state")
    if not isinstance(state, dict):
        return ""
    return _join_keys(state.keys())


def _output_keys(result: Any) -> str:
    if isinstance(result, dict):
        return _join_keys(result.keys())
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        return _join_keys(update.keys())
    return ""


def _goto_value(result: Any) -> str:
    value = getattr(result, "goto", "")
    return str(value or "")


def _join_keys(keys: Any) -> str:
    public_keys = sorted(str(key) for key in keys if not str(key).startswith("_"))
    return ",".join(public_keys[:16])
