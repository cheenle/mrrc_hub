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
    clublog_query: str = ""     # 呼号库页上要查的那个呼号
    clublog_hit: str = ""        # hit-clublog / hit-list / miss / ''（还没查）
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
            acts = (_post(ctx, "/verify", c, "核验通过", pri=True)
                    + _post(ctx, "/reject", c, "拒绝", dgr=True))
        elif status == "verified":
            acts = (_post(ctx, "/grant", c, "分配入口", pri=True)
                    + _post(ctx, "/reject", c, "拒绝", dgr=True))
        elif status == "granted":
            acts = _post(ctx, "/revoke", c, "撤销入口", dgr=True)
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

    破坏性动作（reject/revoke）这里只发"阶段一"——**不带 confirm**。
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
    return ui.confirm_form(f"{ctx.root}/{action}",
                           {"callsign": callsign, "view": "applications"},
                           "确认执行", csrf=ctx.csrf, reason_label=reason_label,
                           title=title.format(call=callsign.upper()), body=body)


def _port_of(ctx: Ctx, label: str) -> str:
    for l, p in ctx.entries:
        if l == label:
            return str(p)
    return "—"


def _days_text(not_after: str) -> str:
    """证书剩余天数的短文案。解析不了就回空串（**不编数字**）。"""
    days = _days_left(not_after)
    return "" if days is None else f"{days} 天"


# ── 实例 ────────────────────────────────────────────────────────────────

@register("instances", "MRRC Portal — 实例")
def view_instances(ctx: Ctx) -> Rendered:
    rows, cards = [], []
    for label, port in sorted(ctx.entries):
        rep = ctx.reports.get(label, {})
        state = rep.get("state") or ctx.states.get(port, ("", ""))[0]
        detail = rep.get("detail") or ctx.states.get(port, ("", ""))[1]
        serving = _is_serving(ctx, state)
        state_pill = ui.pill(ctx.tunnel_pill.get(state, "mute"),
                             ctx.tunnel_text.get(state, state or "未探测"))
        days = _days_text((rep.get("cert") or {}).get("not_after", ""))
        detail_link = (f'<a class="chip" href="{ctx.root}/admin?view=instance&amp;label='
                       f'{ui.esc(label)}">详情</a>')
        entry_link = (f'<a class="chip" href="https://{ui.esc(label)}.mrrc.vlsc.net/" '
                      f'target=_blank rel=noopener>打开入口</a>')
        rows.append([
            ("标签", f"<code>{ui.esc(label)}</code>"),
            ("端口", f'<span class="mono">{port}</span>'),
            ("隧道", state_pill),
            ("证书", f'<span class="mono">{ui.esc(days)}</span>' if days
             else '<span class="hint">—</span>'),
            ("应用", f'<span class="mono">{ui.esc(rep.get("generation") or "—")}</span>'),
            ("动作", f'<div class="tools" style="margin:0">{detail_link}{entry_link}</div>'),
        ])
        # 卡片的第二行直接给下一步 —— "后端无应答"后面必须跟一句该怎么办，
        # 否则运维还得自己回忆 2026-10-03 那次事故的排查顺序。
        hint = ""
        if detail and not serving:
            hint = ('<div class="hint bad">隧道在、但实例应用没起 —— 请查实例机：应用是否在跑、'
                    '<code>localPort</code> 是否等于 <code>MRRC_WEB_PORT</code>、'
                    '<code>MRRC_WEB_HOST</code> 是否被改成了局域网 IP</div>')
        cards.append(ui.card(
            head=f'<b><code>{ui.esc(label)}</code></b>{state_pill}',
            meta=(f'<span class="mono">{port}</span>'
                  f'<span>证书 {ui.esc(days) or "—"}</span>'
                  f'<span class="mono">{ui.esc(rep.get("generation") or "—")}</span>'),
            body=hint + f'<div class="tools" style="margin:9px 0 0">{detail_link}{entry_link}</div>',
            level=_level(ctx, state)))

    serving_n = sum(1 for _l, p in ctx.entries
                    if _is_serving(ctx, ctx.states.get(p, ("", ""))[0]))
    abnormal = len(ctx.entries) - serving_n
    chrome = (_head(ctx, f"{len(ctx.entries)} 个已登记 · {serving_n} 个在服务 · "
                         + (f'<b class="bad-tx">{abnormal} 个异常</b>' if abnormal
                            else '<b class="ok-tx">没有异常</b>')
                         + f" · 探测每 {REFRESH_SECONDS.get('instances', 20)} 秒一轮")
              + ui.toolbar(
                  [("全部", f"{ctx.root}/admin?view=instances", True, len(ctx.entries))],
                  search_html=(f'<form method="get" action="{ctx.root}/admin" class="search" '
                               f'data-tools><input type="hidden" name="view" value="instances">'
                               f'<input name="q" placeholder="搜索标签或端口…"></form>')))
    if rows:
        # 桌面表格与手机卡片是**两份标记**，用断点切换。
        # 为什么不靠 CSS 把表格"捏"成卡片：卡片头部要把标签与状态徽章放在同一行，
        # 表格单元格做不到这件事而不引入空的定位格（那又会让"行格数=表头列数"的守卫失效）。
        body = ('<div class="only-desktop">'
                + ui.grid_table(["标签", "端口", "隧道", "证书", "应用", "动作"], rows)
                + '</div><div class="only-mobile" data-mobile-cards>'
                + "".join(cards) + '</div>')
    else:
        body = ui.empty("注册表为空 —— 还没有实例登记",
                        f'<a class="chip" href="{ctx.root}/admin?view=applications">去看申请</a>')
    body += ui.banner(
        "info",
        "「服务中」= 从 hub 回环向该端口完成 <b>TLS 握手</b>并拿到 HTTP 应答（任何状态码都算）。"
        "仅仅「端口可连」<b>不算</b> —— frps 在本机接受连接，隧道在、后端空的时候照样连得上。")
    return Rendered(title="MRRC Portal — 实例", chrome=chrome,
                    live=live_region("instances", ctx, body))


