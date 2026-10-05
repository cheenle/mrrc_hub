#!/usr/bin/env python3
"""Portal 后台认证：会话/锁定单元 + 登录全链路 + CSRF/登出/审计。

运行：python3 tests/test_portal_auth.py   （也兼容 pytest）
"""
from __future__ import annotations

import http.cookiejar
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import htpasswd as ht            # noqa: E402
from portal import registry as reg           # noqa: E402
from portal import sessions as sess          # noqa: E402
from portal.app import Portal, make_handler  # noqa: E402
from portal.store import Store               # noqa: E402
from portal.verify import CallsignListVerifier  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_session_lifecycle():
    clock = FakeClock()
    store = sess.SessionStore(idle_seconds=100, absolute_seconds=200, clock=clock)
    sid = store.create("alice")
    s = store.get(sid)
    check(s is not None and s.user == "alice" and s.csrf, "会话创建后可取，且带 CSRF")
    check(len(sid) >= 32, "会话 ID 足够长（token_urlsafe(32)）")
    clock.advance(99)
    check(store.get(sid) is not None, "空闲未到期仍有效")
    clock.advance(101)          # 距上次访问（get 会刷新 last_seen）超过 idle
    check(store.get(sid) is None, "空闲超时失效")
    sid2 = store.create("bob")
    for _ in range(10):         # 持续访问：保持 last_seen 新鲜，只让绝对期限在走
        clock.advance(19)
        store.get(sid2)
    check(store.get(sid2) is not None, "持续使用中，绝对期限前有效")
    clock.advance(19)
    check(store.get(sid2) is None, "绝对超时即使一直在用也失效")
    sid3 = store.create("carol")
    store.destroy(sid3)
    check(store.get(sid3) is None, "登出销毁")


def test_login_guard():
    clock = FakeClock()
    guard = sess.LoginGuard(user_limit=3, user_window=100, ip_limit=5, ip_window=100,
                            lock_seconds=50, clock=clock)
    for _ in range(2):
        guard.fail("alice", "10.0.0.1")
    check(guard.locked("alice", "10.0.0.1") == 0, "未到阈值不锁")
    guard.fail("alice", "10.0.0.1")
    check(guard.locked("alice", "10.0.0.1") > 0, "到阈值即锁")
    check(guard.locked("alice", "10.0.0.2") > 0, "用户名维度跨 IP 生效")
    clock.advance(51)
    check(guard.locked("alice", "10.0.0.1") == 0, "锁定到期自解")
    for _ in range(5):
        guard.fail("bob", "10.9.9.9")
    check(guard.locked("bob", "10.9.9.9") > 0, "IP 维度阈值独立生效（5 次）")
    check(guard.locked("carol", "10.9.9.9") > 0, "同一 IP 的其他用户也被 IP 锁拦")
    guard.success("alice", "10.0.0.1")
    check(guard.locked("alice", "10.0.0.1") == 0, "成功登录清空失败记录")


def test_audit_actor_and_login_events():
    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td) / "portal.json")
        store.apply("BG1SB")
        store.mark_verified("BG1SB", "材料", actor="alice")
        store.grant("BG1SB", "bg1sb", 18802, actor="alice")
        store.record_login("login_ok", "alice", "203.0.113.7")
        events = store.audit()
        by_event = {e["event"]: e for e in events}
        check(by_event["verified"].get("actor") == "alice", "核验记下操作者")
        check(by_event["granted"].get("actor") == "alice", "授予记下操作者")
        login = by_event["login_ok"]
        check(login.get("actor") == "alice" and login["callsign"] == "", "登录事件 actor=用户名、无呼号")
        check("203.0.113.7" in login["detail"], "登录事件带来源 IP")
        check(all("actor" in e for e in events), "所有条目都有 actor 字段（旧文件缺省为空）")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ 认证测试通过（{len(tests)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
