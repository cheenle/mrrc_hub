"""hub 侧信任链的漂移检查（只读，不提权）。

**为什么需要它（2026-10-16 真实事故）**：换一台硬件盒子 = 同一个呼号、**一对全新的
密钥**（UC-H08「凭证生命周期可控（泄露或换机可止损）」）。实例侧 `connect()` 会签一张
签给自己入口名的新证书并 `/enroll` 上来，hub 侧则要把这张公钥变成 nginx 真正信任的东西：

    ① `/usr/local/sbin/gen_hub_routes.py` —— 把 `instance-certs/*.pem` 重建成 `trust-bundle.pem`
    ② `systemctl reload nginx`            —— nginx **只在配置加载时**读这份 trust-bundle

**这两步自 V0.17 起是自动的**（`mrrc-hub-routes.timer` 每 30 秒跑一次，**内容哈希变了
且 `nginx -t` 通过**才 reload）—— 所以本模块报出“待重载”时，第一件事是查那个 timer，
而不是上手跑命令（手工命令只是兜底）。

任一步没生效，nginx 的 `proxy_ssl_verify` + `proxy_ssl_name` 就会拒掉实例证书 ⇒ 入口 502，
而**页面上看不出来**：探针走的是"不校验的回环握手"，照样会报"在服务"（那是它的判据，
不是缺陷 —— 见 `app._probe`）。本模块把这两步变成可判读的事实。

**两条判据都刻意避开 `trust-bundle.pem` 的 mtime**：生成器**内容没变也会重写**该文件
（2026-10-16 实测：bundle 00:32:08 / nginx worker 00:27:35，而四个活着的入口其实都正常）。
拿它的 mtime 当判据，会造出一条永远在闪的假警报，运维很快会学会无视它 —— 那比不报还糟。

判据因此只看**真的发生过写入**的两处：注册表（加/删实例时才写）与实例证书文件
（只在登记时写），再与"nginx 上一次读配置的时刻"比。那个时刻取 **worker 的启动时间**：
reload 只换 worker，master 从上线起就没变过（实测 10-03 至今）。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path

#: 自 V0.17 起，**重生成 + reload 是自动的**：`mrrc-hub-routes.timer` 每 30 秒跑一次
#: `mrrc-hub-routes.sh`（重新生成 map + trust-bundle，**内容哈希变了且 `nginx -t` 通过**才
#: `systemctl reload nginx`）。所以页面报“待重载”时，第一步是看那个 timer，而不是上手跑命令。
ROUTES_TIMER = "mrrc-hub-routes.timer"
ROUTES_TIMER_STATUS = f"systemctl status {ROUTES_TIMER}; journalctl -u mrrc-hub-routes -n 20"

#: 手工兜底（仅当确认 timer 停了、或要立即生效时用）。**它不是常规步骤**。
FALLBACK_COMMAND = ("sudo /usr/local/sbin/gen_hub_routes.py && sudo nginx -t "
                    "&& sudo systemctl reload nginx")

#: timer 周期（30 s，见 `mrrc-hub-routes.timer`）。
ROUTES_TIMER_PERIOD_S = 30.0
#: 宽限期 = 3 个周期。**这个常量是防假警报的关键**：刚登记完的那几十秒里
#: "nginx 还没重载"是**正常状态**（timer 还没轮到），不宽容期会让每次 enroll
#: 都把页面刷红一次 —— 那种噪声会教会运维无视这个判据，比不报还糟。
RELOAD_GRACE_S = 3 * ROUTES_TIMER_PERIOD_S


def cert_block(text: str) -> str:
    """取 PEM 里第一段证书（BEGIN…END），去掉首尾空白。取不到返回空串。"""
    begin = text.find("-----BEGIN CERTIFICATE-----")
    end = text.find("-----END CERTIFICATE-----")
    if begin < 0 or end < 0 or end < begin:
        return ""
    return text[begin:end + len("-----END CERTIFICATE-----")].strip()


def fingerprint_of_pem(text: str) -> str:
    """PEM 证书的 DER SHA-256（十六进制小写）；解析不了返回空串。

    PEM 的身体就是 DER 的 base64 —— 所以这一步**不需要 openssl**，纯标准库即可
    （与 `_cert_facts` 拿到的握手 DER 哈希是同一个口径，两侧可以直接相等比较）。
    """
    block = cert_block(text)
    if not block:
        return ""
    body = "".join(line for line in block.splitlines() if "-----" not in line)
    try:
        der = base64.b64decode(body, validate=False)
    except (binascii.Error, ValueError):
        return ""
    return hashlib.sha256(der).hexdigest()


def short_fp(fp: str, n: int = 16) -> str:
    """指纹的短形式（给人看；相等比较永远用全长）。"""
    return (fp or "")[:n]


def bundle_has_cert(bundle_text: str, cert_pem: str) -> bool:
    """这张证书在信任包里吗。

    生成器写 bundle 用的是 `cert.read_text().rstrip()` 再拼接（**逐字**，见
    `deploy/gen_hub_routes.py`），所以"在不在"可以精确地用文本包含回答 —— 不必对
    上百张系统 CA 逐个跑 openssl，那会让每 20 秒一次的轮询变成几百毫秒的开销。
    """
    block = cert_block(cert_pem)
    return bool(block) and block in bundle_text


def _btime(proc_root: Path) -> float | None:
    """`/proc/stat` 的 btime（开机时刻，epoch 秒）。"""
    for line in (proc_root / "stat").read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("btime "):
            continue
        try:
            return float(line.split()[1])
        except (IndexError, ValueError):
            # 畸形内容按「读不到」处理：诚实降级不许拿猜的数当事实。
            return None
    return None

def _starttime_ticks(stat_text: str) -> int | None:
    """`/proc/<pid>/stat` 的第 22 字段（starttime，单位 clock tick）。

    **不能简单 split()**：第 2 字段 comm 是 `(nginx)`，而它可以含空格与括号
    （内核以**最后一个** ')' 收尾）。所以从最后一个 ')' 之后开始切：
    其后第一个字段是第 3 字段（state），于是第 22 字段的下标是 22-3 = 19。
    """
    close = stat_text.rfind(")")
    if close < 0:
        return None
    rest = stat_text[close + 1:].split()
    if len(rest) <= 19:
        return None
    try:
        return int(rest[19])
    except ValueError:
        return None


def last_reload_time(proc_root: str | Path = "/proc") -> float | None:
    """nginx worker 最近一次启动的时刻（epoch 秒）；拿不到返回 None。

    None 的含义是**无法判断**，调用方必须按"不报警"处理（诚实降级：不拿猜的数当事实）。
    """
    proc = Path(proc_root)
    try:
        btime = _btime(proc)
    except OSError:
        return None
    if btime is None:
        return None
    try:
        hz = float(os.sysconf("SC_CLK_TCK"))
    except (ValueError, OSError):
        hz = 100.0
    newest: float | None = None
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue                                   # 进程已退出：正常竞态，跳过
        if b"nginx" not in cmdline or b"worker" not in cmdline:
            continue
        try:
            stat_text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ticks = _starttime_ticks(stat_text)
        if ticks is None:
            continue
        started = btime + ticks / hz
        if newest is None or started > newest:
            newest = started
    return newest


def drift(registry_path: str | Path, cert_dir: str | Path, bundle_path: str | Path,
          reload_at: float | None = None, now: float | None = None) -> dict:
    """把"登记过的证书"与"nginx 真正加载的信任包"之间的差距写成一份事实。

    返回的 dict 是**纯数据**（Ctx 的约定：视图层不许自己采）。键的含义：

    | 键 | 含义 | 运维含义 |
    | --- | --- | --- |
    | `missing` | 注册表里有、信任包里没有 | **真漂移**：生成器没跑（或跑在登记之前）|
    | `retired` | 有证书、注册表里没有 | 已退役的实例证书，按设计不并入（信息，不是故障）|
    | `no_cert` | 注册表里有、从未登记证书 | 只预留了入口，从未接入 ⇒ 入口必然 502 |
    | `stale_reload` | 有写入晚于 nginx 上次 reload（且已超过一个 timer 周期）| 定时器停了，或 `nginx -t` 不过导致它不敢 reload |
    | `newest_write` | 触发上面那条的最近一次（或几次）写入 | 页面直接把它印出来，省得运维自己找 |
    """
    now = now if now is not None else 0.0
    reg = Path(registry_path)
    cert_dir = Path(cert_dir)
    bundle = Path(bundle_path)

    labels: list[str] = []
    try:
        for raw in reg.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                labels.append(line.split()[0].lower())
    except OSError:
        pass

    try:
        bundle_text = bundle.read_text(encoding="utf-8", errors="replace")
    except OSError:
        bundle_text = ""

    missing, no_cert = [], []
    enrolled: dict[str, Path] = {}
    for label in labels:
        path = cert_dir / f"{label}.pem"
        if not path.is_file():
            no_cert.append(label)
            continue
        enrolled[label] = path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(label)
            continue
        if not bundle_text or not bundle_has_cert(bundle_text, text):
            missing.append(label)

    retired = []
    try:
        for path in sorted(cert_dir.glob("*.pem")):
            if path.name.startswith("."):              # 登记用的临时文件
                continue
            if path.stem.lower() not in labels:
                retired.append(path.stem.lower())
    except OSError:
        pass

    # 「谁比 nginx 的配置新」：只看真的会触发写入的两处（见模块说明）。
    # 并列最新的**全部列出**，不挑一个：换机时证书文件才是运维要看的那条，
    # 而 mtime 相同时（同一秒里既改了注册表又登记了证书）谁也不能被隐掉。
    newest_paths: list[str] = []
    newest_at = 0.0
    for path, what in [(reg, "注册表")] + [(p, "实例证书") for p in enrolled.values()]:
        try:
            at = path.stat().st_mtime
        except OSError:
            continue
        if at > newest_at:
            newest_paths, newest_at = [f"{what} {path.name}"], at
        elif at == newest_at and at:
            newest_paths.append(f"{what} {path.name}")
    # 归一化：`None`（拿不到 worker）→ 0.0 表示"无法判断"。对外仍回 `None`，
    # 因为页面要区分"已加载"与"无法判断"——而那两种都不能让算式碰到 Optional。
    try:
        reload_ts = float(reload_at) if reload_at else 0.0
    except (TypeError, ValueError):
        # 本函数是对外接口，`reload_at` 可能来自配置/测试脚本（字符串等）——
        # 读不懂就按"无法判断"处理，不让一个脏参数把整个页面变成 500。
        reload_ts = 0.0
    stale = reload_ts > 0 and (newest_at - reload_ts) > RELOAD_GRACE_S
    return {
        "labels": len(labels),
        "enrolled": len(enrolled),
        "missing": sorted(missing),
        "retired": sorted(retired),
        "no_cert": sorted(no_cert),
        "newest_write": ({"what": "、".join(newest_paths), "files": newest_paths,
                          "at": newest_at} if newest_paths else {}),
        "reload_at": (reload_ts or None),
        "stale_reload": stale,
        "stale_seconds": (newest_at - reload_ts) if stale else 0.0,
        "grace_s": RELOAD_GRACE_S,
        "bundle_readable": bool(bundle_text),
        "timer": ROUTES_TIMER,
        "timer_status": ROUTES_TIMER_STATUS,
        "command": FALLBACK_COMMAND,
        "checked_at": now,
    }
