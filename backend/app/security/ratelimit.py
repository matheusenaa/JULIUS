"""Rate limiting em memória (janela deslizante).

Suficiente para uma instância única (uso pessoal / plano gratuito). Com várias
instâncias, trocar o armazenamento por Redis mantendo a mesma interface.
"""

import threading
import time
from collections import defaultdict, deque

from app.config import get_settings


class RateLimiter:
    def __init__(self, max_hits: int, window_seconds: float) -> None:
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Registra uma tentativa. Retorna False se o limite foi excedido."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_hits:
                return False
            q.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


_s = get_settings()
login_limiter = RateLimiter(max_hits=_s.login_limit_per_15min, window_seconds=15 * 60)
register_limiter = RateLimiter(max_hits=_s.register_limit_per_hour, window_seconds=60 * 60)
ai_limiter = RateLimiter(max_hits=_s.ai_limit_per_minute, window_seconds=60)
