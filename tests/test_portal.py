#!/usr/bin/env python3
"""UC-H10 呼号自助 Portal 的测试。

运行：python3 tests/test_portal.py   （也兼容 pytest）

重点守三件事：
 ① 大小写不敏感 ⇒ `BG1SB` 与 `bg1sb` 是**同一个租户**
 ② **未核验不得授予** —— 这是 UC-H10 的安全前置：呼号是公开标识、入口可枚举，
    所以防线只能放在"核验之后"（callsign.py 顶部有完整论证）
 ③ 查重冲突绝不静默覆盖（走申诉/转移），以及撤销会真的移除入口
"""
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import callsign as cs            # noqa: E402
from portal import registry as reg           # noqa: E402
from portal.app import Portal, make_handler  # noqa: E402
from portal.store import Store               # noqa: E402
from portal.verify import (CallsignListVerifier, ClubLogVerifier,  # noqa: E402
                           ManualVerifier, VerificationOutcome)

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


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
    check(cs.label_for("BG1SB", "legacy") == "bg1sb-legacy", "附加产品加后缀")
    check(cs.label_for("BG1SB", "Old Rig") == "bg1sb-old-rig", "产品名 slug 化")


def test_dedupe_never_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "portal.json")
        store.apply("BG1SB", contact="first")
        raises(ValueError, store.apply, "BG1SB", "second")   # 同一呼号第二次申请必须被拒
        check(store.get("BG1SB").contact == "first", "首个申请的联系方式未被覆盖")


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
                                 ("audit", "审计（最近"), ("clublog", "呼号库")):
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
            check(portal.store.get("BG1ZZZ").status == "verified", "状态真的变了")
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
        check("install_instance_tunnel.sh bg1sb 18802" in result["next_step"], "给出实例侧上线命令")
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


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ Portal 测试通过（{len(tests)} 组）：规范化/查重/核验前置/分配/撤销/审计/HTTP 令牌门")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
