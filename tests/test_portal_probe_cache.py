#!/usr/bin/env python3
"""实例探测的后台缓存：**页面渲染永不探测**。

运行：python3 tests/test_portal_probe_cache.py   （也兼容 pytest）

守的是 2026-10-16 现场那件事：`/admin` 的每一次渲染都在请求线程里探全部实例，
实例详情页还要探两轮；经隧道的一次 TLS 握手在慢实例上要 1–3 s（bg7kxr 1.7 s、
bg7ifp 1.0 s 实测），1 vCPU 的 hub 上于是给出 **4–11 秒** 的页面，而 instances 页
每 20 s 自动刷新一次 —— 探测成了常态负载。

因此这里的断言只有两类，且都必须能在探测器"睡着"时成立：
 ① 请求期间探测调用数**不增加**（渲染只读快照）
 ② 一轮探测同时喂饱「轻探」（states）与「完整探」（reports）—— 两轮探测可以互相
    矛盾（表头说 4 台在服务、行里写着服务中），同源之后这件事从根上消失
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

from portal import htpasswd as ht            # noqa: E402
from portal import metrics as mt             # noqa: E402
from portal import registry as reg           # noqa: E402
from portal.app import Portal, make_handler  # noqa: E402
from portal.store import Store               # noqa: E402
from portal.verify import CallsignListVerifier  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


class SlowProbe:
    """会数数、也会睡觉的探测器替身：页面若在请求里探测，调用数就会当场增加。"""

    def __init__(self, delay=0.30, state="serving"):
        self.delay = delay
        self.state = state
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, port, label, tls_name=""):
        with self.lock:
            self.calls += 1
        time.sleep(self.delay)
        report = {"state": self.state, "detail": f"{label} 在服务", "status_line": "HTTP/1.1 401",
                  "server": "uvicorn", "generation": "mrrc-v52",
                  "cert": {"subject": f"CN={label}.mrrc.vlsc.net",
                           "issuer": f"CN={label}.mrrc.vlsc.net", "not_after": "Dec 29 2026",
                           "names": set(), "name_ok": True, "sha256": "ab" * 32}}
        return report, 12.5


def _entries(labels):
    return [(label, 18802 + i, "") for i, label in enumerate(labels)]


def _cache(labels, probe, **kw):
    return mt.ProbeCache(lambda: _entries(labels), probe, **kw)


def test_one_round_feeds_states_and_reports():
    probe = SlowProbe(delay=0)
    cache = _cache(["bg1sb", "ba4eg"], probe)
    snap = cache.snapshot()
    check(probe.calls == 2, f"首轮探一次每个实例（实测 {probe.calls}）")
    check(snap["states"][18802][0] == "serving", "轻探结论来自这一轮")
    check(snap["reports"]["ba4eg"]["state"] == "serving", "完整报告也来自这一轮")
    check(snap["reports"]["ba4eg"]["cert"]["name_ok"] is True, "证书事实随报告一起给")
    check(snap["age"] is not None and snap["age"] < 1.0, "快照带数据龄")
    check(probe.calls == 2, "读快照不再触发探测")


def test_age_and_first_round_state_are_honest():
    """还没探过就说还没探过 —— 拿空快照冒充"刚探过"是编数据。"""
    clock = [1000.0]
    cache = _cache(["bg1sb"], SlowProbe(delay=0), clock=lambda: clock[0])
    cache.start()                       # 有后台线程时，未探过 = probing，不许在请求里现探
    try:
        snap = cache.snapshot()
        check(snap["probing"] is True or snap["reports"], "有后台线程时快照不等探测")
    finally:
        cache.stop()
    inline = _cache(["bg1sb"], SlowProbe(delay=0), clock=lambda: clock[0])
    inline.tick()
    clock[0] += 7.5
    snap = inline.snapshot()
    check(snap["probing"] is False, "探过一轮后不再是首次")
    check(abs(snap["age"] - 7.5) < 1e-6, f"数据龄 = 距上一轮（实测 {snap['age']}）")


def test_latest_reads_the_snapshot_instead_of_probing():
    """采样器走的是这条路：它原来自己一轮串行探测（14 台 ≈8 s / 30 s），现在只读。"""
    probe = SlowProbe(delay=0)
    cache = _cache(["bg1sb"], probe)
    cache.tick()
    before = probe.calls
    state, detail, latency = cache.latest(18802, "bg1sb")
    check(probe.calls == before, "latest() 不探测")
    check(state == "serving" and "在服务" in detail, "latest() 回报快照里的结论")
    check(latency == 12.5, "延时也来自同一轮（只在握手成功时给值）")
    check(cache.latest(19999, "unknown")[0] == "", "没探到过的实例给空状态，不冒充 down")


def test_background_thread_keeps_probing_on_its_interval():
    probe = SlowProbe(delay=0)
    cache = _cache(["bg1sb"], probe, interval=1.0)
    cache.start()
    try:
        deadline = time.monotonic() + 3.0
        while probe.calls < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        check(probe.calls >= 2, f"后台按 interval 续探（实测 {probe.calls} 轮）")
    finally:
        cache.stop()


def test_a_raising_probe_becomes_a_row_not_a_500():
    def boom(port, label, tls_name=""):
        raise RuntimeError("隧道炸了")

    cache = _cache(["bg1sb"], boom)
    snap = cache.snapshot()
    check("探测异常" in snap["reports"]["bg1sb"]["detail"], "探测器抛异常 → 报告里带原因")
    check(snap["states"][18802][0] == "", "结论未知，不许冒充 down")


# ── 端到端：真实请求路径 ────────────────────────────────────────────────

def _signed_in_opener(base, user, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode({"user": user, "password": password}).encode()
    opener.open(base + "/admin/login", data=data, timeout=10).read()
    return opener


def _server(tmp, probes, labels=("bg1sb", "ba4eg", "bg7kxr")):
    reg_path = tmp / "instances.tsv"
    reg_path.write_text("".join(f"{l}\t{18802 + i}\n" for i, l in enumerate(labels)),
                        encoding="utf-8")
    (tmp / "callsigns.txt").write_text("".join(f"{l.upper()}\n" for l in labels),
                                       encoding="utf-8")
    users_path = tmp / "portal-users"
    users_path.write_text("ops:" + ht.apr1("pw-123456789", "saltward") + "\n", encoding="utf-8")
    portal = Portal(Store(tmp / "portal.json"), reg.Registry(reg_path),
                    CallsignListVerifier(tmp / "callsigns.txt"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        portal, token="tok", users=ht.UsersFile(users_path), probes=probes))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    opener = _signed_in_opener(f"http://127.0.0.1:{httpd.server_address[1]}", "ops",
                               "pw-123456789")
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}", opener


def test_admin_requests_never_probe_and_stay_fast():
    """核心回归：探测慢（0.6 s/台）不影响页面 —— 渲染只读快照。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        probe = SlowProbe(delay=0.6)
        cache = _cache(["bg1sb", "ba4eg", "bg7kxr"], probe)
        cache.tick()                     # 后台那一轮（生产里由线程做）
        httpd, base, opener = _server(tmp, cache)
        try:
            for path in ("/admin?view=instances", "/admin?view=instance&label=bg7kxr",
                         "/admin?view=overview", "/admin?view=instances&part=live"):
                before = probe.calls
                t0 = time.monotonic()
                with opener.open(base + path, timeout=30) as r:
                    page = r.read().decode()
                elapsed = time.monotonic() - t0
                check(r.status == 200, f"{path}: 200")
                check(probe.calls == before,
                      f"{path}: 请求期间没有探测（{before} → {probe.calls}）")
                check(elapsed < 0.5,
                      f"{path}: 页面不等探测（实测 {elapsed:.2f}s，仍在请求里探就是 ≥1.2s）")
            check("bg7kxr" in page, "详情页照常有内容")
        finally:
            httpd.shutdown()


