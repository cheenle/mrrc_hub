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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from portal import callsign as cs          # noqa: E402
from portal import registry as reg          # noqa: E402
from portal.store import Store             # noqa: E402
from portal.store import VERIFIED as STORE_VERIFIED  # noqa: E402
from portal.verify import (CallsignListVerifier, ChainVerifier, ClubLogVerifier,  # noqa: E402
                           ManualVerifier, VerificationOutcome)

DEFAULT_STORE = os.environ.get("MRRC_PORTAL_STORE", "/etc/mrrc-hub/portal.json")
DEFAULT_REGISTRY = os.environ.get("MRRC_PORTAL_REGISTRY", "/etc/mrrc-hub/instances.tsv")
DEFAULT_CALLSIGN_DB = os.environ.get("MRRC_PORTAL_CALLSIGN_DB", "/etc/mrrc-hub/callsigns.txt")
DEFAULT_TOKEN_FILE = os.environ.get("MRRC_PORTAL_TOKEN_FILE", "/etc/mrrc-hub/portal.token")

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
--tx:#fff;--tx2:#8899aa;--txm:#5c6370;--bd:rgba(255,255,255,.08);}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx2);
font:15px/1.7 'Inter',-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;}
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
td,th{border-bottom:1px solid var(--bd);padding:.55rem .8rem;text-align:left;font-size:.875rem;color:var(--tx2);}
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
@media(max-width:720px){.p-apply{grid-template-columns:1fr}}
"""


def _page(title: str, body: str, noindex: bool = False) -> str:
    robots = "<meta name=robots content=noindex>\n" if noindex else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#000000">
{robots}<title>{title}</title>
<style>{_PORTAL_CSS}</style>
</head>
<body data-site="hub">
<header class="p-head">
  <a class="p-brand" href="https://www.vlsc.net/mrrc_hub/">📡 MRRC <em>Cloud Hub</em></a>
  <span class="p-crumb">{html.escape(title)}</span>
</header>
<main class="p-main">
{body}
</main>
<footer class="p-foot">呼号即身份 · 核验通过才授予访问 ·
<a href="https://www.vlsc.net/mrrc_hub/">文档站</a></footer>
<script src="https://www.vlsc.net/js/global-nav.js?v=8" defer></script>
</body>
</html>"""


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

    def grant(self, raw_callsign: str) -> dict:
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
            granted = self.store.grant(normalized, label, port)
        except Exception:
            if label not in known:                        # 失败即回滚，只回滚这次新增的
                self.registry.remove(label)
            raise
        return {"callsign": normalized, "label": label, "port": port,
                # 给租户看的下一步。**不要**再写老式的脚本命令：v1.24.0 起接入在应用
                # 设置菜单里完成（申请→批准→应用自动签证书/登记/起隧道），租户没有任何命令要跑。
                # 只有旧版应用才需要那份脚本，所以按 product 分叉。
                "next_step": (
                    "在应用里：设置 → 接入云端（Cloud Hub）→ 点「刷新状态」即自动完成；无需命令"
                    if (app.product or "").strip() in ("mrrc_modern", "")
                    else f"在实例上运行 mrrc_hub/deploy/install_instance_tunnel.sh {label} {port}"
                ),
                "status": granted.status}

    def revoke(self, raw_callsign: str, reason: str) -> dict:
        normalized = cs.normalize(raw_callsign)
        app = self.store.get(normalized)
        if not app:
            raise KeyError(normalized)
        removed = self.registry.remove(app.label) if app.label else False
        self.store.revoke(normalized, reason)
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


def _tunnel_online(port) -> bool:
    """隧道是否在线：hub 回环上该端口可连接 ⇒ frpc 已建立。

    总览与实例页都要问同一个问题，所以只在这里探一次 —— 两个视图里各写一个同名 `probe`
    会互相遮蔽（同一个函数作用域），后人改动时很容易改错那一个。
    """
    import socket
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.5):
            return True
    except OSError:
        return False


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


