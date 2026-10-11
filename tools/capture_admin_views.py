#!/usr/bin/env python3
"""抓取后台 7 个视图的渲染输出，用于"搬移前后逐字节等价"的证明。

关键点：把**所有易变的采集器**都替换成确定性桩（主机负载、服务状态、网卡、
证书清单、隧道探测、实例报告、呼号库信息），否则输出里混着 loadavg 与文件
mtime，diff 出来的全是噪音。

用法：python3 tools/capture_admin_views.py <输出目录>
"""
from __future__ import annotations

import http.cookiejar
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import portal.app as app_mod                      # noqa: E402
from portal import htpasswd as ht                 # noqa: E402
from portal import registry as reg                # noqa: E402
from portal.app import Portal, make_handler       # noqa: E402
from portal.store import Store                    # noqa: E402
from portal.verify import CallsignListVerifier    # noqa: E402

VIEWS = ("overview", "applications", "instances", "tunnel", "system", "audit", "clublog")

FIXED_STATES = {
    18804: (app_mod.TUNNEL_SERVING, "握手成功，拿到 HTTP 200"),
    18805: (app_mod.TUNNEL_HOLLOW, "隧道在、后端无应答"),
}
FIXED_REPORTS = {
    "bg1sb": {"state": app_mod.TUNNEL_SERVING, "detail": "握手成功，拿到 HTTP 200",
              "status_line": "HTTP/1.1 401 Unauthorized", "server": "uvicorn",
              "generation": "mrrc-v99",
              "cert": {"subject": "bg1sb.mrrc.vlsc.net", "issuer": "bg1sb.mrrc.vlsc.net",
                       "not_after": "Nov 18 00:00:00 2026 GMT", "name_ok": True}},
    "bg7zhs": {"state": app_mod.TUNNEL_HOLLOW, "detail": "隧道在、后端无应答",
               "status_line": "", "server": "", "generation": "", "cert": {}},
}


class _Last:
    latency_ms = 12.0
    out_bps = 2048.0
    in_bps = 1024.0
    today_out = 8192
    today_in = 4096
    cur_conns = 2
    tunnel_state = app_mod.TUNNEL_SERVING
    tunnel_detail = "握手成功"
    note = ""


class _StubSampler:
    def snapshot(self):
        return {"labels": {"bg1sb": {"last": _Last(), "latency_mean": 14.0, "latency_peak": 38.0,
                                     "history": [10, 12, None, 14, 11],
                                     "out_mean": 2048.0, "in_mean": 1024.0, "stale_s": 3}},
                "panel_error": "", "panel_age": 5.0,
                "nic": {"rx_bps": 4096.0, "tx_bps": 1024.0}, "interval": 30.0}


def _patch_collectors(register):
    """把易变事实换成确定性桩；返回恢复函数。"""
    originals = {name: getattr(app_mod, name) for name in (
        "_host_resources", "_service_states", "_net_facts", "_hub_cert_inventory",
        "_cert_days", "_clublog_info", "_tunnel_states", "_instance_reports")}
    app_mod._host_resources = lambda: {
        "load": "0.31 0.28 0.25", "cpu": "1 核", "mem": "可用 900 MB / 共 1914 MB（47% 可用）",
        "disk": "/ 可用 7000 MB / 共 13721 MB（已用 51%）", "uptime": "42 天 3 小时", "python": "3.13.0"}
    app_mod._service_states = lambda units=None: [
        ("frps", "active", "enabled", "2026-10-01 08:00:00", "0"),
        ("mrrc-hub-routes.timer", "未安装", "not-found", "—", "—")]
    app_mod._net_facts = lambda: {"listen": [8989, 18804, 18805], "peers": ["1.2.3.4:5000"],
                                  "note": ""}
    app_mod._hub_cert_inventory = lambda cert_dir=None: [
        ("bg1sb.pem", "bg1sb.mrrc.vlsc.net", "Nov 18 00:00:00 2026 GMT", 38)]
    app_mod._cert_days = lambda path=None: "38"
    app_mod._clublog_info = lambda: "273047 条 · 最后同步 2026-10-11 04:30"
    app_mod._tunnel_states = lambda entries, timeout=2.5: {p: FIXED_STATES[p] for _l, p in entries
                                                           if p in FIXED_STATES}
    app_mod._instance_reports = lambda entries_full, timeout=2.5: dict(FIXED_REPORTS)
    register(originals)

    def restore():
        for name, fn in originals.items():
            setattr(app_mod, name, fn)
    return restore


