#!/usr/bin/env python3
"""portal/ui.py 的测试：令牌对比度、组件、页面外壳、静态资源与降级不变量。

运行：python3 tests/test_portal_ui.py   （也兼容 pytest）

重点守四件事：
 ① **对比度**：调色不许把弱文字调回不达 WCAG AA 的值（改版前的样张就是 3.31:1）
 ② **徽章必须带文字**：颜色不能单独承担状态信息
 ③ **静态资源是白名单精确匹配**：`..` 与未知名字一律 404
 ④ **降级**：导航与筛选都是真 <a href>，JS 只是锦上添花
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ── 令牌与样式表 ────────────────────────────────────────────────────────────

def test_tokens_meet_wcag_aa():
    """每个文字色对两种底色都要 ≥4.5:1。

    这条守卫是防"调色调回去"：改版前的样张用了 #5b6675（实测 3.31:1，不达 AA），
    而最接近的修复候选 #757f90 在卡片底色上只有 4.44:1。调色必须重新过这一关。
    """
    from portal.ui import TOKENS
    for name in ("tx", "tx2", "tx3", "accent", "ok", "warn", "bad"):
        fg = TOKENS[name]
        for bg_name in ("bg", "panel"):
            ratio = contrast(fg, TOKENS[bg_name])
            check(ratio >= 4.5,
                  f"令牌 --{name} on --{bg_name} 对比度 {ratio:.2f}:1，低于 AA 的 4.5:1")


def test_css_is_generated_from_tokens():
    """样式表由 TOKENS 生成 —— 改令牌必须真的进 CSS，不许两处各写一份。"""
    from portal.ui import CSS, TOKENS, stylesheet
    for name, value in TOKENS.items():
        check(f"--{name}:{value}" in CSS, f"CSS 里含 --{name}:{value}")
    check(stylesheet() == CSS, "stylesheet() 与 CSS 一致（单处定义）")


def test_css_keeps_the_guards_the_mobile_test_looks_for():
    """这些字符串是 test_portal.py::test_pages_are_mobile_suitable 在找的，改版时必须留下。"""
    from portal.ui import CSS
    for needle, why in (("@media(max-width:767px)", "窄屏断点"),
                        ("table.stack td::before", "堆叠后的小标题"),
                        ("content:attr(data-label)", "小标题取自 data-label"),
                        ("clip:rect(0 0 0 0)", "表头对读屏保留、只视觉隐藏"),
                        ("min-height:44px", "触摸目标 ≥44px"),
                        ("overflow-wrap:anywhere", "长串不撑破布局"),
                        (".pill.ok", "状态徽章类")):
        check(needle in CSS, f"CSS 含{why}（{needle}）")


# ── 组件 ───────────────────────────────────────────────────────────────────

def test_pill_carries_text_not_just_colour():
    """状态徽章必须带文字：颜色不能单独承担信息（色觉障碍）。"""
    from portal.ui import pill
    for kind in ("ok", "warn", "bad", "mute"):
        out = pill(kind, "服务中")
        check("服务中" in out, f"pill({kind}) 带文字")
        check(f"pill {kind}" in out, f"pill({kind}) 带类名")


def test_pill_escapes_text():
    from portal.ui import pill
    out = pill("ok", "<script>x</script>")
    check("<script>" not in out, "pill 里的文本被转义")


def test_banner_kinds():
    from portal.ui import banner
    for kind in ("info", "ok", "warn", "bad"):
        check(f"banner {kind}" in banner(kind, "x"), f"banner({kind}) 带类名")


def test_banner_passes_markup_through_by_contract():
    """`banner` 的第二参数叫 html_text：**调用方负责安全**，它不转义。

    这条测试把契约写死 —— banner 内部再 escape 一次会让调用方精心拼的
    `<b>` 显示成字面量，而那种 bug 在页面上很难一眼看出。
    """
    from portal.ui import banner
    out = banner("bad", "<b>要动手</b>")
    check("<b>要动手</b>" in out, "banner 原样保留调用方给的标记")
    check("&lt;b&gt;" not in out, "banner 没有二次转义")


def test_stat_renders_label_value_note():
    from portal.ui import stat
    out = stat("待你处理", "3", "申请等着核验", "warn")
    check("待你处理" in out and ">3<" in out and "申请等着核验" in out, "stat 三部分都在")
    check('class="warn"' in out, "stat 的数值带状态类")


def test_kv_is_a_two_column_table():
    from portal.ui import kv
    out = kv([("负载", "0.31"), ("磁盘", "已用 51%")])
    check(out.count("<tr>") == 3, f"kv = 表头 + 两行数据（得到 {out.count('<tr>')} 行）")
    check("负载" in out and "已用 51%" in out, "kv 内容都在")


def test_empty_gives_a_next_step():
    """空状态必须给"下一步做什么"，禁止裸的"（无）"。"""
    from portal.ui import empty
    out = empty("还没有已登记的实例", "<a href='/admin?view=applications'>去看申请</a>")
    check("还没有已登记的实例" in out, "空状态文案在")
    check("去看申请" in out, "空状态带下一步动作")


def test_grid_table_writes_data_labels_for_stacked_tables():
    """窄屏堆叠的小标题来自 data-label；漏一个，手机上那一格就静默变成没名字的一坨。"""
    from portal.ui import grid_table
    out = grid_table(["标签", "端口"], [[("标签", "bg1sb"), ("端口", "18804")]], stack=True)
    check('data-label="标签"' in out and 'data-label="端口"' in out, "每格都带 data-label")
    check('class="stack"' in out, "宽表挂 class=stack")


def test_grid_table_row_arity_matches_header():
    """行格数必须等于表头列数 —— 少了会在桌面上表现为一列没有行名的数字。"""
    from portal.ui import grid_table
    out = grid_table(["a", "b", "c"], [[("a", "1"), "2"]], stack=False)
    check(out.count("<td") == 2, "只写调用方给的格数")
    check('class="stack"' not in out, "stack=False 时不挂 stack 类")


def test_card_and_meta():
    from portal.ui import card
    out = card("<b>bg1sb</b>", "<span>18804</span>", "<small>名字相符</small>")
    check("cardhead" in out and "bg1sb" in out and "名字相符" in out, "卡片头/元信息/正文都在")


def test_card_alert_kinds():
    from portal.ui import card
    check("card alert" in card("h", "m", "b", level="bad"), "bad 级卡片带 alert")
    check("alert warn" in card("h", "m", "b", level="warn"), "warn 级卡片带 alert warn")
    check("alert" not in card("h", "m", "b"), "正常卡片不带 alert")


def test_sparkline_breaks_on_missing_samples():
    """样本缺失就断线 —— 不许补 0（0 ms 是合法测量值，用它冒充缺失是编数据）。"""
    from portal.ui import sparkline
    out = sparkline([10, 12, None, 14, 11])
    check(out.count("<polyline") >= 2, "缺失样本把线断成两段以上")
    check("0,0 0,0" not in out, "没有零长度伪线段")


def test_sparkline_empty_is_explicit():
    from portal.ui import sparkline
    out = sparkline([])
    check(out == "" or "—" in out, "无样本时给破折号，不给假线")


def test_toolbar_chips_are_real_links():
    """筛选 chip 必须是真 <a href>：关掉 JS 也要能用（降级硬要求）。"""
    from portal.ui import toolbar
    out = toolbar([("全部", "/admin?view=instances", True, 5),
                   ("异常", "/admin?view=instances&f=bad", False, 1)])
    check('href="/admin?view=instances"' in out, "chip 是真链接")
    check("aria-current" in out, "当前筛选带 aria-current")
    check(">5<" in out or "5</span>" in out, "chip 带计数")


def test_copy_renders_value_even_without_js():
    """复制按钮是 JS 便利品；关掉 JS 时值本身必须仍然看得见、抄得到。"""
    from portal.ui import copy_button
    out = copy_button("xK9-secret", "登记口令")
    check("xK9-secret" in out, "值在页面上")
    check("data-copy" in out, "带复制钩子")
    check("hidden" in out, "按钮默认隐藏，由 admin.js 显示（关掉 JS 不会留死按钮）")


def test_confirm_form_carries_csrf_and_reason():
    from portal.ui import confirm_form
    out = confirm_form("/admin/revoke", {"callsign": "bg1sb"}, "撤销入口", csrf="tok",
                       title="撤销 bg1sb 的入口？", body="注册表会少一行，访客立刻 502。",
                       reason_label="撤销原因")
    check('action="/admin/revoke"' in out, "指向正确路由")
    check('name="csrf" value="tok"' in out, "带 csrf")
    check('name="callsign" value="bg1sb"' in out, "带原字段")
    check('name="reason"' in out, "带理由输入")
    check('name="confirm" value="yes"' in out, "带二次确认标记")
    check("<dialog" in out, "用原生 dialog（JS 时弹出，JS 关时降级为页内表单）")


# ── 页面外壳 ───────────────────────────────────────────────────────────────

def test_shell_has_sidebar_tabbar_and_skip_link():
    from portal.ui import Nav, page
    nav = Nav(view="instances", root="", badges={"applications": 3, "instances": 1}, csrf="tok")
    out = page("MRRC Portal — 后台管理", "<h1>实例</h1>", nav=nav, noindex=True)
    check("viewport" in out, "有 viewport")
    check('class="side"' in out, "有侧栏")
    check('class="tabbar"' in out, "有底部标签栏")
    check('class="skip"' in out, "有跳到内容的链接")
    check('id="content"' in out, "有内容锚点")
    check("noindex" in out, "后台页带 noindex")
    check(out.count('aria-current="page"') == 2, "侧栏与底栏各恰一处当前页标记")
    # 注意用带引号的形式：内联 CSS 里的 `.navlink[aria-current=page]` 也会命中裸子串，
    # 数裸子串会把样式表算进来，于是“恰两处”变成永远不成立。
    check("3</span>" in out, "申请徽标渲染出待办数")


def test_shell_omits_badges_when_zero():
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="", badges={"applications": 0, "instances": 0}, csrf="tok")
    out = page("x", "y", nav=nav)
    check('class="badge' not in out, "0 的时候不出徽标（不制造噪音）")


def test_fragment_mode_has_no_html_shell():
    """片段响应不含 html/head/style —— 否则 htmx 会把整页塞进目标元素。"""
    from portal.ui import Nav, page
    nav = Nav(view="instances", root="", badges={}, csrf="tok")
    out = page("x", "<h1>实例</h1>", nav=nav, fragment=True)
    check("<html" not in out and "<head" not in out and "<style" not in out,
          "片段里没有 html/head/style")
    check("<h1>实例</h1>" in out, "片段里只有正文")


def test_public_shell_has_no_admin_chrome():
    """公开注册页不该出现侧栏 —— 它是给陌生人的，不是运维台。"""
    from portal.ui import page
    out = page("MRRC Cloud Hub — 呼号自助注册", "<h1>呼号自助注册</h1>")
    check('class="side"' not in out, "公开页没有侧栏")
    check('class="tabbar"' not in out, "公开页没有底部标签栏")
    check("呼号自助注册" in out, "正文在")
    check("body class=\"public\"" in out or "class=\"public\"" in out, "公开页用 public 形态")


def test_admin_shell_loads_js_as_file_not_inline():
    """JS 走文件、不内联 —— 将来上 CSP 时 script-src 'self' 才能直接可用。"""
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="", badges={}, csrf="tok")
    out = page("x", "y", nav=nav)
    check("<script src=" in out, "外链 admin.js")
    check("htmx.min.js" in out, "外链 htmx")
    check("<script>" not in out, "没有内联 script 块")


def test_every_admin_link_is_a_real_href():
    """降级硬要求：所有导航都是 <a href>，不是 hx-get-only 的按钮。"""
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="", badges={}, csrf="tok")
    out = page("x", "y", nav=nav)
    for vid in ("overview", "applications", "instances", "tunnel", "system", "audit", "clublog"):
        check(f'href="/admin?view={vid}"' in out, f"导航含 {vid} 的真实 href")


def test_root_prefix_is_honoured_everywhere():
    """挂载前缀（'' 或 '/mrrc_portal'）必须出现在**每一个**链接与脚本地址上。

    2026-10-05 的现场事故就是相对路径在 /admin/login 上被浏览器再拼一次，
    变成 /admin/admin/login。所以这里逐个检查绝对路径。
    """
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="/mrrc_portal", badges={}, csrf="tok", user="ops")
    out = page("x", "y", nav=nav)
    check('href="/mrrc_portal/admin?view=instances"' in out, "导航带前缀")
    check("/mrrc_portal/admin/static/htmx.min.js" in out, "脚本地址带前缀")
    check('action="/mrrc_portal/admin/logout"' in out, "登出表单带前缀")
    check('href="/admin?view=' not in out.replace("/mrrc_portal/admin?view=", ""),
          "没有漏掉前缀的裸 /admin 链接")


# ── 静态资源 ───────────────────────────────────────────────────────────────

def test_vendored_assets_match_manifest():
    """vendored 文件必须与 manifest 里的 sha256 一致。

    同 website/css/octen.css 的纪律：上游文件逐字节冻结、哈希可核对。手改或版本漂移
    会立刻变红，而不是等到线上表现奇怪才发现。
    """
    import hashlib
    import json
    from portal.ui import STATIC_DIR
    manifest = json.loads((STATIC_DIR / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = STATIC_DIR / item["name"]
        check(path.exists(), f"{item['name']} 存在")
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        check(digest == item["sha256"],
              f"{item['name']} 的 sha256 与 manifest 一致（期望 {item['sha256'][:12]}…，"
              f"实得 {digest[:12]}…）")
        check(path.stat().st_size == item["bytes"], f"{item['name']} 字节数与 manifest 一致")


def test_static_whitelist_rejects_traversal_and_unknown():
    """静态路由是**白名单精确匹配**，绝不做路径拼接。

    `/admin/static/../portal/app.py` 必须 404 —— 用原始 http.client 发字面路径，
    因为 urllib 会在客户端先把 `..` 规范化掉，测不到真正的攻击面。
    """
    import http.client
    import tempfile
    import threading
    from http.server import ThreadingHTTPServer
    from portal import htpasswd as ht
    from portal import registry as reg
    from portal.app import Portal, make_handler
    from portal.store import Store
    from portal.verify import CallsignListVerifier

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
        (tmp / "instances.tsv").write_text("bg1sb\t18802\n", encoding="utf-8")
        users = tmp / "portal-users"
        users.write_text("ops:" + ht.apr1("pw-123456789", "saltward") + "\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            portal, token="tok", users=ht.UsersFile(users)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        try:
            for path, want in (("/admin/static/htmx.min.js", 200),
                               ("/admin/static/../portal/app.py", 404),
                               ("/admin/static/portal/app.py", 404),
                               ("/admin/static/nope.js", 404),
                               ("/admin/static/", 404)):
                conn.request("GET", path)
                r = conn.getresponse()
                r.read()
                check(r.status == want, f"GET {path} → {want}（得到 {r.status}）")
            conn.request("GET", "/admin/static/htmx.min.js")
            r = conn.getresponse()
            r.read()
            cc = r.getheader("Cache-Control") or ""
            check("immutable" in cc, "静态资源带 immutable 缓存")
            check((r.getheader("Content-Type") or "").startswith("application/javascript"),
                  "htmx 的 Content-Type 正确")
            check(r.getheader("X-Content-Type-Options") == "nosniff", "带 nosniff")
            conn.request("POST", "/admin/static/htmx.min.js")
            r = conn.getresponse()
            r.read()
            check(r.status in (404, 405), f"静态资源不接 POST（得到 {r.status}）")
        finally:
            httpd.shutdown()


def test_admin_js_exposes_the_guards_the_pages_rely_on():
    """页面上的 hx-trigger 条件引用了 admin.js 提供的全局函数；名字对不上，
    自动刷新就会静默失效（不会报错，只是永远不刷）。"""
    from portal.ui import STATIC_DIR
    js = (STATIC_DIR / "admin.js").read_text(encoding="utf-8")
    for needle, why in (("__portalPaused", "自动刷新条件"),
                        ("data-pause", "暂停按钮"),
                        ("data-copy", "一键复制"),
                        ("data-confirm-dialog", "确认弹窗"),
                        ("data-drawer", "手机抽屉"),
                        ("visibilitychange", "切到后台即停")):
        check(needle in js, f"admin.js 里有{why}（{needle}）")
    check("window.confirm" not in js, "不用 window.confirm（我们要可填理由的 dialog）")


# ── 视图层的纯度 ───────────────────────────────────────────────────────────

def test_views_layer_is_pure():
    """views.py 不许自己采集事实 —— 出现 subprocess/socket/文件读取就说明边界破了。"""
    import ast
    src = ROOT / "portal" / "views.py"
    check(src.exists(), "views.py 存在")
    if not src.exists():
        return
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned = {"subprocess", "socket", "ssl", "shutil", "urllib", "http"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                check(a.name.split(".")[0] not in banned, f"views.py 不许 import {a.name}")
        if isinstance(node, ast.ImportFrom):
            check((node.module or "").split(".")[0] not in banned,
                  f"views.py 不许 from {node.module} import")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            check(node.func.id not in ("open", "exec", "eval"),
                  f"views.py 不许调用 {node.func.id}()")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ ui 测试通过（{len(tests)} 组）：令牌对比度/组件/外壳/静态白名单/降级/视图层纯度")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
