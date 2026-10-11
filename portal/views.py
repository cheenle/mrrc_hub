"""后台视图：只消费 Ctx 产出 HTML。

**这一层是纯呈现。** 判据（`tests/test_portal_ui.py::test_views_layer_is_pure` 会检查）：
本模块不得出现 `subprocess`、`socket`、`open(` —— 所有事实由 `app.py` 采集。
这样视图可以拿假数据直接测，不必起服务、不必开端口、不必等超时。

模块里唯一允许的"计算"是纯函数：时间差文案、字节/速率格式化、天数换算。
"""
from __future__ import annotations

import html
import time
from dataclasses import dataclass, field

from portal import ui
from portal.ui import trow


@dataclass
class Ctx:
    """一次渲染需要**全部**事实。全部是纯数据，没有行为。"""
    root: str = ""
    csrf: str = ""
    user: str = ""
    msg: str = ""
    view: str = "overview"
    # 申请与审计
    apps: dict = field(default_factory=dict)
    audit: list = field(default_factory=list)
    # 注册表与探测
    entries: list = field(default_factory=list)        # [(label, port)]
    entries_full: list = field(default_factory=list)   # [(label, port, tlsname)]
    states: dict = field(default_factory=dict)         # {port: (state, detail)}
    reports: dict = field(default_factory=dict)        # {label: report}
    # 系统
    resources: dict = field(default_factory=dict)
    services: list = field(default_factory=list)
    net: dict = field(default_factory=dict)
    certs: list = field(default_factory=list)
    # 其它
    cert_days: str = "—"
    clublog: str = ""
    clublog_path: str = ""
    registry_first: int = 0
    registry_last: int = 0
    sampler: dict | None = None
    tunnel_text: dict = field(default_factory=dict)
    tunnel_pill: dict = field(default_factory=dict)
    now: float = 0.0
    # 筛选与定位
    flt: str = ""
    flt_label: str = ""     # 实例详情页要看的那个标签
    q: str = ""
    page: int = 1


@dataclass(frozen=True)
class Rendered:
    title: str
    chrome: str      # 标题、工具条、按钮等"不需要自动刷新"的部分
    live: str        # 会自动刷新的数据区；空串表示本视图不自动刷新


#: 每个视图的自动刷新间隔（秒）。0 = 不刷新。
REFRESH_SECONDS = {"overview": 30, "instances": 20, "tunnel": 30, "system": 60}


VIEWS: dict = {}


def register(view_id: str, title: str):
    def deco(fn):
        VIEWS[view_id] = (title, fn)
        return fn
    return deco


def live_region(view: str, ctx: Ctx, inner: str) -> str:
    """把数据区包成可被 htmx 替换的节点。

    带 `data-live` 供 admin.js 定位；`hx-trigger` 的条件引用 admin.js 的全局闸门。
    关掉 JS 时这些属性无人理会，页面照常显示 —— 只是不会自动刷新。
    """
    every = REFRESH_SECONDS.get(view, 0)
    if not every:
        return inner
    return (f'<div data-live hx-get="{ctx.root}/admin?view={ui.esc(view)}&amp;part=live" '
            f'hx-trigger="every {every}s, refresh [!window.__portalPaused()]" '
            f'hx-swap="outerHTML">{inner}</div>')


def render(view_id: str, ctx: Ctx, part: str | None = None, **kw) -> Rendered:
    """渲染一个视图。part='live' 时只回数据区（自动刷新用）。

    `**kw` 透传给视图函数 —— 实例详情页需要 `label=`。
    """
    title, fn = VIEWS.get(view_id) or VIEWS["overview"]
    ctx.view = view_id
    rendered = fn(ctx, **kw)
    if part == "live":
        return Rendered(rendered.title, chrome="", live=rendered.live)
    return rendered


def badges(ctx: Ctx) -> dict:
    """侧栏与底栏的待办徽标。只在 >0 时显示（ui._badge_html 负责）。"""
    applied = sum(1 for a in ctx.apps.values() if a["status"] in ("applied", "verified"))
    return {"applications": applied}