def make_handler(portal: Portal, token: str, base: str = ""):
    """base 是挂载前缀（如 `/mrrc_portal`），空串表示挂在根。

    两边都容忍：入口收到 `{base}/apply` 或 `/apply` 都能处理（边缘可以保留前缀，
    也可以剥掉前缀）。页面里的链接用**相对形式**（`action="apply"`），因此同一份代码
    挂在根（`https://portal.../`）与挂在前缀（`https://www.vlsc.net/mrrc_portal/`）
    下都指向正确位置 —— 不必为每个挂载点各配一份 base。
    """
    base = ("/" + base.strip("/")) if base and base.strip("/") else ""
    class Handler(BaseHTTPRequestHandler):
        server_version = "MRRC-Portal/1.0"

        def log_message(self, format, *args):    # noqa: A002 - 基类就是这么命名的
            # 不记录 query（可能含呼号/联系方式）
            sys.stderr.write("portal: " + format % args + "\n")

        def _route(self) -> str:
            """去掉挂载前缀后的路径；带前缀与不带前缀两种形式都接受。"""
            path = self.path.split("?")[0]
            if base and (path == base or path.startswith(base + "/")):
                path = path[len(base):] or "/"
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

        def _send(self, code: int, payload: dict | str, ctype="application/json; charset=utf-8"):
            body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _operator_ok(self, body: dict | None = None) -> bool:
            """令牌可来自请求头（curl/脚本）或表单字段（浏览器）。

            表单字段是刻意加的：运维在浏览器里点按钮时无法自定义请求头。
            令牌走 **请求体** 而不是 URL —— URL 会进访问日志与浏览器历史。
            """
            if not token:
                return False
            supplied = (self.headers.get("X-Portal-Token") or "").strip()
            if not supplied and body:
                supplied = str(body.get("token") or "").strip()
            return hmac.compare_digest(supplied, token)

        # ---- operator console ----
        def _admin(self, view: str, token_value: str, msg: str = "") -> str:
            """后台管理台：五个视图，全部服务端渲染。

            安全姿态（延续全过程的不变量）：
              * **不用 cookie、不做重定向** —— 导航与动作都靠表单里的隐藏令牌字段。
                没有会话可被借用，CSRF 因此没有着力点。
              * 令牌只出现在响应体里，不进 URL、不进 Location、不进访问日志。
              * **需要 root 的操作不由本服务执行**：Web 服务解析外网输入，给它
                nginx reload / 拉库的权限是自找麻烦。这里只把命令打出来让运维执行。
            """
            token_attr = html.escape(token_value)
            def nav(label, target):
                state = " style='font-weight:700'" if target == view else ""
                return (f"<form method=post style='display:inline'>"
                        f"<input type=hidden name=token value='{token_attr}'>"
                        f"<input type=hidden name=view value='{target}'>"
                        f"<button{state}>{html.escape(label)}</button></form>")
            def act(route, callsign, label, extra=""):
                return (f"<form method=post action={route} style='display:inline'>"
                        f"<input type=hidden name=callsign value='{html.escape(callsign)}'>"
                        f"<input type=hidden name=token value='{token_attr}'>"
                        f"<input type=hidden name=view value='{view}'>{extra}"
                        f"<button>{html.escape(label)}</button></form>")

            apps = portal.store._load()["applications"]
            registry = portal.registry
            entries = registry.entries()
            body = ""

            if view == "overview":
                by = {}
                for a in apps.values():
                    by[a["status"]] = by.get(a["status"], 0) + 1
                cert = _cert_days()
                cl = _clublog_info()
                online = sum(1 for _, p in entries if _tunnel_online(p))
                body = f"""<h2>总览</h2>
<table><tr><th>项</th><th>值</th></tr>
<tr><td>申请</td><td>{'　'.join(f"{k}={v}" for k, v in sorted(by.items())) or '（无）'}</td></tr>
<tr><td>注册表实例</td><td>{len(entries)} 个，其中隧道在线 <b>{online}</b> 个</td></tr>
<tr><td>入口证书剩余</td><td>{cert}</td></tr>
<tr><td>Club Log 呼号库</td><td>{cl}</td></tr>
<tr><td>端口池</td><td>{registry.first}-{registry.last}，已用 {len(entries)}，空闲 {registry.last - registry.first + 1 - len(entries)}</td></tr>
</table>
<p><small>需要 root 的动作不在此执行，请照抄命令：<br>
<code>sudo /usr/local/sbin/gen_hub_routes.py &amp;&amp; sudo systemctl reload nginx</code>（新增/撤销实例后）<br>
<code>sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh</code>（立即刷新呼号库）</small></p>"""

            elif view == "applications":
                def rows(statuses, actions):
                    out = []
                    for c, a in sorted(apps.items()):
                        if a["status"] not in statuses:
                            continue
                        out.append(f"<tr><td><code>{html.escape(c)}</code></td><td>{html.escape(a['status'])}</td>"
                                   f"<td>{html.escape(a.get('product') or '主产品')}</td>"
                                   f"<td>{html.escape(a.get('label') or '—')}</td><td>{a.get('port') or '—'}</td>"
                                   f"<td>{html.escape((a.get('evidence') or '')[:70])}"
                                   + (f"<br><small>登记口令: <code>{html.escape(a['enroll_secret'])}</code></small>"
                                      if a.get('enroll_secret') and a['status'] == 'granted' else '')
                                   + f"</td><td>{actions(c)}</td></tr>")
                    return ''.join(out) or "<tr><td colspan=7>（无）</td></tr>"
                body = "<h2>申请（全部状态）</h2><table><tr><th>呼号</th><th>状态</th><th>产品</th><th>标签</th><th>端口</th><th>依据</th><th>动作</th></tr>" \
                    + rows({"applied"}, lambda c: act("/verify", c, "核验通过", "<input type=hidden name=evidence value='人工核验通过'>") + act("/reject", c, "拒绝", "<input type=hidden name=reason value='材料不足'>")) \
                    + rows({"verified"}, lambda c: act("/grant", c, "分配入口") + act("/reject", c, "拒绝", "<input type=hidden name=reason value='核验后驳回'>")) \
                    + rows({"granted"}, lambda c: act("/revoke", c, "撤销", "<input type=hidden name=reason value='撤销'>")) \
                    + rows({"rejected", "revoked"}, lambda c: "") + "</table>"

            elif view == "instances":
                def tunnel_cell(port):                 # 同一探测的 HTML 版本（实例页）
                    return ("<b style='color:#34d399'>在线</b>" if _tunnel_online(port)
                            else "<span style='color:#f87171'>未连接</span>")
                rows_ = ''.join(
                    f"<tr><td><code>{html.escape(l)}</code></td><td>{p}</td><td>{tunnel_cell(p)}</td>"
                    f"<td><a href='https://{html.escape(l)}.mrrc.vlsc.net:8899/' target=_blank>打开入口</a></td></tr>"
                    for l, p in sorted(entries)) or "<tr><td colspan=4>（注册表为空）</td></tr>"
                body = ("<h2>实例</h2><table><tr><th>标签</th><th>端口</th><th>隧道</th><th>入口</th></tr>"
                        + rows_ + "</table><p><small>「在线」= hub 回环上该端口可连接 ⇒ frpc 隧道已建立。<br>"
                        "新增后仍需：<code>sudo /usr/local/sbin/gen_hub_routes.py &amp;&amp; sudo systemctl reload nginx</code></small></p>")

            elif view == "audit":
                entries_a = list(reversed(portal.store.audit()))[:60]
                rows_ = ''.join(
                    f"<tr><td>{time.strftime('%m-%d %H:%M', time.localtime(e['at']))}</td>"
                    f"<td><code>{html.escape(e['callsign'])}</code></td><td>{html.escape(e['event'])}</td>"
                    f"<td>{html.escape((e.get('detail') or '')[:90])}</td></tr>" for e in entries_a)
                body = ("<h2>审计（最近 60 条，追加式）</h2><table><tr><th>时间</th><th>呼号</th><th>事件</th><th>细节</th></tr>"
                        + (rows_ or "<tr><td colspan=4>（无）</td></tr>") + "</table>")

            else:  # clublog
                cl = _clublog_info()
                body = (f"<h2>呼号库</h2><table><tr><th>项</th><th>值</th></tr>"
                        f"<tr><td>来源</td><td>Club Log（与站内留言版 www.vlsc.net/feedback 同源）</td></tr>"
                        f"<tr><td>状态</td><td>{cl}</td></tr>"
                        f"<tr><td>路径</td><td><code>{html.escape(str(DEFAULT_CLUBLOG))}</code></td></tr></table>"
                        f"<p><small>hub 每天 04:30 从 www 拉取（受限命令：只能读那一个文件）。<br>"
                        f"立即刷新：<code>sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh</code></small></p>")

            return _page("MRRC Portal — 后台管理",
                         "<h1>呼号自助 — 后台管理</h1>"
                         + (f'<p class=msg>{html.escape(msg)}</p>' if msg else '')
                         + f"<p>{nav('总览','overview')}{nav('申请','applications')}{nav('实例','instances')}{nav('审计','audit')}{nav('呼号库','clublog')}</p>"
                         + body, noindex=True)

        # ---- routes ----        # ---- routes ----
        def do_GET(self):                        # noqa: N802
            if self._route() == "/admin":
                return self._send(200, _page(
                    "MRRC Portal — 运维登录",
                    "<h1>运维审批</h1>"
                    "<form method=post action=admin>"
                    "<input type=password name=token placeholder=\"运维令牌（sudo cat /etc/mrrc-hub/portal.token）\" autofocus>"
                    "<button>进入</button>"
                    "</form>"
                    "<p><small>令牌只随表单提交，不进 URL ✓ 本页与审批页均 <code>noindex</code> ✓</small></p>",
                    noindex=True), ctype="text/html; charset=utf-8")
            if self._route() != "/":
                return self._send(404, {"error": "not found"})
            rows = "".join(
                f"<tr><td>{html.escape(a['callsign'])}</td><td>{html.escape(a['status'])}</td>"
                f"<td>{html.escape(a['label'] or '—')}</td><td>{a['port'] or '—'}</td></tr>"
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
                f"<h2>已授予</h2><table><tr><th>呼号</th><th>状态</th><th>标签</th><th>端口</th></tr>{rows}</table>"),
                       ctype="text/html; charset=utf-8")

        def do_POST(self):                       # noqa: N802
            route = self._route()
            try:
                body = self._body()
            except Exception as exc:             # noqa: BLE001
                return self._send(400, {"error": f"请求体无法解析: {exc}"})
            try:
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
                if route == "/admin":
                    if not self._operator_ok(body):
                        return self._send(403, {"error": "令牌不正确"})
                    return self._send(200, self._admin(body.get("view") or "overview", body.get("token", "").strip()),
                                      ctype="text/html; charset=utf-8")
                if route not in ("/verify", "/reject", "/grant", "/revoke"):
                    return self._send(404, {"error": "not found"})
                if not self._operator_ok(body):
                    return self._send(403, {"error": "运维动作需要 X-Portal-Token"})
                who = cs.normalize(body.get("callsign", ""))
                from_page = bool(body.get("token"))
                def done(msg):
                    if from_page:
                        return self._send(200, self._admin(body.get("view") or "overview", body.get("token", "").strip(), msg),
                                          ctype="text/html; charset=utf-8")
                    return None
                if route == "/verify":
                    result = portal.store.mark_verified(who, body.get("evidence", "人工核验通过"))
                    rendered = done("已核验")
                    return rendered or self._send(200, result if isinstance(result, dict) else {"status": result.status})
                if route == "/reject":
                    result = portal.store.reject(who, body.get("reason", ""))
                    rendered = done("已拒绝")
                    return rendered or self._send(200, result if isinstance(result, dict) else {"status": result.status})
                if route == "/grant":
                    return self._send(200, portal.grant(who))
                result = portal.revoke(who, body.get("reason", ""))
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
    ap.add_argument("--base-path", default=os.environ.get("MRRC_PORTAL_BASE", ""),
                    help="挂载前缀，如 /mrrc_portal（默认空 = 挂在根）")
    ap.add_argument("--dry-run", action="store_true", help="只加载配置并自检，不监听")
    args = ap.parse_args(argv)

    token = Path(args.token_file).read_text(encoding="utf-8").strip() if Path(args.token_file).exists() else ""
    portal = Portal(Store(args.store), reg.Registry(args.registry),
                    build_verifier(args.callsign_db, args.clublog))
    if args.dry_run:
        print(f"store={args.store} registry={args.registry} callsign_db={args.callsign_db}")
        print(f"token={'已配置' if token else '未配置（运维动作会被拒绝）'}")
        print(f"注册表现有条目: {len(portal.registry.entries())} | 占用端口: {sorted(portal.registry.used_ports())[:5]}")
        return 0
    base = ("/" + args.base_path.strip("/")) if args.base_path.strip("/") else ""
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(portal, token, base))
    print(f"Portal 监听 http://{args.host}:{args.port}{base or '/'} （注册表 {args.registry}）", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
