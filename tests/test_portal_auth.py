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


USERS_TEXT = "ops:" + ht.apr1("str0ng-pass", "saltward") + "\n"


def _auth_env(tmp: Path, base="", cookie_secure="auto"):
    """起一个带账号文件的 Portal：返回 (base_url, portal, httpd)。"""
    (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
    users_path = tmp / "portal-users"
    users_path.write_text(USERS_TEXT, encoding="utf-8")
    portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                    CallsignListVerifier(tmp / "callsigns.txt"))
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        portal, token="tok", base=base, users=ht.UsersFile(users_path),
        sessions=sess.SessionStore(), guard=sess.LoginGuard(), cookie_secure=cookie_secure))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", portal, httpd


def _opener(no_follow=False):
    jar = http.cookiejar.CookieJar()
    if no_follow:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        return (urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect()),
                jar)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def _get(opener, url):
    try:
        with opener.open(url, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def _post(opener, url, fields):
    data = urllib.parse.urlencode(fields).encode()
    try:
        with opener.open(url, data=data, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def _csrf_from(page: str) -> str:
    m = (re.search(r"name=csrf value='([^']+)'", page)
         or re.search(r'name=csrf value="([^"]+)"', page))
    if not m:
        raise AssertionError("管理台表单里找不到 csrf 隐藏字段")
    return m.group(1)


def test_login_flow_and_csrf():
    with tempfile.TemporaryDirectory() as td:
        base, portal, httpd = _auth_env(Path(td))
        try:
            op, jar = _opener()
            st, page, _ = _get(op, base + "/admin")
            check(st == 200 and "用户名" in page and "密码" in page, "未登录看到登录页")
            st, page, _ = _post(op, base + "/admin/login", {"user": "ops", "password": "wrong"})
            check(st == 401 and "不正确" in page, "错密码 401 且文案不区分用户是否存在")
            st, page, _ = _post(op, base + "/admin/login", {"user": "ghost", "password": "wrong"})
            check(st == 401 and "不正确" in page, "不存在的用户同文案")
            st, page, _ = _post(op, base + "/admin/login", {"user": "ops", "password": "str0ng-pass"})
            check(st == 200 and "后台管理" in page, "正确密码登录后跟到管理台")
            # Cookie 属性直接从原始 Set-Cookie 头断言：http.cookiejar 不保留 HttpOnly。
            op_nf, _ = _opener(no_follow=True)
            st, _, hdr = _post(op_nf, base + "/admin/login",
                               {"user": "ops", "password": "str0ng-pass"})
            set_cookie = hdr.get("Set-Cookie", "")
            check(st == 303 and "HttpOnly" in set_cookie, "Cookie 带 HttpOnly")
            check("SameSite=Lax" in set_cookie, "Cookie 带 SameSite=Lax")
            check("Secure" not in set_cookie, "回环 Host（auto 策略）不带 Secure，便于本机 SSH 隧道登录")
            st, page, _ = _get(op, base + "/admin?view=system")
            check(st == 200 and "后台管理" in page and "hub 主机" in page, "会话可切换视图")
            portal.store.apply("BG1SB")
            st, _, _ = _post(op, base + "/verify", {"callsign": "BG1SB", "evidence": "人工"})
            check(st == 403, "有会话但没有 CSRF 的动作被拒")
            csrf = _csrf_from(page)
            st, page2, _ = _post(op, base + "/verify",
                                 {"callsign": "BG1SB", "evidence": "人工核验", "csrf": csrf})
            check(st == 200 and "已核验" in page2, "会话+CSRF 动作成功并回到管理台")
            verified = portal.store.get("BG1SB")
            check(verified is not None and verified.status == "verified", "状态真的变了")
            check(portal.store.audit()[-1]["actor"] == "ops", "动作审计记下操作者")
            st, _, _ = _post(op, base + "/admin/logout", {})
            check(st == 403, "登出也要 CSRF")
            st, page3, _ = _post(op, base + "/admin/logout", {"csrf": csrf})
            check(st == 200 and "用户名" in page3, "登出后回到登录页")
            st, page4, _ = _get(op, base + "/admin")
            check(st == 200 and "用户名" in page4, "旧 Cookie 已失效（需要重新登录）")
        finally:
            httpd.shutdown()


def test_cookie_secure_modes_and_host_rule():
    from portal.app import _host_is_loopback
    for host, expect, why in (("127.0.0.1:8890", True, "IPv4 回环"),
                              ("localhost:8890", True, "localhost"),
                              ("[::1]:8890", True, "IPv6 回环"),
                              ("portal.mrrc.vlsc.net", False, "公网域名"),
                              ("", False, "缺 Host") ):
        check(_host_is_loopback(host) is expect, f"Host 判定：{why}")
    with tempfile.TemporaryDirectory() as td:
        base, _, httpd = _auth_env(Path(td), cookie_secure="on")
        try:
            op, _ = _opener(no_follow=True)
            st, _, hdr = _post(op, base + "/admin/login", {"user": "ops", "password": "str0ng-pass"})
            check(st == 303 and "Secure" in hdr.get("Set-Cookie", ""),
                  "cookie_secure=on 时带 Secure（公网形态）")
        finally:
            httpd.shutdown()


def test_token_header_still_works_and_lockout():
    with tempfile.TemporaryDirectory() as td:
        base, portal, httpd = _auth_env(Path(td))
        try:
            op, _ = _opener()
            portal.store.apply("BG1SB")
            portal.store.mark_verified("BG1SB", "x")
            req = urllib.request.Request(
                base + "/grant",
                data=urllib.parse.urlencode({"callsign": "BG1SB"}).encode(),
                headers={"X-Portal-Token": "tok"})
            with urllib.request.urlopen(req, timeout=10) as r:
                check(r.status == 200, "令牌请求头路径不回归")
            check(portal.store.audit()[-1]["actor"] == "token", "令牌动作 actor=token")
            for _ in range(5):
                _post(op, base + "/admin/login", {"user": "ops", "password": "nope"})
            st, page, hdr = _post(op, base + "/admin/login", {"user": "ops", "password": "str0ng-pass"})
            check(st == 429, "5 次失败后即使密码正确也被锁")
            check("Retry-After" in hdr, "锁定响应带 Retry-After")
        finally:
            httpd.shutdown()


def test_redirect_target_follows_the_request_prefix():
    """Location 按请求路径推导：挂根 → /admin；挂前缀 → /mrrc_portal/admin。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        users_path = tmp / "portal-users"
        users_path.write_text(USERS_TEXT, encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            portal, token="tok", base="/mrrc_portal", users=ht.UsersFile(users_path)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            for path, expect in (("/admin/login", "/admin"),
                                 ("/mrrc_portal/admin/login", "/mrrc_portal/admin")):
                op, _ = _opener(no_follow=True)
                st, _, hdr = _post(op, base + path, {"user": "ops", "password": "str0ng-pass"})
                check(st == 303 and hdr.get("Location") == expect,
                      f"{path} 的 Location 应为 {expect}（得到 {hdr.get('Location')!r}）")
            op, _ = _opener(no_follow=True)
            st, page, _ = _get(op, base + "/mrrc_portal/admin")
            check(st == 200 and "action='/mrrc_portal/admin/login'" in page,
                  "前缀形态的登录表单动作带前缀")
        finally:
            httpd.shutdown()


def test_admin_urls_are_absolute_and_paths_normalize():
    """登录失败重渲染后表单不能再被相对拼接；/admin/ 与 /admin/login 也不能 404。

    现场事故（2026-10-05）：密码错一次后浏览器地址停在 /admin/login，
    裸相对 action="admin/login" 被拼成 /admin/admin/login → 404。
    """
    with tempfile.TemporaryDirectory() as td:
        base, _, httpd = _auth_env(Path(td))
        try:
            op, _ = _opener(no_follow=True)
            st, page, _ = _get(op, base + "/admin")
            check(st == 200 and "action='/admin/login'" in page,
                  "登录表单用绝对 action='/admin/login'")
            st, page, _ = _post(op, base + "/admin/login", {"user": "ops", "password": "bad"})
            check(st == 401 and "action='/admin/login'" in page,
                  "失败重渲染的表单仍是绝对路径（不会再拼成 /admin/admin/login）")
            st, page, _ = _get(op, base + "/admin/")
            check(st == 200 and "用户名" in page, "/admin/（尾斜杠）也是登录页")
            st, page, _ = _get(op, base + "/admin/login")
            check(st == 200 and "用户名" in page, "直连 /admin/login 也是登录页")
            op2, _ = _opener(no_follow=True)
            _post(op2, base + "/admin/login", {"user": "ops", "password": "str0ng-pass"})
            st, _, hdr = _get(op2, base + "/admin/login")
            check(st == 303 and hdr.get("Location") == "/admin",
                  "已登录直连 /admin/login → 303 /admin")
        finally:
            httpd.shutdown()


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
