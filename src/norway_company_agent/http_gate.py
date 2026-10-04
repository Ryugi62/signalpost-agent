"""Infrastructure: enforce a RequestBudget on every HTTP request this process sends.

The gate wraps http.client.HTTPConnection.putrequest, which urllib (including redirect hops, robots.txt and
retries) and urllib3 both call once per request. A refused request is never sent: it raises
RequestBudgetExhausted (an OSError, so callers' network-error handling turns it into a non-available state).
"""
from __future__ import annotations

import contextlib
import http.client
import threading
from typing import Callable, Iterator

from .budget import RequestBudget

_local = threading.local()
_install_lock = threading.Lock()


class RequestBudgetExhausted(OSError):
    """The run's outbound request budget refused this request; nothing was sent."""


def current_category() -> str:
    return getattr(_local, "category", None) or "unattributed"


@contextlib.contextmanager
def charging(category: str) -> Iterator[None]:
    previous = getattr(_local, "category", None)
    _local.category = category
    try:
        yield
    finally:
        _local.category = previous


def install_request_gate(budget: RequestBudget) -> Callable[[], None]:
    """Install the gate process-wide; returns a function that removes it."""
    with _install_lock:
        original = http.client.HTTPConnection.putrequest

        def gated_putrequest(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
            category = current_category()
            if not budget.try_acquire(category):
                raise RequestBudgetExhausted(f"run request budget exhausted ({budget.limit}); {category} request to {self.host} not sent")
            return original(self, method, url, *args, **kwargs)

        http.client.HTTPConnection.putrequest = gated_putrequest  # type: ignore[method-assign]

    def uninstall() -> None:
        with _install_lock:
            http.client.HTTPConnection.putrequest = original  # type: ignore[method-assign]

    return uninstall


def is_budget_error(exc: BaseException | None) -> bool:
    """True when an exception (possibly wrapped by urllib) came from the budget gate."""
    seen = 0
    while exc is not None and seen < 5:
        if isinstance(exc, RequestBudgetExhausted):
            return True
        exc = getattr(exc, "reason", None) or exc.__cause__ or exc.__context__
        seen += 1
    return False
