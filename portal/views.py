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
    """侧栏与底栏的待办徽标。只在 >0 时显示（ui._badge_html 负责）。

    红 = 要动手（异常实例、待核验申请），黄 = 要注意（未安装/未跑的服务单元）。
    `system` 那一项只有系统视图才采得到，其它视图不报 —— 宁可没徽标，
    也不要为了让徽标好看而在每个页面上多跑一轮 systemctl。
    """
    applied = sum(1 for a in ctx.apps.values() if a["status"] in ("applied", "verified"))
    abnormal = sum(1 for _l, p in ctx.entries
                   if ctx.tunnel_pill.get(ctx.states.get(p, ("", ""))[0]) != "ok")
    out = {"applications": applied, "instances": abnormal}
    if ctx.services:
        out["system"] = sum(1 for _u, st, en, _s, _r in ctx.services
                            if en == "not-found" or st != "active")
    return out


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
    """旧的页内文字导航（标记保持原样，留着给需要它的视图用）。"""
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
    """视图头部 + 正文。

    导航、登出、待办徽标现在由**外壳**（`ui.page(nav=…)`）提供 —— 侧栏与手机底栏
    都是它的。这里只负责“这个视图叫什么”与操作后的那条消息。
    """
    title = ui.TITLES.get(ctx.view, "后台管理")
    msg = ui.banner("ok", ui.esc(ctx.msg)) if ctx.msg else ""
    return f"<h1>{ui.esc(title)}</h1>{msg}" + body


#: 状态 slug 的中文名。总览页曾把 `applied=1 verified=1` 直接打给运维看（P2）。
STATUS_CN = {"applied": "待核验", "verified": "待分配", "granted": "已授予",
             "rejected": "已拒绝", "revoked": "已撤销"}

#: 申请分组：(组 id, 标题, 组内状态)。默认只看第一组 —— “七种状态一锅端”是 P3。
APP_GROUPS = (
    ("pending", "待处理", ("applied", "verified")),
    ("granted", "已授予", ("granted",)),
    ("closed", "已结束", ("rejected", "revoked")),
)


def _head(ctx: Ctx, subtitle: str = "") -> str:
    """视图头部：标题 + 操作后的消息 + 一句说明。

    导航与登出不在里 —— 它们属于外壳（`ui.page(nav=…)`），外壳变了这里不用跟着改。
    """
    out = f"<h1>{ui.esc(ui.TITLES.get(ctx.view, '后台管理'))}</h1>"
    if ctx.msg:
        out += ui.banner("ok", ui.esc(ctx.msg))
    if subtitle:
        out += f'<div class="hint">{subtitle}</div>'
    return out


def _is_serving(ctx: Ctx, state: str) -> bool:
    """唯一判据是 `TUNNEL_PILL`：“服务中”即 pill == 'ok'。

    视图不 import `TUNNEL_SERVING` 这类常量：它们在 app.py，而 app.py import views
    （循环）；而且状态语义的权威本来就在探针那边。
    """
    return ctx.tunnel_pill.get(state) == "ok"


def _level(ctx: Ctx, state: str) -> str:
    """状态对应的视觉级别（''|warn|bad），同样只来自 tunnel_pill。"""
    return {"ok": "", "warn": "warn", "bad": "bad"}.get(ctx.tunnel_pill.get(state, ""), "")


def _ago_text(now: float, then) -> str:
    if not then:
        return "时间未知"
    d = max(0, int(now - then))
    if d < 60:
        return "刚刚"
    if d < 3600:
        return f"{d // 60} 分钟前"
    if d < 86400:
        return f"{d // 3600} 小时前"
    return f"{d // 86400} 天前"