def main() -> int:
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/admin-golden")
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "instances.tsv").write_text(
            "bg1sb\t18804\tbg1sb.mrrc.vlsc.net\nbg7zhs\t18805\n", encoding="utf-8")
        (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
        users = tmp / "portal-users"
        users.write_text("ops:" + ht.apr1("pw-123456789", "saltward") + "\n", encoding="utf-8")

        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        # 固定 fixture：覆盖 5 种状态各一条，让分组/动作/徽章都有内容可渲染。
        # 走**真实的 store API**而不是改内部字段 —— 顺手验证状态机本身。
        portal.store.apply("BG8XYZ", contact="138****", product="")
        portal.store.apply("BG2ABC")
        portal.store.mark_verified("BG2ABC", "命中呼号库", actor="ops")
        portal.store.apply("BG3DEF")
        portal.store.mark_verified("BG3DEF", "人工核验通过", actor="ops")
        portal.store.grant("BG3DEF", "bg3def", 18808, actor="ops")
        portal.store.apply("BG4GHI")
        portal.store.reject("BG4GHI", "材料不足", actor="ops")
        portal.store.apply("BG5JKL")
        portal.store.mark_verified("BG5JKL", "人工核验通过", actor="ops")
        portal.store.grant("BG5JKL", "bg5jkl", 18809, actor="ops")
        portal.store.revoke("BG5JKL", "冒用被举报", actor="ops")

        restore = _patch_collectors(lambda o: None)
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
                portal, token="tok", users=ht.UsersFile(users), sampler=_StubSampler()))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            opener.open(base + "/admin/login", data=urllib.parse.urlencode(
                {"user": "ops", "password": "pw-123456789"}).encode(), timeout=10).read()
            for view in VIEWS:
                with opener.open(base + f"/admin?view={view}", timeout=30) as r:
                    html_text = r.read().decode()
                # 去掉纯粹的运行时刻（页面上唯一的时间戳来源）
                html_text = _strip_volatile(html_text)
                (outdir / f"{view}.html").write_text(html_text, encoding="utf-8")
                print(f"  {view}: {len(html_text)} 字节")
            httpd.shutdown()
        finally:
            restore()
    print(f"→ {outdir}")
    return 0


def _strip_volatile(html_text: str) -> str:
    """抹掉与环境相关的值，只留下“与代码有关”的字节。

    两类：
      ① CSRF 令牌（每个会话随机）—— 连值带长度一起归一化；
      ② 时间戳（页面上的当前时间）—— 长式与审计页的短式都要盖。

    剩下的任何差异都只能来自代码改动 —— 这就是“搬移无损”的判据。
    """
    import re
    html_text = re.sub(r"name=csrf value='[^']*'", "name=csrf value='<CSRF>'", html_text)
    html_text = re.sub(r"name=csrf value=\"[^\"]*\"", 'name=csrf value="<CSRF>"', html_text)
    html_text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "<TIME>", html_text)
    html_text = re.sub(r"\d{2}-\d{2} \d{2}:\d{2}", "<TIME>", html_text)
    # ③ 登记口令是 grant 时随机生成的（每次跑夹具都不一样）
    html_text = re.sub(r"登记口令: <code>[^<]*</code>", "登记口令: <code>&lt;SECRET&gt;</code>", html_text)
    return html_text


if __name__ == "__main__":
    raise SystemExit(main())
