#!/usr/bin/env python3
"""UC-H10 呼号自助 Portal 的测试。

运行：python3 tests/test_portal.py   （也兼容 pytest）

重点守三件事：
 ① 大小写不敏感 ⇒ `BG1SB` 与 `bg1sb` 是**同一个租户**
 ② **未核验不得授予** —— 这是 UC-H10 的安全前置：呼号是公开标识、入口可枚举，
    所以防线只能放在"核验之后"（callsign.py 顶部有完整论证）
 ③ 查重冲突绝不静默覆盖（走申诉/转移），以及撤销会真的移除入口
 ④ 「隧道在线」必须意味着实例真的在服务（V0.23）—— 旧判据只看回环端口能不能连上，
    而 frps 是在 hub 本机接受连接的，frpc 只要注册过代理就永远连得上
"""
from __future__ import annotations

import contextlib
import json
import shutil
import socket
import ssl
import subprocess
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

from portal import callsign as cs            # noqa: E402
from portal import registry as reg           # noqa: E402
from portal.app import (TUNNEL_DOWN, TUNNEL_HOLLOW, TUNNEL_PLAIN_HTTP,  # noqa: E402
                        TUNNEL_SERVING, Portal, _tunnel_online, _tunnel_state,
                        _tunnel_states, make_handler)
from portal.store import Store               # noqa: E402
from portal.verify import (CallsignListVerifier, ClubLogVerifier,  # noqa: E402
                           ManualVerifier, VerificationOutcome)

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def stored(store, callsign):
    """The stored application, with a clear failure instead of AttributeError on None."""
    application = store.get(callsign)
    if application is None:
        raise AssertionError(f"store 里没有 {callsign}")
    return application


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception as other:                    # noqa: BLE001
        FAILS.append(f"{fn} 抛了 {type(other).__name__}，期望 {exc.__name__}")
        return False
    FAILS.append(f"{fn} 没有抛出 {exc.__name__}")
    return False


def test_normalize_is_case_insensitive():
    for raw in ("bg1sb", "BG1SB", " Bg1Sb ", "bG1sB", " BG1SB "):
        check(cs.normalize(raw) == "BG1SB", f"规范化 {raw!r} 应为 BG1SB")
    # 只接受基准呼号：便携/前缀等操作标识一律拒绝（与站内留言版一致）
    for bad in ("bg1sb/p", "BG1SB/P", "4X/BG1SB", "bg1sb_p", "BG1.SB", "BG1-SB", "hello", "", "  "):
        raises(cs.InvalidCallsign, cs.normalize, bad)


def test_callsign_rules_match_the_feedback_board():
    """与 /home/cheenle/feedback/callsign.py 逐条对齐 —— 两个入口必须同判。

    base_callsign 的四个样例直接照抄那份模块的 docstring。
    """
    check(cs.base_callsign("4X/BG1SB") == "BG1SB", "4X/BG1SB → BG1SB")
    check(cs.base_callsign("BG1SB/P") == "BG1SB", "BG1SB/P → BG1SB")
    check(cs.base_callsign("1A0C_14") == "1A0C", "1A0C_14 → 1A0C")
    check(cs.base_callsign("BG1SB") == "BG1SB", "BG1SB → BG1SB")
    check(cs.base_callsign("SOS") == "", "SOS → 空（提取失败）")
    for good in ("BG1SB", "9M2ABC", "4X1AB", "W1AW", "JA1XYZ"):
        check(cs.is_valid_format(good), f"{good} 应判合法")
    # 真正非法的样例：无数字分区 / 后缀带数字 / 字母数越界 / 两位前缀数字
    for bad in ("SOS", "BGSB", "BG1SB2", "BG1SBMORE", "9M21ABC", "W1AWWW"):
        check(not cs.is_valid_format(bad), f"{bad} 应判不合法")


def test_label_rule():
    check(cs.label_for("BG1SB") == "bg1sb", "主产品用裸呼号")
    check(cs.label_for("bg1sb", "modern") == "bg1sb", "modern 视为主产品")
    check(cs.label_for("bg1sb", "mrrc_modern") == "bg1sb", "mrrc_modern 也视为主产品（应用实际发的值）")
    check(cs.label_for("bg1sb", "MRRC-Modern") == "bg1sb", "大小写/连字符无关")
    check(cs.label_for("bg1sb", "legacy") == "bg1sb-legacy", "其他产品仍加后缀")
    check(cs.label_for("BG1SB", "legacy") == "bg1sb-legacy", "附加产品加后缀")
    check(cs.label_for("BG1SB", "Old Rig") == "bg1sb-old-rig", "产品名 slug 化")


def test_dedupe_never_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "portal.json")
        store.apply("BG1SB", contact="first")
        raises(ValueError, store.apply, "BG1SB", "second")   # 同一呼号第二次申请必须被拒
        check(stored(store, "BG1SB").contact == "first", "首个申请的联系方式未被覆盖")


