"""后台会话与登录防护（内存态，零第三方依赖）。

边界：会话只在 portal 进程内有效 —— 重启即全部登出（规格里明确接受），
因此不落盘、不引入签名密钥。时钟可注入，锁定与超时都能用假时钟测试。
"""
from __future__ import annotations

import math
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Session:
    user: str
    csrf: str
    created: float
    last_seen: float


class SessionStore:
    def __init__(self, idle_seconds: float = 8 * 3600, absolute_seconds: float = 24 * 3600,
                 clock=time.time):
        self.idle_seconds = idle_seconds          # 秒；调用方传 int/float 皆可（比较与加法不挑类型）
        self.absolute_seconds = absolute_seconds
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user: str) -> str:
        sid = secrets.token_urlsafe(32)                       # 登录成功即换发新 ID（防会话固定）
        now = self._clock()
        with self._lock:
            self._sessions[sid] = Session(user=user, csrf=secrets.token_urlsafe(24),
                                          created=now, last_seen=now)
        return sid

    def get(self, sid: str) -> Session | None:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            s = self._sessions.get(sid)
            if s is None:
                return None
            if now - s.last_seen > self.idle_seconds or now - s.created > self.absolute_seconds:
                del self._sessions[sid]
                return None
            s.last_seen = now
            return s

    def destroy(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def count(self) -> int:
        with self._lock:
            self._prune_locked(self._clock())
            return len(self._sessions)

    def _prune_locked(self, now: float) -> None:
        for sid, s in list(self._sessions.items()):
            if now - s.last_seen > self.idle_seconds or now - s.created > self.absolute_seconds:
                del self._sessions[sid]


class LoginGuard:
    """固定阈值硬锁定（规格决策 7）：用户名 5 次/5 分钟、IP 10 次/5 分钟，各锁 5 分钟。

    接受"按用户名锁可被恶意触发"的代价；成功登录清空该用户名与该 IP 的计数。
    """

    def __init__(self, user_limit: int = 5, user_window: float = 300.0,
                 ip_limit: int = 10, ip_window: float = 300.0,
                 lock_seconds: float = 300.0, clock=time.time):
        self.user_limit, self.user_window = user_limit, user_window
        self.ip_limit, self.ip_window = ip_limit, ip_window
        self.lock_seconds = lock_seconds
        self._clock = clock
        self._user_fails: dict[str, deque] = {}
        self._ip_fails: dict[str, deque] = {}
        self._user_locked: dict[str, float] = {}
        self._ip_locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked(self, user: str, ip: str) -> int:
        """剩余锁定秒数（向上取整）；0 = 未锁。"""
        now = self._clock()
        with self._lock:
            remaining = 0.0
            for key, table in ((user, self._user_locked), (ip, self._ip_locked)):
                until = table.get(key, 0.0)
                if until > now:
                    remaining = max(remaining, until - now)
                elif until:
                    table.pop(key, None)
            return math.ceil(remaining) if remaining > 0 else 0

    def fail(self, user: str, ip: str) -> None:
        now = self._clock()
        with self._lock:
            if len(self._record(self._user_fails, user, now, self.user_window)) >= self.user_limit:
                self._user_locked[user] = now + self.lock_seconds
            if len(self._record(self._ip_fails, ip, now, self.ip_window)) >= self.ip_limit:
                self._ip_locked[ip] = now + self.lock_seconds

    def success(self, user: str, ip: str) -> None:
        with self._lock:
            self._user_fails.pop(user, None)
            self._ip_fails.pop(ip, None)

    @staticmethod
    def _record(table: dict, key: str, now: float, window: float) -> deque:
        q = table.setdefault(key, deque())
        q.append(now)
        while q and now - q[0] > window:
            q.popleft()
        return q