# ── 纯格式化 ───────────────────────────────────────────────────────────
# 这四个函数是从 app.py **逐字搬来**的（它们不读任何外部状态）。
# 搬移阶段的硬要求是输出逐字节等价，所以这里连小数位数与单位都不改：
#   * _fmt_bps：1000 进制，bps / kbps / Mbps
#   * _fmt_bytes：1024 进制，B / KiB / MiB / GiB
#   * _ago：`5s 前` 这种紧凑写法
#   * _days_left：解析 openssl 的 `notAfter=Sep 30 01:11:09 2036 GMT`（**与**裸日期）
# 后果：`2.0 kbps` 看起来不如 `2.0 kbps`……但改文案是后续任务的事，
# 不能在“纯搬移”里顺手改，否则就没法用 diff 证明搬移无损了。

def _fmt_bps(value) -> str:
    if value is None:
        return "—"
    if value < 1000:
        return f"{value:.0f} bps"
    if value < 1_000_000:
        return f"{value / 1000:.1f} kbps"
    return f"{value / 1_000_000:.2f} Mbps"


def _fmt_bytes(value) -> str:
    if value is None:
        return "—"
    if value < 1024:
        return f"{value} B"
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KiB"
    if value < 1024 ** 3:
        return f"{value / 1024 ** 2:.1f} MiB"
    return f"{value / 1024 ** 3:.2f} GiB"


def _ago(seconds) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{seconds:.0f}s 前"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m 前"
    return f"{seconds / 3600:.1f}h 前"