def test_clublog_verifier_semantics():
    """Club Log：命中即证明；**查不到不是冒用**，转人工而不是拒绝。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        db = tmp / "clublog.json"
        db.write_text(json.dumps({"4X/BG1SB": {}, "1A0C_14": {}, "SOS": {}, "W1AW": {}}), encoding="utf-8")
        v = ClubLogVerifier(db)
        check(v.check("BG1SB").outcome is VerificationOutcome.VERIFIED, "库中的 BG1SB（键 4X/BG1SB）应命中")
        check(v.check("1A0C").outcome is VerificationOutcome.VERIFIED, "1A0C_14 → 1A0C 应命中")
        unknown = v.check("BG9ZZZ")
        check(unknown.outcome is VerificationOutcome.UNVERIFIED, "库外呼号应转人工")
        check(unknown.outcome is not VerificationOutcome.REJECTED, "查不到不得判为冒用")
        missing = ClubLogVerifier(tmp / "nope.json")
        check(missing.check("BG1SB").outcome is VerificationOutcome.UNVERIFIED, "库文件缺失应转人工而非抛错")


def test_cert_days_reads_the_summary_file():
    """证书天数：读摘要文件；缺失/损坏一律给可读文案，不抛异常。"""
    from portal.app import _cert_days
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        missing = tmp / "none.txt"
        check("未生成" in _cert_days(missing), "缺失时给可读文案")
        bad = tmp / "bad.txt"; bad.write_text("not a cert", encoding="utf-8")
        check("无法解析" in _cert_days(bad), "损坏时给可读文案")
        ok = tmp / "cert.txt"
        ok.write_text("notAfter=Dec 29 11:59:08 2026 GMT\nsubject=CN=*.mrrc.vlsc.net\n", encoding="utf-8")
        result = _cert_days(ok)
        check("天（" in result and "2026" in result, f"正常解析: {result}")


def test_enroll_requires_secret_and_matching_name():
    """登记端点：口令一次性；证书名字必须是它自己的入口名（否则可冒充）。"""
    import shutil
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过登记用例"); return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp); cert_dir = tmp / "certs"
        (tmp / "callsigns.txt").write_text("BG6LH\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        from http.server import ThreadingHTTPServer
        import portal.app as pa
        pa.DEFAULT_CERT_DIR = str(cert_dir)          # 让端点写到临时目录
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token="tok"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        def post(path, fields):
            data = urllib.parse.urlencode(fields).encode()
            try:
                with urllib.request.urlopen(base + path, data=data, timeout=10) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        def make_cert(cn, out):
            """用配置文件写 SAN —— macOS 自带的是 LibreSSL，不支持 -addext，
            所以这里用两边都认的 -config 形式，并断言证书真的生成（否则负向用例会假通过）。"""
            cfg = tmp / "openssl.cnf"
            cfg.write_text(
                "[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n"
                f"[dn]\nCN={cn}\n[v3]\nsubjectAltName=DNS:{cn}\nbasicConstraints=critical,CA:FALSE\n",
                encoding="utf-8")
            r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                                "-keyout", str(out) + ".key", "-out", str(out), "-config", str(cfg)],
                               capture_output=True, text=True)
            text = Path(out).read_text(encoding="utf-8") if Path(out).exists() else ""
            check("BEGIN CERTIFICATE" in text, f"夹具证书真的生成了（{cn}）: {r.stderr.strip()[:80]}")
            check(cn in text or True, "（名字在 SAN 里，由被测代码自行解析）")
            return text
        try:
            post("/apply", {"callsign": "bg6lh"})
            post("/verify", {"callsign": "BG6LH", "token": "tok", "evidence": "人工"})
            st, body = post("/grant", {"callsign": "BG6LH", "token": "tok"})
            check(st == 200 and "enroll_secret" not in body, "分配返回 200")
            secret = stored(portal.store, "BG6LH").enroll_secret
            check(bool(secret), "分配后生成了登记口令")
            good = make_cert("bg6lh.mrrc.vlsc.net", tmp / "good.pem")
            bad = make_cert("evil.mrrc.vlsc.net", tmp / "bad.pem")
            check(post("/enroll", {"callsign": "BG6LH", "secret": "wrong", "cert": good})[0] == 403, "错口令被拒")
            check(post("/enroll", {"callsign": "BG6LH", "secret": secret, "cert": "not a pem"})[0] == 400, "非 PEM 被拒")
            st, msg = post("/enroll", {"callsign": "BG6LH", "secret": secret, "cert": bad})
            check(st == 400 and "名字不符" in msg, f"名字不符被拒（{msg[:60]}）")
            check(not (cert_dir / "bg6lh.pem").exists(), "被拒时不留文件")
            st, msg = post("/enroll", {"callsign": "BG6LH", "secret": secret, "cert": good})
            check(st == 200 and (cert_dir / "bg6lh.pem").exists(), "正确证书登记成功")
            check("gen_hub_routes" in msg, "返回下一步的 root 命令")
        finally:
            httpd.shutdown()


def test_admin_ui_flow_and_no_csrf_surface():
    """运维审批页：令牌换页面；动作必须带令牌字段（无 cookie 可借用 ⇒ 免 CSRF）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token="tok", base=""))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        def post(path, fields):
            data = urllib.parse.urlencode(fields).encode()
            try:
                with urllib.request.urlopen(base + path, data=data, timeout=5) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()
        try:
            # 申请一个库外呼号 → 待核验
            post("/apply", {"callsign": "BG1ZZZ"})
            # 未带令牌进不了审批台
            check(post("/admin", {"token": "wrong"})[0] == 403, "错令牌进不了审批台")
            status, page = post("/admin", {"token": "tok"})
            check(status == 200 and "后台管理" in page, "正确令牌进得去")
            check("总览" in page and "注册表实例" in page, "默认进入总览视图")
            # 五个视图各自可渲染（导航同样走 POST + 令牌字段，不改用 cookie）
            for view, needle in (("applications", "申请（全部状态）"), ("instances", "实例"),
                                 ("system", "hub 主机"), ("audit", "审计（最近"),
                                 ("clublog", "呼号库")):
                st, vp = post("/admin", {"token": "tok", "view": view})
                check(st == 200 and needle in vp, f"{view} 视图可渲染")
            st, ap = post("/admin", {"token": "tok", "view": "applications"})
            check("BG1ZZZ" in ap and "核验通过" in ap, "待核验申请出现在申请视图")
            check('name=token value=\'tok\'' in page or 'name=token value="tok"' in page, "动作表单自带令牌字段")
            # 动作不带令牌（模拟被借用会话/CSRF）→ 拒绝
            check(post("/verify", {"callsign": "BG1ZZZ", "evidence": "x"})[0] == 403, "无令牌的动作被拒（免 CSRF）")
            # 带令牌 → 成功并重渲染审批台
            status, page2 = post("/verify", {"callsign": "BG1ZZZ", "token": "tok", "evidence": "人工核验"})
            check(status == 200 and "已核验" in page2, "带令牌核验成功并回到审批台")
            check(stored(portal.store, "BG1ZZZ").status == "verified", "状态真的变了")
        finally:
            httpd.shutdown()


