"""Thread-safe pool of SQLAlchemy engines keyed by database URL.

Avoids creating a new engine per request (expensive) while supporting
an unbounded number of tenants by evicting the least-recently-used
engine when the pool reaches its maximum size.
"""

import threading
import time
from collections import OrderedDict

from sqlalchemy import Engine, create_engine


class EnginePool:
    """LRU cache of SQLAlchemy engines keyed by database URL.

    Parameters
    ----------
    max_size:
        Maximum number of engines to keep alive. When exceeded the
        least-recently-used engine is disposed and removed.
    max_idle_seconds:
        Engines not accessed within this window are disposed on the
        next ``get()`` call.  Set to 0 to disable idle eviction.
    """

    def __init__(self, max_size: int = 50, max_idle_seconds: int = 3600) -> None:
        self._max_size = max_size
        self._max_idle = max_idle_seconds
        self._lock = threading.Lock()
        # OrderedDict tracks access order: most-recently-used at the end.
        self._engines: OrderedDict[str, tuple[Engine, float]] = OrderedDict()

    def get(self, database_url: str) -> Engine:
        """Return an engine for *database_url*, creating one if needed."""
        now = time.monotonic()

        with self._lock:
            # --- Hit: move to end (most-recently-used) and update timestamp ---
            if database_url in self._engines:
                engine, _ = self._engines.pop(database_url)
                self._engines[database_url] = (engine, now)
                self._evict_idle(now)
                return engine

            # --- Miss: create engine ---
            engine = create_engine(database_url, pool_pre_ping=True)
            self._engines[database_url] = (engine, now)

            # Evict LRU if over capacity
            while len(self._engines) > self._max_size:
                _, (old_engine, _) = self._engines.popitem(last=False)
                old_engine.dispose()

            self._evict_idle(now)
            return engine

    def _evict_idle(self, now: float) -> None:
        """Remove engines that haven't been accessed within the idle window."""
        if self._max_idle <= 0:
            return
        stale_keys = [k for k, (_, ts) in self._engines.items() if now - ts > self._max_idle]
        for key in stale_keys:
            engine, _ = self._engines.pop(key)
            engine.dispose()

    def dispose_all(self) -> None:
        """Dispose every engine in the pool. Called on server shutdown."""
        with self._lock:
            for engine, _ in self._engines.values():
                engine.dispose()
            self._engines.clear()
