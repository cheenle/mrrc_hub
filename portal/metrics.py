"""frps 面板统计的采集与内存历史（纯标准库）。

数据源：hub 上 frps 的 webServer 面板（只绑 127.0.0.1，Basic 认证），
`GET /api/proxy/tcp` 一次取回全部代理的 trafficIn/Out、todayTrafficIn/Out、curConns。
frps 给的是**累计值** ⇒ 带宽是两次采样的差分；历史只存内存（重启即清），
默认 30s × 120 ≈ 1 小时。

诚实降级：拿不到就给可读原因，绝不用 0 冒充（与 app.py 探测器的姿态一致）。
字段名按 frp 0.71 的 dashboard API；拿不到或类型不符时标空并说明 —— 部署时用
`curl` 对照真响应（部署检查单里列了这一步）。
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Panel(Protocol):
    """采集器只依赖这一个方法：便于测试注入替身（不必继承具体实现）。"""

    def fetch(self) -> tuple[list | None, str]: ...


@dataclass
class Sample:
    at: float
    latency_ms: float | None = None
    tunnel_state: str | None = None
    tunnel_detail: str = ""
    in_bps: float | None = None
    out_bps: float | None = None
    cur_conns: int | None = None
    today_in: int | None = None
    today_out: int | None = None
    note: str = ""


class FrpsPanel:
    """回环面板的最小客户端。凭据每轮重读，轮换不必重启 portal。"""

    def __init__(self, url: str = "http://127.0.0.1:7100",
                 credentials_path: str | Path = "/etc/mrrc-hub/frps-web.credentials",
                 timeout: float = 3.0, opener=urllib.request.urlopen):
        self.url = url.rstrip("/")
        self.credentials_path = Path(credentials_path)
        self.timeout = timeout
        self._opener = opener

    def _credentials(self):
        try:
            text = self.credentials_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        user, sep, password = text.partition(":")
        return (user, password) if sep and user else None

    def fetch(self) -> tuple[list | None, str]:
        creds = self._credentials()
        if creds is None:
            return None, f"凭据不可读：{self.credentials_path}"
        token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
        req = urllib.request.Request(self.url + "/api/proxy/tcp",
                                     headers={"Authorization": f"Basic {token}"})
        try:
            with self._opener(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return None, "面板凭据错误"
            return None, f"面板不可用：HTTP {exc.code}"
        except Exception as exc:                       # noqa: BLE001 — 采集器不许把服务带崩
            return None, f"面板不可用：{exc}"
        if isinstance(data, dict) and isinstance(data.get("proxies"), list):
            return data["proxies"], ""      # frp 0.71 dashboard 形态：{"proxies": [...]}
        if isinstance(data, list):
            return data, ""                 # 旧版形态：裸列表
        return None, "面板应答既不是代理列表也不是 {proxies:[…]}（版本差异）"


class ProbeCache:
    """实例探测的后台缓存：后台一轮并发探测，所有页面共享 —— 渲染永不探测。

    **为什么需要它（2026-10-16 现场实测）**：`/admin` 的每一次渲染都在请求线程里探全部
    实例，而实例视图还要探**两轮**（轻探 + 完整探）。经隧道的一次 TLS 握手在慢实例上要
    1–3 s（bg7kxr 1.7 s / bg7ifp 1.0 s，实测），1 vCPU 的 hub 上 8 路并发的余量也就那么
    多 ⇒ 页面 **4–11 s**，而 instances 页每 20 s 自动刷新一次，等于把探测变成常态负载。
    运维看到的正是「后台打开要等十秒」。

    现在的分工：后台线程每 interval 秒探一轮（并发），页面只读快照，并**如实报出数据龄**
    —— 诚实降级照旧：还没探过就说「探测进行中」，过期就说过期，绝不拿旧数据冒充刚探的。
    顺带消掉一类自相矛盾：表头计数与逐行结论从此来自**同一轮**（此前两轮可以背道而驰）。

    `probe` 是注入的：`(port, label, tls_name) -> (report, latency_ms|None)`，只在本模块
    的 `tick()` 里被调用一次（每实例每轮一次），因此单测不必起真隧道。
    """

    def __init__(self, entries, probe, *, interval: float = 20.0, workers: int = 8,
                 clock=time.time):
        self._entries = entries          # () -> [(label, port, tls_name)]
        self._probe = probe              # (port, label, tls_name) -> (report, latency_ms|None)
        self.interval = max(1.0, interval)          # 调用方（argparse/测试）已给数值；不在这里解析
        self._workers = max(1, workers)
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._at: float | None = None
        self._reports: dict = {}
        self._ports: dict = {}
        self._latency: dict = {}

    # ---- 采集 ----
    def _one(self, item):
        label, port, tls = item
        try:
            report, latency = self._probe(port, label, tls)
        except Exception as exc:                       # noqa: BLE001 — 采集器不许把服务带崩
            return label, {"state": "", "detail": f"探测异常：{exc}"}, None
        return label, report, latency

    def tick(self) -> None:
        """一轮：并发探全部实例，然后整份换掉快照（读者永远看到自洽的一份）。"""
        from concurrent.futures import ThreadPoolExecutor

        items = [tuple(item) for item in self._entries()]
        reports: dict = {}
        latency: dict = {}
        if items:
            with ThreadPoolExecutor(max_workers=min(self._workers, len(items))) as pool:
                for label, report, ms in pool.map(self._one, items):
                    reports[label] = report
                    if ms is not None:
                        latency[label] = ms
        with self._lock:
            self._reports, self._latency = reports, latency
            self._ports = {label: port for label, port, _tls in items}
            self._at = self._clock()

    # ---- 读取 ----
    def snapshot(self) -> dict:
        """当前快照。**除首次且没有后台线程之外，绝不在这里探测。**

        没有后台线程（单测、单发脚本、`--dry-run` 之外的一次性调用）时，首轮现探一次，
        此后都读这份快照 —— 于是「页面不探测」这条契约在两种装配下都成立。
        """
        with self._lock:
            at, reports, latency, ports = self._at, self._reports, self._latency, self._ports
        if at is None and self._thread is None:
            self.tick()
            with self._lock:
                at, reports, latency, ports = (self._at, self._reports, self._latency,
                                               self._ports)
        now = self._clock()
        return {
            "at": at,
            "age": (now - at) if at is not None else None,
            "probing": at is None,
            "reports": dict(reports),
            "states": {ports[label]: (rep.get("state", ""), rep.get("detail", ""))
                       for label, rep in reports.items() if label in ports},
            "latency": dict(latency),
            "interval": self.interval,
        }

    def latest(self, port, label: str = "") -> tuple:
        """采样器用的**只读**视图：`(状态, 说明, 延时 ms)` —— 读快照，不探测。

        采样器原先自己一轮**串行**探测（14 台 ≈8 s / 30 s），与页面各探一轮；现在两边
        共用这一轮，hub 上的探测次数直接减半，且延时与页面显示的是同一个数。
        没探到过的实例给空状态（视图按「未探测」渲染）—— 不冒充 `down`，那会让运维
        去查一个并不存在的故障。
        """
        snap = self.snapshot()
        report = snap["reports"].get(label) if label else None
        if report is None:
            state, detail = snap["states"].get(port, ("", "尚未探测"))
        else:
            state, detail = report.get("state", ""), report.get("detail", "")
        return state, detail, snap["latency"].get(label)

    # ---- 线程 ----
    def start(self) -> None:
        if self._thread is not None:
            return

        def loop():
            while True:
                try:
                    self.tick()
                except Exception:            # noqa: BLE001 — 一轮失败不带走线程：
                    pass                     # 快照留在上一轮（数据龄会一直涨，使用者看得见）
                if self._stop.wait(self.interval):
                    break

        self._thread = threading.Thread(target=loop, name="portal-probes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


class Sampler:
    """后台采样线程：面板取数（差分算速率）+ 隧道探测计时（复用 app 的探测函数）。"""

    def __init__(self, entries, probe, panel: Panel, *, interval: float = 30.0,
                 history: int = 120, clock=time.time, nic_path: str | Path = "/proc/net/dev"):
        self._entries = entries              # () -> [(label, port)]
        self._probe = probe                  # (port, label) -> (state, detail, latency_ms|None)
        self._panel = panel
        self.interval = interval
        self._history = history
        self._clock = clock
        self._nic_path = Path(nic_path)
        self._samples: dict[str, deque] = {}
        self._prev: dict[str, tuple] = {}    # label -> (at, trafficIn, trafficOut)
        self._panel_error = ""
        self._panel_at: float | None = None
        self._nic_prev: tuple | None = None
        self._nic_rates: dict | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 采集 ----
    def tick(self) -> None:
        now = self._clock()
        entries = list(self._entries())
        proxies, panel_error = self._panel.fetch()
        by_name = {str(p.get("name")): p for p in (proxies or []) if isinstance(p, dict)}
        fresh: dict[str, Sample] = {}
        for label, port in entries:
            sample = Sample(at=now)
            state, detail, latency = self._probe(port, label)
            sample.tunnel_state, sample.tunnel_detail = state, detail
            sample.latency_ms = latency
            p = by_name.get(label)
            if p is None:
                sample.note = "frps 里没有这个代理（租户隧道未连）"
            else:
                # frp 0.71 的面板没有累计 trafficIn/Out，只有 todayTrafficIn/Out
                # （2026-10-05 在 hub 上用 curl 实测）。差分就用今日累计，跨日/重启
                # 造成的回绕由下面的检测处理。
                tin, tout, base = p.get("trafficIn"), p.get("trafficOut"), "traffic"
                if not (isinstance(tin, int) and isinstance(tout, int)):
                    tin, tout = p.get("todayTrafficIn"), p.get("todayTrafficOut")
                    base = "today"
                if isinstance(tin, int) and isinstance(tout, int):
                    prev = self._prev.get(label)
                    if prev is None or prev[3] != base:
                        sample.note = "首轮采样（速率自下一轮起可算）"
                    else:
                        prev_at, prev_in, prev_out, _ = prev
                        dt = now - prev_at
                        if dt > 0 and tin >= prev_in and tout >= prev_out:
                            sample.in_bps = (tin - prev_in) * 8 / dt
                            sample.out_bps = (tout - prev_out) * 8 / dt
                        else:
                            sample.note = "计数器回绕/重置（跨日或 frps 重启），本轮速率不可算"
                    self._prev[label] = (now, tin, tout, base)
                else:
                    sample.note = "面板未给出 traffic 或 todayTraffic 字段（版本差异）"
                if isinstance(p.get("curConns"), int):
                    sample.cur_conns = p["curConns"]
                if isinstance(p.get("todayTrafficIn"), int):
                    sample.today_in = p["todayTrafficIn"]
                if isinstance(p.get("todayTrafficOut"), int):
                    sample.today_out = p["todayTrafficOut"]
            fresh[label] = sample
        nic = self._nic_tick(now)
        with self._lock:
            self._panel_error = panel_error
            if proxies is not None:
                self._panel_at = now
            if nic is not None:
                self._nic_rates = nic
            for label, sample in fresh.items():
                self._samples.setdefault(label, deque(maxlen=self._history)).append(sample)

    def _nic_tick(self, now: float) -> dict | None:
        try:
            total = [0, 0]
            for line in self._nic_path.read_text().splitlines()[2:]:
                name, _, rest = line.partition(":")
                if name.strip() == "lo":
                    continue
                fields = rest.split()
                total[0] += int(fields[0])
                total[1] += int(fields[8])
        except (OSError, IndexError, ValueError):
            return {"note": "本平台不适用"}
        rates = None
        if self._nic_prev is not None:
            prev_at, prev_rx, prev_tx = self._nic_prev
            dt = now - prev_at
            if dt > 0 and total[0] >= prev_rx and total[1] >= prev_tx:
                rates = {"rx_bps": (total[0] - prev_rx) * 8 / dt,
                         "tx_bps": (total[1] - prev_tx) * 8 / dt}
        self._nic_prev = (now, total[0], total[1])
        return rates or {"note": "首轮采样（速率自下一轮起可算）"}

    # ---- 读取 ----
    def samples_for(self, label: str) -> list:
        with self._lock:
            return list(self._samples.get(label, ()))

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            labels = {}
            for label, q in self._samples.items():
                last = q[-1]
                lats = [s.latency_ms for s in q if s.latency_ms is not None]
                ins = [s.in_bps for s in q if s.in_bps is not None]
                outs = [s.out_bps for s in q if s.out_bps is not None]
                labels[label] = {
                    "last": last,
                    "stale_s": max(0.0, now - last.at),
                    "latency_mean": (sum(lats) / len(lats)) if lats else None,
                    "latency_peak": max(lats) if lats else None,
                    "in_mean": (sum(ins) / len(ins)) if ins else None,
                    "out_mean": (sum(outs) / len(outs)) if outs else None,
                }
            return {"labels": labels, "panel_error": self._panel_error,
                    "panel_age": (now - self._panel_at) if self._panel_at else None,
                    "nic": self._nic_rates, "interval": self.interval}

    # ---- 线程 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        def loop():
            self.tick()
            while not self._stop.wait(self.interval):
                self.tick()
        self._thread = threading.Thread(target=loop, name="portal-metrics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
