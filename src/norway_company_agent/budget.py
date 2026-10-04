"""Hard global request budget (SPEC UC-5). Pure accounting: no I/O, no framework imports.

Every outbound HTTP request of a run (registry, company sites, NAV, Wikidata, robots.txt, retries and
redirect hops) must be granted by one RequestBudget before it is sent. The infrastructure gate in
`http_gate.py` enforces this at the socket-request layer, so no code path can bypass it.
"""
from __future__ import annotations

import math
import threading
from typing import Any

# Default ceiling for the most conservative reading of the published "2,000 outbound requests" daily
# limit (registry calls included). The margin covers requests a harness might count differently.
DEFAULT_LIMIT = 1950

# Order in which the run spends the budget. Fixed batch reads first; then registry-declared websites and the feeds of
# verified sites (about one dated-activity company per two requests); discovery takes the remainder minus the
# reserve kept for per-company registry reads (annual accounts, group structure), which `registry_reserve` sizes so that
# every company keeps its latest filed accounts (required envelope section 2) under the strictest budget reading.
PRIORITY = ["registry_batch", "registry_bulk", "wikidata", "jobs", "website_registry", "activity_feed", "website_discovery", "financials", "group"]
REGISTRY_CATEGORIES = frozenset({"registry_batch", "registry_bulk", "financials", "group"})


class RequestBudget:
    def __init__(self, limit: int, *, ceilings: dict[str, int] | None = None, exempt: frozenset[str] | set[str] = frozenset()) -> None:
        """exempt: categories counted but not charged to the limit (only for a reading of the limit that excludes
        them, e.g. registry reads; the default exempts nothing)."""
        if limit < 0:
            raise ValueError("limit must be >= 0")
        self.limit = int(limit)
        self.exempt = frozenset(exempt)
        self._spent_exempt = 0
        self._ceilings = dict(ceilings or {})
        self._lock = threading.Lock()
        self._spent = 0
        self._by_category: dict[str, int] = {}
        self._denied = 0
        self._denied_by_category: dict[str, int] = {}
        self._reserved: dict[str, int] = {}

    def _free(self) -> int:
        return self.limit - self._spent - sum(self._reserved.values())

    def try_acquire(self, category: str) -> bool:
        """Grant one request to `category`, or refuse. Never grants beyond the limit."""
        with self._lock:
            ceiling = self._ceilings.get(category)
            used = self._by_category.get(category, 0)
            granted = False
            if category in self.exempt:
                if ceiling is None or used < ceiling:
                    self._spent_exempt += 1
                    self._by_category[category] = used + 1
                    return True
                self._denied += 1
                self._denied_by_category[category] = self._denied_by_category.get(category, 0) + 1
                return False
            if ceiling is None or used < ceiling:
                if self._reserved.get(category, 0) > 0:
                    self._reserved[category] -= 1
                    granted = True
                elif self._free() > 0:
                    granted = True
            if granted:
                self._spent += 1
                self._by_category[category] = used + 1
            else:
                self._denied += 1
                self._denied_by_category[category] = self._denied_by_category.get(category, 0) + 1
            return granted

    def reserve(self, category: str, n: int) -> int:
        """Set aside up to n requests that only `category` may use. Returns how many were reserved."""
        with self._lock:
            take = max(0, min(int(n), self._free()))
            self._reserved[category] = self._reserved.get(category, 0) + take
            return take

    def release(self, category: str) -> None:
        with self._lock:
            self._reserved.pop(category, None)

    def set_ceiling(self, category: str, ceiling: int | None) -> None:
        with self._lock:
            if ceiling is None:
                self._ceilings.pop(category, None)
            else:
                self._ceilings[category] = int(ceiling)

    def available(self, category: str) -> int:
        """Requests `category` could still be granted right now (reservation + free pool, capped by its ceiling)."""
        with self._lock:
            pool = 10**9 if category in self.exempt else self._reserved.get(category, 0) + max(0, self._free())
            ceiling = self._ceilings.get(category)
            if ceiling is not None:
                pool = min(pool, ceiling - self._by_category.get(category, 0))
            return max(0, pool)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "limit": self.limit,
                "spent": self._spent,
                "spent_exempt": self._spent_exempt,
                "exempt": sorted(self.exempt),
                "total_outbound": self._spent + self._spent_exempt,
                "remaining": self.limit - self._spent,
                "denied": self._denied,
                "by_category": dict(sorted(self._by_category.items())),
                "denied_by_category": dict(sorted(self._denied_by_category.items())),
                "reserved": {k: v for k, v in self._reserved.items() if v},
                "ceilings": dict(self._ceilings),
            }


def plan_shares(limit: int, n_companies: int, *, registry_sites: int = 0, group_candidates: int = 0, nav_pages: int = 120,
                pages_per_registry_site: int = 5, financials_floor: int = 0) -> dict[str, Any]:
    """Category ceilings that sum to at most `limit`, filled in PRIORITY order.

    Batch registry reads (300 entities per request), two bulk files, Wikidata (400 per query) and the NAV feed
    come first; then registry-declared websites; discovery gets the remainder minus `financials_floor`; then one
    annual-accounts request per company and the group structure for entities the registry marks as part of a
    group (`erIKonsern`, ~7%) take what is left. The run re-opens unspent ceilings in the same order.
    """
    n = max(0, int(n_companies))
    wanted: dict[str, int | None] = {
        "registry_batch": math.ceil(n / 300) + 2,
        "registry_bulk": 2,
        "wikidata": math.ceil(n / 400) + 1,
        "jobs": nav_pages + 12,
        "website_registry": pages_per_registry_site * max(0, int(registry_sites)),
        "activity_feed": max(0, int(registry_sites)) + math.ceil(n / 20),  # one feed read per verified site (registry or discovered)
        "website_discovery": None,  # remainder minus the floor kept for annual accounts
        "financials": n + math.ceil(n / 50),
        "group": max(0, int(group_candidates)),
    }
    left = int(limit)
    ceilings: dict[str, int] = {}
    floor = max(0, int(financials_floor))
    for category in PRIORITY:
        want = wanted[category]
        room = left if category in ("financials", "group") else max(0, left - floor)  # the registry reserve is never lent out
        take = room if want is None else min(want, room)
        ceilings[category] = max(0, take)
        left -= ceilings[category]
    return {"limit": int(limit), "ceilings": ceilings, "order": list(PRIORITY), "unallocated": left,
            "wanted": {k: v for k, v in wanted.items() if v is not None}}


def registry_reserve(n_companies: int, *, group_candidates: int = 0) -> int:
    """Requests kept back from discovery for the per-company registry reads: one annual-accounts request per company,
    a 2% retry margin, and the group structure for entities the registry marks as part of a group (AC-24)."""
    n = max(0, int(n_companies))
    return n + math.ceil(n / 50) + max(0, int(group_candidates))