def test_instances_page_states_and_reports_come_from_the_same_round():
    """表头计数与逐行结论同源：不会再出现"4 台在服务"而某一行写着离线。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cache = _cache(["bg1sb", "ba4eg"], SlowProbe(delay=0))
        cache.tick()
        httpd, base, opener = _server(tmp, cache, labels=("bg1sb", "ba4eg"))
        try:
            with opener.open(base + "/admin?view=instances", timeout=30) as r:
                page = r.read().decode()
        finally:
            httpd.shutdown()
    check("2 个在服务" in page, "计数与行同源（两行都是 serving）")
    check(page.count("服务中") >= 2, "两行都写服务中")
    check("个入口开不了" not in page, "同源之后不报入口故障")


def test_state_changes_are_announced_once_and_reset_the_clock():
    """状态变化 → 一次回调 + 重新计时（2026-10-25）。

    原先「从服务中变成离线」这件事**没有任何地方记录过**：ProbeCache 每 20 秒就知道
    一次，但只把它塞进页面。于是 2026-10-22 那次入口 502 四天，事后只能翻 nginx 日志反推。
    """
    states = ["serving", "serving", "down", "down", "serving"]
    clock = [1000.0]
    seen = []

    def probe(port, label, tls_name=""):
        state = states.pop(0) if states else "serving"
        return ({"state": state, "detail": "换态", "generation": "", "cert": {}}, None)

    cache = mt.ProbeCache(lambda: _entries(["bg1sb"]), probe,
                          clock=lambda: clock[0], on_change=lambda *a: seen.append(a))
    cache.tick()                               # serving：第一轮也算一次「变化」（prev=None）
    check(seen == [("bg1sb", None, "serving", "换态")], f"第一轮记一次（实测 {seen}）")
    first_since = cache.snapshot()["since"]["bg1sb"]
    clock[0] += 20
    cache.tick()                               # 状态不变 → 不重复报，计时不动
    check(len(seen) == 1, f"状态没变就不该再报（实测 {len(seen)} 次）")
    check(cache.snapshot()["since"]["bg1sb"] == first_since, "计时不因同一状态而重置")
    clock[0] += 20
    cache.tick()                               # serving → down：报一次，计时重置
    check(seen[-1][2] == "down", "掉线被报出来")
    check(cache.snapshot()["since"]["bg1sb"] == clock[0], "计时从掉线那一刻起")
    clock[0] += 60
    cache.tick()                               # 仍是 down：不重复报
    check(len(seen) == 2, f"持续离线不再刷屏（实测 {len(seen)} 次）")


def test_a_broken_hook_never_kills_the_prober():
    """回调会写日志、以后还会发通知 —— 它自己出错不许把探测线程带走。"""
    def boom(*_a):
        raise RuntimeError("通知发不出去")

    cache = mt.ProbeCache(lambda: _entries(["bg1sb"]), SlowProbe(delay=0), on_change=boom)
    cache.tick()                               # 不抛
    check(cache.snapshot()["reports"]["bg1sb"]["state"] == "serving", "快照照常更新")


def test_a_long_down_instance_says_how_long_it_has_been_down():
    """实例页要能回答「它已经这样多久了」（2026-10-25）。

    此前只有一个状态字：「刚抖一下」与「已经死了四天」长得一模一样。
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        four_days_ago = time.time() - 4 * 86400
        cache = mt.ProbeCache(lambda: _entries(["bg1sb", "ba4eg"]),
                              SlowProbe(delay=0, state="down"),
                              clock=lambda: four_days_ago)
        cache.tick()
        httpd, base, opener = _server(tmp, cache, labels=("bg1sb", "ba4eg"))
        try:
            with opener.open(base + "/admin?view=instances", timeout=30) as r:
                page = r.read().decode()
            with opener.open(base + "/admin?view=overview", timeout=30) as r:
                overview = r.read().decode()
        finally:
            httpd.shutdown()
    check("已离线 4 天" in page, "实例页要写出离线时长")
    check("已离线 4 天" in overview, "总览待办也要写（否则得逐行点开才知道）")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ 探测缓存测试通过（{len(tests)} 组）：一轮探测喂两个视图/页面永不探测/"
          f"数据龄诚实/异常降级/采样器只读")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