@register("instance", "MRRC Portal — 实例详情")
def view_instance(ctx: Ctx, label: str = "") -> Rendered:
    label = label or ctx.flt_label
    rep = ctx.reports.get(label, {})
    state = rep.get("state", "")
    cert = rep.get("cert") or {}
    name_ok = cert.get("name_ok")
    cert_mark = (ui.pill("ok", "名字相符") if name_ok else
                 ui.pill("bad", "名字不符 ⇒ nginx 必 502") if name_ok is not None else
                 ui.pill("mute", "握手没成，拿不到证书"))
    # 没有证书时**不许**说"自签"：空 issuer == 空 subject 会让它误判成自签，
    # 而真相是"握手没成，什么都没拿到"。
    if not cert.get("subject"):
        issuer = "—"
    elif cert.get("issuer") == cert.get("subject"):
        issuer = "自签"
    else:
        issuer = cert.get("issuer")
    state_pill = ui.pill(ctx.tunnel_pill.get(state, "mute"),
                         ctx.tunnel_text.get(state, state or "未探测"))
    own_audit = [e for e in ctx.audit if (e.get("callsign") or "").upper() == label.upper()][:10]
    audit_html = ui.grid_table(
        ["时间", "事件", "操作者", "细节"],
        [[("时间", time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))),
          ("事件", ui.esc(ACTION_CN.get(e["event"], e["event"]))),
          ("操作者", f'<code>{ui.esc(e.get("actor") or "—")}</code>'),
          ("细节", ui.esc((e.get("detail") or "")[:90]))] for e in own_audit],
        stack=True) if own_audit else ui.empty("这个实例还没有审计记录")

    chrome = (f'<h1><code>{ui.esc(label)}</code></h1>'
              + f'<div class="hint">{ui.esc(label)}.mrrc.vlsc.net · 端口 '
                f'<span class="mono">{_port_of(ctx, label)}</span> · ' + state_pill + '</div>'
              + (ui.banner("ok", ui.esc(ctx.msg)) if ctx.msg else "")
              + '<h2>隧道与实例里的应用</h2>'
              + ui.kv([
                  ("隧道结论", ui.esc(rep.get("detail") or "未探测")),
                  ("上游证书主体", f'<code>{ui.esc(cert.get("subject") or "—")}</code>'),
                  ("签发者", ui.esc(issuer)),
                  ("到期", ui.esc(cert.get("not_after") or "—")),
                  ("名字比对", cert_mark),
                  ("应用状态行", f'<code>{ui.esc(rep.get("status_line") or "—")}</code>'),
                  ("Server", ui.esc(rep.get("server") or "—")),
                  ("构建代号", f'<b>{ui.esc(rep.get("generation") or "—")}</b>'),
              ])
              + '<h2>入口</h2>'
              + f'<div class="tools"><a class="chip" href="https://{ui.esc(label)}.mrrc.vlsc.net/" '
                f'target=_blank rel=noopener>打开入口</a>'
                f'<a class="chip" href="{ctx.root}/admin?view=instances">返回实例列表</a></div>'
              + '<h2>这个实例的审计</h2>' + audit_html
              + '<h2>动作</h2>'
              + _post(ctx, "/revoke", label, "撤销入口", dgr=True)
              + '<p><small>撤销会移除注册表里的一行，入口立刻 404；重开要重新走完核验。</small></p>')
    return Rendered(title=f"MRRC Portal — {label}", chrome=chrome, live="")