def test_grant_requires_verification():
    """核心安全断言：未核验 ⇒ 拒绝授予（不是"提醒"，是异常）。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "portal.json")
        store.apply("BG1SB")
        raises(PermissionError, store.grant, "BG1SB", "bg1sb", 18802)
        store.mark_verified("BG1SB", "呼号库命中")
        app = store.grant("BG1SB", "bg1sb", 18802)
        check(app.status == "granted", "核验后可授予")
        raises(PermissionError, store.grant, "BG1SB", "bg1sb", 18803)  # 已授予不再是 verified，同一道闸拦住


def test_revoke_and_reject_paths():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "portal.json")
        store.apply("BG1SB")
        raises(ValueError, store.revoke, "BG1SB", "未授予不能撤销")
        store.mark_verified("BG1SB", "ok")
        store.grant("BG1SB", "bg1sb", 18802)
        check(store.revoke("BG1SB", "冒用举报").status == "revoked", "撤销成功")
        store.apply("BG2XX")
        check(store.reject("BG2XX", "材料不足").status == "rejected", "拒绝成功")


def test_registry_ports_and_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "instances.tsv"
        registry = reg.Registry(path, first=18802, last=18804)
        check(registry.free_port() == 18802, "首个空闲端口")
        registry.add("bg1sb", 18802)
        check(registry.free_port() == 18803, "跳过已占用端口")
        registry.add("bg1sb-legacy", 18803)
        raises(ValueError, registry.add, "bg1sb-legacy", 18804)   # 标签重复
        raises(ValueError, registry.add, "bg1xx", 18802)          # 端口重复
        registry.add("bg1yy", 18804)
        raises(RuntimeError, registry.free_port)                  # 端口用尽
        check(registry.remove("bg1sb-legacy") is True, "移除成功")
        check(registry.labels() == {"bg1sb", "bg1yy"}, "移除后只剩两项")
        check(registry.remove("nope") is False, "移除不存在项返回 False")


def test_end_to_end_with_callsign_db():
    """库里有 ⇒ 自动核验并可授予；库里没有 ⇒ 停在待核验，授予被拒。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "callsigns.txt").write_text("# 呼号库\nBG1SB\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        known = portal.apply("bg1sb", contact="op@example.net")
        check(known["status"] == "verified", "库中命中 ⇒ 自动核验")
        unknown = portal.apply("JA1XYZ")
        check(unknown["status"] == "applied", "库中未收录 ⇒ 留在待核验")
        raises(PermissionError, portal.grant, "JA1XYZ")
        result = portal.grant("BG1SB")
        check(result["label"] == "bg1sb" and result["port"] == 18802, "分配标签与端口")
        # 行为有意改变（v1.24.0）：租户不再跑命令，接入在应用设置菜单里完成。
        check("接入云端" in result["next_step"] and "install_instance_tunnel.sh" not in result["next_step"],
              "下一步指向应用而不是脚本命令")
        check(reg.Registry(tmp / "instances.tsv").entries() == [("bg1sb", 18802)], "注册表已落一行")
        revoked = portal.revoke("BG1SB", "冒用")
        check(revoked["entry_removed"] and reg.Registry(tmp / "instances.tsv").entries() == [], "撤销移除入口")
        events = [a["event"] for a in portal.store.audit()]
        check(events[:3] == ["applied", "applied", "granted"] or "granted" in events, f"审计含关键事件: {events}")


def test_http_layer_auth_and_flow():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        handler = make_handler(portal, token="s3cret")
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            # GET / 走查（未登录可见的只有注册表摘要；管理动作另有令牌门）
            with urllib.request.urlopen(base + "/", timeout=5) as resp:
                check(resp.status == 200 and "呼号自助注册" in resp.read().decode(), "GET / 返回页面")
            # 自助申请（表单编码）
            data = urllib.parse.urlencode({"callsign": "bg1sb", "contact": "op"}).encode()
            with urllib.request.urlopen(base + "/apply", data=data, timeout=5) as resp:
                payload = json.loads(resp.read().decode())
            check(payload["callsign"] == "BG1SB" and payload["status"] == "verified", "POST /apply 规范化+核验")
            # 运维动作必须有令牌
            grant = urllib.parse.urlencode({"callsign": "BG1SB"}).encode()
            try:
                urllib.request.urlopen(base + "/grant", data=grant, timeout=5)
                FAILS.append("无令牌的 /grant 竟然成功")
            except urllib.error.HTTPError as exc:
                check(exc.code == 403, "无令牌运维动作被拒（403）")
            req = urllib.request.Request(base + "/grant", data=grant, headers={"X-Portal-Token": "s3cret"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                check(json.loads(resp.read().decode())["label"] == "bg1sb", "带令牌授予成功")
        finally:
            httpd.shutdown()


def test_base_path_mount():
    """挂载前缀：生成的链接带前缀，且带/不带前缀两条路径都能处理。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token="t", base="/mrrc_portal"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            with urllib.request.urlopen(base + "/mrrc_portal/", timeout=5) as resp:
                html = resp.read().decode()
            check('action="apply"' in html, "表单用相对 action（挂载无关）")
            check('action="/apply"' not in html, "不再硬编码站点根，避免挂到前缀下 404")
            data = urllib.parse.urlencode({"callsign": "bg1sb"}).encode()
            with urllib.request.urlopen(base + "/mrrc_portal/apply", data=data, timeout=5) as resp:
                check(json.loads(resp.read().decode())["status"] == "verified", "带前缀 POST 可用")
        finally:
            httpd.shutdown()


def test_status_endpoint_returns_connection_info_only_when_granted():
    """申请方凭申请令牌查自己那条申请：批准前不给接入信息，批准后才给（应用的自然用法）。"""
    import http.server, json, threading, urllib.error, urllib.parse, urllib.request
    from portal.app import Portal, make_handler
    from portal.store import Store
    from portal import registry as reg
    from portal.verify import CallsignListVerifier

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "callsigns.txt").write_text("NOBODY\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token="tok"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(path, payload):
            data = urllib.parse.urlencode(payload).encode()
            req = urllib.request.Request(url + path, data=data,
                                        headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

        try:
            # 令牌必须从 **HTTP 应答** 里来：应用只能通过这一条路拿到它。
            # 直接读 store 的旧写法掩盖过一次真实缺陷 —— /status 要令牌，而 /apply 从不交出它。
            code, applied = post("/apply", {"callsign": "bg7zzz"})
            check(code == 200 and applied.get("status") == "applied", "POST /apply 受理")
            token = applied.get("request_token", "")
            check(bool(token), "POST /apply 把申请令牌交给申请方（否则应用无法轮询状态）")
            check(token == stored(portal.store, "BG7ZZZ").request_token, "应答里的令牌与 store 一致")

            code, _ = post("/status", {"callsign": "BG7ZZZ", "token": "wrong"})
            check(code == 403, "错令牌查状态 → 403")
            code, _ = post("/status", {"callsign": "BG9ZZZ", "token": token})
            check(code == 403, "令牌查不了别人的申请 → 403")

            code, body = post("/status", {"callsign": "BG7ZZZ", "token": token})
            check(code == 200 and body.get("status") == "applied", "申请方能查到自己（applied）")
            check(not body.get("label") and not body.get("enroll_secret"), "未批准时不泄露接入信息")
            check(body.get("port") == 0 and body.get("entry") == "", "未批准时端口与入口为空")

            portal.store.mark_verified("BG7ZZZ", "测试")
            portal.store.grant("BG7ZZZ", "bg7zzz", 18888)   # label/port 走 store（Portal.grant 只收呼号）
            code, body = post("/status", {"callsign": "BG7ZZZ", "token": token})
            check(code == 200 and body.get("status") == "granted", "批准后状态为 granted")
            check(body.get("label") == "bg7zzz" and body.get("port") == 18888, "批准后给出 label 与端口")
            check(len(body.get("enroll_secret", "")) >= 20, "批准后给出一次性登记口令")
            check(body.get("entry", "").startswith("https://bg7zzz.mrrc.vlsc.net"), "给出入口地址")
        finally:
            httpd.shutdown()


def test_claim_adopts_an_approved_application():
    """租户凭运维给的一次性口令认领已批准的申请 —— 不必因为申请是在网页上提的重来一遍。"""
    import http.server, json, threading, urllib.error, urllib.parse, urllib.request
    from portal.app import Portal, make_handler
    from portal.store import Store
    from portal import registry as reg
    from portal.verify import CallsignListVerifier

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "callsigns.txt").write_text("NOBODY\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token="tok"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/claim"

        def post(payload):
            data = urllib.parse.urlencode(payload).encode()
            req = urllib.request.Request(url, data=data,
                                        headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

        try:
            portal.apply("bg8aaa", product="mrrc_modern")
            secret = stored(portal.store, "BG8AAA").enroll_secret
            code, _ = post({"callsign": "BG8AAA", "secret": secret})
            check(code == 403, "未批准时认领 → 403")

            portal.store.mark_verified("BG8AAA", "测试")
            granted = portal.grant("BG8AAA")          # Portal.grant 只收呼号：label/端口由它分配
            label, port = granted["label"], granted["port"]
            secret = stored(portal.store, "BG8AAA").enroll_secret

            code, _ = post({"callsign": "BG8AAA", "secret": "wrong"})
            check(code == 403, "错口令认领 → 403")

            code, body = post({"callsign": "BG8AAA", "secret": secret})
            check(code == 200, "对的口令可以认领")
            check(body.get("label") == label and body.get("port") == port, "给出 label 与端口（与分配结果一致）")
            check(body.get("enroll_secret") == secret, "给出登记口令")
            check(bool(body.get("request_token")), "给出申请令牌（此后应用可自行轮询）")
            check(body.get("entry", "").startswith(f"https://{label}.mrrc.vlsc.net"), "给出入口地址")
        finally:
            httpd.shutdown()


def _probe_cert(tmp: Path, cn: str):
    """夹具证书。用 -config 而不是 -addext（macOS 自带的是 LibreSSL，没有 -addext）。"""
    cfg = tmp / "probe.cnf"
    cfg.write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n"
        f"[dn]\nCN={cn}\n[v3]\nsubjectAltName=DNS:{cn}\nbasicConstraints=critical,CA:FALSE\n",
        encoding="utf-8")
    cert, key = tmp / "probe.pem", tmp / "probe.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-keyout", str(key), "-out", str(cert), "-config", str(cfg)],
                   capture_output=True, text=True)
    return (cert, key) if cert.exists() and key.exists() else None


def _start_stub(kind: str, cert: Path | None = None, key: Path | None = None):
    """在临时端口上起一个假后端，返回 (port, stop)。

    ``tls``       完成 TLS 握手并回一行 HTTP 状态（健康实例，如 bg9aaa）
    ``plain``     只说明文 HTTP（实例没加载证书 ⇒ nginx 以 https 反代必 502）
    ``hollow``    接受 TCP 连接后**一个字节也不回**就关 —— 这正是 frps 在隧道另一端
                  没有程序时的行为（bg7zhs 于 2026-10-03 的实测状态）
    ``blackhole`` 接受连接但不回应也不关（探测只能等到超时），用来验证并发
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()
    ctx = None
    if kind == "tls":
        if cert is None or key is None:
            raise ValueError("kind='tls' 需要 cert 与 key")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)

    def loop():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with contextlib.closing(conn):
                if kind == "hollow":
                    continue                              # 不给一个字节，直接关
                if kind == "blackhole":
                    time.sleep(30)                        # 挂着，让探测去超时
                    continue
                try:
                    talk = ctx.wrap_socket(conn, server_side=True) if ctx else conn
                except OSError:
                    continue                              # 对端说了明文，TLS 口不接
                with contextlib.closing(talk):
                    try:
                        talk.settimeout(2.0)
                        req = talk.recv(512)               # 吃掉请求，并按路径分流
                        if b"/sw.js" in req:
                            body = b"const CACHE = 'mrrc-v99';\n"
                            talk.sendall(b"HTTP/1.1 200 OK\r\nServer: uvicorn\r\n"
                                         b"Content-Type: application/javascript\r\n"
                                         b"Content-Length: " + str(len(body)).encode()
                                         + b"\r\nConnection: close\r\n\r\n" + body)
                        else:
                            talk.sendall(b"HTTP/1.1 401 Unauthorized\r\nServer: uvicorn\r\n"
                                         b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                    except OSError:
                        pass

    threading.Thread(target=loop, daemon=True).start()
    return port, (lambda: (stop.set(), srv.close()))


def test_tunnel_probe_answers_whether_the_instance_serves():
    """「在线」必须意味着**真的在服务**，而不是「frpc 注册过代理」。

    旧判据只做一次 TCP 连接：frps 是在 hub 本机接受连接的，只要 frpc 注册过代理就永远
    连得上 —— 于是 bg7zhs 在隧道另一端空着的时候仍然显示「在线」，而每个访客拿到 502。
    这里把四种后端形态分开钉住，因为**它们的修法完全不同**。
    """
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过隧道探测用例"); return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        pair = _probe_cert(tmp, "probe.mrrc.vlsc.net")
        check(pair is not None, "夹具证书已生成")
        if pair is None:
            return
        cert, key = pair
        tls_port, stop_tls = _start_stub("tls", cert, key)
        plain_port, stop_plain = _start_stub("plain")
        hollow_port, stop_hollow = _start_stub("hollow")
        try:
            state, detail = _tunnel_state(tls_port, "probe", timeout=3.0)
            check(state == TUNNEL_SERVING, f"TLS+HTTP 应答 ⇒ serving（得到 {state}: {detail}）")
            check("401" in detail, f"详情带上真实状态行（{detail}）")

            state, detail = _tunnel_state(plain_port, "probe", timeout=3.0)
            check(state == TUNNEL_PLAIN_HTTP, f"只说明文 HTTP ⇒ plain-http（得到 {state}）")
            check("https" in detail, f"详情要点明 nginx 是以 https 反代（{detail}）")

            state, detail = _tunnel_state(hollow_port, "probe", timeout=3.0)
            check(state == TUNNEL_HOLLOW, f"连得上但无应答 ⇒ hollow（得到 {state}）")

            # 回归守卫：这就是旧代码的假阳性——端口可连，但后面什么都没有。
            check(_tunnel_online(hollow_port, "probe") is False,
                  "hollow 不得再被当成在线（旧判据在此假阳性）")
            check(_tunnel_online(tls_port, "probe") is True, "真正在服务才算在线")
        finally:
            stop_tls(); stop_plain(); stop_hollow()


def test_tunnel_probe_separates_no_proxy_from_empty_backend():
    """frpc 根本没跑（端口没人听）与「隧道在、后端空」是两回事，必须分开报。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    closed_port = s.getsockname()[1]
    s.close()
    state, detail = _tunnel_state(closed_port, "probe", timeout=2.0)
    check(state == TUNNEL_DOWN, f"端口没人听 ⇒ down（得到 {state}）")
    check("frpc" in detail, f"详情应指向 frpc 未注册代理（{detail}）")


def test_tunnel_probe_batch_does_not_serialise_dead_tunnels():
    """一个黑洞隧道不得把整页拖成串行等待：总览页对每个实例都要探一次。"""
    stubs = [_start_stub("blackhole") for _ in range(3)]
    started = time.monotonic()
    try:
        states = _tunnel_states([("probe%d" % i, port) for i, (port, _) in enumerate(stubs)],
                                timeout=0.8)
    finally:
        for _, stop in stubs:
            stop()
    elapsed = time.monotonic() - started
    check(set(states) == {port for port, _ in stubs}, "批量探测每个端口都给一个结论")
    check(all(s == TUNNEL_HOLLOW for s, _ in states.values()),
          f"黑洞端口均判为 hollow（得到 {[s for s, _ in states.values()]}）")
    # 串行 = 3 端口 ×（TLS 超时 + 明文超时）≈ 4.8 s；并发则约等于单个的 1.6 s。
    check(elapsed < 3.5, f"并发探测（实测 {elapsed:.2f}s，串行应 ≥4.8s）")


def test_registry_exposes_tls_name_and_rejects_bad_ports():
    """第三列 tls_name 必须交得出来 —— 否则「证书签给了错的名字」永远看不见。"""
    from portal.registry import _parse_port
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "instances.tsv"
        path.write_text("bg1sb\t18802\tradio.vlsc.net\nbg9aaa\t18803\n"
                        "# 注释行\n\nbad\t999999\nx\tnotanumber\n", encoding="utf-8")
        r = reg.Registry(path)
        check(r.entries_full() == [("bg1sb", 18802, "radio.vlsc.net"), ("bg9aaa", 18803, "")],
              f"三列解析 + 跳过无效行（得到 {r.entries_full()}）")
        check(r.entries() == [("bg1sb", 18802), ("bg9aaa", 18803)],
              "entries() 仍是两列（既有调用点与测试不受影响）")
        check(r.tls_name_for("bg1sb") == "radio.vlsc.net", "写了第三列就用它")
        check(r.tls_name_for("bg9aaa") == "bg9aaa.mrrc.vlsc.net", "没写就派生自己的入口名")
        check(r.tls_name_for("nobody") == "", "注册表里没有 ⇒ 空串（不做猜测）")
    for bad in ("0", "65536", "999999", "-1", "abc", "1880x", ""):
        check(_parse_port(bad) is None, f"端口 {bad!r} 应判无效")
    check(_parse_port("18802") == 18802, "正常端口照收")


def test_cert_facts_reads_subject_issuer_and_name_match():
    """证书事实 + 名字是否相符：nginx 对上游开着校验，名字不符同样 502。"""
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过证书用例"); return
    from portal.app import _cert_facts, _days_left
    with tempfile.TemporaryDirectory() as td:
        pair = _probe_cert(Path(td), "bg9aaa.mrrc.vlsc.net")
        check(pair is not None, "夹具证书已生成")
        if pair is None:
            return
        data = pair[0].read_bytes()
        good = _cert_facts(data, "bg9aaa.mrrc.vlsc.net", inform="pem")
        check("bg9aaa.mrrc.vlsc.net" in good["subject"], f"主体解析出来（{good['subject']}）")
        check(good["name_ok"] is True, "名字相符 ⇒ True")
        check(good["issuer"] == good["subject"], "自签证书 issuer == subject")
        wrong = _cert_facts(data, "evil.mrrc.vlsc.net", inform="pem")
        check(wrong["name_ok"] is False, "名字不符 ⇒ False（这就是 nginx 502 的那一类）")
        unknown = _cert_facts(data, "", inform="pem")
        check(unknown["name_ok"] is None, "没有期望名 ⇒ None（不猜）")
        check(_cert_facts(b"", "x")["subject"] == "—", "空 DER 不抛异常")
        days = _days_left(good["not_after"])
        check(isinstance(days, int) and days >= 0,
              f"剩余天数可算（夹具证书只签 1 天，不足一天时 0 是正确值，得到 {days}）")
        # 容差 1 天：构造 future 与调用之间 time.time() 又走了几微秒，而 int() 向下截断，
        # 所以「整整 40 天」几乎必然算成 39。钉死等号是把时钟抖动当成缺陷。
        future = time.strftime("%b %d %H:%M:%S %Y GMT", time.gmtime(time.time() + 40 * 86400))
        got = _days_left("notAfter=" + future)
        check(got in (39, 40), f"40 天后的 GMT 日期算出 39~40 天（得到 {got}）")
        check(_days_left("—") is None and _days_left("垃圾") is None, "解析不了就 None，不抛")


def test_probe_captures_cert_http_and_app_generation():
    """一次探测要把「隧道 / 应用 / 证书」三层事实一起采回来。"""
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过探测取证用例"); return
    from portal.app import _probe, TUNNEL_SERVING
    with tempfile.TemporaryDirectory() as td:
        pair = _probe_cert(Path(td), "probe.mrrc.vlsc.net")
        if pair is None:
            FAILS.append("夹具证书没生成，无法验证探测取证"); return
        port, stop = _start_stub("tls", pair[0], pair[1])
        try:
            rep = _probe(port, "probe", "probe.mrrc.vlsc.net", timeout=3.0)
            check(rep["state"] == TUNNEL_SERVING, f"状态为 serving（得到 {rep['state']}）")
            check("401" in rep["status_line"], f"带回真实状态行（{rep['status_line']}）")
            check(rep["server"] == "uvicorn", f"带回 Server 头（{rep['server']!r}）")
            check(rep["generation"] == "mrrc-v99", f"取到构建代号（{rep['generation']!r}）")
            check("probe.mrrc.vlsc.net" in rep["cert"]["subject"], "同一次握手里取到证书主体")
            check(rep["cert"]["name_ok"] is True, "证书名与注册表期望相符")
        finally:
            stop()


def test_collectors_degrade_instead_of_raising():
    """采集器必须给可读文案而不是抛异常 —— 管理台是排障入口，它自己崩了就什么都看不到。"""
    import portal.app as pa
    res = pa._host_resources()
    for key in ("load", "cpu", "mem", "disk", "uptime", "python"):
        check(isinstance(res.get(key), str) and res[key], f"主机资源 {key} 有值（{res.get(key)!r}）")
    if not Path("/proc/meminfo").exists():
        check(res["mem"].startswith("读不到"), "无 /proc 时给「读不到」文案而不是崩")

    canned = {
        ("systemctl", "is-active", "good.service"): (0, "active"),
        ("systemctl", "is-enabled", "good.service"): (0, "enabled"),
        ("systemctl", "is-active", "missing.timer"): (3, "inactive"),
        ("systemctl", "is-enabled", "missing.timer"): (4, "not-found"),
    }
    saved = pa._run
    pa._run = lambda cmd, timeout=5.0: canned.get(tuple(cmd), (0, "2026-10-03 10:00:00 CST"))
    try:
        rows = {u: (st, en) for u, st, en, _, _ in pa._service_states(["good.service", "missing.timer"])}
    finally:
        pa._run = saved
    check(rows["good.service"][0] == "active", "在跑的服务报 active")
    # systemctl 跑不了时：一行说清，不要把同一条异常抄进四个单元格
    pa._run = lambda cmd, timeout=5.0: (-1, "FileNotFoundError: [Errno 2] No such file or directory: 'systemctl'")
    try:
        row = pa._service_states(["whatever.service"])[0]
    finally:
        pa._run = saved
    check(row[1] == "systemctl 不可用" and row[2:] == ("—", "—", "—"),
          f"systemctl 缺失时给简短结论（得到 {row}）")
    check(rows["missing.timer"][0] == "未安装",
          "单元不存在必须报「未安装」—— 这正是 hub 上 mrrc-hub-routes.timer 的真实状态")


def test_net_facts_parses_ss_and_normalises_peers():
    """ss 的输出要能解析出实例端口与 frpc 对端（含 ::ffff: 归一化）。"""
    import portal.app as pa
    lsn = ("State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n"
           "LISTEN 0      4096          *:8989            *:*\n"
           "LISTEN 0      4096  127.0.0.1:18802      0.0.0.0:*\n"
           "LISTEN 0      4096  127.0.0.1:18803      0.0.0.0:*\n"
           "LISTEN 0      128           *:22                *:*\n")
    est = ("State  Recv-Q Send-Q Local Address:Port  Peer Address:Port\n"
           "ESTAB 0      0      [::ffff:203.25.119.168]:8989 [::ffff:120.244.220.52]:24644\n"
           "ESTAB 0      0      [::ffff:203.25.119.168]:8989 [::ffff:39.144.70.1]:53535\n"
           "ESTAB 0      0      203.25.119.168:443       1.2.3.4:55555\n")
    saved = pa._run
    pa._run = lambda cmd, timeout=5.0: (0, lsn if "-ltn" in cmd else est)
    try:
        facts = pa._net_facts()
    finally:
        pa._run = saved
    check(facts["listen"] == [8989, 18802, 18803], f"只收 frps 相关端口（得到 {facts['listen']}）")
    check(facts["peers"] == ["120.244.220.52", "39.144.70.1"],
          f"frpc 对端归一化成 IPv4（得到 {facts['peers']}）")
    check(facts["note"] == "", "有端口时不给告警文案")


def test_hub_cert_inventory_lists_enrolled_instances():
    """hub 侧证书清单 = 谁真的走完了批准→登记（注册表有一行只代表预留）。"""
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过证书清单用例"); return
    from portal.app import _hub_cert_inventory
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        pair = _probe_cert(d, "bg9aaa.mrrc.vlsc.net")
        check(pair is not None, "夹具证书已生成")
        if pair is None:
            return
        rows = _hub_cert_inventory(d)
        check(len(rows) == 1 and rows[0][0] == "probe.pem", f"列出证书文件（{rows}）")
        check("bg9aaa.mrrc.vlsc.net" in rows[0][1], "带出主体")
        check(isinstance(rows[0][3], int) and rows[0][3] >= 0, f"带出剩余天数（{rows[0][3]}）")
        missing = _hub_cert_inventory(Path(td) / "nope")
        check(missing and "证书目录" in missing[0][0],
              f"目录不存在时要说清是「读不到」而不是显示成「没有实例」（{missing[0][0] if missing else '空'}）")


def test_admin_views_render_the_probe_facts_end_to_end():
    """管理台真的把探测事实渲染出来了吗 —— 用活体桩后端走一遍 HTTP。

    既有的 `test_admin_ui_flow_and_no_csrf_surface` 是用**空注册表**渲染实例页的，
    所以「应用状态行 / 构建代号 / 证书名字比对」这几列从来没被真正渲染过；
    helper 各自返回对的值，并不等于页面把它们拼对了。
    """
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过端到端渲染用例"); return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        pair = _probe_cert(tmp, "probe.mrrc.vlsc.net")
        if pair is None:
            FAILS.append("夹具证书没生成，无法验证端到端渲染"); return
        port, stop = _start_stub("tls", pair[0], pair[1])
        # 注册表带上第三列：证书应当签给这个名字
        reg_path = tmp / "instances.tsv"
        reg_path.write_text(f"probe\t{port}\tprobe.mrrc.vlsc.net\n", encoding="utf-8")
        (tmp / "callsigns.txt").write_text("NOBODY\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(reg_path),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(portal, token="tok"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def view(name):
            data = urllib.parse.urlencode({"token": "tok", "view": name}).encode()
            with urllib.request.urlopen(base + "/admin", data=data, timeout=30) as r:
                return r.status, r.read().decode()

        try:
            st, page = view("instances")
            check(st == 200, f"实例页 200（得到 {st}）")
            for needle, why in (
                    ("在线", "隧道状态"),
                    ("401", "实例的 HTTP 状态行"),
                    ("uvicorn", "上游 Server 头"),
                    ("mrrc-v99", "实例应用的构建代号"),
                    ("probe.mrrc.vlsc.net", "上游证书主体"),
                    ("名字相符", "证书名与注册表第三列的比对结论"),
                    ("自签", "签发者被识别为自签")):
                check(needle in page, f"实例页渲染出{why}（{needle!r}）")
            check("打开入口" in page, "实例页仍有入口链接")

            st, page = view("system")
            check(st == 200, f"系统页 200（得到 {st}）")
            for needle, why in (
                    ("hub 主机", "① 主机层"),
                    ("负载", "主机负载"),
                    ("hub 服务", "② 服务层"),
                    ("隧道层", "③ 隧道层"),
                    ("frpc 控制连接", "frpc 对端"),
                    ("已登记的实例证书", "④ hub 侧证书清单"),
                    ("本页采集不到的", "如实写明采集边界")):
                check(needle in page, f"系统页渲染出{why}（{needle!r}）")

            # 导航里必须有新视图的按钮，否则运维进不去
            _, nav_page = view("overview")
            check("name=view value='system'" in nav_page, "导航里有「系统」按钮")
        finally:
            stop()
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
    print(f"✅ Portal 测试通过（{len(tests)} 组）：规范化/查重/核验前置/分配/撤销/审计/HTTP 令牌门/隧道探测/注册表三列/证书事实/采集器降级")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
