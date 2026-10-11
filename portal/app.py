"""Portal 自助（UC-H10）：规范化 → 查重 → 核验 → 分配。

一条闭环，对应 UC-H10 的四个步骤：

    POST /apply    规范化 → 查重 → 交给核验器（命中呼号库即 verified，否则入人工队列）
    POST /verify   人工核验通过（维护者 / 执照材料）
    POST /grant    分配标签与端口 → 写注册表 → 打印实例侧上线命令
    POST /revoke   撤销并移除注册表条目（冒用被举报后走这里）

安全姿态：
* 默认只绑 **127.0.0.1** —— 这是管理面，不直接暴露到公网。
* 运维动作（verify/reject/grant/revoke）需要令牌，且用常数时间比较。
* 授予在代码层带硬性前置条件：**未核验不得授予**（见 `store.grant`）。
  理由是呼号是公开标识、入口可枚举（AD-H15 / I-H9），防线的位置只能在"核验之后"。

零第三方依赖（标准库 http.server），因为 hub 上只需要跑一个小内部服务。
"""
from __future__ import annotations

import argparse
import hmac
import html
import json
import os
import re
import subprocess
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from portal import callsign as cs          # noqa: E402
from portal import htpasswd as hp          # noqa: E402
from portal import metrics as metrics_mod   # noqa: E402
from portal import registry as reg          # noqa: E402
from portal import ui                       # noqa: E402
from portal import views as vs              # noqa: E402
from portal.views import _days_left         # noqa: E402,F401 — 权威实现在 views，这里 re-export
from portal.sessions import LoginGuard, SessionStore  # noqa: E402
from portal.store import Store             # noqa: E402
from portal.store import VERIFIED as STORE_VERIFIED  # noqa: E402
from portal.verify import (CallsignListVerifier, ChainVerifier, ClubLogVerifier,  # noqa: E402
                           ManualVerifier, VerificationOutcome)

DEFAULT_STORE = os.environ.get("MRRC_PORTAL_STORE", "/etc/mrrc-hub/portal.json")
DEFAULT_REGISTRY = os.environ.get("MRRC_PORTAL_REGISTRY", "/etc/mrrc-hub/instances.tsv")
DEFAULT_CALLSIGN_DB = os.environ.get("MRRC_PORTAL_CALLSIGN_DB", "/etc/mrrc-hub/callsigns.txt")
DEFAULT_TOKEN_FILE = os.environ.get("MRRC_PORTAL_TOKEN_FILE", "/etc/mrrc-hub/portal.token")
DEFAULT_USERS_FILE = os.environ.get("MRRC_PORTAL_USERS", "/etc/mrrc-hub/portal-users")
DEFAULT_FRPS_API = os.environ.get("MRRC_PORTAL_FRPS_API", "http://127.0.0.1:7100")
DEFAULT_FRPS_CREDENTIALS = os.environ.get("MRRC_PORTAL_FRPS_CREDENTIALS",
                                          "/etc/mrrc-hub/frps-web.credentials")

#: 后台会话 Cookie。名字独立于实例的 `mrrc_auth`：通配子域下命名空间公用，
#: 同名会互相覆盖或让实例读到 Hub 的凭据（约束 hub-cookie-name-not-instance-auth）。
COOKIE_NAME = "mrrc_portal_session"


def _host_is_loopback(host_header: str) -> bool:
    """Cookie 的 Secure 策略用：只有本机名不带 Secure，其余一律带。

    这样公网经 nginx 访问必然带 Secure（不依赖 nginx 是否记得 X-Forwarded-Proto），
    而本机 SSH 隧道直连 8890 仍可登录。
    """
    host = (host_header or "").strip().lower()
    if host.startswith("["):                      # [::1]:8890 → ::1
        host = host[1:].split("]")[0]
    else:
        host = host.split(":")[0]
    return host in ("127.0.0.1", "localhost", "::1")

#: frps 令牌的服务账号可读副本（部署时 `install -m 640 -o root -g <服务账号>` 一份出来）。
#: 端点**不**直接读 /etc/frp/frps.token：那是 root 的文件，服务账号读不到，也不该读到。
FRPS_TOKEN_FILE = os.environ.get("MRRC_PORTAL_FRPS_TOKEN_FILE", "/etc/mrrc-hub/frps.token.portal")


def _frps_token() -> str:
    try:
        return Path(FRPS_TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"⚠️ 读不到 frps 令牌副本 {FRPS_TOKEN_FILE}: {exc!r}", file=sys.stderr)
        return ""
DEFAULT_CLUBLOG = os.environ.get("MRRC_PORTAL_CLUBLOG", "/var/lib/mrrc-hub/portal/clublog_users.json")
DEFAULT_CERT_DIR = os.environ.get("MRRC_PORTAL_CERT_DIR", "/etc/mrrc-hub/instance-certs")

# 页面外壳与 www.vlsc.net 设计系统同 token（黑底 / 青 accent / Inter），
# 但样式内联、不外链 CSS —— 门户自身保持零依赖，www 不可用时注册页仍完整可用。
_PORTAL_CSS = """
:root{--accent:#22d3ee;--bg:#000;--bg2:#0d1117;--card:rgba(255,255,255,.03);
--tx:#fff;--tx2:#8899aa;--txm:#5c6370;--bd:rgba(255,255,255,.08);
--ok:#34d399;--warn:#fbbf24;--bad:#f87171;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx2);
font:15px/1.7 'Inter',-apple-system,BlinkMacSystemFont,'SF Pro Display','PingFang SC',sans-serif;
-webkit-text-size-adjust:100%;}
.p-head{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;
max-width:960px;margin:0 auto;padding:1.5rem 1.25rem .25rem;}
.p-brand{color:var(--tx);text-decoration:none;font-weight:700;font-size:1.1rem;letter-spacing:-.02em;}
.p-brand em{color:var(--accent);font-style:normal;}
.p-crumb{color:var(--txm);font-size:.8125rem;}
.p-main{max-width:960px;margin:0 auto;padding:.75rem 1.25rem 2.5rem;}
h1{color:var(--tx);font-size:1.7rem;letter-spacing:-.02em;margin:1.1rem 0 .6rem;}
h2{color:var(--tx);font-size:1.15rem;margin:2.2rem 0 .6rem;padding-bottom:.45rem;border-bottom:1px solid var(--bd);}
p{margin:.7rem 0}
a{color:var(--accent)}
code{font-family:'JetBrains Mono','SF Mono',monospace;font-size:.85em;
background:rgba(34,211,238,.09);color:#7dd3fc;padding:.12em .4em;border-radius:5px;}
table{border-collapse:collapse;width:100%;margin:1rem 0 1.6rem;background:var(--card);
border:1px solid var(--bd);border-radius:10px;overflow:hidden;}
td,th{border-bottom:1px solid var(--bd);padding:.55rem .8rem;text-align:left;font-size:.875rem;
color:var(--tx2);overflow-wrap:anywhere;word-break:break-word;vertical-align:top;}
/* 长串（证书主体、SHA、HTTP 状态行）不许撑破布局 */
td code{font-size:.78rem;white-space:normal}
/* 状态徽章：颜色集中在 CSS，不再散落成各视图里的内联 style */
.pill{display:inline-block;padding:.12rem .55rem;border-radius:999px;font-size:.75rem;
font-weight:600;line-height:1.55;white-space:nowrap;border:1px solid transparent}
.pill.ok{background:rgba(52,211,153,.14);color:var(--ok);border-color:rgba(52,211,153,.32)}
.pill.warn{background:rgba(251,191,36,.13);color:var(--warn);border-color:rgba(251,191,36,.32)}
.pill.bad{background:rgba(248,113,113,.13);color:var(--bad);border-color:rgba(248,113,113,.32)}
.pill.mute{background:rgba(255,255,255,.06);color:var(--tx2)}
h3{color:var(--tx);font-size:.95rem;margin:1.5rem 0 .3rem}
/* 导航：可换行、触摸目标 ≥44px、当前页用 aria-current 标记（不是内联 font-weight）*/
.nav{display:flex;flex-wrap:wrap;gap:.4rem;margin:.7rem 0 1.1rem}
.nav form{margin:0}
.nav button{min-height:44px;padding:.5rem 1rem;font-size:.9rem}
.nav a{display:inline-flex;align-items:center;min-height:44px;padding:.5rem 1rem;font-size:.9rem;
color:var(--tx2);text-decoration:none;border:1px solid var(--bd);border-radius:8px}
.nav a[aria-current=page]{background:var(--tx);border-color:var(--tx);color:#000}
.who{display:flex;justify-content:flex-end;margin:-.4rem 0 .8rem}
td form{display:inline-block;margin:.15rem .25rem .15rem 0}
td button{min-height:36px;padding:.35rem .7rem;font-size:.8125rem}
th{color:var(--txm);font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;background:rgba(255,255,255,.02);}
tr:last-child td{border-bottom:0}
td b{color:var(--tx)}
input,button{font:inherit;padding:.55rem .8rem;border-radius:8px;border:1px solid var(--bd);
background:var(--bg2);color:var(--tx);}
input::placeholder{color:var(--txm)}
input:focus{outline:none;border-color:var(--accent);}
button{background:var(--accent);border-color:var(--accent);color:#000;font-weight:600;cursor:pointer;padding:.55rem 1.1rem;}
button:hover{filter:brightness(1.1)}
form{margin:.4rem 0}
.msg{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.35);color:#34d399;
padding:.6rem .9rem;border-radius:8px;}
small{color:var(--txm);font-size:.8125rem;line-height:1.7;}
.p-foot{max-width:960px;margin:0 auto;padding:1.2rem 1.25rem 2.5rem;border-top:1px solid var(--bd);
color:var(--txm);font-size:.8125rem;}
.p-apply{display:grid;gap:.6rem;grid-template-columns:repeat(3,1fr);margin:1rem 0;}
.p-apply button{grid-column:1/-1;}
@media(max-width:720px){
.p-apply{grid-template-columns:1fr}
.p-head{padding:1rem .9rem .2rem;flex-wrap:wrap;gap:.25rem}
.p-main{padding:.6rem .9rem 2rem}
.p-foot{padding:1rem .9rem 2rem}
h1{font-size:1.35rem;margin:.9rem 0 .5rem}
h2{font-size:1.05rem;margin:1.5rem 0 .5rem}
h3{font-size:.9rem;margin:1.2rem 0 .25rem}
td,th{padding:.5rem .6rem;font-size:.8125rem}
.nav{gap:.35rem}
.nav button{flex:1 1 auto;padding:.5rem .6rem}
small{font-size:.78rem}
/* 宽表在窄屏堆叠成卡片：每格用 data-label 当小标题（表头对读屏仍可用，只是视觉隐藏）*/
table.stack{display:block;border:0;background:none;margin:.7rem 0 1.2rem}
table.stack thead{position:absolute;width:1px;height:1px;margin:-1px;padding:0;
overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
table.stack tr{display:block;border:1px solid var(--bd);border-radius:10px;
background:var(--card);margin:.55rem 0;overflow:hidden}
table.stack td{display:block;border-bottom:1px solid var(--bd);padding:.5rem .75rem}
table.stack tr td:last-child{border-bottom:0}
table.stack td::before{content:attr(data-label);display:block;color:var(--txm);font-size:.66rem;
text-transform:uppercase;letter-spacing:.07em;margin-bottom:.18rem}
table.stack td:not([data-label])::before{content:none}
/* 两列的「项/值」表本来就窄，保持表格但允许横向滚动兜底 */
table.kv{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
}
"""