def _days_left(not_after: str):
    """openssl 的 `notAfter=Sep 30 01:11:09 2036 GMT` → 剩余天数（解析不了就 None）。

    权威实现只有这一份：`app.py` 从本模块 re-export 它（`_hub_cert_inventory` 与
    `tests/test_portal.py` 都用它）。
    """
    if not not_after or not_after == "—":
        return None
    try:
        import calendar
        stamp = not_after.split("=", 1)[-1].strip()
        # openssl 给的是 GMT，所以用 timegm 而不是 mktime —— 后者按本地时区解释，
        # 会带进最多 ±14 小时的偏差。
        end = calendar.timegm(time.strptime(" ".join(stamp.split()[:4]), "%b %d %H:%M:%S %Y"))
        return int((end - time.time()) // 86400)
    except (ValueError, IndexError):
        return None


# ── 视图 ────────────────────────────────────────────────────────────────

def _nav(ctx: Ctx, label: str, target: str) -> str:
    cur = " aria-current=page" if target == ctx.view else ""
    return (f"<a class=navlink href='{ctx.root}/admin?view={target}'{cur}>"
            f"{html.escape(label)}</a>")


def _act(ctx: Ctx, route: str, callsign: str, label: str, extra: str = "") -> str:
    return (f"<form method=post action='{ctx.root}{route}' style='display:inline'>"
            f"<input type=hidden name=callsign value='{html.escape(callsign)}'>"
            f"<input type=hidden name=csrf value='{html.escape(ctx.csrf)}'>"
            f"<input type=hidden name=view value='{html.escape(ctx.view)}'>{extra}"
            f"<button>{html.escape(label)}</button></form>")


def _wrap(ctx: Ctx, body: str) -> str:
    """导航 + 登录者 + 视图正文。搬移阶段这里是逐字节照抄的旧标记。"""
    return ("<h1>呼号自助 — 后台管理</h1>"
            + (f'<p class=msg>{html.escape(ctx.msg)}</p>' if ctx.msg else '')
            + "<nav class=nav>"
            + _nav(ctx, '总览', 'overview') + _nav(ctx, '申请', 'applications')
            + _nav(ctx, '实例', 'instances') + _nav(ctx, '隧道', 'tunnel')
            + _nav(ctx, '系统', 'system') + _nav(ctx, '审计', 'audit')
            + _nav(ctx, '呼号库', 'clublog')
            + "</nav>"
            + (f"<div class=who><form method=post action='{ctx.root}/admin/logout' "
               f"style='display:inline'>"
               f"<input type=hidden name=csrf value='{html.escape(ctx.csrf)}'>"
               f"<button>登出（{html.escape(ctx.user)}）</button></form></div>" if ctx.user else "")
            + body)


@register("overview", "MRRC Portal — 后台管理")
def view_overview(ctx: Ctx) -> Rendered:
    by: dict[str, int] = {}
    for a in ctx.apps.values():
        by[a["status"]] = by.get(a["status"], 0) + 1
    online = sum(1 for s, _ in ctx.states.values() if s == "serving")
    # 不能只给个数字：“3 个在线”与“3 个在线但其中 1 个其实用不了”是两回事，
    # 而后者正是支持回路里最耗时的那种误判。
    not_serving = [(l, p) + ctx.states[p] for l, p in ctx.entries
                   if ctx.states.get(p, ("", ""))[0] != "serving"]
    bad = "".join(
        f"<br><small><span class='pill {ctx.tunnel_pill[s]}'>{html.escape(ctx.tunnel_text[s])}</span> "
        f"<code>{html.escape(l)}</code>:{p} — {html.escape(d)}</small>"
        for l, p, s, d in not_serving)
    tunnel_summary = ""
    if ctx.sampler is not None:
        snap = ctx.sampler
        lats = [i["last"].latency_ms for i in snap["labels"].values()
                if i["last"].latency_ms is not None]
        outs = [i["last"].out_bps for i in snap["labels"].values()
                if i["last"].out_bps is not None]
        if lats and outs:
            tunnel_summary = (f"<br><small>延时均值 {sum(lats) / len(lats):.0f} ms；"
                              f"出带宽 {_fmt_bps(sum(outs))}（<a href='?view=tunnel'>隧道视图</a>）</small>")
        elif snap["panel_error"]:
            tunnel_summary = f"<br><small>{html.escape(snap['panel_error'])}</small>"
    body = f"""<h2>总览</h2>
<table class=kv><tr><th>项</th><th>值</th></tr>
<tr><td>申请</td><td>{'　'.join(f"{k}={v}" for k, v in sorted(by.items())) or '（无）'}</td></tr>
<tr><td>注册表实例</td><td>{len(ctx.entries)} 个，其中<b>真正在服务</b> {online} 个{bad}{tunnel_summary}</td></tr>
<tr><td>入口证书剩余</td><td>{ctx.cert_days}</td></tr>
<tr><td>Club Log 呼号库</td><td>{ctx.clublog}</td></tr>
<tr><td>端口池</td><td>{ctx.registry_first}-{ctx.registry_last}，已用 {len(ctx.entries)}，空闲 {ctx.registry_last - ctx.registry_first + 1 - len(ctx.entries)}</td></tr>
</table>
<p><small>需要 root 的动作不在此执行，请照抄命令：<br>
<code>sudo /usr/local/sbin/gen_hub_routes.py &amp;&amp; sudo systemctl reload nginx</code>（新增/撤销实例后）<br>
<code>sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh</code>（立即刷新呼号库）</small></p>"""
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")


@register("applications", "MRRC Portal — 后台管理")
def view_applications(ctx: Ctx) -> Rendered:
    def rows(statuses, actions):
        out = []
        for c, a in sorted(ctx.apps.items()):
            if a["status"] not in statuses:
                continue
            out.append(trow(
                ("呼号", f"<code>{html.escape(c)}</code>"),
                ("状态", f"<span class='pill mute'>{html.escape(a['status'])}</span>"),
                ("产品", html.escape(a.get('product') or '主产品')),
                ("标签", html.escape(a.get('label') or '—')),
                ("端口", str(a.get('port') or '—')),
                ("依据", html.escape((a.get('evidence') or '')[:70])
                 + (f"<br><small>登记口令: <code>{html.escape(a['enroll_secret'])}</code></small>"
                    if a.get('enroll_secret') and a['status'] == 'granted' else '')),
                ("动作", actions(c))))
        return ''.join(out) or "<tr><td colspan=7>（无）</td></tr>"

    body = "<h2>申请（全部状态）</h2><table class=stack><tr><th>呼号</th><th>状态</th><th>产品</th><th>标签</th><th>端口</th><th>依据</th><th>动作</th></tr>" \
        + rows({"applied"}, lambda c: _act(ctx, "/verify", c, "核验通过", "<input type=hidden name=evidence value='人工核验通过'>") + _act(ctx, "/reject", c, "拒绝", "<input type=hidden name=reason value='材料不足'>")) \
        + rows({"verified"}, lambda c: _act(ctx, "/grant", c, "分配入口") + _act(ctx, "/reject", c, "拒绝", "<input type=hidden name=reason value='核验后驳回'>")) \
        + rows({"granted"}, lambda c: _act(ctx, "/revoke", c, "撤销", "<input type=hidden name=reason value='撤销'>")) \
        + rows({"rejected", "revoked"}, lambda c: "") + "</table>"
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")


@register("system", "MRRC Portal — 后台管理")
def view_system(ctx: Ctx) -> Rendered:
    res, svc, net, certs = ctx.resources, ctx.services, ctx.net, ctx.certs
    # 两列的「项/值」表在窄屏保持表格形态（class=kv），所以**不要**给 data-label；
    # 而 trow() 收到单个 tuple 会当成「一个单元格 + 它的标签」，一行只剩 1 个 td，
    # 而标签只在窄屏的 ::before 里出现 —— 桌面上就成了一列没有行名的数字。
    rows_ = ''.join(trow(html.escape(k), html.escape(str(v)))
                    for k, v in (("负载 (1/5/15 分钟)", res["load"]), ("CPU", res["cpu"]),
                                 ("内存", res["mem"]), ("磁盘", res["disk"]),
                                 ("已运行", res["uptime"]), ("Python", res["python"])))
    svc_rows = ''.join(trow(
        ("单元", f"<code>{html.escape(u)}</code>"),
        ("状态", f"<span class='pill {'ok' if st == 'active' else 'bad'}'>{html.escape(st)}</span>"),
        ("开机自启", html.escape(en)),
        ("起于", html.escape(si)),
        ("重启次数", html.escape(nr)))
        for u, st, en, si, nr in svc)
    reg_ports = {p for _, p in ctx.entries}
    listening = [p for p in net["listen"] if 18800 <= p <= 18999]
    missing = sorted(reg_ports - set(listening))
    stray = sorted(set(listening) - reg_ports)
    cert_rows = ''.join(trow(
        ("文件", f"<code>{html.escape(n)}</code>"),
        ("主体", html.escape(su)),
        ("到期", html.escape(na)),
        ("剩余", "—" if dy is None else f"{dy} 天"))
        for n, su, na, dy in certs) or "<tr><td colspan=4>（无）</td></tr>"

    # ③ 的附加行：frps 面板（隧道速率来自它，拿不到就如实标注原因）
    if ctx.sampler is None:
        tunnel_rows = "<tr><td>frps 面板</td><td>采集器未启用</td></tr>"
    else:
        snap = ctx.sampler
        panel_line = ("可用" if not snap["panel_error"]
                      else f"<b>{html.escape(snap['panel_error'])}</b>")
        if snap["panel_age"] is not None:
            panel_line += f"（{_ago(snap['panel_age'])}）"
        agg_in = agg_out = 0.0
        have_agg = False
        for item in snap["labels"].values():
            if item["last"].in_bps is not None and item["last"].out_bps is not None:
                agg_in += item["last"].in_bps
                agg_out += item["last"].out_bps
                have_agg = True
        agg_line = (f"↓ {_fmt_bps(agg_out)} / ↑ {_fmt_bps(agg_in)}"
                    if have_agg else "（本轮不可算）")
        nic = snap["nic"] or {}
        nic_line = (f"↓ {_fmt_bps(nic.get('rx_bps'))} / ↑ {_fmt_bps(nic.get('tx_bps'))}"
                    if "rx_bps" in nic else html.escape(nic.get("note", "—")))
        tunnel_rows = (f"<tr><td>frps 面板</td><td>{panel_line}</td></tr>"
                       f"<tr><td>全代理合计速率</td><td>{agg_line}</td></tr>"
                       f"<tr><td>hub 网卡</td><td>{nic_line}</td></tr>")
    body = (
        "<h2>系统</h2>"
        "<h3>① hub 主机</h3><table class=kv><tr><th>项</th><th>值</th></tr>" + rows_ + "</table>"
        "<h3>② hub 服务</h3><table class=stack><tr><th>单元</th><th>状态</th><th>开机自启</th>"
        "<th>起于</th><th>重启次数</th></tr>" + svc_rows + "</table>"
        "<p><small>「未安装」是一种<b>结论</b>而不是错误：单元文件在仓库里、却没装到 hub 上，"
        "正是路由不会自动重生成的原因（<code>mrrc-hub-routes.timer</code> 实测 "
        "<code>is-enabled</code> = not-found，而 SDD V0.22 写着「V0.17 起 30 s timer 自动」）。</small></p>"
        "<h3>③ 隧道层（frps）</h3><table class=kv><tr><th>项</th><th>值</th></tr>"
        f"<tr><td>frps 接入端口 8989</td><td>{'在听' if 8989 in net['listen'] else '<b>没在听</b>'}</td></tr>"
        f"<tr><td>frpc 控制连接</td><td>{len(net['peers'])} 条"
        f"{'：' + html.escape(', '.join(net['peers'])) if net['peers'] else ''}</td></tr>"
        f"<tr><td>注册表实例端口</td><td>{len(reg_ports)} 个</td></tr>"
        f"<tr><td>实际在听的实例端口</td><td>{len(listening)} 个"
        f"{'：' + ', '.join(str(x) for x in listening) if listening else ''}</td></tr>"
        f"<tr><td>注册了但没在听</td><td>{', '.join(str(x) for x in missing) or '（无）'}</td></tr>"
        f"<tr><td>在听但注册表里没有</td><td>{', '.join(str(x) for x in stray) or '（无）'}</td></tr>"
        + tunnel_rows
        + "</table>"
        + (f"<p><small>⚠️ {html.escape(net['note'])}</small></p>" if net["note"] else "")
        + "<h3>④ hub 侧已登记的实例证书</h3>"
        "<table class=stack><tr><th>文件</th><th>主体</th><th>到期</th><th>剩余</th></tr>" + cert_rows + "</table>"
        "<p><small>注册表里有一行只代表<b>预留</b>；没有证书就说明该实例从未走完批准→登记，"
        "它的入口只能 502。<br>"
        "本页采集不到的：<code>/var/log/nginx/*.log</code>（mrrcportal 不可读 ⇒ 无每实例的 nginx 错误计数）、"
        "实例内部状态（电台/录音/会话都在令牌之后）；frps 面板未启用或凭据不可读时，隧道速率会如实标注原因而不是显示 0。"
        "</small></p>")
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")


@register("instances", "MRRC Portal — 后台管理")
def view_instances(ctx: Ctx) -> Rendered:
    reports = ctx.reports

    def tunnel_cell(rep):                  # 同一探测的 HTML 版本（实例页）
        state = rep.get("state", "down")
        return (f"<span class='pill {ctx.tunnel_pill[state]}' "
                f"title='{html.escape(rep.get('detail', '未探测'), quote=True)}'>"
                f"{html.escape(ctx.tunnel_text[state])}</span>")

    def app_cell(rep):
        line = rep.get("status_line") or ""
        if not line:
            return "<small>—</small>"
        gen = rep.get("generation") or "—"
        srv = rep.get("server") or ""
        return (f"<small><code>{html.escape(line)}</code>"
                + (f"<br>server: {html.escape(srv)}" if srv else "")
                + f"<br>构建代号 <b>{html.escape(str(gen))}</b></small>")

    def cert_cell(rep):
        c = rep.get("cert") or {}
        if not c or c.get("subject", "—") == "—":
            return "<small>—<br>（握手没成，拿不到证书）</small>"
        ok = c.get("name_ok")
        mark = ("<span class='pill ok'>名字相符</span>" if ok else
                "<span class='pill bad'>名字不符 ⇒ nginx 必 502</span>" if ok is not None else "")
        issuer = "自签" if c.get("issuer") == c.get("subject") else (c.get("issuer") or "")[:44]
        days = _days_left(c.get("not_after", ""))
        return (f"<small><code>{html.escape(c.get('subject', ''))}</code><br>"
                f"{html.escape(issuer)}<br>到期 {html.escape(c.get('not_after', ''))}"
                f"{'（' + str(days) + ' 天）' if days is not None else ''}<br>{mark}</small>")

    rows_ = ''.join(trow(
        ("标签", f"<code>{html.escape(l)}</code>"),
        ("端口", str(p)),
        ("隧道", tunnel_cell(reports.get(l, {}))),
        ("实例里的应用", app_cell(reports.get(l, {}))),
        ("上游证书", cert_cell(reports.get(l, {}))),
        ("入口", f"<a href='https://{html.escape(l)}.mrrc.vlsc.net/' target=_blank "
                f"rel=noopener>打开入口</a>"))
        for l, p in sorted(ctx.entries)) or "<tr><td colspan=6>（注册表为空）</td></tr>"
    body = ("<h2>实例</h2><table class=stack><tr><th>标签</th><th>端口</th><th>隧道</th>"
            "<th>实例里的应用</th><th>上游证书</th><th>入口</th></tr>"
            + rows_ + "</table><p><small>「在线」= 从 hub 回环向该端口完成 TLS 握手并拿到 HTTP 应答"
            "（<b>任何</b>状态码都算，包括 401）；鼠标悬停可看探测详情。<br>"
            "⚠️ 仅仅「端口可连」<b>不能</b>证明实例在服务：frps 是在 hub 本机接受连接的，"
            "frpc 只要注册过代理就一定连得上，所以旧判据会把「隧道在、后端空」显示成在线"
            "（2026-10-03 的 bg7zhs 就是这个状态，而每个访客拿到 502）。"
            "「隧道在、后端无应答」请查实例机：应用是否在跑、frpc 的 <code>localPort</code> 是否等于"
            "应用的 <code>MRRC_WEB_PORT</code>、<code>MRRC_WEB_HOST</code> 是否被改成了局域网 IP"
            "（那就只听那个地址，frpc 拨 127.0.0.1 必然失败）。<br>"
            "新增后仍需：<code>sudo /usr/local/sbin/gen_hub_routes.py &amp;&amp; sudo systemctl reload nginx</code></small></p>")
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")


@register("audit", "MRRC Portal — 后台管理")
def view_audit(ctx: Ctx) -> Rendered:
    entries_a = ctx.audit[:60]
    rows_ = ''.join(trow(
        ("时间", time.strftime('%m-%d %H:%M', time.localtime(e['at']))),
        ("呼号", f"<code>{html.escape(e['callsign'])}</code>" if e['callsign'] else "—"),
        ("事件", html.escape(e['event'])),
        ("操作者", f"<code>{html.escape(e.get('actor') or '—')}</code>"),
        ("细节", html.escape((e.get('detail') or '')[:90]))) for e in entries_a)
    body = ("<h2>审计（最近 60 条，追加式）</h2><table class=stack><tr><th>时间</th><th>呼号</th><th>事件</th>"
            "<th>操作者</th><th>细节</th></tr>"
            + (rows_ or "<tr><td colspan=5>（无）</td></tr>") + "</table>")
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")


@register("tunnel", "MRRC Portal — 后台管理")
def view_tunnel(ctx: Ctx) -> Rendered:
    if ctx.sampler is None:
        body = ("<h2>隧道</h2><p class=msg>采集器未启用（--metrics-interval 0 或 dry-run）。"
                "延时与带宽需要后台采样线程。</p>")
    else:
        snap = ctx.sampler
        rows_ = []
        for label, port in sorted(ctx.entries):
            item = snap["labels"].get(label)
            if item is None:
                rows_.append(trow(("标签", f"<code>{html.escape(label)}</code>"),
                                  ("隧道", "<small>首轮采样中…</small>"),
                                  ("延时", "—"), ("带宽（↓/↑）", "—"),
                                  ("今日流量（↓/↑）", "—"), ("连接数", "—"), ("采样", "—")))
                continue
            last = item["last"]
            state = last.tunnel_state
            state_pill = (f"<span class='pill {ctx.tunnel_pill[state]}'>"
                          f"{html.escape(ctx.tunnel_text[state])}</span>") if state in ctx.tunnel_pill else "—"
            if last.latency_ms is not None:
                lat = (f"{last.latency_ms:.0f} ms<br><small>均值 {item['latency_mean']:.0f} · "
                       f"峰值 {item['latency_peak']:.0f}</small>")
            else:
                lat = f"<small>—（{html.escape(last.tunnel_detail or '无应答')}）</small>"
            bw = (f"↓ {_fmt_bps(last.out_bps)}<br>↑ {_fmt_bps(last.in_bps)}<br>"
                  f"<small>均值 ↓ {_fmt_bps(item['out_mean'])} / ↑ {_fmt_bps(item['in_mean'])}</small>")
            traffic = f"↓ {_fmt_bytes(last.today_out)}<br>↑ {_fmt_bytes(last.today_in)}"
            conns = "—" if last.cur_conns is None else str(last.cur_conns)
            fresh = _ago(item["stale_s"])
            if last.note:
                fresh += f"<br><small>{html.escape(last.note)}</small>"
            rows_.append(trow(("标签", f"<code>{html.escape(label)}</code>"),
                              ("隧道", state_pill), ("延时", lat), ("带宽（↓/↑）", bw),
                              ("今日流量（↓/↑）", traffic), ("连接数", conns), ("采样", fresh)))
        body = ("<h2>隧道</h2><table class=stack><tr><th>标签</th><th>隧道</th><th>延时</th>"
                "<th>带宽（↓/↑）</th><th>今日流量（↓/↑）</th><th>连接数</th><th>采样</th></tr>"
                + ("".join(rows_) or "<tr><td colspan=7>（注册表为空）</td></tr>") + "</table>"
                + (f"<p class=msg>⚠️ {html.escape(snap['panel_error'])}</p>"
                   if snap["panel_error"] else "")
                + "<p><small>带宽来自 frps 面板的累计字节差分（30 s 一轮）；历史只存内存、重启即清。"
                "延时是 hub 回环经隧道到实例应用的完整 TLS 握手耗时（只在握手成功时给出）。"
                "拿不到的一律如实标注，不用 0 冒充。</small></p>")
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")


@register("clublog", "MRRC Portal — 后台管理")
def view_clublog(ctx: Ctx) -> Rendered:
    body = (f"<h2>呼号库</h2><table class=kv><tr><th>项</th><th>值</th></tr>"
            f"<tr><td>来源</td><td>Club Log（与站内留言版 www.vlsc.net/feedback 同源）</td></tr>"
            f"<tr><td>状态</td><td>{ctx.clublog}</td></tr>"
            f"<tr><td>路径</td><td><code>{html.escape(ctx.clublog_path)}</code></td></tr></table>"
            f"<p><small>hub 每天 04:30 从 www 拉取（受限命令：只能读那一个文件）。<br>"
            f"立即刷新：<code>sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh</code></small></p>")
    return Rendered("MRRC Portal — 后台管理", chrome=_wrap(ctx, body), live="")
