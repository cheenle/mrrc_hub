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
                 credentials_path="/etc/mrrc-hub/frps-web.credentials",
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
        if not isinstance(data, list):
            return None, "面板应答不是代理列表（字段名可能随版本变化）"
        return data, ""


class Sampler:
    """后台采样线程：面板取数（差分算速率）+ 隧道探测计时（复用 app 的探测函数）。"""

    def __init__(self, entries, probe, panel: FrpsPanel, *, interval: float = 30.0,
                 history: int = 120, clock=time.time, nic_path: str = "/proc/net/dev"):
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
                tin, tout = p.get("trafficIn"), p.get("trafficOut")
                if isinstance(tin, int) and isinstance(tout, int):
                    prev = self._prev.get(label)
                    if prev is None:
                        sample.note = "首轮采样（速率自下一轮起可算）"
                    else:
                        prev_at, prev_in, prev_out = prev
                        dt = now - prev_at
                        if dt > 0 and tin >= prev_in and tout >= prev_out:
                            sample.in_bps = (tin - prev_in) * 8 / dt
                            sample.out_bps = (tout - prev_out) * 8 / dt
                        else:
                            sample.note = "计数器回绕/重置，本轮速率不可算"
                    self._prev[label] = (now, tin, tout)
                else:
                    sample.note = "面板未给出该字段（版本差异）"
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