# ── 隧道 ────────────────────────────────────────────────────────────────

@register("tunnel", "MRRC Portal — 隧道")
def view_tunnel(ctx: Ctx) -> Rendered:
    chrome = _head(ctx, "延时是 hub 回环经隧道到实例应用的完整 TLS 握手耗时；"
                        "带宽与今日流量来自 frps 面板的累计字节差分。")
    if ctx.sampler is None:
        return Rendered(title="MRRC Portal — 隧道", chrome=chrome,
                        live=live_region("tunnel", ctx, ui.banner(
                            "warn", "采集器未启用（<code>--metrics-interval 0</code> 或 dry-run）。"
                                    "延时与带宽需要后台采样线程。")))
    snap = ctx.sampler
    rows, cards = [], []
    tot_out = tot_in = 0.0
    have_tot = False
    for label, port in sorted(ctx.entries):
        item = snap["labels"].get(label)
        if item is None:
            rows.append([("标签", f"<code>{ui.esc(label)}</code>"),
                         ("隧道", '<span class="hint">首轮采样中…</span>'),
                         ("延时（近 1 小时）", "—"), ("带宽（↓/↑）", "—"),
                         ("今日流量（↓/↑）", "—"), ("连接数", "—"), ("采样", "—")])
            continue
        last = item["last"]
        state = last.tunnel_state
        good = _is_serving(ctx, state)
        state_pill = ui.pill(ctx.tunnel_pill.get(state, "mute"),
                             ctx.tunnel_text.get(state, state))
        # 走势图的颜色也跟着状态走：断了的链路不画成青色假装它好好的。
        spark = ui.sparkline(item.get("history") or [], kind=("accent" if good else "bad"))
        if last.latency_ms is not None:
            lat = f'<span class="mono">{last.latency_ms:.0f} ms</span>'
            lat_note = f'均值 {item["latency_mean"]:.0f} · 峰值 {item["latency_peak"]:.0f}'
        else:
            lat = '<span class="hint">—</span>'
            lat_note = ui.esc(last.tunnel_detail or "无应答")
        if last.out_bps is not None and last.in_bps is not None:
            tot_out += last.out_bps
            tot_in += last.in_bps
            have_tot = True
            bw = (f'<span class="mono">↓ {_fmt_bps(last.out_bps)}</span><br>'
                  f'<span class="mono">↑ {_fmt_bps(last.in_bps)}</span>')
        else:
            bw = '<span class="hint">—</span>'
        traffic = (f'<span class="mono">↓ {_fmt_bytes(last.today_out)}</span><br>'
                   f'<span class="mono">↑ {_fmt_bytes(last.today_in)}</span>')
        conns = "—" if last.cur_conns is None else f'<span class="mono">{last.cur_conns}</span>'
        fresh = _ago(item["stale_s"])
        if last.note:
            fresh += f'<br><small>{ui.esc(last.note)}</small>'
        rows.append([("标签", f"<code>{ui.esc(label)}</code>"), ("隧道", state_pill),
                     ("延时（近 1 小时）", f'{lat}<br><small>{lat_note}</small><br>{spark}'),
                     ("带宽（↓/↑）", bw), ("今日流量（↓/↑）", traffic),
                     ("连接数", conns), ("采样", fresh)])
        cards.append(ui.card(
            head=f'<b><code>{ui.esc(label)}</code></b>{state_pill}',
            meta=(f'<span class="mono">{port}</span><span>{lat}</span>'
                  f'<span>{lat_note}</span>'),
            body=(spark + f'<div class="meta" style="margin-top:6px">'
                          f'<span>{bw}</span><span>{traffic}</span><span>{fresh}</span></div>'),
            level=_level(ctx, state)))

    if not ctx.entries:
        body = ui.empty("注册表为空 —— 没有可采的隧道")
    else:
        total = (f'<p class="hint">全代理合计：↓ {_fmt_bps(tot_out)} / ↑ {_fmt_bps(tot_in)}</p>'
                 if have_tot else '<p class="hint">本轮合计不可算</p>')
        body = ('<div class="only-desktop">'
                + ui.grid_table(["标签", "隧道", "延时（近 1 小时）", "带宽（↓/↑）",
                                 "今日流量（↓/↑）", "连接数", "采样"], rows)
                + total + '</div><div class="only-mobile" data-mobile-cards>'
                + "".join(cards) + '</div>')
    if snap.get("panel_error"):
        body = ui.banner("bad", ui.esc(snap["panel_error"])) + body
    body += ui.banner("info", "带宽来自 frps 面板的累计字节差分（30 秒一轮）；"
                              "历史只存内存、重启即清。拿不到的一律如实标注，<b>不用 0 冒充</b>。")
    return Rendered(title="MRRC Portal — 隧道", chrome=chrome,
                    live=live_region("tunnel", ctx, body))