def _int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _todo_items(ctx: Ctx) -> list[tuple[str, str, str, str]]:
    """待办清单 → [(级别, 标题, 说明, 动作 HTML)]。

    这是总览的核心：它回答“我现在该做什么”。级别决定颜色，**红＝要动手**。
    """
    items: list[tuple[str, str, str, str]] = []
    pending = [a for a in ctx.apps.values() if a["status"] == "applied"]
    for a in sorted(pending, key=lambda a: a.get("at") or 0)[:5]:
        evidence = (a.get("evidence") or "需人工核验")[:60]
        items.append((
            "warn", f"待核验 · {a['callsign'].upper()}",
            f"{ui.esc(evidence)} · {_ago_text(ctx.now, a.get('at'))}",
            f'<a class="chip" href="{ctx.root}/admin?view=applications">去处理</a>'))
    for label, port in ctx.entries:
        state, detail = ctx.states.get(port, ("", "未探测"))
        if _is_serving(ctx, state):
            continue
        items.append((
            "bad" if _level(ctx, state) == "bad" else "warn",
            f"{label} · {ctx.tunnel_text.get(state, state or '未探测')}",
            ui.esc(detail) + " —— 访客会拿到 502，请查实例机",
            f'<a class="chip" href="{ctx.root}/admin?view=instances">看实例</a>'))
    for unit, st, enabled, _since, _restarts in ctx.services:
        if enabled != "not-found" and st == "active":
            continue
        note = ("单元文件在仓库里、没装到 hub 上 —— 路由不会自动重生成"
                if enabled == "not-found" else f"当前 {st}")
        items.append(("warn", f"服务 {unit} · {st}", ui.esc(note),
                      f'<a class="chip" href="{ctx.root}/admin?view=system">去系统页</a>'))
    days = _int_or_none(ctx.cert_days)
    if days is not None and days < 30:
        items.append(("warn", "入口证书临期", f"还剩 {days} 天，到期前必须续",
                      f'<a class="chip" href="{ctx.root}/admin?view=system">看证书</a>'))
    if ctx.sampler and ctx.sampler.get("panel_error"):
        items.append(("warn", "frps 面板取不到数",
                      ui.esc(ctx.sampler["panel_error"]) + " —— 隧道带宽会缺数",
                      f'<a class="chip" href="{ctx.root}/admin?view=system">去看原因</a>'))
    return items


@register("overview", "MRRC Portal — 总览")
def view_overview(ctx: Ctx) -> Rendered:
    by: dict[str, int] = {}
    for a in ctx.apps.values():
        by[a["status"]] = by.get(a["status"], 0) + 1
    serving = sum(1 for _l, p in ctx.entries
                  if _is_serving(ctx, ctx.states.get(p, ("", ""))[0]))
    todos = _todo_items(ctx)

    lat = [i["last"].latency_ms for i in (ctx.sampler or {}).get("labels", {}).values()
           if i["last"].latency_ms is not None]
    lat_note = f"均值 {sum(lat) / len(lat):.0f} 毫秒 · {serving} 条在线" if lat else "暂无采样"
    cert_note = "天后到期" if _int_or_none(ctx.cert_days) is not None else ui.esc(ctx.cert_days)

    stats = ('<div class="stats">'
             + ui.stat("待你处理", str(len(todos)), "按下面那张清单计",
                       "warn" if todos else "ok")
             + ui.stat("实例异常", str(max(0, len(ctx.entries) - serving)),
                       f"{len(ctx.entries)} 个已登记",
                       "bad" if serving < len(ctx.entries) else "ok")
             + ui.stat("入口证书", ctx.cert_days, cert_note)
             + ui.stat("隧道总延时", f"{sum(lat) / len(lat):.0f}" if lat else "—", lat_note)
             + '</div>')

    todo_html = "".join(
        f'<div class="card {"alert warn" if lv == "warn" else "alert"}">'
        f'<div class="cardhead">{ui.pill(lv, "要动手" if lv == "bad" else "待处理")}'
        f'<b>{title}</b>{action}</div>'
        f'<div class="meta"><span>{note}</span></div></div>'
        for lv, title, note, action in todos) or ui.empty(
            "没有待办 —— 所有申请都已处理，已登记的实例都在服务",
            f'<a class="chip" href="{ctx.root}/admin?view=instances">看实例清单</a>')

    port_used = len(ctx.entries)
    kv_rows = [
        ("申请状态分布", "　".join(f"{STATUS_CN.get(k, k)}={v}" for k, v in sorted(by.items()))
         or "（无）"),
        ("端口池", f"{ctx.registry_first}-{ctx.registry_last}，已用 {port_used}，"
                   f"空闲 {ctx.registry_last - ctx.registry_first + 1 - port_used}"),
        ("Club Log 呼号库", ui.esc(ctx.clublog) if ctx.clublog else "—"),
    ]
    cmd = ('<div class="card"><div class="cardhead"><b>需要 root 的运维命令</b></div>'
           '<div class="meta"><span>新增/撤销实例后</span></div>'
           + ui.copy_button("sudo /usr/local/sbin/gen_hub_routes.py && sudo systemctl reload nginx")
           + '<div class="meta" style="margin-top:6px"><span>立即刷新呼号库</span></div>'
           + ui.copy_button("sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh")
           + '</div>')

    body = (stats + "<h2>需要你处理的</h2>" + todo_html
            + "<h2>概览</h2>" + ui.kv(kv_rows) + cmd)
    return Rendered(title="MRRC Portal — 总览", chrome=_head(ctx),
                    live=live_region("overview", ctx, body))


