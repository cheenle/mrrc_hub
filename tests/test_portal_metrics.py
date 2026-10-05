#!/usr/bin/env python3
"""portal.metrics 的测试：面板取数、差分速率、探测计时、环形历史与诚实降级。

运行：python3 tests/test_portal_metrics.py   （也兼容 pytest）
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import metrics as mt  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakePanel:
    """可编排的面板替身：每次 fetch 弹出一个预设结果，最后一个结果可重复取。"""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0] if self.results else (None, "panel down")


def proxy(name, tin, tout, conns=0, today_in=0, today_out=0):
    return {"name": name, "trafficIn": tin, "trafficOut": tout, "curConns": conns,
            "todayTrafficIn": today_in, "todayTrafficOut": today_out}


def test_rates_and_history():
    clock = FakeClock()
    panel = FakePanel([
        ([proxy("a", 1000, 2000, 2, 500, 800)], ""),
        ([proxy("a", 1500, 2600, 3, 900, 1500)], ""),
    ])
    probes = {"a": ("serving", "握手成功", 12.5)}
    s = mt.Sampler(lambda: [("a", 18802)], lambda port, label: probes[label],
                   panel, interval=30.0, history=5, clock=clock, nic_path="/nonexistent")
    s.tick()
    snap = s.snapshot()["labels"]["a"]
    check(snap["last"].in_bps is None and "首轮" in snap["last"].note,
          "首轮没有差分 ⇒ 速率标空并说明（不是 0）")
    check(snap["last"].cur_conns == 2 and snap["last"].today_in == 500, "首轮拿累计值")
    clock.now += 30
    s.tick()
    snap = s.snapshot()["labels"]["a"]
    check(abs(snap["last"].out_bps - (600 * 8 / 30)) < 1e-6, "下行速率 = Δbytes×8/Δt")
    check(abs(snap["last"].in_bps - (500 * 8 / 30)) < 1e-6, "上行速率 = Δbytes×8/Δt")
    check(snap["latency_mean"] == 12.5 and snap["latency_peak"] == 12.5, "延时统计")
    check(snap["last"].cur_conns == 3 and snap["last"].today_out == 1500, "累计值随样本更新")
    check(snap["stale_s"] == 0.0, "新鲜度以假时钟计")
    for _ in range(8):
        clock.now += 30
        s.tick()
    check(len(s.samples_for("a")) == 5, "环形历史不超过 maxlen")


def test_counter_reset_and_missing_proxy():
    clock = FakeClock()
    panel = FakePanel([
        ([proxy("a", 5000, 5000)], ""),
        ([proxy("a", 10, 20)], ""),
        ([], ""),
    ])
    s = mt.Sampler(lambda: [("a", 18802), ("b", 18803)],
                   lambda port, label: ("down", "连接被拒", None),
                   panel, interval=30.0, history=10, clock=clock, nic_path="/nonexistent")
    s.tick(); clock.now += 30; s.tick()
    last = s.snapshot()["labels"]["a"]["last"]
    check(last.in_bps is None and "计数器" in last.note, "计数器回绕 ⇒ 速率标空并说明")
    clock.now += 30; s.tick()
    snap = s.snapshot()
    check("frps 里没有这个代理" in snap["labels"]["a"]["last"].note, "代理消失有明确原因")
    check(snap["labels"]["b"]["last"].note.startswith("frps 里没有这个代理"), "从未出现的代理不冒充 0")
    check(snap["labels"]["b"]["last"].latency_ms is None, "探测失败不编造延时")


def test_panel_and_probe_failures():
    clock = FakeClock()
    panel = FakePanel([(None, "面板不可用：connection refused")])
    s = mt.Sampler(lambda: [("a", 18802)],
                   lambda port, label: ("hollow", "隧道在、后端无应答", None),
                   panel, interval=30.0, history=10, clock=clock, nic_path="/nonexistent")
    s.tick()
    snap = s.snapshot()
    check("面板不可用" in snap["panel_error"], "面板错误原样呈现")
    check(snap["panel_age"] is None, "从没成功过 ⇒ 无采样年龄")
    check(snap["labels"]["a"]["last"].tunnel_state == "hollow", "探测结论保留")
    check(snap["labels"]["a"]["last"].tunnel_detail == "隧道在、后端无应答", "探测细节保留")
    check(snap["nic"]["note"] == "本平台不适用", "/proc/net/dev 缺失 ⇒ 明确标注")


def test_frps_panel_credentials_parsing():
    with tempfile.TemporaryDirectory() as td:
        cred = Path(td) / "frps-web.credentials"
        cred.write_text("portal:secret42\n", encoding="utf-8")
        panel = mt.FrpsPanel("http://127.0.0.1:7100", cred)
        check(panel._credentials() == ("portal", "secret42"), "凭据文件 user:password 解析")
        cred.unlink()
        check(panel._credentials() is None, "凭据缺失返回 None（不炸）")
        _, reason = panel.fetch()
        check(reason.startswith("凭据不可读"), "fetch 对凭据缺失给可读原因")


def test_nic_rates_from_fake_proc():
    clock = FakeClock()
    tmp = Path(tempfile.mkdtemp()) / "net_dev"
    tmp.write_text("Inter-|   Receive                                                |  Transmit\n"
                   " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                   "  en0: 1000 5 0 0 0 0 0 0 2000 6 0 0 0 0 0 0\n"
                   "  lo: 99999 5 0 0 0 0 0 0 99999 6 0 0 0 0 0 0\n", encoding="utf-8")
    s = mt.Sampler(lambda: [], lambda port, label: ("serving", "", 1.0),
                   FakePanel([([], "")]), interval=30.0, history=10, clock=clock, nic_path=tmp)
    s.tick()
    check(s.snapshot()["nic"].get("note", "").startswith("首轮"), "网卡首轮只有说明")
    clock.now += 10
    tmp.write_text("Inter-|   Receive                                                |  Transmit\n"
                   " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
                   "  en0: 3000 5 0 0 0 0 0 0 5000 6 0 0 0 0 0 0\n"
                   "  lo: 99999 5 0 0 0 0 0 0 99999 6 0 0 0 0 0 0\n", encoding="utf-8")
    s.tick()
    nic = s.snapshot()["nic"]
    check(abs(nic["rx_bps"] - (2000 * 8 / 10)) < 1e-6, "网卡入速率（lo 不计）")
    check(abs(nic["tx_bps"] - (3000 * 8 / 10)) < 1e-6, "网卡出速率（lo 不计）")


def test_tunnel_view_renders_end_to_end():
    """假采样器 → 登录后的管理台真的把延时/带宽拼对了吗（延续 V0.24 的拼接教训）。"""
    import http.cookiejar
    import threading
    import urllib.parse
    import urllib.request
    from http.server import ThreadingHTTPServer

    from portal import htpasswd as ht
    from portal import registry as reg
    from portal import sessions as sess
    from portal.app import Portal, make_handler
    from portal.store import Store
    from portal.verify import CallsignListVerifier

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "callsigns.txt").write_text("NOBODY\n", encoding="utf-8")
        (tmp / "instances.tsv").write_text("bg1sb\t18802\n", encoding="utf-8")
        (tmp / "portal-users").write_text(
            "ops:" + ht.apr1("pw-123456789", "saltward") + "\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        clock = FakeClock()
        panel = FakePanel([([proxy("bg1sb", 1000, 2000, 4, 2_000_000, 7_000_000)], ""),
                           ([proxy("bg1sb", 4000, 11000, 5, 2_400_000, 7_600_000)], "")])
        s = mt.Sampler(lambda: [("bg1sb", 18802)],
                       lambda port, label: ("serving", "握手成功", 23.4),
                       panel, interval=30.0, history=10, clock=clock, nic_path="/nonexistent")
        s.tick()
        clock.now += 30
        s.tick()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            portal, token="tok", users=ht.UsersFile(tmp / "portal-users"),
            sessions=sess.SessionStore(), guard=sess.LoginGuard(), sampler=s))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            opener.open(base + "/admin/login",
                        data=urllib.parse.urlencode({"user": "ops", "password": "pw-123456789"}).encode(),
                        timeout=10)
            with opener.open(base + "/admin?view=tunnel", timeout=10) as r:
                page = r.read().decode()
            # Δin=3000B·8/30s=800 bps，Δout=9000B·8/30s=2400 bps
            for needle, why in (("隧道", "视图标题"), ("bg1sb", "实例标签"),
                                ("23 ms", "延时数值"), ("在线", "隧道四态文案"),
                                ("800 bps", "上行差分速率"), ("2.4 kbps", "下行差分速率"),
                                ("2.3 MiB", "今日下行流量"), ("5", "当前连接数")):
                check(needle in page, f"隧道视图渲染出{why}（{needle!r}）")
            with opener.open(base + "/admin?view=system", timeout=10) as r:
                sys_page = r.read().decode()
            check("frps 面板" in sys_page and "全代理合计速率" in sys_page, "系统页有面板聚合行")
            with opener.open(base + "/admin?view=overview", timeout=10) as r:
                ov = r.read().decode()
            check("延时均值" in ov and "出带宽" in ov, "总览页有隧道摘要")
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
    print(f"✅ metrics 测试通过（{len(tests)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