# ── 系统 ────────────────────────────────────────────────────────────────

def _svc_level(row) -> str:
    """服务单元的级别。

    `enabled == "not-found"` = 单元文件在仓库里、没装到 hub 上 ⇒ 黄（要注意）；
    跑了但没 active ⇒ 红（要动手）；其余 ⇒ 绿。
    这条分级来自 SDD 里反复踩到的那件事：路由不会自动重生成，就是因为 timer 没装。
    """
    _unit, st, enabled, _since, _restarts = row
    if enabled == "not-found":
        return "warn"
    if st == "active":
        return ""
    return "bad"


@register("system", "MRRC Portal — 系统")
def view_system(ctx: Ctx) -> Rendered:
    res, svc, net, certs = ctx.resources, ctx.services, ctx.net, ctx.certs

    # ① 主机：没有硬阈值，只判"读得到还是读不到"。
    host_lines = [("负载 (1/5/15 分钟)", res.get("load", "—")), ("CPU", res.get("cpu", "—")),
                  ("内存", res.get("mem", "—")), ("磁盘", res.get("disk", "—")),
                  ("已运行", res.get("uptime", "—")), ("Python", res.get("python", "—"))]
    blind = [k for k, v in host_lines if "读不到" in str(v)]
    host_verdict = (ui.banner("warn", f"有 {len(blind)} 项读不到：" + ui.esc("、".join(blind)))
                    if blind else ui.banner("ok", "主机读数完整"))

    # ② 服务
    svc_rows = []
    for row in svc:
        unit, st, enabled, since, restarts = row
        lvl = _svc_level(row)
        svc_rows.append([("单元", f"<code>{ui.esc(unit)}</code>"),
                         ("状态", ui.pill({"": "ok", "warn": "warn", "bad": "bad"}[lvl], st)),
                         ("开机自启", ui.esc(enabled)), ("起于", ui.esc(since)),
                         ("重启次数", ui.esc(restarts)),
                         ("动作", (f'<a class="chip" href="#fix-{ui.esc(unit)}">修复命令</a>'
                                   if lvl else ""))])
    svc_bad = [r for r in svc if _svc_level(r)]
    svc_verdict = (ui.banner("warn", f"<b>{len(svc_bad)} 项要处理</b>："
                                      + ui.esc("、".join(r[0] for r in svc_bad))
                                      + f"（上面 {len(svc)} 个单元）")
                   if svc_bad else ui.banner("ok", f"全部 {len(svc)} 个单元都在跑"))
    svc_fix = "".join(
        f'<div class="card" id="fix-{ui.esc(r[0])}"><div class="cardhead">'
        f'<b>{ui.esc(r[0])} 的修法</b></div>'
        + ui.copy_button(
            f"sudo systemctl enable --now {r[0]}" if r[2] == "not-found"
            else f"sudo systemctl restart {r[0]}")
        + '<div class="meta" style="margin-top:6px"><span>'
        + ("单元文件在仓库的 <code>deploy/systemd/</code> 下；没装到 hub 上，"
           "路由就不会自动重生成" if r[2] == "not-found" else "跑不起来先看日志")
        + '</span></div></div>' for r in svc_bad)

    # ③ 隧道层
    reg_ports = {p for _l, p in ctx.entries}
    listening = [p for p in net.get("listen", []) if 18800 <= p <= 18999]
    missing = sorted(reg_ports - set(listening))
    stray = sorted(set(listening) - reg_ports)
    frps_up = 8989 in net.get("listen", [])
    port_ok = frps_up and not missing and not stray
    port_verdict = (ui.banner("ok", "frps 8989 在听，注册表与实际监听口一致")
                    if port_ok else
                    ui.banner("warn",
                              ("" if frps_up else "frps 8989 <b>没在听</b>。")
                              + (f"注册了但没在听：{missing}。" if missing else "")
                              + (f"在听但注册表里没有：{stray}。" if stray else "")))
    if ctx.sampler is None:
        tunnel_rows = [("frps 面板", "采集器未启用（--metrics-interval 0）")]
    else:
        snap = ctx.sampler
        agg_in = agg_out = 0.0
        have_agg = False
        for item in snap["labels"].values():
            if item["last"].in_bps is not None and item["last"].out_bps is not None:
                agg_in += item["last"].in_bps
                agg_out += item["last"].out_bps
                have_agg = True
        panel = ("可用" if not snap["panel_error"]
                 else f'<b>{ui.esc(snap["panel_error"])}</b>')
        if snap["panel_age"] is not None:
            panel += f"（{_ago(snap['panel_age'])}）"
        nic = snap["nic"] or {}
        nic_line = (f"↓ {_fmt_bps(nic.get('rx_bps'))} / ↑ {_fmt_bps(nic.get('tx_bps'))}"
                    if "rx_bps" in nic else ui.esc(nic.get("note", "—")))
        tunnel_rows = [("frps 面板", panel),
                       ("全代理合计速率", (f"↓ {_fmt_bps(agg_out)} / ↑ {_fmt_bps(agg_in)}"
                                           if have_agg else "（本轮不可算）")),
                       ("hub 网卡", nic_line)]
    listen_rows = [
        ("frps 接入端口 8989", "在听" if frps_up else "<b>没在听</b>"),
        ("frpc 控制连接", f"{len(net.get('peers', []))} 条"
                        + ("：" + ui.esc(", ".join(net["peers"])) if net.get("peers") else "")),
        ("注册表实例端口", f"{len(reg_ports)} 个"),
        ("实际在听的实例端口", f"{len(listening)} 个"
                           + ("：" + ", ".join(str(x) for x in listening) if listening else "")),
        ("注册了但没在听", ", ".join(str(x) for x in missing) or "（无）"),
        ("在听但注册表里没有", ", ".join(str(x) for x in stray) or "（无）"),
    ]

    # ④ 证书
    soon = [c for c in certs if (c[3] if isinstance(c[3], int) else 999) < 30]
    cert_verdict = (ui.banner("warn", f"{len(soon)} 张证书 30 天内到期")
                    if soon else ui.banner("ok", f"{len(certs)} 张已登记证书都不在 30 天窗口内"))
    cert_rows = [[("文件", f"<code>{ui.esc(n)}</code>"), ("主体", ui.esc(su)),
                  ("到期", ui.esc(na)),
                  ("剩余", "—" if dy is None else f"{dy} 天")] for n, su, na, dy in certs] \
        or [[("文件", '<span class="hint">（无）</span>')]]

    body = (
        '<h2>① hub 主机</h2>' + host_verdict + ui.kv(host_lines)
        + '<h2>② hub 服务</h2>' + svc_verdict
        + ui.grid_table(["单元", "状态", "开机自启", "起于", "重启次数", "动作"], svc_rows,
                        stack=True)
        + svc_fix
        + '<p><small>「未安装」是一种<b>结论</b>而不是错误：单元文件在仓库里、却没装到 hub 上，'
          '正是路由不会自动重生成的原因。</small></p>'
        + '<h2>③ 隧道层（frps）</h2>' + port_verdict + ui.kv(listen_rows + tunnel_rows)
        + (f"<p class='hint'>⚠️ {ui.esc(net['note'])}</p>" if net.get("note") else "")
        + '<h2>④ hub 侧已登记的实例证书</h2>' + cert_verdict
        + ui.grid_table(["文件", "主体", "到期", "剩余"], cert_rows, stack=True)
        + '<p><small>注册表里有一行只代表<b>预留</b>；没有证书就说明该实例从未走完批准→登记，'
          '它的入口只能 502。<br>'
          '本页采集不到的：<code>/var/log/nginx/*.log</code>（mrrcportal 不可读 ⇒ 无每实例的 '
          'nginx 错误计数）、实例内部状态（电台/录音/会话都在令牌之后）；'
          'frps 面板未启用或凭据不可读时，隧道速率会如实标注原因而不是显示 0。</small></p>')
    return Rendered(title="MRRC Portal — 系统", chrome=_head(ctx),
                    live=live_region("system", ctx, body))