# 兼容导出：既有测试从 portal.app 取 _PORTAL_CSS。样式表的权威在 portal/ui.py。
_PORTAL_CSS = ui.CSS


def _page(title: str, body: str, noindex: bool = False) -> str:
    """兼容包装：旧调用点（登录页/公开页）仍用 3 参数形式。

    页面外壳的权威在 `portal/ui.page()`；旧的两套外观（p-head/p-foot + 外链
    global-nav.js）已被新外壳取代。登录页与公开页在后续任务里改用 ui 组件直接渲染。
    """
    return ui.page(title, body, noindex=noindex)


# 兼容导出：既有代码与测试从 portal.app 取 trow。实现已搬去 portal/ui.py。
trow = ui.trow


def build_verifier(callsign_db: str | Path = DEFAULT_CALLSIGN_DB,
                   clublog: str | Path = DEFAULT_CLUBLOG):
    """核验链：Club Log 权威库 → 运维自建清单 → 人工兜底。

    顺序即优先级：能给出**确定结论**的依据先问（Club Log 27 万条），自建清单用于
    库里暂时没有的呼号（新用户），人工始终兜底 —— 与留言版同源，两个入口对同一呼号
    给出一致结论。
    """
    return ChainVerifier(ClubLogVerifier(clublog), CallsignListVerifier(callsign_db), ManualVerifier())


class Portal:
    """把 store + registry + verifier 组装成用例（与 HTTP 层解耦，便于测试）。"""

    def __init__(self, store: Store, registry: reg.Registry, verifier=None):
        self.store = store
        self.registry = registry
        self.verifier = verifier or build_verifier()

    def apply(self, raw_callsign: str, contact: str = "", product: str = "") -> dict:
        normalized = cs.normalize(raw_callsign)          # ① 规范化
        app = self.store.apply(normalized, contact, product)   # ② 查重（冲突即抛错）
        result = self.verifier.check(normalized)         # ③ 核验
        if result.outcome is VerificationOutcome.VERIFIED:
            app = self.store.mark_verified(normalized, result.evidence)
        elif result.outcome is VerificationOutcome.REJECTED:
            app = self.store.reject(normalized, result.evidence)
        return {"callsign": normalized, "status": app.status, "evidence": result.evidence,
                "label": cs.label_for(normalized, product),
                # 申请令牌只随这一次应答交给申请方本人：应用在设置里存下它，凭它轮询 /status。
                # 它读不了别人的申请、也改不了任何状态（见 store.Application.request_token）。
                "request_token": app.request_token}

    def grant(self, raw_callsign: str, actor: str = "") -> dict:
        normalized = cs.normalize(raw_callsign)
        app = self.store.get(normalized)
        if not app:
            raise KeyError(normalized)
        # 先查前置再动注册表：写注册表就是"开入口"，而开入口只有在核验之后才允许。
        # （早期实现先写注册表后调用 store.grant，于是未核验的申请虽被拒绝，
        #  注册表里却留下了一行 —— 测试抓到的就是它。）
        if app.status != STORE_VERIFIED:
            raise PermissionError(
                f"拒绝分配：{normalized} 当前状态 {app.status}，只有 {STORE_VERIFIED} 才可分配入口"
            )
        # 已经分配过入口的申请，重新申请必须沿用原来那个（标签 + 端口都由注册表承载，
        # hub 的 nginx 路由从注册表生成）。否则重新申请会把入口指到别处。
        if app.label and dict(self.registry.entries()).get(app.label):
            label = app.label
        else:
            label = cs.label_for(normalized, app.product)     # ④ 分配
        # 同一呼号再次申请必须落到同一个入口：注册表是 label -> port，hub 的 nginx 路由由它
        # 生成。早先这里无条件取下一个空闲端口，于是重新申请会把入口指到一个没人监听的端口
        # （实测：老朋友 18804 仍在路由里，隧道却起来在 18803，入口 502）。
        known = dict(self.registry.entries())
        if label in known:
            port = known[label]
        else:
            port = self.registry.free_port()
            self.registry.add(label, port)
        try:
            granted = self.store.grant(normalized, label, port, actor=actor)
        except Exception:
            if label not in known:                        # 失败即回滚，只回滚这次新增的
                self.registry.remove(label)
            raise
        return {"callsign": normalized, "label": label, "port": port,
                # 给租户看的下一步。**不要**再写老式的脚本命令：v1.24.0 起接入在应用
                # 设置菜单里完成（申请→批准→应用自动签证书/登记/起隧道），租户没有任何命令要跑。
                # 只有旧版应用才需要那份脚本，所以按 product 分叉。
                "next_step": (
                    "无需操作：批准后应用会自动完成接入（客户侧 v1.25.0 起每 30 秒自查一次）；"
                    "想立即完成就在应用里点：抽屉菜单（顶栏 ☰）→ 接入云端（Cloud Hub）→ 刷新状态"
                    if (app.product or "").strip() in ("mrrc_modern", "")
                    else f"在实例上运行 mrrc_hub/deploy/install_instance_tunnel.sh {label} {port}"
                ),
                "status": granted.status}

    def revoke(self, raw_callsign: str, reason: str, actor: str = "") -> dict:
        normalized = cs.normalize(raw_callsign)
        app = self.store.get(normalized)
        if not app:
            raise KeyError(normalized)
        removed = self.registry.remove(app.label) if app.label else False
        self.store.revoke(normalized, reason, actor=actor)
        return {"callsign": normalized, "label": app.label, "entry_removed": removed, "status": "revoked"}