@register("applications", "MRRC Portal — 申请")
def view_applications(ctx: Ctx) -> Rendered:
    groups: dict[str, list] = {gid: [] for gid, _t, _s in APP_GROUPS}
    for a in ctx.apps.values():
        for gid, _title, statuses in APP_GROUPS:
            if a["status"] in statuses:
                groups[gid].append(a)
    for v in groups.values():
        v.sort(key=lambda a: -(a.get("at") or 0))

    active = ctx.flt or "pending"
    chips = [(f"{title} {len(groups[gid])}",
              f"{ctx.root}/admin?view=applications&f={gid}", gid == active, None)
             for gid, title, _s in APP_GROUPS]
    chips.append(("全部", f"{ctx.root}/admin?view=applications&f=all", active == "all", None))
    chrome = (_head(ctx, "把「规范化 → 查重 → 核验 → 分配」走完；"
                         "呼号核验通过才会分配入口。")
              + ui.toolbar(chips, search_html=(
                  f'<form method="get" action="{ctx.root}/admin" class="search" data-tools>'
                  f'<input type="hidden" name="view" value="applications">'
                  f'<input name="q" value="{ui.esc(ctx.q)}" placeholder="搜索呼号…"></form>')))

    HEADERS = ["呼号", "状态", "产品", "依据", "时间", "动作"]

    def row(a) -> list:
        c = a["callsign"]
        status = a["status"]
        shown = a.get("label") if status == "granted" and a.get("label") else c.upper()
        cells = [
            ("呼号", f"<code>{ui.esc(shown)}</code>"),
            ("状态", ui.pill("mute", STATUS_CN.get(status, status))),
            ("产品", ui.esc(a.get("product") or "主产品")),
            ("依据", ui.esc((a.get("evidence") or "")[:70])),
            ("时间", _ago_text(ctx.now, a.get("at"))),
        ]
        if status == "applied":
            acts = (_post(ctx, "/admin/verify", c, "核验通过", pri=True)
                    + _post(ctx, "/admin/reject", c, "拒绝", dgr=True))
        elif status == "verified":
            acts = (_post(ctx, "/admin/grant", c, "分配入口", pri=True)
                    + _post(ctx, "/admin/reject", c, "拒绝", dgr=True))
        elif status == "granted":
            acts = _post(ctx, "/admin/revoke", c, "撤销入口", dgr=True)
            if a.get("enroll_secret"):
                acts = ui.copy_button(a["enroll_secret"], "复制登记口令") + acts
        else:
            acts = ""
        cells.append(("动作", acts))
        return cells

    blocks = []
    for gid, title, _s in APP_GROUPS:
        if active not in (gid, "all"):
            continue
        rows = [row(a) for a in groups[gid]]
        blocks.append(f"<h2>{ui.esc(title)}（{len(groups[gid])}）</h2>"
                      + (ui.grid_table(HEADERS, rows, stack=True) if rows
                         else ui.empty(f"没有{title}的申请",
                                       f'<a class="chip" '
                                       f'href="{ctx.root}/admin?view=applications&f=all">'
                                       f'看全部</a>')))
    return Rendered(title="MRRC Portal — 申请", chrome=chrome,
                    live=live_region("applications", ctx, "".join(blocks)))


def _post(ctx: Ctx, route: str, callsign: str, label: str, *, pri: bool = False,
          dgr: bool = False) -> str:
    """状态变更表单。**永远带 csrf**，永远是真 form（关掉 JS 也能提交）。

    破坏性动作（reject/revoke）这里只发“阶段一”——**不带 confirm**。
    服务端收到没带 confirm 的请求时回确认页，那一步才真正执行。
    """
    cls = ' class="pri"' if pri else (' class="dgr"' if dgr else '')
    return (f'<form method="post" action="{ctx.root}{route}">'
            f'<input type="hidden" name="csrf" value="{ui.esc(ctx.csrf)}">'
            f'<input type="hidden" name="callsign" value="{ui.esc(callsign)}">'
            f'<button{cls}>{ui.esc(label)}</button></form>')


#: 确认页的文案。写在这里而不是拼在 app.py 里：它是界面，不是路由逻辑。
CONFIRM_TITLES = {
    "revoke": ("撤销 {call} 的入口？",
               "注册表会少一行，访客立刻拿不到入口。撤销是长期的，重开要重新走完核验。"),
    "reject": ("拒绝 {call} 的申请？",
               "申请会被标记为已拒绝。若对方是合法持照者，需要重新申请。"),
}


def confirm_page(action: str, callsign: str, ctx: Ctx, *, reason_label: str = "原因") -> str:
    """破坏性动作的第二阶段：带理由输入的确认表单（服务端渲染，JS 可有可无）。"""
    title, body = CONFIRM_TITLES.get(action, (f"确认 {action}？", "此操作会改变状态。"))
    return ui.confirm_form(f"{ctx.root}/admin/{action}",
                           {"callsign": callsign, "view": "applications"},
                           "确认执行", csrf=ctx.csrf, reason_label=reason_label,
                           title=title.format(call=callsign.upper()), body=body)


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
