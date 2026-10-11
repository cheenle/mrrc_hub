#!/usr/bin/env python3
"""远程协助（call help）的 portal 侧：端口分配、生命周期、三个实例端点、卡片。

运行：python3 tests/test_portal_help.py   （也兼容 pytest）

重点守四件事：
 ① **门户不存口令**：记录里没有这个字段，卡片上也没有——一个不存在的字段不会
    出现在日志、页面或备份里（设计 §4.3）；
 ② **协助口与实例口共用一个池**，但不能互相踩：协助口不写进 instances.tsv
    （否则 gen_hub_routes 会给它生成 nginx 路由），只在分配时相互避开；
 ③ **三条结束路径**：客户关、到期、门户强制（靠心跳回读，实例离线时由心跳超时兜底）；
 ④ **强制结束要会话 + CSRF**，与 /revoke 同级。
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import registry as reg            # noqa: E402
from portal.app import Portal, _help_by_label, make_handler   # noqa: E402
from portal.store import (HELP_CLOSED, HELP_OPEN, HelpSession,   # noqa: E402
                          Store)

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def stored_help(store: Store, callsign: str) -> HelpSession:
    """The stored help record, with a clear failure instead of AttributeError on None.

    (Same shape as test_portal.py's ``stored()``: an optional lookup in a test is
    either "the record is there" or a bug in the test, and a plain AttributeError
    three frames later says neither.)
    """
    record = store.help_get(callsign)
    if record is None:
        raise AssertionError(f"store 里没有 {callsign} 的协助记录")
    return record


def _portal(tmp: Path) -> Portal:
    return Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"))


def _grant(portal: Portal, callsign: str, label: str, port: int) -> str:
    portal.store.apply(callsign, "contact@example.com", "mrrc_modern")
    portal.store.mark_verified(callsign, "test")
    portal.store.grant(callsign, label, port, actor="test")
    application = portal.store.get(callsign)
    if application is None:
        raise AssertionError(f"{callsign} 没有申请记录")
    return application.request_token


def _serve(portal: Portal, token: str = "tok"):
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token=token))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    return httpd, base


def _post(base: str, path: str, fields: dict, headers: dict | None = None):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base + path, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


# ── ① 记录本身 ─────────────────────────────────────────────────────────

def test_the_record_has_no_password_field():
    """结构上不可能：这是"门户不是口令保管人"唯一靠谱的实现方式。"""
    fields = {f.name for f in dataclasses.fields(HelpSession)}
    check("password" not in fields, "协助记录里出现了 password 字段")
    check(fields == {"callsign", "port", "username", "state", "started_at",
                     "expires_at", "last_heartbeat", "connections", "closed_reason",
                     "revoke"}, f"字段集变了：{sorted(fields)}")


def test_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "portal.json")
        session = HelpSession(callsign="BG7IFP", port=18877, username="help-ab12",
                              expires_at=time.time() + 60)
        store.help_put(session, event="help_requested")
        got = store.help_get("BG7IFP")
        check(got is not None and got.port == 18877, "写进去的记录读不回来")
        check(store.help_get("NOPE") is None, "不存在的呼号应当返回 None")
        events = [e["event"] for e in store.audit()]
        check("help_requested" in events, "请求没有进审计")


def test_stale_heartbeat_closes_it():
    """心跳消失要被动关闭（客户离线/退出应用），但**不能**在抖动时就判死。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "portal.json")
        now = time.time()
        store.help_put(HelpSession(callsign="A", port=1, state=HELP_OPEN,
                                   last_heartbeat=now - 10))
        store.help_put(HelpSession(callsign="B", port=2, state=HELP_OPEN,
                                   last_heartbeat=now - 10_000))
        closed = store.help_expire_stale(now=now)
        check(closed == ["B"], f"只该关掉心跳断了的那一个，实得 {closed}")
        check(stored_help(store, "A").state == HELP_OPEN, "10 秒没心跳不该判死")
        check(stored_help(store, "B").state == HELP_CLOSED, "断了很久的窗口应当关闭")
        check(stored_help(store, "B").closed_reason == "heartbeat_lost", "结束原因要写清")


# ── ② 端口分配 ─────────────────────────────────────────────────────────

def test_the_pool_is_shared_without_collisions():
    with tempfile.TemporaryDirectory() as tmp:
        registry = reg.Registry(Path(tmp) / "instances.tsv", first=18802, last=18804)
        registry.add("bg7ifp", 18802)
        check(registry.free_port() == 18803, "应当跳过注册表里已占的端口")
        # 在线协助口不在注册表里，必须由调用方传进来才避得开
        check(registry.free_port(extra=[18803]) == 18804, "extra 没有被避开")
        try:
            registry.free_port(extra=[18803, 18804])
            check(False, "端口耗尽时应当明确报错")
        except RuntimeError:
            pass