def _cert_days(path=None) -> str:
    """入口证书剩余天数。

    读的是证书任务写的摘要文件（`/var/lib/mrrc-hub/portal/cert.txt`），而不是直接读
    `/etc/mrrc-hub/tls/fullchain.pem` —— 那个目录是私有的，Portal 以 mrrcportal 运行，
    读不到。**收紧权限是对的，所以改写入方，而不是放宽读取方。**
    """
    path = Path(path or os.environ.get("MRRC_PORTAL_CERT_INFO", "/var/lib/mrrc-hub/portal/cert.txt"))
    if not path.exists():
        return "未生成（证书任务下次运行时会写）"
    try:
        text = path.read_text(encoding="utf-8")
        stamp = [ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("notAfter=")][0]
        end = time.mktime(time.strptime(" ".join(stamp.split()[:4]), "%b %d %H:%M:%S %Y"))
        days = int((end - time.time()) // 86400)
        return f"{days} 天（{stamp}）" + ("　⚠️ 需检查续期" if days < 14 else "")
    except Exception:                                  # noqa: BLE001
        return "（摘要文件无法解析）"


#: 隧道探测的四种结论。分这么细是因为**修法完全不同**：
#: 「未连接」是租户那边 frpc 没跑；「后端无应答」是 frpc 在跑但它转发的本地端口上没有程序
#: （应用没起 / 端口写错 / 绑到了别的地址）；「在说明文 HTTP」是应用起来了但没加载证书，
#: 而 nginx 是以 https 反代并校验上游证书的 ⇒ 访客一律 502。
TUNNEL_SERVING = "serving"
TUNNEL_PLAIN_HTTP = "plain-http"
TUNNEL_HOLLOW = "hollow"
TUNNEL_DOWN = "down"

TUNNEL_TEXT = {
    TUNNEL_SERVING: "在线",
    TUNNEL_PLAIN_HTTP: "在说明文 HTTP",
    TUNNEL_HOLLOW: "隧道在、后端无应答",
    TUNNEL_DOWN: "未连接",
}

#: 每种状态对应的徽章类。能服务=绿；两类「连得上但用不了」=琥珀（容易和真离线混淆，
#: 所以不用红）；完全没连上=红。颜色本身在 CSS 里，这里只给类名。
TUNNEL_PILL = {
    TUNNEL_SERVING: "ok",
    TUNNEL_PLAIN_HTTP: "warn",
    TUNNEL_HOLLOW: "warn",
    TUNNEL_DOWN: "bad",
}


def _fmt_bps(value) -> str:
    """已搬去 portal/views.py（纯格式化）；保留名字以免外部引用断掉。"""
    return vs._fmt_bps(value)


def _fmt_bytes(value) -> str:
    return vs._fmt_bytes(value)


def _ago(seconds) -> str:
    return vs._ago(seconds)


# ── 可观测面：系统 → 服务 → 隧道 → 实例 → 实例里的应用 ──────────────
# 设计约束：本服务以非特权用户 mrrcportal 运行（NoNewPrivileges、不能 sudo）。
# 2026-10-03 在 hub 上逐项实测的可达面：
#   可读   /etc/mrrc-hub/instances.tsv、callsigns.txt、instance-certs/*.pem、
#          /proc/{loadavg,meminfo,uptime}
#   可执行 systemctl is-active/is-enabled/show、ss -tn / -ltn（不带 -p）、openssl、python3
#   不可读 /var/log/nginx/*.log ⇒ **拿不到每实例的 nginx 错误计数**；/etc/frp/frps.toml
# 每个采集器失败时都返回可读文案而**不抛异常** —— 管理台是排障入口，它自己崩了
# 就什么都看不到了（与 _cert_days 同一个姿态）。

#: 管理台要盯的单元。**缺单元本身就是要暴露的事实**：hub 上 mrrc-hub-routes.timer
#: 根本没装（`is-enabled` = not-found），而 SDD V0.22 写着「V0.17 起 30 s timer 自动
#: 重生成路由」⇒ 新增实例后 nginx 路由不会自动出现，入口一直 404 直到有人手工跑
#: gen_hub_routes.py。这类漂移只有在页面上列出来才会被发现。
WATCHED_UNITS = ("frps", "nginx", "mrrc-portal",
                 "mrrc-hub-routes.timer", "mrrc-hub-routes.path", "certbot.timer")


def _run(cmd, timeout: float = 5.0):
    """跑一条只读命令 → (returncode, stdout)。任何异常都变成可读文案，不外抛。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except Exception as exc:                                     # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def _run_der(cmd, der: bytes, timeout: float = 5.0) -> str:
    """把 DER 从 stdin 喂给 openssl（避免落临时文件）。"""
    try:
        r = subprocess.run(cmd, input=der, capture_output=True, timeout=timeout)
        return (r.stdout or b"").decode("utf-8", "replace").strip()
    except Exception as exc:                                     # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def _host_resources() -> dict:
    """第 1 层：hub 主机自身。全部来自 /proc、os 与 `df -Pk`，不需要特权。"""
    out = {"load": "—", "cpu": "—", "mem": "—", "disk": "—", "uptime": "—",
           "python": sys.version.split()[0]}
    try:
        out["load"] = " ".join(f"{x:.2f}" for x in os.getloadavg())
        out["cpu"] = f"{os.cpu_count()} 核"
    except OSError as exc:
        out["load"] = f"读不到：{exc}"
    try:
        mem = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            k, _, rest = line.partition(":")
            mem[k.strip()] = int(rest.strip().split()[0])          # kB
        if "MemAvailable" in mem and "MemTotal" in mem:
            out["mem"] = (f"可用 {mem['MemAvailable'] // 1024} MB / 共 {mem['MemTotal'] // 1024} MB"
                          f"（{100 * mem['MemAvailable'] // max(1, mem['MemTotal'])}% 可用）")
    except (OSError, ValueError, IndexError) as exc:
        out["mem"] = f"读不到：{exc}"
    try:
        up = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        out["uptime"] = f"{int(up // 86400)} 天 {int(up % 86400 // 3600)} 小时"
    except (OSError, ValueError, IndexError) as exc:
        out["uptime"] = f"读不到：{exc}"
    # 用 df 而不是 shutil.disk_usage：APFS 上后者拿到的 total 是**整个容器**、free 是
    # 容器剩余，于是 used = total - free 把别的卷也算了进来 —— macOS 上实测显示
    # 「已用 95%」，而 df 说 51%（本卷只用 11.7 GB / 容器 233 GB）。排障时运维会拿页面
    # 数字和 df 对照，差这么多足以让他去追一个不存在的磁盘问题。
    # `-k` 固定 1024 字节块：BSD 的 `-P` 默认 512 字节块（除非设 POSIXLY_CORRECT），
    # Linux 是 1024，不统一就会算错一倍。
    rc, text = _run(["df", "-Pk", "/"], timeout=3)
    fields = text.splitlines()[1].split() if rc == 0 and len(text.splitlines()) > 1 else []
    if len(fields) >= 5 and fields[1].isdigit() and fields[3].isdigit():
        try:
            # isdigit() 对 '²' 这类 Unicode 数字也为真，而 int() 会抛 ValueError ——
            # 所以真正的护栏是这里的 except，不是上面那个判断。
            out["disk"] = (f"/ 可用 {int(fields[3]) // 1024} MB / 共 {int(fields[1]) // 1024} MB"
                           f"（已用 {fields[4]}）")
        except (ValueError, IndexError) as exc:
            out["disk"] = f"df 行无法解析：{exc}（{text[:60]}）"
    else:
        out["disk"] = f"df 没有给出可解析的行（rc={rc}）：{text[:60]}"
    return out


def _service_states(units=WATCHED_UNITS) -> list:
    """第 2 层：hub 上的服务 → [(单元, 状态, 开机自启, 起于, 重启次数)]。

    「未安装」是一种**结论**而不是错误：单元文件在仓库里、却没装到 hub 上，
    正是路由不会自动重生成的原因。
    """
    rows = []
    for u in units:
        rc, active = _run(["systemctl", "is-active", u], timeout=3)
        if rc == -1:
            # systemctl 根本跑不了（本机不是 systemd 系统，或 PATH 里没有）。
            # 一行说清即可 —— 把同一条异常抄进四个单元格、还被 [:24] 截成半截词，
            # 那是噪音不是信息。
            rows.append((u, "systemctl 不可用", "—", "—", "—"))
            continue
        _, enabled = _run(["systemctl", "is-enabled", u], timeout=3)
        state = active or "?"
        if enabled == "not-found":
            state = "未安装"
        since = restarts = "—"
        if state not in ("未安装",):
            _, v = _run(["systemctl", "show", u, "-p", "ActiveEnterTimestamp", "--value"], timeout=3)
            since = v[:24] or "—"
            _, v = _run(["systemctl", "show", u, "-p", "NRestarts", "--value"], timeout=3)
            restarts = v or "—"
        rows.append((u, state, enabled or "—", since, restarts))
    return rows


def _net_facts() -> dict:
    """第 3 层：frps 的监听口与 frpc 的控制连接（ss 不带 -p，非特权可用）。"""
    out = {"listen": [], "peers": [], "note": ""}
    _, lsn = _run(["ss", "-ltn"], timeout=3)
    ports = set()
    for line in lsn.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4 and ":" in parts[3]:
            try:
                port = int(parts[3].rsplit(":", 1)[1])
            except ValueError:
                continue
            if 18800 <= port <= 18999 or port == 8989:
                ports.add(port)
    out["listen"] = sorted(ports)
    _, est = _run(["ss", "-tn"], timeout=3)
    peers = set()
    for line in est.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5 and parts[3].endswith(":8989"):
            ip = parts[4].rsplit(":", 1)[0].strip("[]")
            peers.add(ip[7:] if ip.startswith("::ffff:") else ip)
    out["peers"] = sorted(peers)
    if not ports:
        out["note"] = "ss 没有给出任何 frps 端口（ss 不可用？还是 frps 没在跑？）"
    return out


def _cert_facts(der: bytes, expect: str = "", inform: str = "der") -> dict:
    """上游证书的主体/签发者/到期日，以及**名字是否与期望一致**。

    用 openssl 解析而不是引第三方库 —— 与 `cert_names()` 同一个理由（stdlib 不能解析
    证书，而本服务刻意不引依赖）。expect 为空表示无法判断（注册表没给 tls_name）。
    """
    out = {"subject": "—", "issuer": "—", "not_after": "—", "names": set(), "name_ok": None}
    if not der:
        return out
    text = _run_der(["openssl", "x509", "-inform", inform, "-noout",
                     "-subject", "-issuer", "-enddate", "-ext", "subjectAltName"], der)
    for line in text.splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("subject="):
            out["subject"] = line.split("=", 1)[1].strip()
            m = re.search(r"CN\s*=\s*([^,/\n]+)", line)
            if m:
                out["names"].add(m.group(1).strip().lower())
        elif low.startswith("issuer="):
            out["issuer"] = line.split("=", 1)[1].strip()
        elif low.startswith("notafter="):
            out["not_after"] = line.split("=", 1)[1].strip()
        elif low.startswith("dns:"):
            out["names"].add(line[4:].strip().lower())
        elif "DNS:" in line:                      # -ext 的多值行：DNS:a, DNS:b
            for part in line.split("DNS:")[1:]:
                name = part.split(",")[0].strip().lower()
                if name:
                    out["names"].add(name)
    if expect:
        out["name_ok"] = expect.strip().lower() in out["names"]
    return out


def _hub_cert_inventory(cert_dir=None) -> list:
    """hub 侧已登记的实例证书 → [(文件名, 主体, 到期, 剩余天数)]。

    这是「谁真的走完了批准→登记」的权威凭据：注册表里有一行只代表**预留**，
    没有证书就说明它从未接入（bh1eih 就是这种，所以它的入口只能 502）。
    `mrrcportal` 实测可读该目录，所以不需要提权。
    """
    d = Path(cert_dir or DEFAULT_CERT_DIR)
    # Path.glob() 对不存在的目录**不抛异常、只返回空**，所以下面的 try/except 拦不住它。
    # 而「读不到目录」与「没有实例登记过」在页面上必须长得不同：前者是权限/路径故障，
    # 后者是业务事实。混为一谈会让运维以为没人接入过。
    if not d.is_dir():
        return [(f"（证书目录不存在或不可读：{d}）", "—", "—", None)]
    out = []
    try:
        files = sorted(x for x in d.glob("*.pem") if x.is_file())
    except OSError as exc:
        return [(f"（读不到证书目录：{exc}）", "—", "—", None)]
    for f in files:
        try:
            data = f.read_bytes()
        except OSError as exc:
            out.append((f.name, f"读不到：{exc}", "—", None))
            continue
        facts = _cert_facts(data, "", inform="pem")
        out.append((f.name, facts["subject"], facts["not_after"], _days_left(facts["not_after"])))
    return out


def _app_generation(port, label: str, timeout: float = 2.5) -> str:
    """第 5 层：实例里那个应用的构建代号（`sw.js` 的 `CACHE = 'mrrc-vNN'`）。

    **这不是 semver**：实例没有任何未鉴权的版本端点（`/api/*` 全部要令牌，
    `/login`、`/manifest.json`、`/version.txt` 都不含版本号 —— 2026-10-03 实测），
    所以只能取这个每次改静态资产都会 bump 的缓存代号，用来判断各实例**是否同代**。
    要拿到确切版本，得让应用自己上报（它在轮询 /status 时带上 detect_version()），
    那是一次应用侧改动，不在本服务能单独完成的范围内。
    """
    import contextlib
    import socket
    import ssl

    host_header = f"{label}.mrrc.vlsc.net" if label else "127.0.0.1"
    try:
        raw = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    except OSError:
        return "—"
    with contextlib.closing(raw):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            tls = ctx.wrap_socket(raw, server_hostname=host_header)
        except (ssl.SSLError, OSError):
            return "—"
        with contextlib.closing(tls):
            try:
                tls.settimeout(timeout)
                tls.sendall(f"GET /sw.js HTTP/1.0\r\nHost: {host_header}\r\n"
                            f"User-Agent: mrrc-hub-probe\r\n\r\n".encode("ascii"))
                body = b""
                while len(body) < 65536:
                    chunk = tls.recv(4096)
                    if not chunk:
                        break
                    body += chunk
            except OSError:
                return "—"
    m = re.search(rb"CACHE\s*=\s*['\"]([^'\"]+)['\"]", body)
    return m.group(1).decode("latin-1") if m else "（sw.js 里没有 CACHE 标记）"


def _probe(port, label: str = "", tls_name: str = "", timeout: float = 2.5) -> dict:
    """一次探测采齐一个实例的全部可见事实（判据见 _tunnel_state 的说明）。

    证书是在**同一次 TLS 握手**里顺带取走的（getpeercert 的 DER 形式），不再多开连接；
    `plain-http` 与 `hollow` 拿不到证书，因为握手根本没成。
    """
    import contextlib
    import socket
    import ssl

    host_header = f"{label}.mrrc.vlsc.net" if label else "127.0.0.1"
    rep = {"state": TUNNEL_DOWN, "detail": "", "status_line": "", "server": "",
           "cert": {"subject": "—", "issuer": "—", "not_after": "—", "names": set(),
                    "name_ok": None},
           "generation": "—"}
    try:
        raw = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    except OSError as exc:
        rep["detail"] = f"回环端口连不上（frpc 未注册代理）：{exc}"
        return rep

    tls_err = ""
    with contextlib.closing(raw):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            tls = ctx.wrap_socket(raw, server_hostname=host_header)
        except (ssl.SSLError, OSError) as exc:
            tls_err = f"{type(exc).__name__}: {exc}"
        else:
            with contextlib.closing(tls):
                try:
                    der = tls.getpeercert(binary_form=True) or b""
                except (ssl.SSLError, OSError):
                    der = b""
                rep["cert"] = _cert_facts(der, tls_name or host_header)
                status, server = _probe_http(tls, host_header, timeout)
                rep["status_line"], rep["server"] = status, server
            if status:
                rep["state"] = TUNNEL_SERVING
                rep["detail"] = status
                rep["generation"] = _app_generation(port, label, timeout)
                return rep
            rep["state"] = TUNNEL_HOLLOW
            rep["detail"] = "TLS 握手成了，但没有任何 HTTP 应答"
            return rep

    # TLS 走不通：后面是不是有个只说明文 HTTP 的应用？（v1.24.5「装完黑屏」的同一形状）
    try:
        plain = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    except OSError:
        rep["state"] = TUNNEL_HOLLOW
        rep["detail"] = f"端口可连但无应答（TLS：{tls_err}）"
        return rep
    with contextlib.closing(plain):
        status, server = _probe_http(plain, host_header, timeout)
    rep["status_line"], rep["server"] = status, server
    if status:
        rep["state"] = TUNNEL_PLAIN_HTTP
        rep["detail"] = f"后端只说明文 HTTP（{status}），而 nginx 以 https 反代"
    else:
        rep["state"] = TUNNEL_HOLLOW
        rep["detail"] = f"端口可连、明文与 TLS 都无应答（TLS：{tls_err}）"
    return rep


def _probe_http(sock, host_header: str, timeout: float):
    """要一次 `/api/health`，返回 (状态行, Server 头)；对端不给任何字节则两项皆空。

    **任何状态码都算在服务**（包括 401/404）—— 这里要回答的是「后面有没有一个活的应用」，
    不是「它健不健康」。跟 `mrrc_modern/launcher_net.answers()` 同一个判据：那边正是因为
    把 401 当成失败，才让启动器在服务器明明活着的时候去开了另一个协议（v1.24.6 黑屏）。

    读到 `\r\n\r\n` 为止而不是只读一行：`Server` 头在状态行之后，而它是判断上游到底是不是
    本项目（实测为 `server: uvicorn`）的唯一未鉴权线索。
    """
    try:
        sock.settimeout(timeout)
        sock.sendall((f"GET /api/health HTTP/1.0\r\nHost: {host_header}\r\n"
                      f"User-Agent: mrrc-hub-probe\r\nConnection: close\r\n\r\n").encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 8192:
            chunk = sock.recv(1024)
            if not chunk:
                break
            head += chunk
    except OSError:
        return "", ""
    if not head:
        return "", ""
    text = head.decode("latin-1", "replace")
    lines = text.split("\r\n")
    server = ""
    for line in lines[1:]:
        if line.lower().startswith("server:"):
            server = line.split(":", 1)[1].strip()
            break
    return (lines[0].strip() if lines else ""), server


def _tunnel_state(port, label: str = "", timeout: float = 2.5):
    """一个实例端口的 (状态, 说明)。判据与四种结论的修法见 `_probe`。

    旧判据只做一次 TCP 连接，那是个**假阳性**：frps 是在 hub 本机接受连接的，只要
    frpc 注册过代理就永远连得上 —— 于是 bg7zhs 在隧道另一端空着的时候仍然显示「在线」，
    而每个访客拿到 nginx 的 502（2026-10-03 实测）。
    """
    rep = _probe(port, label, "", timeout)
    return rep["state"], rep["detail"]


def _probe_timed(port, label: str = "", timeout: float = 2.5) -> tuple:
    """采样器用的探测：复用四态判据，顺带把端到端耗时量出来。

    延时只在握手真正完成（serving）时给值 —— 连不上的等待时间不是网络延时，
    把它当延时展示是编数据（诚实降级原则）。
    """
    start = time.monotonic()
    try:
        state, detail = _tunnel_state(port, label, timeout)
    except Exception as exc:                          # noqa: BLE001 — 采集器不许把服务带崩
        return TUNNEL_DOWN, f"探测异常：{exc}", None
    elapsed = (time.monotonic() - start) * 1000.0
    return state, detail, (elapsed if state == TUNNEL_SERVING else None)


def _tunnel_states(entries, timeout: float = 2.5) -> dict:
    """并发探测全部实例 ⇒ 一个死掉的隧道不会把整页拖成串行等待。

    最坏情况是每个实例都黑洞（等到超时），4 个实例串行就是 4×timeout；总览页不该为此卡住。
    """
    from concurrent.futures import ThreadPoolExecutor

    if not entries:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as pool:
        futures = {pool.submit(_tunnel_state, port, label, timeout): port
                   for label, port in entries}
        return {port: fut.result() for fut, port in futures.items()}


def _instance_reports(entries_full, timeout: float = 2.5) -> dict:
    """并发采集每个实例的完整可见事实 ⇒ {label: 报告}。

    与 `_tunnel_states` 一样并发：最坏情况是每个实例都黑洞（TLS 与明文各等满一次超时），
    串行会把管理台页面拖成 N×2×timeout。
    """
    from concurrent.futures import ThreadPoolExecutor

    items = [(label, port, tls) for label, port, tls in entries_full]
    if not items:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        futures = {pool.submit(_probe, port, label, tls, timeout): label
                   for label, port, tls in items}
        return {label: fut.result() for fut, label in futures.items()}


def _tunnel_online(port, label: str = "") -> bool:
    """兼容用的布尔包装：**只有真正在服务才算在线**。

    总览与实例页都要问同一个问题，所以只在这里探一次 —— 两个视图里各写一个同名 `probe`
    会互相遮蔽（同一个函数作用域），后人改动时很容易改错那一个。
    """
    return _tunnel_state(port, label)[0] == TUNNEL_SERVING


def _clublog_info() -> str:
    """Club Log 库的文件时间与规模（不解析 36MB，只 stat；条数由核验器缓存提供）。"""
    from portal.verify import ClubLogVerifier
    path = Path(DEFAULT_CLUBLOG)
    if not path.exists():
        return "未就位（核验将全部转人工）"
    size = path.stat().st_size
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return f"{size / 1048576:.1f} MB，更新于 {age_h:.1f} 小时前" + ("　⚠️ 超过 48 小时" if age_h > 48 else "")


def cert_names(pem_path) -> set:
    """用 openssl 读证书的 subject CN 与 SAN 里的 DNS 名。

    本服务不引第三方库，而 stdlib 又不能解析证书 ⇒ 调 openssl（hub 一定有）。
    读失败返回空集合，调用方据此拒绝登记。
    """
    names: set = set()
    try:
        out = subprocess.run(["openssl", "x509", "-in", str(pem_path), "-noout", "-subject", "-ext", "subjectAltName"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return names
        for line in out.stdout.splitlines():
            if line.lower().startswith("subject="):
                m = re.search(r"CN\s*=\s*([^/,\s]+)", line)
                if m:
                    names.add(m.group(1).strip().lower())
            elif "dns:" in line.lower():
                names.update(part.strip().lower() for part in re.findall(r"DNS:([^,\s]+)", line, re.I))
    except Exception as exc:                            # noqa: BLE001
        # 静默吞掉这里的原因曾让排查绕了两轮：名字解析失败会被下游当成"证书名字不符"。
        # 现在把原因写进日志（journalctl -u mrrc-portal 可见）。
        print(f"⚠️ cert_names 解析失败: {exc!r}", file=sys.stderr)
    return names


def make_handler(portal: Portal, token: str, base: str = "", *,
                 users: hp.UsersFile | None = None,
                 sessions: SessionStore | None = None,
                 guard: LoginGuard | None = None,
                 sampler=None,
                 cookie_secure: str = "auto"):
    """base 是挂载前缀（如 `/mrrc_portal`），空串表示挂在根。

    两边都容忍：入口收到 `{base}/apply` 或 `/apply` 都能处理（边缘可以保留前缀，
    也可以剥掉前缀）。页面里的链接用**相对形式**（`action="apply"`），因此同一份代码
    挂在根（`https://portal.../`）与挂在前缀（`https://www.vlsc.net/mrrc_portal/`）
    下都指向正确位置 —— 不必为每个挂载点各配一份 base。

    认证装配（默认值让旧调用点不受影响）：`users` 是账号文件；`sessions`/`guard`
    是内存态会话与登录锁定；`sampler` 是隧道指标采集器（None = 视图显示未启用）。
    """
    base = ("/" + base.strip("/")) if base and base.strip("/") else ""
    session_store: SessionStore = sessions if sessions is not None else SessionStore()
    login_guard: LoginGuard = guard if guard is not None else LoginGuard()
    class Handler(BaseHTTPRequestHandler):
        server_version = "MRRC-Portal/1.0"

        def log_message(self, format, *args):    # noqa: A002 - 基类就是这么命名的
            # 不记录 query（可能含呼号/联系方式）
            sys.stderr.write("portal: " + format % args + "\n")

        def _route(self) -> str:
            """去掉挂载前缀后的路径；带前缀与不带前缀两种形式都接受。

            末尾斜杠归一化：`/admin/` 与 `/admin` 是同一个路由（否则表单动作
            相对当前地址再拼一次就会变成 `/admin/admin/...`）。
            """
            path = self.path.split("?")[0]
            if base and (path == base or path.startswith(base + "/")):
                path = path[len(base):] or "/"
            if len(path) > 1 and path.endswith("/"):
                path = path.rstrip("/")
            return path

        # ---- helpers ----
        def _body(self) -> dict:
            # 解析失败一律抛 ValueError：调用方把它变成 400「请求体无法解析」（而不是 500），
            # 所以这里说清楚是哪一步失败，同时不让裸的 int()/json.loads() 逃出去。
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Content-Length 不是数字: {exc}") from exc
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            if (self.headers.get("Content-Type") or "").startswith("application/json"):
                try:
                    return json.loads(raw or "{}")
                except json.JSONDecodeError as exc:
                    raise ValueError(f"JSON 无法解析: {exc}") from exc
            from urllib.parse import parse_qs
            return {k: v[0] for k, v in parse_qs(raw).items()}

        def _send(self, code: int, payload: dict | str, ctype="application/json; charset=utf-8",
                  headers: dict | None = None):
            body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        # ---- 静态资源（白名单）----
        def _serve_static(self, name: str):
            """白名单静态资源。名字**精确匹配**，不做路径拼接 ⇒ `..` 无从下手。

            不需要登录：这是公开的第三方库与本站脚本，且公开注册页也要用它。
            缓存一年 + immutable：内容按 sha256 冻结，靠 manifest 守卫保证它不变。
            """
            ctype = ui.STATIC_WHITELIST.get(name)
            if ctype is None:
                return self._send(404, {"error": "not found"})
            try:
                blob = (ui.STATIC_DIR / name).read_bytes()
            except OSError as exc:
                return self._send(404, {"error": f"asset unavailable: {exc}"})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", ui.STATIC_CACHE)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(blob)

        # ---- 认证：会话 Cookie + CSRF（浏览器），令牌请求头（机器）----
        def _query(self) -> dict:
            from urllib.parse import parse_qs, urlsplit
            return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

        def _session(self):
            """→ (sid, Session) 或 (None, None)。"""
            jar = SimpleCookie()
            jar.load(self.headers.get("Cookie") or "")
            morsel = jar.get(COOKIE_NAME)
            if not morsel:
                return None, None
            s = session_store.get(morsel.value)
            return (morsel.value, s) if s else (None, None)

        def _cookie_secure(self) -> bool:
            if cookie_secure == "on":
                return True
            if cookie_secure == "off":
                return False
            return not _host_is_loopback(self.headers.get("Host") or "")

        def _cookie_header(self, sid: str, max_age: float) -> str:
            parts = [f"{COOKIE_NAME}={sid}", f"Path={base or '/'}", "HttpOnly", "SameSite=Lax",
                     f"Max-Age={max_age:.0f}"]
            if self._cookie_secure():
                parts.append("Secure")
            return "; ".join(parts)

        def _client_ip(self) -> str:
            """回环对端才信任代理头；否则用 socket 对端。nginx 未透传时会退化为 127.0.0.1
            全局桶 —— 这是已记录的退化，部署检查单里要求核对（SDD §12.9）。"""
            peer = self.client_address[0] if self.client_address else ""
            if peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                xff = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
                return xff or (self.headers.get("X-Real-IP") or "").strip() or peer
            return peer

        def _csrf_ok(self, body: dict, s) -> bool:
            return bool(s) and hmac.compare_digest(str(body.get("csrf") or ""), s.csrf)

        def _action_actor(self, body: dict) -> tuple[bool, str]:
            """机器路径（X-Portal-Token 请求头）或浏览器路径（会话+CSRF）：→ (通过, actor)。"""
            if self._operator_ok(body):
                return True, "token"
            _, s = self._session()
            if s and self._csrf_ok(body, s):
                return True, s.user
            return False, ""

        def _admin_root(self) -> str:
            """请求路径里 `/admin` 之前的前缀（`''` 或 `/mrrc_portal`）——浏览器可见的那一段。

            管理台内部的链接与表单全部用它拼**绝对路径**：登录失败后页面是在
            `/admin/login` 上重渲染的，当时表单用的是裸相对 `action=admin/login`，
            浏览器把它拼成了 `/admin/admin/login`（2026-10-05 现场事故）。
            """
            path = self.path.split("?")[0]
            idx = path.find("/admin")
            return path[:idx] if idx > 0 else ""

        def _console_url(self) -> str:
            """浏览器可见的管理台路径（挂根 `/admin`，挂前缀 `/mrrc_portal/admin`）。"""
            return self._admin_root() + "/admin"

        def _login_page(self, error: str = "", status: int = 200, retry_after: int = 0):
            note = ("<p><small>账号文件：<code>/etc/mrrc-hub/portal-users</code>（htpasswd，"
                    "$apr1$；用 <code>openssl passwd -apr1</code> 生成）。脚本/curl 仍可用 "
                    "<code>X-Portal-Token</code> 请求头调用运维动作。</small></p>")
            if retry_after:
                note = (f"<p class=msg>失败次数过多，请 {retry_after} 秒后再试。</p>" + note)
            elif error:
                note = f"<p class=msg>{html.escape(error)}</p>" + note
            body = ("<h1>运维审批</h1>"
                    f"<form method=post action='{self._admin_root()}/admin/login'>"
                    "<input name=user placeholder=用户名 autocomplete=username autofocus required>"
                    "<input type=password name=password placeholder=密码 autocomplete=current-password required>"
                    "<button>登录</button></form>" + note)
            headers = {"Retry-After": str(retry_after)} if retry_after else None
            return self._send(status, _page("MRRC Portal — 运维登录", body, noindex=True),
                              ctype="text/html; charset=utf-8", headers=headers)

        def _operator_ok(self, body: dict | None = None) -> bool:
            """令牌**只认请求头**：浏览器路径已由会话+CSRF 取代（表单字段不再接受）。"""
            if not token:
                return False
            supplied = (self.headers.get("X-Portal-Token") or "").strip()
            return hmac.compare_digest(supplied, token)

        # ---- operator console ----
        def _ctx_for(self, view: str, msg: str = "", flt: str = "", q: str = "",
                     page: int = 1, label: str = "") -> "vs.Ctx":
            """装配一次渲染需要的**全部**事实。这是唯一的采集点（视图层不许自己采）。

            采集量按视图裁剪：只有实例页要跑 TLS 探测，只有系统页要读主机事实 ——
            否则「换个 tab」也要把每个实例都探一遍。
            """
            _, session = self._session()
            entries = portal.registry.entries()
            entries_full = portal.registry.entries_full()
            return vs.Ctx(
                root=self._admin_root(),
                csrf=session.csrf if session else "",
                user=session.user if session else "",
                msg=msg,
                view=view,
                apps=portal.store._load()["applications"],
                audit=list(reversed(portal.store.audit())),
                entries=entries,
                entries_full=entries_full,
                states=_tunnel_states(entries) if view in ("overview", "instances") else {},
                reports=_instance_reports(entries_full) if view == "instances" else {},
                resources=_host_resources() if view == "system" else {},
                services=_service_states() if view == "system" else [],
                net=_net_facts() if view == "system" else {},
                certs=_hub_cert_inventory() if view == "system" else [],
                cert_days=_cert_days() if view == "overview" else "—",
                clublog=_clublog_info() if view in ("overview", "clublog") else "",
                clublog_path=str(DEFAULT_CLUBLOG),
                registry_first=portal.registry.first,
                registry_last=portal.registry.last,
                sampler=(sampler.snapshot() if sampler is not None else None),
                tunnel_text=TUNNEL_TEXT,
                tunnel_pill=TUNNEL_PILL,
                now=time.time(),
                flt=flt,
                q=q,
                page=page,
                flt_label=label,
            )

        def _admin(self, view: str, msg: str = "", part: str | None = None,
                   flt: str = "", q: str = "", page: int = 1) -> str:
            """后台管理台：装配 Ctx → 交给 views 渲染（服务端渲染，全部 7 个视图）。

            安全姿态（变化的与不变的要分清）：
              * 浏览器路径靠**会话 Cookie（HttpOnly/SameSite=Lax/Secure）+ 表单 CSRF 字段**；
                机器路径（脚本/curl）仍用 `X-Portal-Token` 请求头，**表单不再接受令牌字段**。
              * 令牌/会话值不进 URL、不进 Location、不进访问日志；导航只是 GET `?view=`。
              * **需要 root 的操作不由本服务执行**：Web 服务解析外网输入，给它
                nginx reload / 拉库的权限是自找麻烦。这里只把命令打出来让运维执行。
            """
            ctx = self._ctx_for(view, msg=msg, flt=flt, q=q, page=page)
            r = vs.render(view, ctx, part=part)
            return _page(r.title, r.chrome + r.live, noindex=True)

        # ---- routes ----
        def do_GET(self):                        # noqa: N802
            route = self._route()
            if route.startswith("/admin/static/"):
                return self._serve_static(route[len("/admin/static/"):])
            if route in ("/admin", "/admin/login"):
                _, session = self._session()
                if session is None:
                    return self._login_page()
                if route == "/admin/login":
                    # 直连 /admin/login 时把已登录者送回控制台（保持单一 URL）
                    return self._send(303, "", ctype="text/plain; charset=utf-8",
                                      headers={"Location": self._console_url()})
                return self._send(200, self._admin(self._query().get("view") or "overview"),
                                  ctype="text/html; charset=utf-8")
            if self._route() != "/":
                return self._send(404, {"error": "not found"})
            # 这是租户在**自己手机上**看的那张表，所以同样要能在窄屏堆叠。
            rows = "".join(trow(
                ("呼号", f"<code>{html.escape(a['callsign'])}</code>"),
                ("状态", f"<span class='pill ok'>{html.escape(a['status'])}</span>"),
                ("标签", html.escape(a['label'] or '—')),
                ("端口", str(a['port'] or '—')))
                for a in portal.store.bindings().values()
            ) or "<tr><td colspan=4>（暂无已授予实例）</td></tr>"
            self._send(200, _page(
                "MRRC Cloud Hub — 呼号自助注册",
                "<h1>呼号自助注册</h1>"
                "<p>按 <strong>规范化 → 查重 → 核验 → 分配</strong> 四步完成。呼号经核验通过后才会分配入口。</p>"
                "<form method=\"post\" action=\"apply\" class=\"p-apply\">"
                "<input name=\"callsign\" placeholder=\"呼号，例如 BG1SB\" required>"
                "<input name=\"contact\" placeholder=\"联系方式（可选）\">"
                "<input name=\"product\" placeholder=\"产品（留空=主产品）\">"
                "<button type=\"submit\">提交申请</button>"
                "</form>"
                "<p><small>为什么必须核验：呼号是<strong>公开标识</strong>，入口名就是呼号，"
                "因此实例存在性必然可枚举（I-H9 已接受）。防不了“被猜到”，就只能守住"
                "“核验通过才授予访问”。冒用可被举报并撤销（<code>/revoke</code>）。</small></p>"
                f"<h2>已授予</h2><table class=stack><tr><th>呼号</th><th>状态</th><th>标签</th><th>端口</th></tr>{rows}</table>"),
                       ctype="text/html; charset=utf-8")

        def do_POST(self):                       # noqa: N802
            route = self._route()
            try:
                body = self._body()
            except Exception as exc:             # noqa: BLE001
                return self._send(400, {"error": f"请求体无法解析: {exc}"})
            try:
                if route == "/admin/login":
                    user = str(body.get("user") or "").strip()
                    password = str(body.get("password") or "")
                    ip = self._client_ip()
                    remaining = login_guard.locked(user, ip)
                    if remaining:
                        portal.store.record_login("login_locked", user, ip)
                        return self._login_page("", status=429, retry_after=remaining)
                    ok, reason = (users.verify(user, password) if users
                                  else (False, "unreadable: 账号文件未配置"))
                    if reason.startswith("unreadable"):
                        # 部署问题不计入锁定：重试再多也修不好，锁管理员只会阻碍修复。
                        portal.store.record_login("login_failed", user, ip)
                        return self._login_page("账号文件不可读或未配置（部署问题，不是密码问题）。", status=503)
                    if not ok:
                        login_guard.fail(user, ip)
                        portal.store.record_login("login_failed", user, ip)
                        return self._login_page("用户名或密码不正确。", status=401)
                    login_guard.success(user, ip)
                    sid = session_store.create(user)
                    portal.store.record_login("login_ok", user, ip)
                    return self._send(303, "", ctype="text/plain; charset=utf-8",
                                      headers={"Location": self._console_url(),
                                               "Set-Cookie": self._cookie_header(
                                                   sid, session_store.absolute_seconds)})

                if route == "/admin/logout":
                    sid, s = self._session()
                    if not sid or not s or not self._csrf_ok(body, s):
                        return self._send(403, {"error": "登出需要会话与 CSRF 令牌"})
                    session_store.destroy(sid)
                    return self._send(303, "", ctype="text/plain; charset=utf-8",
                                      headers={"Location": self._console_url(),
                                               "Set-Cookie": self._cookie_header("", 0)})

                if route == "/apply":
                    return self._send(200, portal.apply(body.get("callsign", ""),
                                                        body.get("contact", ""), body.get("product", "")))
                if route == "/claim":
                    # 用运维给的一次性口令"认领"一条**已批准**的申请。
                    # 为什么需要它：应用只能看见它自己提交的那条申请（申请令牌是那时发的）。
                    # 但审批本来就是审批 —— 租户不该因为"申请是在网页上提的"而被迫重来。
                    # 口令本来就是交给租户的（它同时是 /enroll 的凭据），所以这里没有扩大攻击面：
                    # 有口令的人本来就能为这个名字登记证书。
                    callsign = cs.normalize(body.get("callsign", ""))
                    app = portal.store.get(callsign)
                    supplied = str(body.get("secret") or "")
                    if not app or app.status != "granted" or not app.enroll_secret \
                            or not hmac.compare_digest(supplied, app.enroll_secret):
                        return self._send(403, {"error": "登记口令无效或未获授权"})
                    return self._send(200, {
                        "callsign": app.callsign,
                        "status": app.status,
                        "label": app.label,
                        "port": int(app.port or 0),
                        "enroll_secret": app.enroll_secret,
                        "hub_token": _frps_token(),
                        "entry": (f"https://{app.label}.mrrc.vlsc.net/" if app.label else ""),
                        "request_token": app.request_token,
                    })

                if route == "/status":
                    # 申请方（应用）查询自己那条申请。用 POST 而不是 GET：令牌不进 URL/日志
                    # （与 AD-H11/AD-024 一致）。凭申请令牌只能读自己这一条，改不了任何东西。
                    callsign = cs.normalize(body.get("callsign", ""))
                    app = portal.store.get(callsign)
                    supplied = str(body.get("token") or "")
                    if not app or not app.request_token or \
                            not hmac.compare_digest(supplied, app.request_token):
                        return self._send(403, {"error": "申请令牌无效"})
                    reply = {
                        "callsign": app.callsign,
                        "status": app.status,
                        # 批准后才给出的接入信息；未批准时为空，不泄露半个字段
                        "label": app.label if app.status == "granted" else "",
                        "port": int(app.port or 0) if app.status == "granted" else 0,
                        "enroll_secret": app.enroll_secret if app.status == "granted" else "",
                        "entry": (f"https://{app.label}.mrrc.vlsc.net/"
                                  if app.status == "granted" and app.label else ""),
                        # 隧道登录用的 frps 令牌。租户拿不到运维密钥，所以批准后随接入信息一起给
                        # （与登记口令同一信任级别；共享令牌这个偏离本身记在 AD-H11 里）。
                        "hub_token": _frps_token() if app.status == "granted" else "",
                    }
                    return self._send(200, reply)

                if route == "/enroll":
                    # 实例提交自签证书的公钥。这条路**对公网开放**，所以凭据是一次性口令，
                    # 而且要校验证书名字就是它自己的入口名 —— 否则可以拿别人的证书来冒充。
                    callsign = cs.normalize(body.get("callsign", ""))
                    app = portal.store.get(callsign)
                    supplied = str(body.get("secret") or "")
                    if not app or app.status != "granted" or not app.enroll_secret \
                            or not hmac.compare_digest(supplied, app.enroll_secret):
                        return self._send(403, {"error": "登记口令无效或未获授权"})
                    pem = str(body.get("cert") or "").strip()
                    if "BEGIN CERTIFICATE" not in pem or "END CERTIFICATE" not in pem:
                        return self._send(400, {"error": "cert 必须是 PEM 文本"})
                    expected = f"{app.label}.mrrc.vlsc.net"
                    cert_dir = Path(DEFAULT_CERT_DIR)
                    cert_dir.mkdir(parents=True, exist_ok=True)
                    tmp = cert_dir / f".{app.label}.pem.tmp"
                    tmp.write_text(pem if pem.endswith("\n") else pem + "\n", encoding="utf-8")
                    names = cert_names(tmp)
                    if expected not in names:
                        tmp.unlink(missing_ok=True)
                        return self._send(400, {"error": f"证书名字不符：期望 {expected}，实得 {sorted(names) or '解析失败'}"})
                    tmp.replace(cert_dir / f"{app.label}.pem")
                    portal.store._load  # noqa: B018  (仅表明状态未变；审计见下)
                    return self._send(200, {
                        "callsign": callsign, "cert": str(cert_dir / f"{app.label}.pem"),
                        "names": sorted(names),
                        "next_step": "sudo /usr/local/sbin/gen_hub_routes.py && sudo nginx -t && sudo systemctl reload nginx",
                    })
                if route not in ("/verify", "/reject", "/grant", "/revoke"):
                    return self._send(404, {"error": "not found"})
                ok, actor = self._action_actor(body)
                if not ok:
                    return self._send(403, {"error": "运维动作需要会话+CSRF 令牌，或 X-Portal-Token 请求头"})
                who = cs.normalize(body.get("callsign", ""))
                def done(msg):
                    # 浏览器路径（会话+CSRF）重渲染管理台；机器路径（令牌头）只回 JSON。
                    if actor != "token":
                        return self._send(200, self._admin(str(body.get("view") or "overview"), msg),
                                          ctype="text/html; charset=utf-8")
                    return None
                if route == "/verify":
                    result = portal.store.mark_verified(who, body.get("evidence", "人工核验通过"), actor=actor)
                    rendered = done("已核验")
                    return rendered or self._send(200, result if isinstance(result, dict) else {"status": result.status})
                if route == "/reject":
                    result = portal.store.reject(who, body.get("reason", ""), actor=actor)
                    rendered = done("已拒绝")
                    return rendered or self._send(200, result if isinstance(result, dict) else {"status": result.status})
                if route == "/grant":
                    return self._send(200, portal.grant(who, actor=actor))
                result = portal.revoke(who, body.get("reason", ""), actor=actor)
                return done("已撤销") or self._send(200, result)
            except cs.InvalidCallsign as exc:
                return self._send(400, {"error": str(exc)})
            except KeyError as exc:
                return self._send(404, {"error": f"无此申请: {exc}"})
            except PermissionError as exc:            # noqa: BLE001
                # 权限问题不是"冲突"：写成 409 会让运维以为是自己提交的东西不对，
                # 而真相往往是 hub 上目录属主/权限没给服务账号（2026-10-01 实测误导了两轮排障）。
                self._send(500, {"error": "hub writes failed (check the directory owner): " + str(exc)})
            except (ValueError, RuntimeError) as exc:      # noqa: BLE001
                return self._send(409, {"error": str(exc)})

    return Handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MRRC Cloud Hub 呼号自助 Portal（UC-H10）")
    ap.add_argument("--host", default="127.0.0.1", help="默认仅本机；管理面不要直接暴露公网")
    ap.add_argument("--port", type=int, default=8890)
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--callsign-db", default=DEFAULT_CALLSIGN_DB)
    ap.add_argument("--clublog", default=DEFAULT_CLUBLOG,
                    help="Club Log 呼号库 JSON（与站内留言版同源；由 hub 定时从 www 拉取）")
    ap.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    ap.add_argument("--users-file", default=DEFAULT_USERS_FILE,
                    help="htpasswd 账号文件（$apr1$，一行一个 `用户名:哈希`）")
    ap.add_argument("--cookie-secure", choices=("auto", "on", "off"), default="auto",
                    help="会话 Cookie 的 Secure：auto=回环 Host 不带、其余带")
    ap.add_argument("--session-idle-hours", type=float, default=8)
    ap.add_argument("--session-max-hours", type=float, default=24)
    ap.add_argument("--frps-api-url", default=DEFAULT_FRPS_API,
                    help="frps 面板（webServer，只绑回环）的地址")
    ap.add_argument("--frps-credentials", default=DEFAULT_FRPS_CREDENTIALS,
                    help="面板凭据文件（user:password，0640 root:mrrcportal）")
    ap.add_argument("--metrics-interval", type=float, default=30.0,
                    help="隧道指标采样间隔秒；0 = 关闭采集器")
    ap.add_argument("--metrics-history", type=int, default=120,
                    help="每实例保留的样本数（默认 30s × 120 ≈ 1 小时）")
    ap.add_argument("--base-path", default=os.environ.get("MRRC_PORTAL_BASE", ""),
                    help="挂载前缀，如 /mrrc_portal（默认空 = 挂在根）")
    ap.add_argument("--dry-run", action="store_true", help="只加载配置并自检，不监听")
    args = ap.parse_args(argv)

    token = Path(args.token_file).read_text(encoding="utf-8").strip() if Path(args.token_file).exists() else ""
    users = hp.UsersFile(args.users_file)
    portal = Portal(Store(args.store), reg.Registry(args.registry),
                    build_verifier(args.callsign_db, args.clublog))
    if args.dry_run:
        parsed, users_err = users.read()
        print(f"store={args.store} registry={args.registry} callsign_db={args.callsign_db}")
        print(f"token={'已配置' if token else '未配置（运维动作会被拒绝）'}")
        print(f"账号文件={args.users_file}（"
              + (f"{len(parsed)} 个账号" if parsed is not None else f"不可读：{users_err}") + "）")
        print(f"frps 面板={args.frps_api_url} 凭据={args.frps_credentials}"
              f"{'（采集器关闭）' if args.metrics_interval <= 0 else f'（每 {args.metrics_interval:.0f}s 一轮）'}")
        print(f"注册表现有条目: {len(portal.registry.entries())} | 占用端口: {sorted(portal.registry.used_ports())[:5]}")
        return 0
    base = ("/" + args.base_path.strip("/")) if args.base_path.strip("/") else ""
    sampler = None
    if args.metrics_interval > 0:
        sampler = metrics_mod.Sampler(
            entries=lambda: portal.registry.entries(),
            probe=lambda port, label: _probe_timed(port, label),
            panel=metrics_mod.FrpsPanel(args.frps_api_url, args.frps_credentials),
            interval=args.metrics_interval, history=args.metrics_history)
        sampler.start()
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(
        portal, token, base, users=users,
        sessions=SessionStore(args.session_idle_hours * 3600, args.session_max_hours * 3600),
        guard=LoginGuard(), cookie_secure=args.cookie_secure, sampler=sampler))
    print(f"Portal 监听 http://{args.host}:{args.port}{base or '/'} （注册表 {args.registry}）", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
