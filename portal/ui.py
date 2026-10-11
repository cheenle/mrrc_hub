"""Portal 界面层：设计令牌、样式表、组件与页面外壳。

这一层是**纯呈现**：不读文件、不起进程、不开 socket（`STATIC_DIR` 只是路径常量）。
所有事实由 `app.py` 采集后装进 `views.Ctx`，视图只做排版。

设计纪律只有一条：**白 = 强调，色 = 状态。** 青色（--accent）只用于焦点环、链接与
图表线，不承担任何"重要"语义 —— 否则红色出现时就不再是信号。
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

#: 设计令牌。**唯一来源**：CSS 由它生成，测试读它算对比度。
#: 改任何一个值都要重新过 tests/test_portal_ui.py 的对比度守卫。
TOKENS: dict[str, str] = {
    "bg": "#0b0e14",          # 页面底
    "panel": "#121721",       # 侧栏 / 卡片 / 表头
    "panel2": "#171e29",      # hover / 次级面
    "bd": "rgba(255,255,255,.07)",
    "bds": "rgba(255,255,255,.13)",
    "tx": "#e6edf3",          # 主文字（也是"强调"色）
    "tx2": "#93a1b1",         # 次文字
    "tx3": "#7c8798",         # 弱文字 —— 原样张的 #5b6675 只有 3.31:1，不达 AA
    "accent": "#22d3ee",      # 焦点环 / 链接 / 图表线
    "ok": "#4ade80",
    "warn": "#fbbf24",
    "bad": "#fb7185",
}

#: 静态资源目录与**白名单**。只有这里的名字能被送出；不做通用文件服务，
#: 也不把请求路径拼进文件路径 —— 精确字典查找是唯一的安全边界。
STATIC_DIR = Path(__file__).resolve().parent / "static"

STATIC_WHITELIST: dict[str, str] = {
    "htmx.min.js": "application/javascript; charset=utf-8",
    "admin.js": "application/javascript; charset=utf-8",
    "htmx.LICENSE": "text/plain; charset=utf-8",
}

#: 静态资源的缓存头：内容按哈希冻结，可以永久缓存。
STATIC_CACHE = "public, max-age=31536000, immutable"


def _root_vars() -> str:
    return "".join(f"--{k}:{v};" for k, v in TOKENS.items())


#: 全站样式。保持内联（不经静态路由）：页面外壳的首要保证是"样式一定在"，
#: 公开注册页不应因静态资源故障而裸奔。代价是将来上 CSP 需要 style-src 'unsafe-inline'。
_CSS_BODY = """
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx2);
font:13px/1.6 Inter,-apple-system,BlinkMacSystemFont,'SF Pro Display','PingFang SC',sans-serif;
-webkit-text-size-adjust:100%;-webkit-font-smoothing:antialiased}
a{color:var(--accent)}
h1{color:var(--tx);font-size:19px;letter-spacing:-.022em;margin:0 0 3px;font-weight:700}
h2{color:var(--tx);font-size:15px;margin:22px 0 8px;font-weight:600}
h3{color:var(--tx);font-size:13px;margin:16px 0 6px;font-weight:600}
p{margin:8px 0}
table{border-collapse:collapse;width:100%}
td,th{text-align:left;padding:9px 10px;border-bottom:1px solid var(--bd);vertical-align:middle;
color:var(--tx2);overflow-wrap:anywhere}
th{font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--tx3);font-weight:600}
code,kbd,.mono{font-family:'SF Mono',ui-monospace,Menlo,monospace;font-size:.92em;
font-variant-numeric:tabular-nums}
code{background:rgba(255,255,255,.05);border-radius:5px;padding:1px 5px;color:var(--tx)}
input,button,select,textarea{font:inherit;border-radius:8px;border:1px solid var(--bd);
background:var(--panel2);color:var(--tx);padding:7px 10px}
input:focus-visible,button:focus-visible,select:focus-visible,a:focus-visible{
outline:2px solid var(--accent);outline-offset:1px}
button{background:var(--panel2);cursor:pointer;font-weight:600;min-height:34px}
button.pri{background:var(--tx);color:var(--bg);border-color:transparent}
button.dgr{color:var(--bad);border-color:rgba(251,113,133,.3);background:rgba(251,113,133,.07)}
button:disabled{opacity:.5;cursor:default}
small{font-size:11.5px;color:var(--tx3)}
.skip{position:absolute;left:-9999px}
.skip:focus{left:8px;top:8px;background:var(--accent);color:#000;padding:8px 12px;
border-radius:8px;z-index:99}
/* ── 外壳 ── */
.shell{display:flex;min-height:100vh}
.side{width:190px;flex:0 0 auto;background:var(--panel);border-right:1px solid var(--bd);
padding:14px 10px;display:flex;flex-direction:column}
.brand{color:var(--tx);font-weight:700;font-size:12.5px;margin:2px 8px 4px;text-decoration:none}
.brand em{color:var(--accent);font-style:normal}
.grp{font-size:9.5px;color:var(--tx3);letter-spacing:.11em;margin:14px 8px 5px;
font-weight:600;text-transform:uppercase}
.navlink{display:flex;align-items:center;justify-content:space-between;gap:6px;padding:7px 8px;
border-radius:7px;color:var(--tx2);text-decoration:none;margin-bottom:1px;min-height:34px}
.navlink:hover{background:rgba(255,255,255,.04)}
.navlink[aria-current=page]{background:rgba(255,255,255,.09);color:var(--tx);font-weight:600}
.sidefoot{margin-top:auto;padding:10px 8px 2px;border-top:1px solid var(--bd);
font-size:10.5px;color:var(--tx3);line-height:1.7}
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.top{display:flex;align-items:center;gap:12px;padding:9px 16px;border-bottom:1px solid var(--bd);
background:rgba(255,255,255,.015);position:sticky;top:0;z-index:5}
.live{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:11px;color:var(--tx3)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--ok);
box-shadow:0 0 0 3px rgba(74,222,128,.14);flex:0 0 auto}
body.is-paused .dot{background:var(--tx3);box-shadow:none}
.content{padding:16px;flex:1;min-width:0}
.content:focus{outline:none}
/* ── 组件 ── */
.pill{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:2px 8px;
font-size:10.5px;font-weight:600;white-space:nowrap;border:1px solid}
.pill::before{content:'';width:5px;height:5px;border-radius:50%;background:currentColor;flex:0 0 auto}
.pill.ok{color:var(--ok);border-color:rgba(74,222,128,.3);background:rgba(74,222,128,.09)}
.pill.warn{color:var(--warn);border-color:rgba(251,191,36,.3);background:rgba(251,191,36,.08)}
.pill.bad{color:var(--bad);border-color:rgba(251,113,133,.3);background:rgba(251,113,133,.09)}
.pill.mute{color:var(--tx3);border-color:var(--bd);background:rgba(255,255,255,.03)}
.banner{display:flex;gap:9px;align-items:flex-start;border-radius:9px;padding:9px 12px;
font-size:12px;margin:10px 0;border:1px solid}
.banner.info{background:rgba(34,211,238,.06);border-color:rgba(34,211,238,.22)}
.banner.ok{background:rgba(74,222,128,.07);border-color:rgba(74,222,128,.28)}
.banner.warn{background:rgba(251,191,36,.07);border-color:rgba(251,191,36,.28)}
.banner.bad{background:rgba(251,113,133,.08);border-color:rgba(251,113,133,.3)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.stat{background:var(--panel);border:1px solid var(--bd);border-radius:9px;padding:10px 12px}
.stat span{display:block;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;
color:var(--tx3);font-weight:600}
.stat b{display:block;color:var(--tx);font-size:22px;font-weight:700;letter-spacing:-.03em;
margin:3px 0 1px;font-family:'SF Mono',ui-monospace,Menlo,monospace}
.stat b.ok{color:var(--ok)}.stat b.warn{color:var(--warn)}.stat b.bad{color:var(--bad)}
.stat em{font-style:normal;font-size:11px;color:var(--tx3)}
.tools{display:flex;align-items:center;gap:7px;margin:10px 0;flex-wrap:wrap}
.chip{border:1px solid var(--bd);border-radius:999px;padding:5px 11px;font-size:11px;
color:var(--tx2);text-decoration:none;min-height:30px;display:inline-flex;align-items:center}
.chip.on{background:rgba(255,255,255,.1);color:var(--tx);border-color:var(--bds);font-weight:600}
.chip.hot{color:var(--bad);border-color:rgba(251,113,133,.3)}
.tools .search{flex:1;min-width:150px}
.card{background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:11px 12px;
margin-bottom:9px}
.card.alert{border-color:rgba(251,113,133,.33)}
.card.alert.warn{border-color:rgba(251,191,36,.33)}
.cardhead{display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap}
.cardhead b{color:var(--tx);font-size:13px;font-weight:600;flex:1;min-width:0}
.meta{font-size:11px;color:var(--tx3);display:flex;gap:7px;flex-wrap:wrap}
.meta b{color:var(--tx2);font-weight:500}
.hint{font-size:10.5px;color:var(--tx3)}
.hint.bad{color:var(--bad)}.hint.warn{color:var(--warn)}
.empty{text-align:center;padding:26px 12px;color:var(--tx3);font-size:12px}
.empty p{margin:0 0 10px}
.badge{background:rgba(251,113,133,.16);color:var(--bad);border:1px solid rgba(251,113,133,.35);
border-radius:999px;font-size:9.5px;font-weight:700;padding:0 6px;line-height:16px}
.badge.w{background:rgba(251,191,36,.13);color:var(--warn);border-color:rgba(251,191,36,.3)}
.copybar{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.spark{vertical-align:middle}
.confirm{border:1px solid var(--bds);border-radius:12px;background:var(--panel);color:var(--tx2);
max-width:420px;padding:16px}
.confirm::backdrop{background:rgba(0,0,0,.6)}
.tabbar{display:none}
/* 公开页形态：正文 15px（面向陌生读者，不压密度），单栏居中 */
body.public{font-size:15px;line-height:1.7}
body.public .content{max-width:680px;margin:0 auto;padding:24px 16px 48px;width:100%}
body.public .top{background:none;border-bottom:0}
/* ── 窄屏 ── */
/* 断点从旧版的 720px 提到 767px：桌面侧栏在 768px 以上才出现，两者必须对齐，
   否则 721–767px 这段宽度会出现"有侧栏但没有底部标签栏"的真空。 */
@media(max-width:767px){
/* 触摸目标：手机上一切可点元素 ≥44px。桌面表格里的紧凑按钮不受影响，
   因为这条规则只在窄屏生效。 */
button,input,select,.chip,.navlink,.tabbar a{min-height:44px}
.shell{display:block}
.side{position:fixed;inset:0 auto 0 0;width:250px;z-index:20;transform:translateX(-100%);
transition:transform .18s ease;box-shadow:0 0 40px rgba(0,0,0,.5)}
body.drawer .side{transform:none}
body.drawer::after{content:'';position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10}
.content{padding:12px 12px 76px}
.top{padding:10px 13px}
.sidefoot{display:none}
.tabbar{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:15;
background:var(--panel);border-top:1px solid var(--bd);
padding-bottom:env(safe-area-inset-bottom)}
.tabbar a{flex:1;padding:7px 0 8px;text-align:center;font-size:9.5px;color:var(--tx3);
text-decoration:none;min-height:48px}
.tabbar a[aria-current=page]{color:var(--accent)}
.tabbar a b{display:block;font-size:16px;font-weight:400;margin-bottom:1px;position:relative}
.tabbar a i{position:absolute;top:-1px;right:-7px;width:6px;height:6px;border-radius:50%;
background:var(--bad)}
.stats{grid-template-columns:1fr 1fr}
.tools{gap:6px}
.tools .search{flex:1 1 100%}
/* 宽表在窄屏堆叠成卡片（申请/系统/审计/呼号库仍在用） */
table.stack{display:block;border:0}
table.stack thead{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}
table.stack tbody,table.stack tr{display:block}
table.stack tr{border:1px solid var(--bd);border-radius:10px;background:var(--panel);
margin:8px 0;overflow:hidden}
table.stack td{display:block;border-bottom:1px solid var(--bd)}
table.stack tr td:last-child{border-bottom:0}
table.stack td::before{content:attr(data-label);display:block;color:var(--tx3);font-size:9.5px;
text-transform:uppercase;letter-spacing:.07em;margin-bottom:2px}
table.stack td:not([data-label])::before{content:none}
}
@media(min-width:768px){.only-mobile{display:none}}
@media(max-width:767px){.only-desktop{display:none}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def stylesheet() -> str:
    return f":root{{{_root_vars()}}}\n{_CSS_BODY}"


CSS = stylesheet()


# ── 组件 ────────────────────────────────────────────────────────────────
# 约定：参数名叫 `text` 的**一律当纯文本**处理（内部 html.escape）；叫 `html_text` / `body`
# 的由调用方负责安全（调用方只能是 views.py 的固定模板，用户输入必须自己先 esc()）。
# 这条约定让"哪里被转义过"在调用点一眼可见。

def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def pill(kind: str, text: str) -> str:
    """状态徽章。kind ∈ ok|warn|bad|mute；颜色只是辅助，文字必须在。"""
    return f'<span class="pill {esc(kind)}">{esc(text)}</span>'


def banner(kind: str, html_text: str) -> str:
    """页内通知条。kind ∈ info|ok|warn|bad；html_text 由调用方保证安全。"""
    return f'<div class="banner {esc(kind)}"><div>{html_text}</div></div>'


def stat(label: str, value: str, note: str = "", kind: str = "") -> str:
    cls = f" {esc(kind)}" if kind else ""
    tail = f"<em>{esc(note)}</em>" if note else ""
    return (f'<div class="stat"><span>{esc(label)}</span>'
            f'<b class="{cls.strip()}">{esc(value)}</b>{tail}</div>')


def kv(rows) -> str:
    """两列的「项 / 值」表（窄屏保持表格形态，不做堆叠 —— 它本来就只有两列）。"""
    body = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="kv"><tr><th>项</th><th>值</th></tr>{body}</table>'


def empty(text: str, action: str = "") -> str:
    """空状态：一句说明 + 一个下一步动作。**不要**用「（无）」代替这个函数。"""
    tail = f"<div>{action}</div>" if action else ""
    return f'<div class="empty"><p>{esc(text)}</p>{tail}</div>'


def grid_table(headers, rows, stack: bool = False) -> str:
    """标准表格。stack=True 时窄屏堆叠成卡片，每格必须带 data-label。

    rows 的每个 cell 是 `(标签, HTML)` 或裸 HTML 字符串。标签与单元格写在同一处，
    所以以后加一列不可能忘了配标签 —— `tests/test_portal.py` 的移动性守卫会盯着这点。
    """
    cls = ' class="stack"' if stack else ""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        tds = []
        for cell in row:
            label, value = cell if isinstance(cell, tuple) else ("", cell)
            attr = f' data-label="{html.escape(label, quote=True)}"' if label else ""
            tds.append(f"<td{attr}>{value}</td>")
        body.append("<tbody><tr>" + "".join(tds) + "</tr></tbody>")
    return f'<table{cls}><thead><tr>{head}</tr></thead>{"".join(body)}</table>'


def card(head: str, meta: str, body: str = "", *, level: str = "") -> str:
    """移动端卡片。level ∈ '' | warn | bad —— 颜色必须与同一行的状态徽章一致。"""
    cls = "card"
    if level:
        cls += " alert" + (" warn" if level == "warn" else "")
    return (f'<div class="{cls}"><div class="cardhead">{head}</div>'
            f'<div class="meta">{meta}</div>{body}</div>')


def sparkline(samples, kind: str = "accent", width: int = 92, height: int = 26) -> str:
    """延时/带宽走势小图。缺失样本（None）**断开线段**，不补 0。

    0 是合法的测量值（本地回环的延时可能真的是 0.x ms），用它冒充缺失样本
    属于编数据 —— 与采集器的诚实降级同一条纪律。
    """
    vals = list(samples)
    if not vals or all(v is None for v in vals):
        return '<span class="hint">—</span>'
    known = [v for v in vals if v is not None]
    lo, hi = min(known), max(known)
    span = (hi - lo) or 1.0
    step = width / max(1, len(vals) - 1)

    segments: list[list[str]] = []
    current: list[str] = []
    for i, v in enumerate(vals):
        if v is None:
            if len(current) > 1:
                segments.append(current)
            current = []
            continue
        x = round(i * step, 1)
        y = round(height - 3 - (v - lo) / span * (height - 6), 1)
        current.append(f"{x},{y}")
    if len(current) > 1:
        segments.append(current)

    lines = "".join(
        f'<polyline fill="none" stroke="var(--{esc(kind)})" stroke-width="1.5" '
        f'points="{" ".join(seg)}"/>' for seg in segments)
    return (f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-hidden="true">{lines}</svg>')


def toolbar(chips, search_html: str = "", right_html: str = "") -> str:
    """筛选 chip + 搜索框 + 右侧控件。chips: [(label, href, active, count|None)]。

    chip 一律渲染成真 `<a href>`：关掉 JS 时筛选照常工作。
    """
    out = []
    for label, href, active, count in chips:
        cur = ' aria-current="page"' if active else ""
        n = f' <span class="hint">{count}</span>' if count is not None else ""
        out.append(f'<a class="chip{" on" if active else ""}" href="{html.escape(href, quote=True)}"'
                   f'{cur}>{esc(label)}{n}</a>')
    return f'<div class="tools">{"".join(out)}{search_html}{right_html}</div>'


def copy_button(value: str, label: str = "复制") -> str:
    """一键复制。**值本身始终渲染在页面上**（关掉 JS 也能看见、手抄），
    按钮默认 hidden，由 admin.js 显示 —— 避免留下按了没反应的死按钮。"""
    return (f'<span class="copybar"><code>{esc(value)}</code>'
            f'<button type="button" data-copy="{html.escape(value, quote=True)}" hidden>'
            f'{esc(label)}</button></span>')


def confirm_form(action: str, fields: dict, label: str, *, csrf: str, title: str,
                 body: str, reason_label: str = "", kind: str = "dgr") -> str:
    """破坏性动作的**两阶段**表单（服务端确认，不依赖 JS 的 window.confirm）。

    阶段一：只提交 action + fields + csrf（不含 confirm）。
    阶段二：服务端返回本组件渲染的确认页；其中 `confirm=yes` + 理由 + 同一个 csrf，
            提交后才真正执行。JS 在时把它塞进 <dialog> 就地弹出；JS 关时它是一个
            普通页面。**两条路走同一段服务端代码**，所以不必为降级另写一套。
    """
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k, quote=True)}" '
        f'value="{html.escape(str(v), quote=True)}">' for k, v in fields.items())
    hidden += f'<input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}">'
    reason = (f'<label class="hint">{esc(reason_label)}<br>'
              f'<input name="reason" required maxlength="200" style="width:100%"></label>'
              if reason_label else "")
    return (f'<dialog open class="confirm" data-confirm-dialog>'
            f'<form method="post" action="{html.escape(action, quote=True)}">'
            f'{hidden}<input type="hidden" name="confirm" value="yes">'
            f'<h3>{esc(title)}</h3><p>{body}</p>{reason}'
            f'<div class="tools"><button class="{esc(kind)}">{esc(label)}</button>'
            f'<button type="button" data-dialog-close>取消</button></div>'
            f'</form></dialog>')


# ── 页面外壳 ────────────────────────────────────────────────────────────

#: 导航分组。顺序即侧栏顺序；tab=True 的项进手机底部标签栏。
NAV_GROUPS = (
    ("运维", (
        ("overview", "总览", "▤", False),
        ("instances", "实例", "▦", True),
        ("tunnel", "隧道", "⇅", True),
        ("system", "系统", "⚙", False),
    )),
    ("流程", (
        ("applications", "申请", "✉", True),
        ("audit", "审计", "🕘", False),
        ("clublog", "呼号库", "☰", False),
    )),
)

#: 徽标颜色：红＝要动手，黄＝要注意。键是视图 id。
BADGE_KIND = {"instances": "bad", "applications": "bad", "system": "warn"}

#: 顶栏中间的当前视图名（侧栏在手机上收进抽屉，顶栏要说明你在哪）。
TITLES = {"overview": "总览", "instances": "实例", "tunnel": "隧道", "system": "系统",
          "applications": "申请", "audit": "审计", "clublog": "呼号库",
          "instance": "实例详情"}


@dataclass(frozen=True)
class Nav:
    """导航状态。`root` 是浏览器可见的挂载前缀（'' 或 '/mrrc_portal'），
    所有链接都由它拼**绝对路径** —— 2026-10-05 的 `/admin/admin/login` 事故就是
    相对路径在 `/admin/login` 上被浏览器再拼一次造成的。"""
    view: str
    root: str
    badges: dict = field(default_factory=dict)
    user: str = ""
    csrf: str = ""
    live_seconds: int = 0


def _badge_html(vid: str, badges: dict) -> str:
    n = badges.get(vid) or 0
    if not n:
        return ""
    cls = "badge" + (" w" if BADGE_KIND.get(vid) == "warn" else "")
    return f'<span class="{cls}">{int(n)}</span>'


def _nav_links(nav: Nav) -> str:
    out = []
    for group, items in NAV_GROUPS:
        out.append(f'<div class="grp">{esc(group)}</div>')
        for vid, label, _icon, _tab in items:
            cur = ' aria-current="page"' if vid == nav.view else ""
            out.append(f'<a class="navlink" href="{nav.root}/admin?view={vid}"{cur}>'
                       f'<span>{esc(label)}</span>{_badge_html(vid, nav.badges)}</a>')
    return "".join(out)


def _tabbar(nav: Nav) -> str:
    out = []
    for vid, label, icon, tab in (i for g in NAV_GROUPS for i in g[1]):
        if not tab:
            continue
        cur = ' aria-current="page"' if vid == nav.view else ""
        dot = "<i></i>" if (nav.badges.get(vid) or 0) else ""
        out.append(f'<a href="{nav.root}/admin?view={vid}"{cur}>'
                   f'<b>{esc(icon)}{dot}</b>{esc(label)}</a>')
    cur = ' aria-current="page"' if nav.view in ("system", "audit", "clublog") else ""
    more = "<i></i>" if (nav.badges.get("system") or 0) else ""
    out.append(f'<a href="#" data-drawer{cur}><b>⋯{more}</b>更多</a>')
    return f'<nav class="tabbar">{"".join(out)}</nav>'


def page(title: str, body: str, nav: Nav | None = None, *, noindex: bool = False,
         fragment: bool = False, live: str = "", extra_head: str = "") -> str:
    """页面外壳。

    `nav is None` ⇒ 公开页形态（品牌头 + 页脚，无侧栏/底栏）。
    `fragment=True` ⇒ 只回正文（htmx 局部替换用；不含 html/head/style）。

    `live` 是自动刷新的数据区 HTML；它被放在**稳定的** aria-live 容器里，
    刷新的只是内层节点 —— 否则每次 outerHTML 替换都会让读屏漏播。
    """
    if fragment:
        return body + live
    robots = "<meta name=robots content=noindex>\n" if noindex else ""
    scripts = ""
    if nav is not None:
        scripts = (f'<script src="{nav.root}/admin/static/htmx.min.js" defer></script>'
                   f'<script src="{nav.root}/admin/static/admin.js" defer></script>')
    if nav is None:
        inner = ('<div class="publicwrap">'
                 '<header class="top"><a class="brand" href="/">📡 MRRC <em>Cloud Hub</em></a>'
                 '</header>'
                 f'<main class="content" id="content">{body}</main></div>')
    else:
        livewrap = f'<div class="livewrap" aria-live="polite">{live}</div>' if live else ""
        logout = ""
        if nav.user:
            logout = (f'<form method="post" action="{nav.root}/admin/logout" style="margin:0">'
                      f'<input type="hidden" name="csrf" value="{esc(nav.csrf)}">'
                      f'<button class="dgr">登出（{esc(nav.user)}）</button></form>')
        inner = (
            '<div class="shell">'
            f'<aside class="side" id="nav" data-tools>{_nav_links(nav)}'
            '<div class="sidefoot">呼号即身份 · 核验通过才授予</div></aside>'
            '<div class="main">'
            '<header class="top">'
            '<button type="button" class="only-mobile" data-drawer aria-label="打开导航">☰</button>'
            f'<span class="hint">{esc(TITLES.get(nav.view, ""))}</span>'
            '<span class="live"><span class="dot"></span>'
            f'<span data-live-status>实时 · {int(nav.live_seconds)} 秒前</span>'
            '<button type="button" data-pause hidden>暂停</button>'
            '<button type="button" data-reload>刷新</button>'
            f'{logout}</span></header>'
            f'<main class="content" id="content" tabindex="-1">{body}{livewrap}</main>'
            '</div></div>'
            f'{_tabbar(nav)}')
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="{TOKENS['bg']}">
{robots}<title>{esc(title)}</title>
<style>{CSS}</style>
{extra_head}
</head>
<body class="{'admin' if nav is not None else 'public'}">
<a class="skip" href="#content">跳到内容</a>
{inner}
{scripts}
</body>
</html>"""