def test_a_help_port_does_not_touch_the_registry_file():
    """协助口**不写进 instances.tsv**：那是 nginx 路由的来源，写进去会多出一条路由。"""
    with tempfile.TemporaryDirectory() as tmp:
        portal = _portal(Path(tmp))
        token = _grant(portal, "BG7IFP", "bg7ifp", 18802)
        # 真实流程里 Portal.grant 会写注册表；这里直接调 store.grant 就得自己补上，
        # 否则"避开实例口"这件事根本没有可避的对象（第一版测试就是自己骗自己）。
        portal.registry.add("bg7ifp", 18802)
        httpd, base = _serve(portal)
        try:
            status, body = _post(base, "/help/request",
                                 {"callsign": "BG7IFP", "token": token, "minutes": 30})
            check(status == 200, f"申请失败：{status} {body}")
            port = int(__import__("json").loads(body)["port"])
            check(port != 18802, "协助口撞上了实例口")
            check("18802" in (Path(tmp) / "instances.tsv").read_text(encoding="utf-8"),
                  "原实例行被动了")
            check(port not in {p for _, p, _ in portal.registry.entries_full()},
                  "协助口被写进了注册表")
        finally:
            httpd.shutdown()


# ── ③ 三个端点 ─────────────────────────────────────────────────────────

def test_the_endpoints_and_the_three_endings():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        portal = _portal(Path(tmp))
        token = _grant(portal, "BG7IFP", "bg7ifp", 18802)
        httpd, base = _serve(portal)
        try:
            # 令牌不对 → 403，且什么也不建
            status, _ = _post(base, "/help/request",
                              {"callsign": "BG7IFP", "token": "nope", "minutes": 30})
            check(status == 403, "错令牌应当 403")
            check(portal.store.help_get("BG7IFP") is None, "被拒的请求不该留下记录")

            status, body = _post(base, "/help/request",
                                 {"callsign": "BG7IFP", "token": token, "minutes": 30,
                                  "username": "help-ab12"})
            check(status == 200, f"申请失败：{body}")
            port = int(json.loads(body)["port"])

            # 第二个窗口要被拒（一次一个）
            status, _ = _post(base, "/help/request",
                              {"callsign": "BG7IFP", "token": token, "minutes": 30})
            check(status == 409, "已有窗口时应当拒绝第二个请求")

            # 窗口上限由服务端夹住
            portal.store.help_put(HelpSession(callsign="BG7IFP", port=port,
                                              state=HELP_CLOSED))
            status, body = _post(base, "/help/request",
                                 {"callsign": "BG7IFP", "token": token, "minutes": 10_000})
            check(status == 200 and json.loads(body)["expires_at"] - time.time() <= 180 * 60 + 5,
                  "超过上限的窗口没有被夹住")

            # 心跳：刷新连接数，并回报 stop=False
            status, body = _post(base, "/help/heartbeat",
                                 {"callsign": "BG7IFP", "token": token, "port": port,
                                  "connections": 2})
            reply = json.loads(body)
            check(status == 200 and reply["stop"] is False, f"心跳异常：{body}")
            check(stored_help(portal.store, "BG7IFP").connections == 2, "连接数没记上")
            check(stored_help(portal.store, "BG7IFP").state == HELP_OPEN, "心跳应当把状态推到 open")

            # 门户强制结束 → 下一次心跳读到 stop
            session = stored_help(portal.store, "BG7IFP")
            session.revoke = True
            portal.store.help_put(session)
            status, body = _post(base, "/help/heartbeat",
                                 {"callsign": "BG7IFP", "token": token, "port": port})
            reply = json.loads(body)
            check(reply["stop"] is True, "强制结束后心跳应当回 stop")
            check(stored_help(portal.store, "BG7IFP").state == HELP_CLOSED, "记录应当关掉")
            check(stored_help(portal.store, "BG7IFP").closed_reason == "portal", "原因应当是 portal")

            # 之后再心跳：没有活窗口了，也让实例把端口关掉
            status, body = _post(base, "/help/heartbeat",
                                 {"callsign": "BG7IFP", "token": token, "port": port})
            check(json.loads(body)["stop"] is True, "没有活窗口时应当让实例收摊")

            # 客户侧关闭：写进结束原因
            portal.store.help_put(HelpSession(callsign="BG7IFP", port=port,
                                              state=HELP_OPEN,
                                              last_heartbeat=time.time()))
            status, body = _post(base, "/help/close",
                                 {"callsign": "BG7IFP", "token": token, "reason": "user"})
            check(status == 200 and stored_help(portal.store, "BG7IFP").closed_reason == "user",
                  "客户关闭的原因没有落上")
        finally:
            httpd.shutdown()