# ── 审计 ────────────────────────────────────────────────────────────────

#: 审计每页条数与筛选组。登录事件单独一组 —— "有没有异常登录"是运维最先问的问题。
AUDIT_PAGE_SIZE = 50
LOGIN_EVENTS = ("login_ok", "login_failed", "login_locked")
ACTION_EVENTS = ("verify", "reject", "grant", "revoke", "enroll", "claim")
AUDIT_FILTERS = (("all", "全部", None),
                 ("login", "登录事件", LOGIN_EVENTS),
                 ("action", "运维动作", ACTION_EVENTS))

#: 事件 slug 的中文名。与 STATUS_CN 同理：英文 slug 不直接给运维看。
ACTION_CN = {"apply": "提交申请", "verify": "核验通过", "reject": "拒绝", "grant": "分配入口",
             "revoke": "撤销入口", "enroll": "证书登记", "claim": "自助取回凭证",
             "login_ok": "登录成功", "login_failed": "登录失败", "login_locked": "登录被锁"}


@register("audit", "MRRC Portal — 审计")
def view_audit(ctx: Ctx) -> Rendered:
    active = ctx.flt or "all"
    allowed = {fid: ev for fid, _l, ev in AUDIT_FILTERS}.get(active)
    picked = [e for e in ctx.audit if allowed is None or e.get("event") in allowed]
    if ctx.q.strip():
        needle = ctx.q.strip().upper()
        picked = [e for e in picked if needle in (e.get("callsign") or "").upper()]

    pages = max(1, (len(picked) + AUDIT_PAGE_SIZE - 1) // AUDIT_PAGE_SIZE)
    page = min(max(1, ctx.page), pages)
    start = (page - 1) * AUDIT_PAGE_SIZE
    window = picked[start:start + AUDIT_PAGE_SIZE]

    def link(fid: str, p: int = 1) -> str:
        """回**原始** URL：HTML 转义是 href 出口的事。
        在这里先写 &amp; 会被出口再转一次，变成 &amp;amp; —— 筛选就点不动了。"""
        return f"{ctx.root}/admin?view=audit&f={fid}&page={p}"

    chips = []
    for fid, label, evs in AUDIT_FILTERS:
        n = len([e for e in ctx.audit if evs is None or e.get("event") in evs])
        chips.append((f"{label} {n}", link(fid), fid == active, None))
    chrome = (_head(ctx, "追加式记录，最新的在前。登录事件带来源 IP；"
                         "运维动作带操作者归因（<code>actor</code>）。")
              + ui.toolbar(chips, search_html=(
                  f'<form method="get" action="{ctx.root}/admin" class="search" data-tools>'
                  f'<input type="hidden" name="view" value="audit">'
                  f'<input type="hidden" name="f" value="{ui.esc(active)}">'
                  f'<input name="q" value="{ui.esc(ctx.q)}" placeholder="按呼号筛选…"></form>')))

    rows = [[
        ("时间", f'<span class="mono">'
                f'{time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))}</span>'
                f'<br><small>{ui.esc(_ago_text(ctx.now, e["at"]))}</small>'),
        ("呼号", f'<code>{ui.esc(e["callsign"].upper())}</code>' if e.get("callsign")
         else '<span class="hint">—</span>'),
        ("事件", ui.pill("bad" if e["event"] == "login_failed" else
                         "warn" if e["event"] == "login_locked" else "mute",
                         ACTION_CN.get(e["event"], e["event"]))),
        ("操作者", f'<code>{ui.esc(e.get("actor") or "—")}</code>'),
        ("细节", ui.esc((e.get("detail") or "")[:90])),
    ] for e in window]
    body = (ui.grid_table(["时间", "呼号", "事件", "操作者", "细节"], rows, stack=True)
            if rows else ui.empty("这一筛选下没有记录",
                                  f'<a class="chip" href="{link("all")}">看全部</a>'))
    if pages > 1:
        body += (f'<div class="tools"><span class="hint">第 {page} / {pages} 页'
                 f'（共 {len(picked)} 条）</span>'
                 + (f'<a class="chip" href="{link(active, page - 1)}">上一页</a>'
                    if page > 1 else "")
                 + (f'<a class="chip" href="{link(active, page + 1)}">下一页</a>'
                    if page < pages else "")
                 + '</div>')
    return Rendered(title="MRRC Portal — 审计", chrome=chrome,
                    live=live_region("audit", ctx, body))


# ── 呼号库 ──────────────────────────────────────────────────────────────

@register("clublog", "MRRC Portal — 呼号库")
def view_clublog(ctx: Ctx) -> Rendered:
    verdict = ""
    if ctx.clublog_query:
        shown = ui.esc(ctx.clublog_query.upper())
        if ctx.clublog_hit == "hit-clublog":
            verdict = ui.banner("ok", f'<b>{shown}</b> 在库中 —— 命中 <b>Club Log</b>（权威库）')
        elif ctx.clublog_hit == "hit-list":
            verdict = ui.banner("ok", f'<b>{shown}</b> 在库中 —— 命中 <b>运维自建清单</b>')
        elif ctx.clublog_hit == "miss":
            verdict = ui.banner("warn", f'<b>{shown}</b> 不在库中 —— 将转 <b>人工核验</b>')
        else:
            verdict = ui.banner("bad", f'<b>{shown}</b> 查询失败（库不可读？）')
    form = (f'<form method="get" action="{ctx.root}/admin" data-tools class="tools">'
            f'<input type="hidden" name="view" value="clublog">'
            f'<input name="q" value="{ui.esc(ctx.clublog_query)}" '
            f'placeholder="查一个呼号，例如 BG1SB"><button>查一下</button></form>')
    body = (form + verdict
            + ui.kv([("来源", "Club Log（与站内留言版 www.vlsc.net/feedback 同源）"),
                     ("状态", ui.esc(ctx.clublog) or "—"),
                     ("路径", f'<code>{ui.esc(ctx.clublog_path)}</code>')])
            + '<p><small>核验链：Club Log（权威）→ 运维自建清单 → 人工兜底。'
              '本页查询<b>纯本地</b>，不联网。<br>'
              'hub 每天 04:30 从 www 拉取（受限命令：只能读那一个文件）。</small></p>'
            + ui.copy_button("sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh", "复制刷新命令"))
    return Rendered(title="MRRC Portal — 呼号库", chrome=_head(ctx),
                    live=live_region("clublog", ctx, body))
