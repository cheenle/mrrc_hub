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
import sys
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
DEFAULT_CLUBLOG = os.environ.get("MRRC_PORTAL_CLUBLOG", "/var/lib/mrrc-hub/portal/clublog_users.json")


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
                "label": cs.label_for(normalized, product)}

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
        label = cs.label_for(normalized, app.product)     # ④ 分配
        port = self.registry.free_port()
        self.registry.add(label, port)
        try:
            granted = self.store.grant(normalized, label, port)
        except Exception:
            self.registry.remove(label)                   # 失败即回滚，不留孤儿条目
            raise
        return {"callsign": normalized, "label": label, "port": port,
                "next_step": f"sudo bash deploy/install_instance_tunnel.sh {label} {port}",
                "status": granted.status}

    def revoke(self, raw_callsign: str, reason: str) -> dict:
        normalized = cs.normalize(raw_callsign)
        app = self.store.get(normalized)
        if not app:
            raise KeyError(normalized)
        removed = self.registry.remove(app.label) if app.label else False
        self.store.revoke(normalized, reason)
        return {"callsign": normalized, "label": app.label, "entry_removed": removed, "status": "revoked"}


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

        def log_message(self, fmt, *args):       # 不记录 query（可能含呼号/联系方式）
            sys.stderr.write("portal: " + fmt % args + "\n")

        def _route(self) -> str:
            """去掉挂载前缀后的路径；带前缀与不带前缀两种形式都接受。"""
            path = self.path.split("?")[0]
            if base and (path == base or path.startswith(base + "/")):
                path = path[len(base):] or "/"
            return path

        # ---- helpers ----
        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            if (self.headers.get("Content-Type") or "").startswith("application/json"):
                return json.loads(raw or "{}")
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

        # ---- operator UI ----
        def _forms(self, token_value: str, msg: str = "") -> str:
            """运维页：待核验/待分配/已授予 三个清单 + 每行动作按钮。

            安全姿态（有意为之）：
              * **不用 cookie、不做重定向** —— 每个动作表单都带隐藏的 token 字段。
                于是不存在会话可被 CSRF 借用的问题：伪造的请求拿不到令牌。
              * 令牌只出现在**响应体**里，不进 URL、不进 Location 头、不进日志。
            """
            store, registry = portal.store, portal.registry
            data = store._load()["applications"]

            def row(callsign, app, actions):
                return (f"<tr><td><code>{html.escape(callsign)}</code></td>"
                        f"<td>{html.escape(app['status'])}</td>"
                        f"<td>{html.escape(app.get('product') or '主产品')}</td>"
                        f"<td>{html.escape(app.get('contact') or '—')}</td>"
                        f"<td>{html.escape(app.get('evidence') or '')[:60]}</td>"
                        f"<td>{actions}</td></tr>")

            def btn(route, callsign, label, extra=""):
                return (f"<form method=post action={route} style='display:inline'>"
                        f"<input type=hidden name=callsign value='{html.escape(callsign)}'>"
                        f"<input type=hidden name=token value='{html.escape(token_value)}'>"
                        f"{extra}<button>{html.escape(label)}</button></form>")

            pending = [row(c, a, btn("/verify", c, "核验通过", "<input type=hidden name=evidence value='人工核验通过'>")
                          + btn("/reject", c, "拒绝", "<input type=hidden name=reason value='材料不足'>"))
                       for c, a in sorted(data.items()) if a["status"] == "applied"]
            verified = [row(c, a, btn("/grant", c, "分配入口") + btn("/reject", c, "拒绝", "<input type=hidden name=reason value='核验后驳回'>"))
                        for c, a in sorted(data.items()) if a["status"] == "verified"]
            granted = [row(c, a, btn("/revoke", c, "撤销", "<input type=hidden name=reason value='撤销'>"))
                       for c, a in sorted(data.items()) if a["status"] == "granted"]
            empty = "<tr><td colspan=6>（无）</td></tr>"
            return f"""<!doctype html><meta charset="utf-8"><meta name=robots content=noindex>
<title>MRRC Portal — 运维</title>
<style>body{{font:15px/1.6 -apple-system,sans-serif;max-width:1100px;margin:32px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left;font-size:14px}}
button{{font:inherit;padding:4px 10px;margin-right:4px}}code{{background:#f4f4f4;padding:1px 4px}}
.msg{{background:#e8f5e9;border:1px solid #a5d6a7;padding:8px 12px}}h2{{margin-top:28px}}</style>
<h1>呼号自助 — 运维审批</h1>
{f'<p class=msg>{html.escape(msg)}</p>' if msg else ''}
<p><small>令牌只在本页表单里提交（不进 URL）✓ 核验依据：Club Log 呼号库 ✓ 未命中 ⇒ 人工判断 ✓
　·　注册表：{html.escape(str(registry.path))}（分配后仍需 root 执行 <code>gen_hub_routes.py</code> + <code>nginx reload</code>）</small></p>
<h2>待核验（{len(pending)}）</h2><table><tr><th>呼号</th><th>状态</th><th>产品</th><th>联系</th><th>依据</th><th>动作</th></tr>{''.join(pending) or empty}</table>
<h2>已核验待分配（{len(verified)}）</h2><table><tr><th>呼号</th><th>状态</th><th>产品</th><th>联系</th><th>依据</th><th>动作</th></tr>{''.join(verified) or empty}</table>
<h2>已授予（{len(granted)}）</h2><table><tr><th>呼号</th><th>状态</th><th>标签</th><th>端口</th><th>—</th><th>动作</th></tr>
{''.join(granted) or empty}</table>"""

        # ---- routes ----
        def do_GET(self):                        # noqa: N802
            if self._route() == "/admin":
                return self._send(200, f"""<!doctype html><meta charset="utf-8"><meta name=robots content=noindex>
<title>MRRC Portal — 运维登录</title>
<style>body{{font:15px/1.6 -apple-system,sans-serif;max-width:520px;margin:60px auto;padding:0 16px}}
input,button{{font:inherit;padding:8px;width:100%;box-sizing:border-box}}button{{margin-top:10px}}
code{{background:#f4f4f4;padding:1px 4px}}</style>
<h1>运维审批</h1>
<form method=post action=admin>
  <input type=password name=token placeholder="运维令牌（sudo cat /etc/mrrc-hub/portal.token）" autofocus>
  <button>进入</button>
</form>
<p><small>令牌只随表单提交，不进 URL ✓ 本页与审批页均 <code>noindex</code> ✓</small></p>""",
                               ctype="text/html; charset=utf-8")
            if self._route() != "/":
                return self._send(404, {"error": "not found"})
            rows = "".join(
                f"<tr><td>{html.escape(a['callsign'])}</td><td>{html.escape(a['status'])}</td>"
                f"<td>{html.escape(a['label'] or '—')}</td><td>{a['port'] or '—'}</td></tr>"
                for a in portal.store.bindings().values()
            ) or "<tr><td colspan=4>（暂无已授予实例）</td></tr>"
            self._send(200, f"""<!doctype html><meta charset="utf-8">
<title>MRRC Cloud Hub — 呼号自助注册</title>
<style>body{{font:15px/1.6 -apple-system,sans-serif;max-width:760px;margin:40px auto;padding:0 16px}}
input,button{{font:inherit;padding:8px}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left}}
code{{background:#f4f4f4;padding:1px 4px}}</style>
<h1>呼号自助注册</h1>
<p>按 <strong>规范化 → 查重 → 核验 → 分配</strong> 四步完成。呼号经核验通过后才会分配入口。</p>
<form method="post" action="apply">
  <p><input name="callsign" placeholder="呼号，例如 BG1SB" required>
     <input name="contact" placeholder="联系方式（可选）">
     <input name="product" placeholder="产品（留空=主产品）"></p>
  <button type="submit">提交申请</button>
</form>
<p><small>为什么必须核验：呼号是<strong>公开标识</strong>，入口名就是呼号，
因此实例存在性必然可枚举（I-H9 已接受）。防不了"被猜到"，就只能守住
"核验通过才授予访问"。冒用可被举报并撤销（<code>/revoke</code>）。</small></p>
<h2>已授予</h2><table><tr><th>呼号</th><th>状态</th><th>标签</th><th>端口</th></tr>{rows}</table>""",
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
                if route == "/admin":
                    if not self._operator_ok(body):
                        return self._send(403, {"error": "令牌不正确"})
                    return self._send(200, self._forms(body.get("token", "").strip()),
                                      ctype="text/html; charset=utf-8")
                if route not in ("/verify", "/reject", "/grant", "/revoke"):
                    return self._send(404, {"error": "not found"})
                if not self._operator_ok(body):
                    return self._send(403, {"error": "运维动作需要 X-Portal-Token"})
                who = cs.normalize(body.get("callsign", ""))
                from_page = bool(body.get("token"))
                def done(msg):
                    if from_page:
                        return self._send(200, self._forms(body.get("token", "").strip(), msg),
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
            except (ValueError, PermissionError, RuntimeError) as exc:
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