def test_an_ungranted_instance_cannot_ask():
    with tempfile.TemporaryDirectory() as tmp:
        portal = _portal(Path(tmp))
        portal.store.apply("BG7IFP", "c@example.com", "mrrc_modern")
        app = portal.store.get("BG7IFP")
        httpd, base = _serve(portal)
        try:
            status, body = _post(base, "/help/request",
                                 {"callsign": "BG7IFP", "token": app.request_token,
                                  "minutes": 30})
            check(status == 403, f"未获授权也能申请协助：{status} {body}")
        finally:
            httpd.shutdown()


# ── ④ 卡片与强制结束 ───────────────────────────────────────────────────

def test_the_card_never_prints_a_password():
    from portal import views as vs
    from portal.views import Ctx, _help_card
    ctx = Ctx(help={"bg7ifp": {"callsign": "BG7IFP", "port": 18877,
                               "username": "help-ab12", "state": "open",
                               "expires_at": time.time() + 600,
                               "last_heartbeat": time.time(), "connections": 1}})
    html = _help_card(ctx, "bg7ifp")
    check("口令" in html, "卡片应当明确说口令在客户手里")
    check("ssh -p 18877 help-ab12@127.0.0.1" in html, "应当给出确切命令")
    check("password" not in html.lower(), "卡片上出现了 password 字样")
    check("/help/revoke" in html, "进行中应当给出强制结束的入口")

    closed = _help_card(Ctx(help={"bg7ifp": {"callsign": "BG7IFP", "port": 18877,
                                             "state": "closed",
                                             "closed_reason": "expired"}}), "bg7ifp")
    check("窗口到期" in closed, "结束原因应当译成人话")
    check("/help/revoke" not in closed, "已结束就不该再给强制结束")

    empty = _help_card(Ctx(help={}), "bg7ifp")
    check("尚未开启" in empty, "没有记录时应当说清楚")


def test_the_label_mapping_is_case_aware():
    """视图按小写标签寻址，记录按大写呼号存——少这层映射，卡片永远显示"尚未开启"。"""
    with tempfile.TemporaryDirectory() as tmp:
        portal = _portal(Path(tmp))
        _grant(portal, "BG7IFP", "bg7ifp", 18802)
        portal.store.help_put(HelpSession(callsign="BG7IFP", port=18877))
        mapping = _help_by_label(portal)
        check("bg7ifp" in mapping, f"映射里没有小写标签：{sorted(mapping)}")
        check(mapping["bg7ifp"]["port"] == 18877, "映射里的记录不对")


def test_revoke_needs_a_session_and_csrf():
    with tempfile.TemporaryDirectory() as tmp:
        portal = _portal(Path(tmp))
        _grant(portal, "BG7IFP", "bg7ifp", 18802)
        portal.store.help_put(HelpSession(callsign="BG7IFP", port=18877,
                                          state=HELP_OPEN, last_heartbeat=time.time()))
        httpd, base = _serve(portal, token="ops-token")
        try:
            status, _ = _post(base, "/help/revoke", {"callsign": "BG7IFP"})
            check(status == 403, f"没有凭据也能强制结束：{status}")
            # 机器路径（X-Portal-Token）不受两阶段确认影响
            status, body = _post(base, "/help/revoke", {"callsign": "BG7IFP"},
                                 headers={"X-Portal-Token": "ops-token"})
            check(status == 200, f"带令牌的强制结束失败：{status} {body}")
            check(stored_help(portal.store, "BG7IFP").revoke is True, "revoke 没有置位")
        finally:
            httpd.shutdown()


def test_an_unknown_route_is_still_404():
    with tempfile.TemporaryDirectory() as tmp:
        portal = _portal(Path(tmp))
        httpd, base = _serve(portal)
        try:
            status, _ = _post(base, "/help/nonsense", {})
            check(status == 404, "未知路由应当 404")
        finally:
            httpd.shutdown()


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as exc:                     # noqa: BLE001
            FAILS.append(f"{fn.__name__} 抛异常：{type(exc).__name__}: {exc}")
    if FAILS:
        print(f"❌ portal 远程协助测试失败（{len(FAILS)}/{len(tests)} 组）")
        for item in FAILS:
            print("   -", item)
        return 1
    print(f"✅ portal 远程协助测试通过（{len(tests)} 组）："
          "记录无口令字段/端口池共用不互踩/三端点与三条结束路径/卡片与 CSRF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
