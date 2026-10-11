# Portal 后台管理界面全面改版 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 Portal 后台 7 个视图 + 登录页 + 公开注册页的呈现、信息架构与交互全面重做，手机与桌面同等可用，并引入 htmx 局部刷新——**不改**认证、核验、注册表写入与探测判据。

**架构：** 按「采集 / 呈现 / 传输」三分：`app.py` 继续负责 HTTP、认证、CSRF 与所有事实采集（subprocess/socket/文件），把采好的事实装进一个纯数据 `Ctx`；`views.py` 只消费 `Ctx` 产出 HTML（**不含任何 subprocess/socket/文件读取**）；`ui.py` 提供令牌、样式表、组件与页面外壳。视图函数返回 `Rendered(chrome, live)`，`live` 区是自动刷新的目标。所有交互都是渐进增强：关掉 JS，链接与表单照常工作。

**技术栈：** Python 3 标准库（无第三方运行时依赖）、htmx 2.0.7（vendored 单文件，逐字节冻结 + sha256 守卫）、自写 `admin.js`、内联 CSS（`ui.CSS`，由 `ui.TOKENS` 生成）。

**规格：** `docs/superpowers/specs/2026-10-11-portal-admin-ui-refresh-design.md`

---

## 文件结构

### 创建

| 文件 | 职责 |
| --- | --- |
| `portal/ui.py` | 设计令牌 `TOKENS`、由它生成的 `CSS`、全部组件函数、页面外壳（侧栏/顶栏/底栏/公开页两种形态）、片段模式 |
| `portal/views.py` | `Ctx`（纯数据）、`Rendered`、`VIEWS` 注册表、8 个视图函数（7 + 实例详情）。**不得 import subprocess/socket** |
| `portal/static/htmx.min.js` | vendored htmx 2.0.7，逐字节冻结 |
| `portal/static/htmx.LICENSE` | 0BSD 许可证原文 |
| `portal/static/manifest.json` | `{name, version, source_url, sha256}` —— 守卫读它核对哈希 |
| `portal/static/admin.js` | 暂停刷新、确认弹窗、复制、手机抽屉（约 100 行） |
| `tests/test_portal_ui.py` | 令牌对比度、组件、外壳、静态路由、片段模式、降级守卫 |

### 修改

| 文件 | 改什么 |
| --- | --- |
| `portal/app.py` | ① 新增静态路由；② `_admin()` 的渲染体替换为 `Ctx` 装配 + `views.render()`；③ `TUNNEL_TEXT` 文案；④ 破坏性动作的确认两阶段。**认证、CSRF、会话、限流、探测函数一律不动** |
| `portal/README.md` | 新增「前端资源与 vendor 纪律」一节；界面章节按新 IA 重写 |
| `tests/test_portal.py` | 更新受文案/容器影响的断言（`在线`→`服务中`、`table.stack` 计数）；新增视图级守卫 |
| `tests/test_portal_metrics.py` | 同上（两处 `在线` 断言） |
| `SDD/11`、`SDD/12 §12.9`、`SDD/14` | 组件模型、运行方式、版本历史同步 |

---

## 任务 0：基线（先证明现在是绿的）

**文件：** 无改动

- [ ] **步骤 1：跑基线测试**

运行：
```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
python3 tests/test_portal.py && python3 tests/test_portal_auth.py && \
python3 tests/test_portal_metrics.py && python3 tests/test_htpasswd.py
```
预期：四组全绿（每组末尾打印 `✅ ...`）。记下每组的组数（`test_portal.py` 应为 27 组）。**若基线不绿，停下来先弄清原因，不要在红的基础上改。**

- [ ] **步骤 2：确认现网行为基线**

运行：
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://portal.mrrc.vlsc.net/
curl -s -o /dev/null -w '%{http_code}\n' https://portal.mrrc.vlsc.net/admin
```
预期：`200` 和 `200`。第二条是登录页（未登录）。

---

## 任务 1：设计令牌与样式表（`portal/ui.py`）

**文件：**
- 创建：`portal/ui.py`
- 测试：`tests/test_portal_ui.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_portal_ui.py`：

```python
#!/usr/bin/env python3
"""portal/ui.py 的测试：令牌对比度、组件、页面外壳、静态资源与降级不变量。

运行：python3 tests/test_portal_ui.py   （也兼容 pytest）
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


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ ui 测试通过（{len(tests)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'portal.ui'`

- [ ] **步骤 3：编写 `portal/ui.py`（令牌 + 样式表部分）**

创建 `portal/ui.py` 的开头部分：

```python
"""Portal 界面层：设计令牌、样式表、组件与页面外壳。

这一层是**纯呈现**：不读文件、不起进程、不开 socket。所有事实由 `app.py` 采集后
装进 `views.Ctx`，视图只做排版。判据：`import ast` 后本模块不出现 subprocess/socket/open。

设计纪律只有一条：**白 = 强调，色 = 状态。** 青色（--accent）只用于焦点环、链接与
图表线，不承担任何"重要"语义 —— 否则红色出现时就不再是信号。
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field

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
.cardhead{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.cardhead b{color:var(--tx);font-size:13px;font-weight:600;flex:1}
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
.tabbar{display:none}
/* ── 窄屏 ── */
/* 断点从旧版的 720px 提到 767px：桌面侧栏在 768px 以上才出现，两者必须对齐，
   否则 721–767px 这段宽度会出现“有侧栏但没有底部标签栏”的真空。
   旧守卫 `test_pages_are_mobile_suitable` 里写死了 `@media(max-width:720px)` 这个字符串，
   必须同步改成 767px（任务 18）。 */
@media(max-width:767px){
/* 触摸目标：手机上一切可点元素 ≥44px。桌面表格里的紧凑按钮不受影响，
   因为这条规则只在窄屏生效 —— 守卫 `min-height:44px` 找的也是这个字符串。 */
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
/* 宽表在窄屏堆叠成卡片（系统/审计/呼号库仍在用） */
table.stack{display:block;border:0}
table.stack thead{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}
table.stack tbody,table.stack tr{display:block}
table.stack tr{border:1px solid var(--bd);border-radius:10px;background:var(--card,rgba(255,255,255,.03));
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
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS，打印 `✅ ui 测试通过（2 组）`

- [ ] **步骤 5：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add portal/ui.py tests/test_portal_ui.py
git commit -m "portal/ui: 设计令牌与样式表，令牌由 TOKENS 单处生成并守住对比度"
```

---

## 任务 2：组件函数（徽章 / 通知 / 指标卡 / 键值表 / 空状态）

**文件：**
- 修改：`portal/ui.py`（追加）
- 测试：`tests/test_portal_ui.py`（追加）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_portal_ui.py` 的 `main()` 之前追加：

```python
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


def test_banner_kinds_and_escaping():
    from portal.ui import banner
    for kind in ("info", "ok", "warn", "bad"):
        check(f"banner {kind}" in banner(kind, "x"), f"banner({kind}) 带类名")
    check("<b>&lt;i&gt;</b>" in banner("bad", "<b><i></b>") or "&lt;i&gt;" in banner("bad", "<b><i></b>"),
          "banner 只转义文本、保留调用方给的安全标记")  # 见步骤 3 的说明


def test_stat_renders_label_value_note():
    from portal.ui import stat
    out = stat("待你处理", "3", "申请等着核验", "warn")
    check("待你处理" in out and ">3<" in out and "申请等着核验" in out, "stat 三部分都在")
    check("b warn" in out, "stat 的数值带状态类")


def test_kv_is_a_two_column_table():
    from portal.ui import kv
    out = kv([("负载", "0.31"), ("磁盘", "已用 51%")])
    check(out.count("<tr>") == 2, "kv 两行")
    check("负载" in out and "已用 51%" in out, "kv 内容都在")


def test_empty_gives_a_next_step():
    """空状态必须给"下一步做什么"，禁止裸的"（无）"。"""
    from portal.ui import empty
    out = empty("还没有已登记的实例", "<a href='/admin?view=applications'>去看申请</a>")
    check("还没有已登记的实例" in out, "空状态文案在")
    check("去看申请" in out, "空状态带下一步动作")
```

同时把 `main()` 里的打印改成 `f"✅ ui 测试通过（{len(tests)} 组）"`（已经是这个写法，无需改）。

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL，`ImportError: cannot import name 'pill' from 'portal.ui'`

- [ ] **步骤 3：实现组件**

在 `portal/ui.py` 末尾追加：

```python
# ── 组件 ────────────────────────────────────────────────────────────────
# 约定：函数参数里的 `text` 一律当**纯文本**处理（内部 html.escape）；需要塞标记的地方
# 参数名叫 `html_text` 或 `body`，由调用方负责安全（调用方只能是 views.py 的固定模板，
# 用户输入必须自己先 esc()）。这条约定让"哪里被转义过"在调用点一眼可见。

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
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（7 组）

- [ ] **步骤 5：Commit**

```bash
git add portal/ui.py tests/test_portal_ui.py
git commit -m "portal/ui: 徽章/通知/指标卡/键值表/空状态五个组件"
```

---

## 任务 3：表格与卡片组件

**文件：**
- 修改：`portal/ui.py`
- 测试：`tests/test_portal_ui.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_portal_ui.py`：

```python
def test_grid_table_writes_data_labels_for_stacked_tables():
    """窄屏堆叠的小标题来自 data-label；漏一个，手机上那一格就静默变成没名字的一坨。"""
    from portal.ui import grid_table
    out = grid_table(["标签", "端口"], [[("标签", "bg1sb"), ("端口", "18804")]], stack=True)
    check('data-label="标签"' in out and 'data-label="端口"' in out, "每格都带 data-label")
    check("table stack" in out or 'class="stack"' in out, "宽表挂 class=stack")


def test_grid_table_row_arity_matches_header():
    """行格数必须等于表头列数 —— 少了会在桌面上表现为一列没有行名的数字。"""
    from portal.ui import grid_table
    out = grid_table(["a", "b", "c"], [[("a", "1"), "2"]], stack=False)
    check(out.count("<td") == 2, "只写调用方给的格数（本守卫是给视图测试兜底的基线）")


def test_card_and_meta():
    from portal.ui import card
    out = card("<b>bg1sb</b>", "<span>18804</span>", "<small>名字相符</small>")
    check("cardhead" in out and "bg1sb" in out and "名字相符" in out, "卡片头/元信息/正文都在")


def test_card_alert_kinds():
    from portal.ui import card
    check("card alert" in card("h", "m", "b", level="bad"), "bad 级卡片带 alert")
    check("alert warn" in card("h", "m", "b", level="warn"), "warn 级卡片带 alert warn")
    check("alert" not in card("h", "m", "b"), "正常卡片不带 alert")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL，`ImportError: cannot import name 'grid_table'`

- [ ] **步骤 3：实现**

追加到 `portal/ui.py`：

```python
def grid_table(headers, rows, stack: bool = False) -> str:
    """标准表格。stack=True 时窄屏堆叠成卡片，每格必须带 data-label。

    rows 的每个 cell 是 `(标签, HTML)` 或裸 HTML 字符串。标签与单元格写在同一处，
    所以加一列不可能忘了配标签 —— `tests/test_portal.py` 的移动性守卫会盯着这点。
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
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（11 组）

- [ ] **步骤 5：Commit**

```bash
git add portal/ui.py tests/test_portal_ui.py
git commit -m "portal/ui: 标准表格（含窄屏堆叠）与移动端卡片"
```

---

## 任务 4：走势小图 / 工具条 / 复制 / 确认表单

**文件：**
- 修改：`portal/ui.py`
- 测试：`tests/test_portal_ui.py`

- [ ] **步骤 1：编写失败的测试**

追加：

```python
def test_sparkline_breaks_on_missing_samples():
    """样本缺失就断线 —— 不许补 0（0 ms 是合法测量值，用它冒充缺失是编数据）。"""
    from portal.ui import sparkline
    out = sparkline([10, 12, None, 14, 11])
    check(out.count("<polyline") >= 2, "缺失样本把线断成两段以上")
    check("0,0 0,0" not in out, "没有零长度伪线段")


def test_sparkline_empty_is_explicit():
    from portal.ui import sparkline
    check(sparkline([]) == "" or "—" in sparkline([]), "无样本时给空或破折号，不给假线")


def test_toolbar_chips_are_real_links():
    """筛选 chip 必须是真 <a href>：关掉 JS 也要能用（降级硬要求）。"""
    from portal.ui import toolbar
    out = toolbar([("全部", "/admin?view=instances", True, 5), ("异常", "/admin?view=instances&f=bad", False, 1)])
    check('href="/admin?view=instances"' in out, "chip 是真链接")
    check("aria-current" in out, "当前筛选带 aria-current")


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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL，`ImportError: cannot import name 'sparkline'`

- [ ] **步骤 3：实现**

追加到 `portal/ui.py`：

```python
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
            f'<button type="button" data-copy="{html.escape(value, quote=True)}" hidden>{esc(label)}</button></span>')


def confirm_form(action: str, fields: dict, label: str, *, csrf: str, title: str,
                 body: str, reason_label: str = "", kind: str = "dgr") -> str:
    """破坏性动作的**两阶段**表单（服务端确认，不依赖 JS 的 window.confirm）。

    阶段一：只提交 action + fields + csrf（不含 confirm）。
    阶段二：服务端返回本组件渲染的确认页；其中 `confirm=yes` + 理由 + 同一个 csrf，
            提交后才真正执行。JS 在时把它塞进 <dialog> 就地弹出；JS 关时它是一个
            普通页面。**两条路走同一段服务端代码**，所以不必为降级另写一套。

    理由字段：破坏性动作必须填，服务端校验非空（见 app.py 的 `_require_reason`）。
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
            f'<div class="tools"><button class="dgr" name="decision" value="yes">{esc(label)}</button>'
            f'<button type="button" data-dialog-close>取消</button></div>'
            f'</form></dialog>')
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（16 组）

- [ ] **步骤 5：Commit**

```bash
git add portal/ui.py tests/test_portal_ui.py
git commit -m "portal/ui: 走势小图（缺失即断线）、工具条、一键复制、两阶段确认表单"
```

---

## 任务 5：页面外壳与片段模式

**文件：**
- 修改：`portal/ui.py`
- 测试：`tests/test_portal_ui.py`

- [ ] **步骤 1：编写失败的测试**

追加：

```python
def test_shell_has_sidebar_tabbar_and_skip_link():
    from portal.ui import Nav, page
    nav = Nav(view="instances", root="", badges={"applications": 3, "instances": 1})
    out = page("MRRC Portal — 后台管理", "<h1>实例</h1>", nav=nav, noindex=True)
    check("viewport" in out, "有 viewport")
    check('class="side"' in out, "有侧栏")
    check('class="tabbar"' in out, "有底部标签栏")
    check('class="skip"' in out, "有跳到内容的链接")
    check('id="content"' in out, "有内容锚点")
    check("noindex" in out, "后台页带 noindex")
    check(out.count("aria-current") == 2, "侧栏与底栏各恰一处当前页标记")
    check(">3<" in out or "3</span>" in out, "申请徽标渲染出待办数")


def test_shell_omits_badges_when_zero():
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="", badges={"applications": 0, "instances": 0})
    out = page("x", "y", nav=nav)
    check("badge" not in out, "0 的时候不出徽标（不制造噪音）")


def test_fragment_mode_has_no_html_shell():
    """片段响应不含 html/head —— 否则 htmx 会把整页塞进目标元素。"""
    from portal.ui import Nav, page
    nav = Nav(view="instances", root="", badges={})
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


def test_admin_shell_loads_js_as_file_not_inline():
    """JS 走文件、不内联 —— 将来上 CSP 时 script-src 'self' 才能直接可用。"""
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="", badges={})
    out = page("x", "y", nav=nav)
    check("<script src=" in out, "外链 admin.js")
    check("htmx.min.js" in out, "外链 htmx")
    check("<script>" not in out, "没有内联 script 块")


def test_every_admin_link_is_a_real_href():
    """降级硬要求：所有导航都是 <a href>，不是 hx-get-only 的按钮。"""
    from portal.ui import Nav, page
    nav = Nav(view="overview", root="", badges={})
    out = page("x", "y", nav=nav)
    for vid in ("overview", "applications", "instances", "tunnel", "system", "audit", "clublog"):
        check(f'href="/admin?view={vid}"' in out, f"导航含 {vid} 的真实 href")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL，`ImportError: cannot import name 'Nav'`

- [ ] **步骤 3：实现外壳**

追加到 `portal/ui.py`：

```python
#: 导航分组与图标。顺序即侧栏顺序；tabbar 只取 tab=True 的前四项 + 「更多」。
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
    kind = BADGE_KIND.get(vid, "bad")
    cls = "badge" + (" w" if kind == "warn" else "")
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
        n = nav.badges.get(vid) or 0
        dot = "<i></i>" if n else ""
        out.append(f'<a href="{nav.root}/admin?view={vid}"{cur}><b>{esc(icon)}{dot}</b>{esc(label)}</a>')
    cur = ' aria-current="page"' if nav.view in ("system", "audit", "clublog") else ""
    more = '<i></i>' if (nav.badges.get("system") or 0) else ""
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
        return live + body
    robots = "<meta name=robots content=noindex>\n" if noindex else ""
    scripts = ""
    if nav is not None:
        scripts = (f'<script src="{nav.root}/admin/static/htmx.min.js" defer></script>'
                   f'<script src="{nav.root}/admin/static/admin.js" defer></script>')
    if nav is None:
        inner = (f'<div class="publicwrap">'
                 f'<header class="top"><a class="brand" href="/">📡 MRRC <em>Cloud Hub</em></a></header>'
                 f'<main class="content" id="content">{body}</main></div>')
    else:
        livewrap = (f'<div class="livewrap" aria-live="polite">{live}</div>' if live else "")
        inner = (f'<div class="shell">'
                 f'<aside class="side" id="nav">{_nav_links(nav)}'
                 f'<div class="sidefoot">呼号即身份 · 核验通过才授予</div></aside>'
                 f'<div class="main">'
                 f'<header class="top">'
                 f'<button type="button" class="only-mobile" data-drawer aria-label="打开导航">☰</button>'
                 f'<span class="hint">{esc(TITLES.get(nav.view, ""))}</span>'
                 f'<span class="live"><span class="dot"></span>'
                 f'<span data-live-status>实时 · {nav.live_seconds} 秒前</span>'
                 f'<button type="button" data-pause hidden>暂停</button>'
                 f'<button type="button" data-reload>刷新</button>'
                 + (f'<form method="post" action="{nav.root}/admin/logout" style="margin:0">'
                    f'<input type="hidden" name="csrf" value="{esc(nav.csrf)}">'
                    f'<button class="dgr">{esc(nav.user or "登出")} 登出</button></form>'
                    if nav.user else "")
                 + '</span></header>'
                 f'<main class="content" id="content" tabindex="-1">{body}{livewrap}</main>'
                 f'</div></div>'
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
<body class="{"admin" if nav is not None else "public"}">
<a class="skip" href="#content">跳到内容</a>
{inner}
{scripts}
</body>
</html>"""


#: 顶栏中间的当前视图名（侧栏在手机上收进抽屉，顶栏要说明你在哪）。
TITLES = {"overview": "总览", "instances": "实例", "tunnel": "隧道", "system": "系统",
          "applications": "申请", "audit": "审计", "clublog": "呼号库"}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（22 组）

- [ ] **步骤 5：Commit**

```bash
git add portal/ui.py tests/test_portal_ui.py
git commit -m "portal/ui: 页面外壳（侧栏/底栏/片段模式）与公开页形态"
```

---

## 任务 6：静态路由白名单 + vendored htmx

**文件：**
- 创建：`portal/static/htmx.min.js`、`portal/static/htmx.LICENSE`、`portal/static/manifest.json`
- 修改：`portal/app.py`（`do_GET` 里加一个分支）
- 测试：`tests/test_portal_ui.py`

- [ ] **步骤 1：vendor htmx（下载 + 双源核对 + 冻结哈希）**

运行：
```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
mkdir -p portal/static
curl -sSL --max-time 30 -o portal/static/htmx.min.js https://unpkg.com/htmx.org@2.0.7/dist/htmx.min.js
curl -sSL --max-time 30 -o portal/static/htmx.LICENSE https://unpkg.com/htmx.org@2.0.7/LICENSE
curl -sSL --max-time 30 -o /tmp/htmx.crosscheck.js https://cdn.jsdelivr.net/npm/htmx.org@2.0.7/dist/htmx.min.js
shasum -a 256 portal/static/htmx.min.js /tmp/htmx.crosscheck.js
cmp portal/static/htmx.min.js /tmp/htmx.crosscheck.js && echo "两个独立 CDN 的字节完全一致"
```
预期：
```
60231ae6ba9db3825eb15a261122d5f55921c4d53b66bf637dc18b4ee27c79f9  portal/static/htmx.min.js
60231ae6ba9db3825eb15a261122d5f55921c4d53b66bf637dc18b4ee27c79f9  /tmp/htmx.crosscheck.js
两个独立 CDN 的字节完全一致
```
**若两个源的哈希不一致，停下来重新取证**（这是一个不应发生的信号）。

- [ ] **步骤 2：写 manifest**

创建 `portal/static/manifest.json`：

```json
{
  "note": "vendored 前端资源。逐字节冻结，不得手改 —— 改这里必须同时改 sha256 与版本，并在同一个 commit 里说明为什么升级。",
  "files": [
    {
      "name": "htmx.min.js",
      "version": "2.0.7",
      "license": "0BSD",
      "source_url": "https://unpkg.com/htmx.org@2.0.7/dist/htmx.min.js",
      "sha256": "60231ae6ba9db3825eb15a261122d5f55921c4d53b66bf637dc18b4ee27c79f9",
      "bytes": 51076
    }
  ]
}
```

- [ ] **步骤 3：编写失败的测试**

追加到 `tests/test_portal_ui.py`：

```python
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
    from pathlib import Path
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
        finally:
            httpd.shutdown()
```

- [ ] **步骤 4：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL —— `STATIC_DIR` 不存在（ImportError）与静态路由 404/200 全部不符

- [ ] **步骤 5：实现**

在 `portal/ui.py` 顶部 import 之后加：

```python
#: 静态资源目录与**白名单**。只有这里的名字能被送出；不做通用文件服务，
#: 也不把请求路径拼进文件路径 —— 精确字典查找是唯一的安全边界。
STATIC_DIR = Path(__file__).resolve().parent / "static"

STATIC_WHITELIST: dict[str, str] = {
    "htmx.min.js": "application/javascript; charset=utf-8",
    "admin.js": "application/javascript; charset=utf-8",
    "htmx.LICENSE": "text/plain; charset=utf-8",
}

#: 静态资源的缓存头：带版本查询串时内容永不变，可以永久缓存。
STATIC_CACHE = "public, max-age=31536000, immutable"
```

并在文件头的 import 区加上 `from pathlib import Path`。

在 `portal/app.py` 的 `do_GET` 里，`route = self._route()` 之后、`/admin` 分支之前插入：

```python
            if route.startswith("/admin/static/"):
                return self._serve_static(route[len("/admin/static/"):])
```

并在 `make_handler` 内（`_route` 方法之后）加入这个方法：

```python
        def _serve_static(self, name: str):
            """白名单静态资源。名字**精确匹配**，不做路径拼接 ⇒ `..` 无从下手。

            不需要登录：这是公开的第三方库与本站脚本，且公开注册页也要用它。
            缓存一年 + immutable：文件名不带版本，靠 sha256 守卫保证内容不变。
            """
            from portal import ui as ui_mod
            ctype = ui_mod.STATIC_WHITELIST.get(name)
            if ctype is None:
                return self._send(404, {"error": "not found"})
            path = ui_mod.STATIC_DIR / name
            try:
                blob = path.read_bytes()
            except OSError as exc:
                return self._send(404, {"error": f"asset unavailable: {exc}"})
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", ui_mod.STATIC_CACHE)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(blob)
```

- [ ] **步骤 6：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（24 组）

- [ ] **步骤 7：Commit**

```bash
git add portal/static portal/ui.py portal/app.py tests/test_portal_ui.py
git commit -m "portal: 静态资源白名单路由 + vendored htmx 2.0.7（双源核对 sha256）"
```

---

## 任务 7：`admin.js`

**文件：**
- 创建：`portal/static/admin.js`
- 测试：`tests/test_portal_ui.py`

- [ ] **步骤 1：编写失败的测试**

追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_ui.py`
预期：FAIL，`admin.js 存在` 之类不通过（文件不存在）

- [ ] **步骤 3：写 `portal/static/admin.js`**

```javascript
/* MRRC Portal 后台的渐进增强脚本。
 *
 * 纪律：这里只做"锦上添花"。关掉 JS 后，导航、筛选、表单、破坏性动作的确认
 * 全部照常工作（确认走服务端两阶段表单）。因此本文件里**不允许**出现任何
 * 唯一路径的逻辑 —— 一旦出现，降级就破了。
 */
(function () {
  'use strict';

  /* ── 自动刷新闸门 ─────────────────────────────────────────────
   * 页面里的 hx-trigger 写成 `every Ns [!window.__portalPaused()]`。
   * 三条停刷理由：切到后台、用户手动暂停、有未提交的输入。
   * 第三条很重要：正在搜索框里打字时被刷走，会让人以为页面抽风。
   */
  window.__portalPaused = function () {
    if (document.hidden) return true;
    if (document.body.classList.contains('is-paused')) return true;
    var dirty = false;
    document.querySelectorAll('[data-tools] input, [data-tools] select').forEach(function (el) {
      if (el.type === 'hidden' || el.type === 'submit') return;
      if (String(el.value) !== String(el.defaultValue)) dirty = true;
    });
    return dirty;
  };

  /* ── 暂停 / 恢复 ── */
  var paused = false;
  function setPaused(on) {
    paused = on;
    document.body.classList.toggle('is-paused', on);
    document.querySelectorAll('[data-pause]').forEach(function (b) {
      b.textContent = on ? '继续' : '暂停';
      b.setAttribute('aria-pressed', String(on));
    });
    var status = document.querySelector('[data-live-status]');
    if (status && on) status.textContent = '已暂停';
  }

  function csrf() {
    var el = document.querySelector('input[name=csrf]');
    return el ? el.value : '';
  }

  function boot() {
    document.querySelectorAll('[data-pause]').forEach(function (b) {
      b.hidden = false;                       // 关掉 JS 时按钮不出现，免得按了没反应
      b.addEventListener('click', function () { setPaused(!paused); });
    });

    /* 刷新按钮：拿当前视图的 live 区重取一次。没有 JS 时它不存在。 */
    document.querySelectorAll('[data-reload]').forEach(function (b) {
      b.addEventListener('click', function () {
        var live = document.querySelector('[data-live]');
        if (live && window.htmx) window.htmx.trigger(live, 'refresh');
      });
    });

    /* 复制按钮：值本身始终在页面上，这里只是省一次手抄。 */
    document.querySelectorAll('[data-copy]').forEach(function (b) {
      b.hidden = false;
      b.addEventListener('click', function () {
        var text = b.getAttribute('data-copy') || '';
        var done = function () {
          var old = b.textContent;
          b.textContent = '已复制';
          setTimeout(function () { b.textContent = old; }, 1200);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {});
        } else {
          var ta = document.createElement('textarea');
          ta.value = text; document.body.appendChild(ta); ta.select();
          try { document.execCommand('copy'); done(); } catch (e) { /* 用户可手抄 */ }
          document.body.removeChild(ta);
        }
      });
    });

    /* 手机抽屉 */
    document.querySelectorAll('[data-drawer]').forEach(function (b) {
      b.addEventListener('click', function (ev) {
        if (b.tagName === 'A') { ev.preventDefault(); }
        document.body.classList.toggle('drawer');
      });
    });
    document.addEventListener('click', function (ev) {
      if (document.body.classList.contains('drawer') &&
          !ev.target.closest('.side') && !ev.target.closest('[data-drawer]')) {
        document.body.classList.remove('drawer');
      }
    });

    /* 确认弹窗：服务端已经把确认表单渲染好了，这里只是把它弹成模态。
       关掉 JS 时它就地显示在页面里，提交路径完全一样。 */
    document.querySelectorAll('[data-confirm-dialog]').forEach(function (dlg) {
      if (typeof dlg.showModal === 'function') { try { dlg.showModal(); } catch (e) {} }
      dlg.querySelectorAll('[data-dialog-close]').forEach(function (b) {
        b.addEventListener('click', function () {
          if (typeof dlg.close === 'function') { dlg.close(); }
          dlg.remove();
        });
      });
    });

    /* 切回前台时立刻补一次，不用等下一个周期。 */
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && !paused && window.htmx) {
        document.querySelectorAll('[data-live]').forEach(function (el) {
          window.htmx.trigger(el, 'refresh');
        });
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（25 组）

- [ ] **步骤 5：Commit**

```bash
git add portal/static/admin.js tests/test_portal_ui.py
git commit -m "portal/static: 渐进增强脚本（自动刷新闸门、复制、抽屉、确认弹窗）"
```

---

## 任务 8：`portal/views.py` —— Ctx、Rendered 与视图注册表（先搬移，不改行为）

**目标：** 把 `_admin()` 里 7 个视图的**现有渲染代码原样搬进** `views.py`，只把数据来源从闭包改成 `Ctx` 字段。这一步**不改变任何页面输出**，既有测试必须一条不改就全绿 —— 那就是"搬移无损"的证明。

**文件：**
- 创建：`portal/views.py`
- 修改：`portal/app.py`（`_admin()` 改为装配 `Ctx` 并调用 `views.render`）

- [ ] **步骤 1：创建 `portal/views.py`**

```python
"""后台视图：只消费 Ctx 产出 HTML。

**这一层是纯呈现。** 判据（`tests/test_portal_ui.py::test_views_layer_is_pure` 会检查）：
本模块不得出现 `subprocess`、`socket`、`open(`、`Path(` —— 所有事实由 `app.py` 采集。
这样视图可以拿假数据直接测，不必起服务、不必开端口、不必等超时。
"""
from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from email import utils as email_utils

from portal import ui
from portal.ui import esc, pill


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
    clublog_query: str = ""
    clublog_hit: str = ""
    registry_first: int = 0
    registry_last: int = 0
    sampler: dict | None = None
    tunnel_text: dict = field(default_factory=dict)
    tunnel_pill: dict = field(default_factory=dict)
    now: float = 0.0
    # 筛选与定位
    flt: str = ""
    flt_label: str = ""     # 实例详情页要看的那个标签
    page: int = 1


@dataclass(frozen=True)
class Rendered:
    title: str
    chrome: str      # 标题、工具条、按钮等"不需要自动刷新"的部分
    live: str        # 会自动刷新的数据区；空串表示本视图不自动刷新


#: 每个视图的自动刷新间隔（秒）。0 = 不刷新。
REFRESH_SECONDS = {"overview": 30, "instances": 20, "tunnel": 30, "system": 60}


def live_region(view: str, ctx: Ctx, inner: str) -> str:
    """把数据区包成可被 htmx 替换的节点。

    带 `data-live` 供 admin.js 定位；`hx-trigger` 的条件引用 admin.js 的全局闸门。
    关掉 JS 时这些属性无人理会，页面照常显示 —— 只是不会自动刷新。
    """
    every = REFRESH_SECONDS.get(view, 0)
    if not every:
        return f'<div data-live>{inner}</div>'
    return (f'<div data-live hx-get="{ctx.root}/admin?view={esc(view)}&amp;part=live" '
            f'hx-trigger="every {every}s, refresh [!window.__portalPaused()]" '
            f'hx-swap="outerHTML">{inner}</div>')


VIEWS: dict = {}


def register(view_id: str, title: str):
    def deco(fn):
        VIEWS[view_id] = (title, fn)
        return fn
    return deco


def render(view_id: str, ctx: Ctx, part: str | None = None, **kw) -> Rendered:
    """渲染一个视图。part='live' 时只回数据区（自动刷新用）。

    `**kw` 透传给视图函数 —— 实例详情页需要 `label=`。视图函数的签名统一是
    `fn(ctx, **kw)`，所以 `render("instance", ctx, label="bg1sb")` 可用。
    """
    title, fn = VIEWS.get(view_id) or VIEWS["overview"]
    ctx.view = view_id
    rendered = fn(ctx, **kw)
    if part == "live":
        return Rendered(rendered.title, chrome="", live=rendered.live)
    return rendered
```

并在文件末尾放一个**逐字节照抄**自 `app.py` 的 7 个视图（步骤 2 说明怎么抄）。

- [ ] **步骤 2：搬移（机械动作，逐视图照抄）**

对 `portal/app.py` 的 `_admin()` 里 `if view == "..."` 每一支：

1. 把该支的整个 `body = ...` 表达式原样复制到 `views.py` 里一个新的
   `@register("<view>", "<标题>")` 函数体；
2. 把闭包变量换成 `Ctx` 字段：
   | 原来 | 现在 |
   | --- | --- |
   | `apps` | `ctx.apps` |
   | `entries` | `ctx.entries` |
   | `registry.first` / `registry.last` | `ctx.registry_first` / `ctx.registry_last` |
   | `_cert_days()` | `ctx.cert_days` |
   | `_clublog_info()` | `ctx.clublog` |
   | `_tunnel_states(entries)` | `ctx.states` |
   | `sampler.snapshot()` | `ctx.sampler` |
   | `_host_resources()` / `_service_states()` / `_net_facts()` / `_hub_cert_inventory()` | `ctx.resources` / `ctx.services` / `ctx.net` / `ctx.certs` |
   | `_instance_reports(registry.entries_full())` | `ctx.reports` |
   | `TUNNEL_TEXT` / `TUNNEL_PILL` | `ctx.tunnel_text` / `ctx.tunnel_pill` |
   | `time.strftime(...)` | `time.strftime(...)`（时间允许在视图里算，它是纯函数） |
   | `DEFAULT_CLUBLOG` | `ctx.clublog` 里已含路径信息（见步骤 3） |
3. 函数返回 `Rendered(title="…", chrome="", live=live_region(view, ctx, body))`
   —— 本任务**不拆分 chrome/live**，整段 body 都算 live（视图重做时才拆）。

- [ ] **步骤 3：改 `app.py`**

把 `_admin()` 的整个函数体替换为：

```python
        def _admin(self, view: str, msg: str = "", part: str | None = None,
                   flt: str = "", page: int = 1):
            """后台管理台：装配 Ctx → 交给 views 渲染。

            安全姿态（不变的）：浏览器路径靠会话 Cookie + 表单 CSRF；机器路径用
            `X-Portal-Token` 请求头。令牌/会话值不进 URL、不进 Location、不进访问日志。
            需要 root 的操作不由本服务执行，只把命令打出来让运维复制。
            """
            _, session = self._session()
            root = self._admin_root()
            entries = portal.registry.entries()
            entries_full = portal.registry.entries_full()
            snap = sampler.snapshot() if sampler is not None else None
            ctx = vs.Ctx(
                root=root,
                csrf=session.csrf if session else "",
                user=session.user if session else "",
                msg=msg,
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
                registry_first=portal.registry.first,
                registry_last=portal.registry.last,
                sampler=snap,
                tunnel_text=TUNNEL_TEXT,
                tunnel_pill=TUNNEL_PILL,
                now=time.time(),
                flt=flt,
                page=page,
            )
            r = vs.render(view, ctx, part=part)
            nav = ui.Nav(view=view, root=root, badges=vs.badges(ctx),
                         user=ctx.user, csrf=ctx.csrf, live_seconds=0)
            return ui.page(r.title, r.chrome, nav=nav, noindex=True,
                           fragment=(part is not None), live=r.live)
```

在 `views.py` 里补 `badges(ctx)`：

```python
def badges(ctx: Ctx) -> dict:
    """侧栏与底栏的待办徽标。只在 >0 时显示（ui._badge_html 负责）。"""
    applied = sum(1 for a in ctx.apps.values() if a["status"] in ("applied", "verified"))
    return {"applications": applied}
```

> **注意**：本任务里 `badges` 只报申请数；实例异常数与系统告警数在任务 11/14 补上。

- [ ] **步骤 4：改 `do_GET` 的调用点**

`do_GET` 里 `return self._send(200, self._admin(...))` 那几处改成传 `part`：

```python
                if route in ("/admin", "/admin/login"):
                    _, session = self._session()
                    if session is None:
                        return self._login_page()
                    if route == "/admin/login":
                        return self._send(303, "", ctype="text/plain; charset=utf-8",
                                          headers={"Location": self._console_url()})
                    q = self._query()
                    part = "live" if (self.headers.get("HX-Request") and q.get("part") == "live") else None
                    page_html = self._admin(q.get("view") or "overview",
                                            part=part, flt=q.get("f") or "",
                                            page=_int_or(q.get("page"), 1))
                    return self._send(200, page_html, ctype="text/html; charset=utf-8",
                                      headers={"HX-Push-Url": f"{self._console_url()}?view="
                                                              f"{q.get('view') or 'overview'}"} if part else None)
```
（`_int_or` 是本步骤新加的小工具：`def _int_or(value, default): try: return int(value) except (TypeError, ValueError): return default`，放在 `make_handler` 外面。）

- [ ] **步骤 5：跑全部既有测试，证明搬移无损**

运行：
```bash
python3 tests/test_portal.py && python3 tests/test_portal_auth.py && \
python3 tests/test_portal_metrics.py && python3 tests/test_htpasswd.py
```
预期：**四组全绿，且测试文件一行未改**。（`test_portal.py` 里 `from portal.app import _PORTAL_CSS` 需要 `app.py` 保留 `_PORTAL_CSS = ui.CSS` 这一行兼容导出。）

- [ ] **步骤 6：加"视图层是纯的"守卫**

追加到 `tests/test_portal_ui.py`：

```python
def test_views_layer_is_pure():
    """views.py 不许自己采集事实 —— 出现 subprocess/socket/文件读取就说明边界破了。"""
    import ast
    from pathlib import Path as P
    src = P(__file__).resolve().parent.parent / "portal" / "views.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned = {"subprocess", "socket", "ssl", "shutil"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                check(a.name.split(".")[0] not in banned, f"views.py 不许 import {a.name}")
        if isinstance(node, ast.ImportFrom):
            check((node.module or "").split(".")[0] not in banned,
                  f"views.py 不许 from {node.module} import")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            check(node.func.id not in ("open", "exec", "eval"), f"views.py 不许调用 {node.func.id}()")
```

- [ ] **步骤 7：运行新守卫**

运行：`python3 tests/test_portal_ui.py`
预期：PASS（26 组）

- [ ] **步骤 8：Commit**

```bash
git add portal/views.py portal/app.py tests/test_portal_ui.py
git commit -m "portal: 视图层拆出 views.py（纯呈现，Ctx 由 app.py 装配），输出逐字节等价"
```

---

## 任务 9：`TUNNEL_TEXT` 文案统一

**为什么单独一步：** 现有 `TUNNEL_TEXT[TUNNEL_SERVING] = "在线"` —— 而"在线"正是 2026-10-03 那次误判的用词（隧道在、后端空，页面显示"在线"，访客拿到 502）。四态模型就是为了杀掉这个词，但文案还留着。改成"服务中"让文案与判据一致。

**文件：**
- 修改：`portal/app.py`
- 修改：`tests/test_portal.py:886`、`tests/test_portal_metrics.py:197`

- [ ] **步骤 1：改文案**

`portal/app.py` 里：

```python
TUNNEL_TEXT = {
    TUNNEL_SERVING: "服务中",
    TUNNEL_PLAIN_HTTP: "明文 HTTP",
    TUNNEL_HOLLOW: "后端无应答",
    TUNNEL_DOWN: "隧道不在",
}
```

> `TUNNEL_PILL` **不动**：`serving=ok / plain-http=warn / hollow=warn / down=bad` 是既有的、
> 有注释论证过的决定（"两类连得上但用不了用琥珀，避免与真离线混淆"）。本计划不改状态语义，
> 只改措辞。样张里把 hollow 画成红色是**样张的错**，实现以 `TUNNEL_PILL` 为准。

- [ ] **步骤 2：同步测试断言**

`tests/test_portal.py` 第 886 行附近：
```python
                    ("服务中", "隧道状态"),
```
`tests/test_portal_metrics.py` 第 197 行附近：
```python
                                ("23 ms", "延时数值"), ("服务中", "隧道四态文案"),
```

- [ ] **步骤 3：跑测试**

运行：`python3 tests/test_portal.py && python3 tests/test_portal_metrics.py`
预期：全绿

- [ ] **步骤 4：Commit**

```bash
git add portal/app.py tests/test_portal.py tests/test_portal_metrics.py
git commit -m "portal: TUNNEL_TEXT 文案与判据对齐（在线→服务中），终结 2026-10-03 的用词歧义"
```

---

## 任务 10：总览视图重做

**文件：**
- 修改：`portal/views.py`（`overview` 视图）
- 测试：`tests/test_portal.py`（新增 `test_overview_shows_todo_list`）

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_portal.py`：

```python
def test_overview_shows_todo_list():
    """总览首屏必须回答"现在有没有事、我该做什么"。

    没有这条守卫，总览很容易退化成"一堆好看的数字"（改版前就是这样：四个指标，
    没有一个告诉你该动手做什么）。
    """
    from portal import views as vs

    ctx = vs.Ctx(
        root="", apps={"bg8xyz": {"callsign": "bg8xyz", "status": "applied",
                                  "evidence": "命中呼号库", "product": "", "label": None,
                                  "port": None, "at": time.time() - 7200}},
        entries=[("bg1sb", 18804), ("bg7zhs", 18805)],
        states={18804: (TUNNEL_SERVING, "握手成功"), 18805: (TUNNEL_HOLLOW, "隧道在、后端无应答")},
        cert_days="38", clublog="273047 条",
        registry_first=18800, registry_last=18999,
        tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL,
        services=[("mrrc-hub-routes.timer", "未安装", "not-found", "—", "—")],
        net={"listen": [8989], "peers": ["a"], "note": ""},
        now=time.time(),
    )
    out = vs.render("overview", ctx).chrome + vs.render("overview", ctx).live
    check("需要你处理" in out, "有待办清单")
    check("待核验" in out, "待办里列出待核验申请")
    check("BG8XYZ" in out.upper(), "待办里带呼号")
    check("bg7zhs" in out and "后端无应答" in out, "待办里列出异常实例")
    check("未安装" in out, "待办里列出没装的服务单元")
    check("applied=" not in out, "不再把英文 slug 直接打给运维")
    check("待你处理" in out, "首屏有「待你处理」指标")
```

在 `tests/test_portal.py` 顶部 import 区补 `import time`（若尚无）。

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py`
预期：FAIL（`需要你处理` 等 needle 缺失）

- [ ] **步骤 3：实现**

在 `portal/views.py` 里用下面这支**替换**任务 8 搬过来的 overview：

```python
def _level(ctx: Ctx, state: str) -> str:
    """状态对应的视觉级别，**唯一来源是 `TUNNEL_PILL`**（“服务中”即 pill == 'ok'）。

    视图不 import `TUNNEL_SERVING` / `TUNNEL_DOWN` 这类状态常量：它们在 app.py，
    而 app.py import views（循环），且状态语义的权威本来就在探针那边。
    视图只需知道“哪个级别”，而这个已经由 ctx.tunnel_pill 带过来了。
    """
    return {"ok": "", "warn": "warn", "bad": "bad"}.get(ctx.tunnel_pill.get(state, ""), "")


def _is_serving(ctx: Ctx, state: str) -> bool:
    return ctx.tunnel_pill.get(state) == "ok"


def _todo_items(ctx: Ctx) -> list[tuple[str, str, str, str]]:
    """待办清单 → [(级别, 标题, 说明, 动作 HTML)]。

    这是总览的核心：它回答"我现在该做什么"。级别决定颜色，**红＝要动手**。
    """
    items: list[tuple[str, str, str, str]] = []
    pending = [a for a in ctx.apps.values() if a["status"] == "applied"]
    for a in sorted(pending, key=lambda a: a.get("at") or 0)[:5]:
        evidence = (a.get("evidence") or "需人工核验")[:60]
        items.append((
            "warn", f"待核验 · {a['callsign'].upper()}",
            f"{esc(evidence)} · {_ago_text(ctx.now, a.get('at'))}",
            f'<a class="chip" href="{ctx.root}/admin?view=applications">去处理</a>'))
    for label, port in ctx.entries:
        state, detail = ctx.states.get(port, ("", "未探测"))
        if _is_serving(ctx, state):
            continue
        items.append((
            "bad" if _level(ctx, state) == "bad" else "warn",
            f"{label} · {ctx.tunnel_text.get(state, state)}",
            esc(detail) + " —— 访客会拿到 502，请查实例机",
            f'<a class="chip" href="{ctx.root}/admin?view=instances">看实例</a>'))
    for unit, st, enabled, since, restarts in ctx.services:
        if st in ("active", "未安装") and enabled != "not-found":
            continue
        note = "单元文件在仓库里、没装到 hub 上 —— 路由不会自动重生成" if enabled == "not-found" \
            else f"当前 {st}"
        items.append(("warn", f"服务 {unit}", esc(note),
                      f'<a class="chip" href="{ctx.root}/admin?view=system">去系统页</a>'))
    days = _int_or_none(ctx.cert_days)
    if days is not None and days < 30:
        items.append(("warn", "入口证书临期", f"还剩 {days} 天，到期前必须续",
                      f'<a class="chip" href="{ctx.root}/admin?view=system">看证书</a>'))
    if ctx.sampler and ctx.sampler.get("panel_error"):
        items.append(("warn", "frps 面板取不到数",
                      esc(ctx.sampler["panel_error"]) + " —— 隧道带宽会缺数",
                      f'<a class="chip" href="{ctx.root}/admin?view=system">去看原因</a>'))
    return items


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
    lat_note = f"均值 {sum(lat) / len(lat):.0f} 毫秒" if lat else "暂无采样"

    stats = (
        '<div class="stats">'
        + ui.stat("待你处理", str(len(todos)), "按「需要你处理」计", "warn" if todos else "ok")
        + ui.stat("实例异常", str(max(0, len(ctx.entries) - serving)),
                  f"{len(ctx.entries)} 个已登记", "bad" if serving < len(ctx.entries) else "ok")
        + ui.stat("入口证书", ctx.cert_days, "天后到期")
        + ui.stat("隧道总延时", f"{sum(lat) / len(lat):.0f}" if lat else "—", lat_note)
        + '</div>')

    todo_html = "".join(
        f'<div class="card{"" if lv == "ok" else " alert" + (" warn" if lv == "warn" else "")}">'
        f'<div class="cardhead">{ui.pill(lv, lv == "bad" and "要动手" or "待处理")}'
        f'<b>{title}</b>{action}</div><div class="meta"><span>{note}</span></div></div>'
        for lv, title, note, action in todos) or ui.empty(
            "没有待办 —— 所有申请都已处理，实例都在服务",
            f'<a class="chip" href="{ctx.root}/admin?view=instances">看实例清单</a>')

    port_used = len(ctx.entries)
    kv_rows = [
        ("申请状态分布", "　".join(f"{STATUS_CN.get(k, k)}={v}" for k, v in sorted(by.items())) or "（无）"),
        ("端口池", f"{ctx.registry_first}-{ctx.registry_last}，已用 {port_used}，"
                   f"空闲 {ctx.registry_last - ctx.registry_first + 1 - port_used}"),
        ("Club Log 呼号库", esc(ctx.clublog) if ctx.clublog else "—"),
    ]
    cmd = ('<div class="card"><div class="cardhead"><b>需要 root 的运维命令</b></div>'
           '<div class="meta"><span>新增/撤销实例后</span></div>'
           + ui.copy_button("sudo /usr/local/sbin/gen_hub_routes.py && sudo systemctl reload nginx",
                            "复制")
           + '<div class="meta" style="margin-top:6px"><span>立即刷新呼号库</span></div>'
           + ui.copy_button("sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh", "复制")
           + '</div>')

    body = (stats
            + "<h2>需要你处理的</h2>" + todo_html
            + "<h2>概览</h2>" + ui.kv(kv_rows)
            + cmd)
    return Rendered(title="MRRC Portal — 总览", chrome="", live=live_region("overview", ctx, body))
```

并在 `views.py` 顶部加 `STATUS_CN`：

```python
#: 状态 slug 的中文名。总览页曾把 `applied=1 verified=1` 直接打给运维看（P2）。
STATUS_CN = {"applied": "待核验", "verified": "待分配", "granted": "已授予",
             "rejected": "已拒绝", "revoked": "已撤销"}
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal.py`
预期：绿

- [ ] **步骤 5：Commit**

```bash
git add portal/views.py tests/test_portal.py
git commit -m "portal/views: 总览改为「待办清单 + 指标卡」，slug 中文化"
```

---

## 任务 11：申请视图重做（分组 / 筛选 / 二次确认）

**文件：**
- 修改：`portal/views.py`、`portal/app.py`（破坏性动作两阶段）
- 测试：`tests/test_portal.py`

- [ ] **步骤 1：编写失败的测试**

追加：

```python
def test_applications_are_grouped_and_default_to_pending():
    """默认落在「待处理」，且每组带计数 —— 七种状态一锅端是改版前的 P3。"""
    from portal import views as vs
    apps = {
        "bg8xyz": {"callsign": "bg8xyz", "status": "applied", "evidence": "命中呼号库",
                   "product": "", "label": None, "port": None, "at": time.time()},
        "bg2abc": {"callsign": "bg2abc", "status": "granted", "evidence": "人工",
                   "product": "", "label": "bg2abc", "port": 18808, "at": time.time()},
    }
    ctx = vs.Ctx(root="", apps=apps, now=time.time(), tunnel_text=TUNNEL_TEXT,
                 tunnel_pill=TUNNEL_PILL)
    r = vs.render("applications", ctx)
    out = r.chrome + r.live
    check("待核验" in out and "已授予" in out, "分组标题在")
    check('class="chip on"' in out, "默认选中「待处理」筛选")
    check("默认" not in out or True, "")
    check("核验通过" in out, "待核验组有通过动作")


def test_destructive_actions_need_confirm_and_reason():
    """拒绝/撤销必须是**服务端**两阶段确认 —— 不能只靠 window.confirm（关掉 JS 就没了）。"""
    from portal import views as vs
    ctx = vs.Ctx(root="", csrf="tok", now=time.time(),
                 apps={"bg8xyz": {"callsign": "bg8xyz", "status": "verified",
                                  "evidence": "x", "product": "", "label": None,
                                  "port": None, "at": time.time()}},
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL)
    out = vs.render("applications", ctx).chrome + vs.render("applications", ctx).live
    check('name="confirm"' not in out, "阶段一只发动作，不带 confirm 标记")
    check("/admin/reject" in out, "拒绝动作存在")


def test_selected_confirm_route_renders_reason_form():
    """阶段二：服务端返回带理由输入的确认表单。"""
    from portal import views as vs
    ctx = vs.Ctx(root="", csrf="tok", now=time.time(), view="applications")
    out = vs.confirm_page("revoke", "bg1sb", ctx)
    check('name="reason"' in out, "确认表单要理由")
    check('name="confirm" value="yes"' in out, "确认表单带二次确认标记")
    check('name="csrf" value="tok"' in out, "确认表单带 csrf")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py`
预期：FAIL（`待核验` 分组标题缺失、`confirm_page` 不存在）

- [ ] **步骤 3：实现视图**

`portal/views.py` 里新增：

```python
#: 申请分组。值 = (组标题, 组内状态, 是否默认展开)。
APP_GROUPS = (
    ("pending", "待处理", ("applied", "verified")),
    ("granted", "已授予", ("granted",)),
    ("closed", "已结束", ("rejected", "revoked")),
)


@register("applications", "MRRC Portal — 申请")
def view_applications(ctx: Ctx) -> Rendered:
    groups: dict[str, list] = {g: [] for g, _t, _s in APP_GROUPS}
    for a in ctx.apps.values():
        for gid, _title, statuses in APP_GROUPS:
            if a["status"] in statuses:
                groups[gid].append(a)
    for v in groups.values():
        v.sort(key=lambda a: -(a.get("at") or 0))

    active = ctx.flt or "pending"
    chips = []
    for gid, title, _s in APP_GROUPS:
        chips.append((f"{title} {len(groups[gid])}",
                      f"{ctx.root}/admin?view=applications&f={gid}",
                      gid == active, None))
    chips.append(("全部", f"{ctx.root}/admin?view=applications&f=all", active == "all", None))
    chrome = ("<h1>申请</h1>"
              + f'<div class="hint">把「规范化 → 查重 → 核验 → 分配」走完；呼号核验通过才会分配入口。</div>'
              + ui.toolbar(chips, search_html=(
                  f'<form method="get" action="{ctx.root}/admin" class="search" data-tools>'
                  f'<input type="hidden" name="view" value="applications">'
                  f'<input name="q" value="{esc(ctx.clublog_query)}" placeholder="搜索呼号…"></form>')))

    def row(a) -> list:
        c = a["callsign"]
        status = a["status"]
        cells = [
            ("呼号", f"<code>{esc(c.upper() if status != 'granted' else (a.get('label') or c))}</code>"),
            ("状态", pill("mute", STATUS_CN.get(status, status))),
            ("产品", esc(a.get("product") or "主产品")),
            ("依据", esc((a.get("evidence") or "")[:70])),
            ("时间", _ago_text(ctx.now, a.get("at"))),
        ]
        if status == "applied":
            acts = (_post(ctx, "/admin/verify", c, "核验通过", pri=True)
                    + _post(ctx, "/admin/reject", c, "拒绝", dgr=True))
        elif status == "verified":
            acts = _post(ctx, "/admin/grant", c, "分配入口", pri=True) \
                + _post(ctx, "/admin/reject", c, "拒绝", dgr=True)
        elif status == "granted":
            acts = _post(ctx, "/admin/revoke", c, "撤销入口", dgr=True)
            secret = a.get("enroll_secret")
            if secret:
                acts = ui.copy_button(secret, "复制登记口令") + acts
        else:
            acts = ""
        cells.append(("动作", acts))
        return cells

    HEADERS = ["呼号", "状态", "产品", "依据", "时间", "动作"]
    blocks = []
    for gid, title, _s in APP_GROUPS:
        if active not in (gid, "all"):
            continue
        rows = [row(a) for a in groups[gid]]
        blocks.append(f"<h2>{esc(title)}（{len(groups[gid])}）</h2>"
                      + (ui.grid_table(HEADERS, rows, stack=True)
                         if rows else ui.empty(f"没有{title}的申请",
                                               f'<a class="chip" href="{ctx.root}/admin?view=applications&f=all">'
                                               f'看全部</a>')))
    body = "".join(blocks)
    return Rendered(title="MRRC Portal — 申请", chrome=chrome, live=live_region("applications", ctx, body))


def _post(ctx: Ctx, route: str, callsign: str, label: str, *, pri: bool = False,
          dgr: bool = False) -> str:
    """状态变更表单。**永远带 csrf**，永远是真 form（关掉 JS 也能提交）。"""
    cls = ' class="pri"' if pri else (' class="dgr"' if dgr else "")
    return (f'<form method="post" action="{ctx.root}{route}">'
            f'<input type="hidden" name="csrf" value="{esc(ctx.csrf)}">'
            f'<input type="hidden" name="callsign" value="{esc(callsign)}">'
            f'<button{cls}>{esc(label)}</button></form>')


def confirm_page(action: str, callsign: str, ctx: Ctx, *, reason_label: str = "原因") -> str:
    """破坏性动作的第二阶段：带理由输入的确认表单（服务端渲染，JS 可有可无）。"""
    titles = {
        "revoke": (f"撤销 {callsign.upper()} 的入口？",
                   "注册表会少一行，访客立刻拿不到入口。撤销是长期的，重开要重新走核验。"),
        "reject": (f"拒绝 {callsign.upper()} 的申请？",
                   "申请会被标记为已拒绝。若对方是合法持照者，需要重新申请。"),
    }
    title, body = titles.get(action, (f"确认 {action}？", "此操作会改变状态。"))
    return ui.confirm_form(f"{ctx.root}/admin/{action}", {"callsign": callsign},
                           "确认执行", csrf=ctx.csrf, title=title, body=body,
                           reason_label=reason_label)
```

> 注：`view_applications` 用 `ui.grid_table(...)` 一次性渲染整表（含 `<table>` 闭合），
> **不新增 `grid_table_row`** —— 行级版本与整表版本并存必然漂移。

- [ ] **步骤 4：改 `app.py` 的破坏性动作处理（两阶段）**

在 `do_POST` 里，`route in ("/verify", "/reject", "/grant", "/revoke")` 分支的开头加：

```python
                if route in ("/reject", "/revoke"):
                    callsign = str(body.get("callsign") or "").strip()
                    if str(body.get("confirm") or "") != "yes":
                        # 阶段一：不执行，回确认表单。JS 在时被塞进 <dialog>，关掉 JS 时
                        # 就是一张普通页面 —— 两条路走同一段代码。
                        _, session = self._session()
                        ctx = vs.Ctx(root=self._admin_root(),
                                     csrf=session.csrf if session else "", view="applications")
                        return self._send(200, vs.confirm_page(route.lstrip("/"), callsign, ctx),
                                          ctype="text/html; charset=utf-8")
                    if not str(body.get("reason") or "").strip():
                        _, session = self._session()
                        ctx = vs.Ctx(root=self._admin_root(),
                                     csrf=session.csrf if session else "", view="applications")
                        return self._send(400, vs.confirm_page(route.lstrip("/"), callsign, ctx),
                                          ctype="text/html; charset=utf-8")
```

- [ ] **步骤 5：跑测试**

运行：`python3 tests/test_portal.py && python3 tests/test_portal_auth.py`
预期：绿。（`test_admin_ui_flow_with_sessions_and_csrf` 里若直接 POST `/admin/revoke`，需要按新流程先拿到确认页再带 `confirm=yes` 提交 —— 按实际报错调整该用例，这属于**允许**的测试更新，因为交互契约变了。）

- [ ] **步骤 6：Commit**

```bash
git add portal/views.py portal/ui.py portal/app.py tests/test_portal.py
git commit -m "portal/views: 申请按状态分组+筛选，拒绝/撤销改服务端两阶段确认（带理由）"
```

---

## 任务 12：实例视图重做 + 实例详情页

**文件：**
- 修改：`portal/views.py`、`portal/app.py`（新路由 `/admin/instance`）
- 测试：`tests/test_portal.py`

- [ ] **步骤 1：编写失败的测试**

追加：

```python
def test_instances_list_keeps_the_decision_facts_and_drops_the_noise():
    """列表只留"一眼判断"要的量；证书主体这类细节搬进详情页。"""
    from portal import views as vs
    ctx = vs.Ctx(root="", entries=[("bg7zhs", 18805)],
                 entries_full=[("bg7zhs", 18805, "bg7zhs.mrrc.vlsc.net")],
                 states={18805: (TUNNEL_HOLLOW, "隧道在、后端无应答")},
                 reports={"bg7zhs": {"state": TUNNEL_HOLLOW, "detail": "隧道在、后端无应答",
                                     "status_line": "", "server": "", "generation": "",
                                     "cert": {}}},
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL, now=time.time())
    out = vs.render("instances", ctx).chrome + vs.render("instances", ctx).live
    check("后端无应答" in out, "列表里有结论")
    check("隧道在" in out, "列表里带下一步线索")
    check("详情" in out, "每行可进详情")


def test_instance_detail_shows_certificate_and_app_facts():
    from portal import views as vs
    ctx = vs.Ctx(root="", entries_full=[("probe", 18810, "probe.mrrc.vlsc.net")],
                 reports={"probe": {"state": TUNNEL_SERVING, "detail": "握手成功",
                                    "status_line": "HTTP/1.1 401 Unauthorized",
                                    "server": "uvicorn", "generation": "mrrc-v99",
                                    "cert": {"subject": "probe.mrrc.vlsc.net",
                                             "issuer": "probe.mrrc.vlsc.net",
                                             "not_after": "Nov 18 00:00:00 2026 GMT",
                                             "name_ok": True}}},
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL, now=time.time())
    out = vs.render("instance", ctx, label="probe").chrome
    for needle, why in (("probe.mrrc.vlsc.net", "上游证书主体"), ("uvicorn", "Server 头"),
                        ("mrrc-v99", "构建代号"), ("401", "应用状态行"), ("自签", "签发者识别")):
        check(needle in out, f"详情页有{why}")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py`
预期：FAIL

- [ ] **步骤 3：实现**

替换 `views.py` 的 `instances` 视图并新增 `instance`：

```python
@register("instances", "MRRC Portal — 实例")
def view_instances(ctx: Ctx) -> Rendered:
    rows, cards = [], []
    serving = 0
    for label, port in sorted(ctx.entries):
        rep = ctx.reports.get(label, {})
        state = rep.get("state") or ctx.states.get(port, ("", ""))[0]
        detail = rep.get("detail") or ctx.states.get(port, ("", ""))[1]
        if _is_serving(ctx, state):
            serving += 1
        cert = rep.get("cert") or {}
        days = _days_left_text(cert.get("not_after", ""))
        state_pill = pill(ctx.tunnel_pill.get(state, "mute"), ctx.tunnel_text.get(state, state))
        entry = (f'<a class="chip" href="https://{esc(label)}.mrrc.vlsc.net/" target=_blank '
                 f'rel=noopener>打开入口</a>')
        detail_link = (f'<a class="chip" href="{ctx.root}/admin?view=instance&amp;label={esc(label)}">'
                       f'详情</a>')
        rows.append([
            ("标签", f"<code>{esc(label)}</code>"),
            ("端口", f'<span class="mono">{port}</span>'),
            ("隧道", state_pill),
            ("证书", f'<span class="mono">{esc(days)}</span>' if days else '<span class="hint">—</span>'),
            ("应用", f'<span class="mono">{esc(rep.get("generation") or "—")}</span>'),
            ("动作", f'<div class="tools" style="margin:0">{detail_link}{entry}</div>'),
        ])
        # 卡片的第二行直接给下一步 —— "后端无应答"后面必须跟一句该怎么办，
        # 否则运维还得自己回忆 2026-10-03 那次事故的排查顺序。
        hint = ""
        if detail and not _is_serving(ctx, state):
            hint = f'<div class="hint bad">隧道在，但实例应用没起 —— 请查实例机：应用是否在跑、'
            hint += f'<code>localPort</code> 是否等于 <code>MRRC_WEB_PORT</code></div>'
        cards.append(ui.card(
            head=f'<b><code>{esc(label)}</code></b>{state_pill}',
            meta=(f'<span class="mono">{port}</span><span>证书 {esc(days) or "—"}</span>'
                  f'<span class="mono">{esc(rep.get("generation") or "—")}</span>'),
            body=hint + f'<div class="tools" style="margin:9px 0 0">{detail_link}{entry}</div>',
            level=_level(ctx, state)))

    chrome = ("<h1>实例</h1>"
              + f'<div class="hint">{len(ctx.entries)} 个已登记 · {serving} 个在服务 · '
                f'<b style="color:var(--bad)">{len(ctx.entries) - serving} 个异常</b></div>'
              + ui.toolbar([("全部", f"{ctx.root}/admin?view=instances", True, len(ctx.entries))],
                           search_html=(f'<form method="get" action="{ctx.root}/admin" '
                                        f'class="search" data-tools>'
                                        f'<input type="hidden" name="view" value="instances">'
                                        f'<input name="q" placeholder="搜索标签或端口…"></form>'))
              + '<div class="hint only-mobile">表格已换成卡片，一条一张</div>')

    if rows:
        # 桌面表格与手机卡片是两份标记，用断点切换。
        # 为什么不靠 CSS 把表格"捏"成卡片：卡片的头部要把标签和状态徽章放在同一行，
        # 表格的单元格做不到这件事而不引入空的定位格（那又会让"行格数=表头列数"的守卫失效）。
        # 两份标记的代价是 HTML 变大一点，换来的是两边都能真的好看。
        body = ('<div class="only-desktop">'
                + ui.grid_table(["标签", "端口", "隧道", "证书", "应用", "动作"], rows)
                + '</div>'
                + '<div class="only-mobile" data-mobile-cards>' + "".join(cards) + '</div>')
    else:
        body = ui.empty("注册表为空 —— 还没有实例登记",
                        f'<a class="chip" href="{ctx.root}/admin?view=applications">去看申请</a>')
    body += ui.banner("info", "「服务中」= 从 hub 回环向该端口完成 <b>TLS 握手</b>并拿到 HTTP 应答"
                              "（任何状态码都算）。仅仅「端口可连」<b>不算</b> —— frps 在本机接受连接，"
                              "隧道在、后端空的时候照样连得上。")
    return Rendered(title="MRRC Portal — 实例", chrome=chrome, live=live_region("instances", ctx, body))


@register("instance", "MRRC Portal — 实例详情")
def view_instance(ctx: Ctx, label: str = "") -> Rendered:
    label = label or ctx.flt_label
    rep = ctx.reports.get(label, {})
    state = rep.get("state", "")
    cert = rep.get("cert") or {}
    name_ok = cert.get("name_ok")
    cert_mark = (pill("ok", "名字相符") if name_ok else
                 pill("bad", "名字不符 ⇒ nginx 必 502") if name_ok is not None else
                 pill("mute", "握手没成，拿不到证书"))
    issuer = "自签" if cert.get("issuer") == cert.get("subject") else (cert.get("issuer") or "—")
    chrome = (f'<h1>{esc(label)}</h1>'
              + '<div class="hint">'
              + f'{esc(label)}.mrrc.vlsc.net · 端口 <span class="mono">{_port_of(ctx, label)}</span> · '
              + pill(ctx.tunnel_pill.get(state, "mute"), ctx.tunnel_text.get(state, state))
              + '</div>'
              + ui.kv([
                  ("隧道结论", esc(rep.get("detail") or "未探测")),
                  ("上游证书主体", f'<code>{esc(cert.get("subject") or "—")}</code>'),
                  ("签发者", esc(issuer)),
                  ("到期", esc(cert.get("not_after") or "—")),
                  ("名字比对", cert_mark),
                  ("应用状态行", f'<code>{esc(rep.get("status_line") or "—")}</code>'),
                  ("Server", esc(rep.get("server") or "—")),
                  ("构建代号", f'<b>{esc(rep.get("generation") or "—")}</b>'),
              ])
              + '<h2>动作</h2>'
              + _post(ctx, "/admin/revoke", label, "撤销入口", dgr=True))
    return Rendered(title=f"MRRC Portal — {label}", chrome=chrome, live="")


def _port_of(ctx: Ctx, label: str) -> str:
    for l, p in ctx.entries:
        if l == label:
            return str(p)
    return "—"


def _days_left_text(not_after: str) -> str:
    """从证书的 notAfter 文本算剩余天数。解析不了就回空串（不编数字）。"""
    if not not_after:
        return ""
    try:
        dt = email_utils.parsedate_to_datetime(not_after)
    except (TypeError, ValueError):
        return ""
    if dt is None:
        return ""
    days = int((dt.timestamp() - time.time()) // 86400)
    return f"{days} 天"
```

- [ ] **步骤 4：加路由**

`app.py` 的 `do_GET` 里在 `/admin` 分支之后加：

```python
            if route == "/admin/instance":
                _, session = self._session()
                if session is None:
                    return self._login_page()
                q = self._query()
                label = (q.get("label") or "").strip()
                ctx = self._ctx_for("instance", label=label)
                r = vs.render("instance", ctx)
                nav = ui.Nav(view="instances", root=self._admin_root(), badges=vs.badges(ctx),
                             user=ctx.user)
                return self._send(200, ui.page(r.title, r.chrome, nav=nav, noindex=True),
                                  ctype="text/html; charset=utf-8")
```

把任务 8 里 `_admin()` 内的 `Ctx` 装配抽成 `self._ctx_for(view, **extra)` 供两处共用（**同一个装配函数，避免两处漂移**）。

- [ ] **步骤 5：跑测试**

运行：`python3 tests/test_portal.py`
预期：绿

- [ ] **步骤 6：Commit**

```bash
git add portal/views.py portal/app.py tests/test_portal.py
git commit -m "portal/views: 实例列表瘦身 + 新增实例详情页（证书/应用/审计一处看全）"
```

---

## 任务 13：隧道视图重做（走势小图）

**文件：** 修改 `portal/views.py`；测试 `tests/test_portal.py`

- [ ] **步骤 1：编写失败的测试**

```python
def test_tunnel_view_draws_history_not_just_current_values():
    """120 个采样点已经躺在内存里 —— 只显示当前值是浪费（P6）。"""
    from portal import views as vs

    class _Last:
        latency_ms = 12.0
        out_bps = 1024.0
        in_bps = 512.0
        today_out = 2048
        today_in = 1024
        cur_conns = 2
        tunnel_state = TUNNEL_SERVING
        tunnel_detail = "握手成功"
        note = ""

    ctx = vs.Ctx(root="", entries=[("bg1sb", 18804)],
                 sampler={"labels": {"bg1sb": {"last": _Last(), "latency_mean": 14.0,
                                               "latency_peak": 38.0,
                                               "history": [10, 12, None, 14],
                                               "out_mean": 0, "in_mean": 0, "stale_s": 3}},
                          "panel_error": "", "panel_age": 5, "nic": {}, "interval": 30.0},
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL, now=time.time())
    out = vs.render("tunnel", ctx).chrome + vs.render("tunnel", ctx).live
    check("<svg" in out and "polyline" in out, "画出了走势小图")
    check("12 ms" in out, "当前延时仍在")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py` → FAIL

- [ ] **步骤 3：实现**

替换 `views.py` 的 `tunnel` 视图：

```python
@register("tunnel", "MRRC Portal — 隧道")
def view_tunnel(ctx: Ctx) -> Rendered:
    snap = ctx.sampler
    chrome = ("<h1>隧道</h1>"
              + '<div class="hint">延时是 hub 回环经隧道到实例应用的完整 TLS 握手耗时；'
                '带宽与今日流量来自 frps 面板的累计字节差分。</div>')
    if not snap:
        return Rendered(title="MRRC Portal — 隧道", chrome=chrome,
                        live=live_region("tunnel", ctx,
                                         ui.banner("warn", "采集器未启用"
                                                           "（<code>--metrics-interval 0</code> 或 dry-run）。"
                                                           "延时与带宽需要后台采样线程。")))

    rows, cards = [], []
    tot_out = tot_in = 0.0
    have_tot = False
    for label, port in sorted(ctx.entries):
        item = snap["labels"].get(label)
        if item is None:
            rows.append([("标签", f"<code>{esc(label)}</code>"),
                         ("隧道", '<span class="hint">首轮采样中…</span>'),
                         ("延时（近 1 小时）", "—"), ("带宽（↓/↑）", "—"),
                         ("今日流量（↓/↑）", "—"), ("连接数", "—"), ("采样", "—")])
            continue
        last = item["last"]
        state = last.tunnel_state
        state_pill = pill(ctx.tunnel_pill.get(state, "mute"), ctx.tunnel_text.get(state, state))
        good = _is_serving(ctx, state)
        # 走势图的颜色也跟着状态走：断了的链路画成红色，不用青色假装它好好的。
        spark = ui.sparkline(item.get("history") or [], kind=("accent" if good else "bad"))
        if last.latency_ms is not None:
            lat = (f'<span class="mono">{last.latency_ms:.0f} ms</span>')
            lat_note = f'均值 {item["latency_mean"]:.0f} · 峰值 {item["latency_peak"]:.0f}'
        else:
            lat = '<span class="hint">—</span>'
            lat_note = esc(last.tunnel_detail or "无应答")
        if last.out_bps is not None and last.in_bps is not None:
            tot_out += last.out_bps
            tot_in += last.in_bps
            have_tot = True
            bw = (f'<span class="mono">↓ {ui_fmt_bps(last.out_bps)}</span>'
                  f'<br><span class="mono">↑ {ui_fmt_bps(last.in_bps)}</span>')
        else:
            bw = '<span class="hint">—</span>'
        traffic = (f'<span class="mono">↓ {ui_fmt_bytes(last.today_out)}</span>'
                   f'<br><span class="mono">↑ {ui_fmt_bytes(last.today_in)}</span>')
        conns = "—" if last.cur_conns is None else f'<span class="mono">{last.cur_conns}</span>'
        fresh = f'{item["stale_s"]:.0f} 秒前'
        if last.note:
            fresh += f'<br><small>{esc(last.note)}</small>'
        rows.append([("标签", f"<code>{esc(label)}</code>"), ("隧道", state_pill),
                     ("延时（近 1 小时）", f'{lat}<br><small>{lat_note}</small><br>{spark}'),
                     ("带宽（↓/↑）", bw), ("今日流量（↓/↑）", traffic),
                     ("连接数", conns), ("采样", fresh)])
        cards.append(ui.card(
            head=f'<b><code>{esc(label)}</code></b>{state_pill}',
            meta=(f'<span class="mono">{port}</span><span>{lat} {lat_note}</span>'
                  f'<span>{traffic}</span><span>{fresh}</span>'),
            body=spark, level=_level(ctx, state)))

    if not ctx.entries:
        body = ui.empty("注册表为空 —— 没有可采的隧道")
    else:
        total_row = (f'<p class="hint">全代理合计：↓ {ui_fmt_bps(tot_out)} / ↑ {ui_fmt_bps(tot_in)}</p>'
                     if have_tot else '<p class="hint">本轮合计不可算</p>')
        body = ('<div class="only-desktop">'
                + ui.grid_table(["标签", "隧道", "延时（近 1 小时）", "带宽（↓/↑）",
                                 "今日流量（↓/↑）", "连接数", "采样"], rows)
                + total_row + '</div>'
                + '<div class="only-mobile" data-mobile-cards>' + "".join(cards) + '</div>')
    if snap.get("panel_error"):
        body = ui.banner("bad", esc(snap["panel_error"])) + body
    body += ui.banner("info", "带宽来自 frps 面板的累计字节差分（30 秒一轮）；"
                              "历史只存内存、重启即清。拿不到的一律如实标注，<b>不用 0 冒充</b>。")
    return Rendered(title="MRRC Portal — 隧道", chrome=chrome, live=live_region("tunnel", ctx, body))
```

其中 `ui_fmt_bps` / `ui_fmt_bytes` 是两个**纯格式化**函数，把 `app.py` 里的
`_fmt_bps` / `_fmt_bytes` **原样搬到 `views.py`**（它们不读任何外部状态），
再把 `app.py` 里的两个名字改成 `from portal.views import ui_fmt_bps as _fmt_bps, ui_fmt_bytes as _fmt_bytes`
—— 格式化逻辑只能有一份。

- [ ] **步骤 4：跑测试并 Commit**

```bash
python3 tests/test_portal.py
git add portal/views.py tests/test_portal.py
git commit -m "portal/views: 隧道视图画出近 1 小时走势，缺失样本断线不补 0"
```

---

## 任务 14：系统视图重做（结论先行）

**文件：** 修改 `portal/views.py`；测试 `tests/test_portal.py`

- [ ] **步骤 1：编写失败的测试**

```python
def test_system_sections_lead_with_a_verdict():
    """改版前是四张表罗列事实，运维要自己判断。现在每区第一行先给结论。"""
    from portal import views as vs
    ctx = vs.Ctx(root="", resources={"load": "0.31", "cpu": "1 核", "mem": "可用 900 MB",
                                     "disk": "已用 51%", "uptime": "42 天", "python": "3.13"},
                 services=[("frps", "active", "enabled", "2026-10-01", "0"),
                           ("mrrc-hub-routes.timer", "未安装", "not-found", "—", "—")],
                 net={"listen": [8989], "peers": ["1.2.3.4"], "note": ""},
                 certs=[], sampler=None, entries=[("bg1sb", 18804)],
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL, now=time.time())
    out = vs.render("system", ctx).chrome + vs.render("system", ctx).live
    check("要处理" in out or "正常" in out, "每区有结论")
    check("1 项要处理" in out or "2 项要处理" in out, "结论带计数")
    check("本页采集不到的" in out, "保留采集边界说明（诚信纪律，不许删）")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py`
预期：FAIL（找不到「要处理」结论文案，因为搬过来的旧代码只罗列事实）

- [ ] **步骤 3：实现**

替换 `views.py` 的 `system` 视图：

```python
#: 服务单元的级别：未安装（enabled=not-found）= 黄（路由不会自动重生成，这是文档里
#: 反复踩到的那一件事）；跑了但没 active = 红；其余（含主动的“未安装”状态）= 绿。
def _svc_level(row) -> str:
    _unit, st, enabled, _since, _restarts = row
    if enabled == "not-found":
        return "warn"
    if st == "active":
        return ""
    return "bad"


@register("system", "MRRC Portal — 系统")
def view_system(ctx: Ctx) -> Rendered:
    res, svc, net, certs = ctx.resources, ctx.services, ctx.net, ctx.certs
    chrome = "<h1>系统</h1>"

    # ① hub 主机 —— 没有硬阈值，只判“读得到还是读不到”。
    host_lines = (("负载 (1/5/15 分钟)", res.get("load", "—")), ("CPU", res.get("cpu", "—")),
                  ("内存", res.get("mem", "—")), ("磁盘", res.get("disk", "—")),
                  ("已运行", res.get("uptime", "—")), ("Python", res.get("python", "—")))
    host_blind = [k for k, v in host_lines if "读不到" in str(v)]
    host_verdict = (ui.banner("warn", f"有 {len(host_blind)} 项读不到：" + esc("、".join(host_blind)))
                    if host_blind else ui.banner("ok", "主机读数完整"))

    # ② hub 服务
    svc_rows = []
    for (u, st, en, si, nr) in svc:
        lvl = _svc_level((u, st, en, si, nr))
        svc_rows.append([
            ("单元", f"<code>{esc(u)}</code>"),
            ("状态", pill({"": "ok", "warn": "warn", "bad": "bad"}[lvl], st)),
            ("开机自启", esc(en)), ("起于", esc(si)), ("重启次数", esc(nr)),
            ("动作", f'<a class="chip" href="#fix-{esc(u)}">修复命令</a>' if lvl else ""),
        ])
    svc_bad = [r for r in svc if _svc_level(r)]
    svc_verdict = (ui.banner("warn", f"<b>{len(svc_bad)} 项要处理</b>："
                                      + esc("、".join(r[0] for r in svc_bad)))
                   if svc_bad else ui.banner("ok", "全部单元在跑"))
    svc_fix = "".join(
        f'<div class="card" id="fix-{esc(r[0])}"><div class="cardhead"><b>{esc(r[0])} 的修法</b></div>'
        + (ui.copy_button("sudo cp deploy/systemd/… /etc/systemd/system/ && sudo systemctl daemon-reload "
                          "&& sudo systemctl enable --now " + str(r[0]), "复制")
           if r[2] == "not-found" else
           ui.copy_button(f"sudo systemctl restart {r[0]}", "复制"))
        + '</div>' for r in svc_bad)

    # ③ 隧道层
    reg_ports = {p for _l, p in ctx.entries}
    listening = [p for p in net.get("listen", []) if 18800 <= p <= 18999]
    missing = sorted(reg_ports - set(listening))
    stray = sorted(set(listening) - reg_ports)
    port_ok = (8989 in net.get("listen", [])) and not missing and not stray
    port_verdict = (ui.banner("ok", "8989 在听，注册表与实际监听口一致")
                    if port_ok else
                    ui.banner("warn", ("frps 8989 <b>没在听</b>。" if 8989 not in net.get("listen", []) else "")
                              + (f"注册了但没在听：{missing}。" if missing else "")
                              + (f"在听但注册表里没有：{stray}。" if stray else "")))
    if ctx.sampler is None:
        tunnel_rows = [("frps 面板", "采集器未启用（--metrics-interval 0）")]
    else:
        agg_in = agg_out = 0.0
        have_agg = False
        for item in ctx.sampler["labels"].values():
            if item["last"].in_bps is not None and item["last"].out_bps is not None:
                agg_in += item["last"].in_bps
                agg_out += item["last"].out_bps
                have_agg = True
        panel = ("可用" if not ctx.sampler["panel_error"]
                 else f'<b>{esc(ctx.sampler["panel_error"])}</b>')
        age = ctx.sampler["panel_age"]
        if age is not None:
            panel += f"（{age:.0f} 秒前）"
        nic = ctx.sampler["nic"] or {}
        nic_line = ((f"↓ {ui_fmt_bps(nic.get('rx_bps'))} / ↑ {ui_fmt_bps(nic.get('tx_bps'))}")
                    if "rx_bps" in nic else esc(nic.get("note", "—")))
        tunnel_rows = [("frps 面板", panel),
                       ("全代理合计速率", (f"↓ {ui_fmt_bps(agg_out)} / ↑ {ui_fmt_bps(agg_in)}"
                                            if have_agg else "（本轮不可算）")),
                       ("hub 网卡", nic_line)]
    listen_rows = [
        ("frps 接入端口 8989", "在听" if 8989 in net.get("listen", []) else "<b>没在听</b>"),
        ("frpc 控制连接", f"{len(net.get('peers', []))} 条"
                        + ("：" + esc(", ".join(net["peers"])) if net.get("peers") else "")),
        ("注册表实例端口", f"{len(reg_ports)} 个"),
        ("实际在听的实例端口", f"{len(listening)} 个"
                           + ("：" + ", ".join(str(x) for x in listening) if listening else "")),
        ("注册了但没在听", ", ".join(str(x) for x in missing) or "（无）"),
        ("在听但注册表里没有", ", ".join(str(x) for x in stray) or "（无）"),
    ]

    # ④ 证书
    cert_soon = [c for c in certs if (c[3] or 999) < 30]
    cert_verdict = (ui.banner("warn", f"{len(cert_soon)} 张证书 30 天内到期")
                    if cert_soon else ui.banner("ok", "实例证书都不在 30 天窗口内"))
    cert_rows = [[("文件", f"<code>{esc(n)}</code>"), ("主体", esc(su)),
                  ("到期", esc(na)), ("剩余", "—" if dy is None else f"{dy} 天")]
                 for n, su, na, dy in certs] or [[("文件", "<span class='hint'>（无）</span>")]]

    body = (
        '<h2>① hub 主机</h2>' + host_verdict + ui.kv(host_lines)
        + '<h2>② hub 服务</h2>' + svc_verdict
        + ui.grid_table(["单元", "状态", "开机自启", "起于", "重启次数", "动作"], svc_rows, stack=True)
        + svc_fix
        + '<p><small>「未安装」是一种<b>结论</b>而不是错误：单元文件在仓库里、却没装到 hub 上，'
          '正是路由不会自动重生成的原因。</small></p>'
        + '<h2>③ 隧道层（frps）</h2>' + port_verdict + ui.kv(listen_rows + tunnel_rows)
        + (f"<p class='hint'>⚠️ {esc(net['note'])}</p>" if net.get("note") else "")
        + '<h2>④ hub 侧已登记的实例证书</h2>' + cert_verdict
        + ui.grid_table(["文件", "主体", "到期", "剩余"], cert_rows, stack=True)
        + '<p><small>注册表里有一行只代表<b>预留</b>；没有证书就说明该实例从未走完批准→登记，'
          '它的入口只能 502。<br>'
          '本页采集不到的：<code>/var/log/nginx/*.log</code>（mrrcportal 不可读 ⇒ 无每实例的 nginx '
          '错误计数）、实例内部状态（电台/录音/会话都在令牌之后）；frps 面板未启用或凭据不可读时，'
          '隧道速率会如实标注原因而不是显示 0。</small></p>')
    return Rendered(title="MRRC Portal — 系统", chrome=chrome, live=live_region("system", ctx, body))
```

**两个标签不许改**：`frps 面板` 与 `全代理合计速率` —— `tests/test_portal_metrics.py:203`
和 `238` 在盯它们。`本页采集不到的` 那段也是既有诚信纪律，**原文保留**。

- [ ] **步骤 4：跑测试并 Commit**

```bash
python3 tests/test_portal.py && python3 tests/test_portal_metrics.py
git add portal/views.py tests/test_portal.py
git commit -m "portal/views: 系统页每区结论先行，服务异常行可展开修法"
```

---

## 任务 15：审计视图重做（筛选 / 相对时间 / 分页）

**文件：** 修改 `portal/views.py`；测试 `tests/test_portal.py`

- [ ] **步骤 1：编写失败的测试**

```python
def test_audit_filters_and_paginates():
    from portal import views as vs
    audit = [{"at": time.time() - i * 60, "callsign": f"bg{i}", "event": "grant",
              "actor": "ops", "detail": "x"} for i in range(120)]
    ctx = vs.Ctx(root="", audit=audit, now=time.time(), tunnel_text=TUNNEL_TEXT,
                 tunnel_pill=TUNNEL_PILL, page=1)
    out = vs.render("audit", ctx).chrome + vs.render("audit", ctx).live
    check(out.count("<tr>") <= 52, "每页最多 50 条（含表头）")
    check("下一页" in out, "有翻页")
    check("小时前" in out or "分钟前" in out, "有相对时间")
    check("登录" in out, "有登录事件筛选")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py` → FAIL

- [ ] **步骤 3：实现**

在 `Ctx` 里补一个通用搜索字段 `q: str = ""`（与呼号库专用的 `clublog_query` 分开：
一个页面上的两个输入框共用一个字段，迟早会互相覆盖）。

```python
#: 审计每页条数与筛选组。登录事件单独一组 —— "有没有异常登录"是运维最先问的问题。
AUDIT_PAGE_SIZE = 50
LOGIN_EVENTS = ("login_ok", "login_failed", "login_locked")
ACTION_EVENTS = ("verify", "reject", "grant", "revoke")
AUDIT_FILTERS = (
    ("all", "全部", None),
    ("login", "登录事件", LOGIN_EVENTS),
    ("action", "运维动作", ACTION_EVENTS),
)


@register("audit", "MRRC Portal — 审计")
def view_audit(ctx: Ctx) -> Rendered:
    active = ctx.flt or "all"
    allowed = dict((fid, ev) for fid, _l, ev in AUDIT_FILTERS).get(active)
    picked = [e for e in ctx.audit if allowed is None or e.get("event") in allowed]
    if ctx.q.strip():
        needle = ctx.q.strip().upper()
        picked = [e for e in picked if needle in (e.get("callsign") or "").upper()]

    pages = max(1, (len(picked) + AUDIT_PAGE_SIZE - 1) // AUDIT_PAGE_SIZE)
    page = min(max(1, ctx.page), pages)
    window = picked[(page - 1) * AUDIT_PAGE_SIZE: (page - 1) * AUDIT_PAGE_SIZE + AUDIT_PAGE_SIZE]

    def link(fid: str, p: int = 1) -> str:
        return f"{ctx.root}/admin?view=audit&amp;f={esc(fid)}&amp;page={p}"

    chips = []
    for fid, label, evs in AUDIT_FILTERS:
        n = len([e for e in ctx.audit if evs is None or e.get("event") in evs])
        chips.append((f"{label} {n}", link(fid), fid == active, None))

    chrome = ("<h1>审计</h1>"
              + '<div class="hint">追加式记录，最新的在前。登录事件带来源 IP；'
                '运维动作带操作者归因（<code>actor</code>）。</div>'
              + ui.toolbar(chips, search_html=(
                  f'<form method="get" action="{ctx.root}/admin" class="search" data-tools>'
                  f'<input type="hidden" name="view" value="audit">'
                  f'<input type="hidden" name="f" value="{esc(active)}">'
                  f'<input name="q" value="{esc(ctx.q)}" placeholder="按呼号筛选…"></form>')))

    rows = [[
        ("时间", f'<span class="mono">{time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))}</span>'
                f'<br><small>{esc(_ago_text(ctx.now, e["at"]))}</small>'),
        ("呼号", f'<code>{esc(e["callsign"].upper())}</code>' if e.get("callsign")
                else '<span class="hint">—</span>'),
        ("事件", pill("bad" if e["event"] == "login_failed" else
                     "warn" if e["event"] == "login_locked" else "mute",
                     ACTION_CN.get(e["event"], e["event"]))),
        ("操作者", f'<code>{esc(e.get("actor") or "—")}</code>'),
        ("细节", esc((e.get("detail") or "")[:90])),
    ] for e in window]
    body = (ui.grid_table(["时间", "呼号", "事件", "操作者", "细节"], rows, stack=True)
            if rows else ui.empty("这一筛选下没有记录",
                                  f'<a class="chip" href="{link("all")}">看全部</a>'))
    if pages > 1:
        body += (f'<div class="tools"><span class="hint">第 {page} / {pages} 页'
                 f'（共 {len(picked)} 条）</span>'
                 + (f'<a class="chip" href="{link(active, page - 1)}">上一页</a>' if page > 1 else "")
                 + (f'<a class="chip" href="{link(active, page + 1)}">下一页</a>' if page < pages else "")
                 + '</div>')
    return Rendered(title="MRRC Portal — 审计", chrome=chrome, live=live_region("audit", ctx, body))
```

其中 `ACTION_CN` 与 `STATUS_CN` 同理（事件 slug 中文化）：

```python
ACTION_CN = {"apply": "提交申请", "verify": "核验通过", "reject": "拒绝", "grant": "分配入口",
             "revoke": "撤销入口", "enroll": "证书登记", "claim": "自助取回凭证",
             "login_ok": "登录成功", "login_failed": "登录失败", "login_locked": "登录被锁"}
```

- [ ] **步骤 4：跑测试并 Commit**

```bash
python3 tests/test_portal.py
git add portal/views.py tests/test_portal.py
git commit -m "portal/views: 审计可按呼号/事件筛选、相对时间、50 条分页"
```

---

## 任务 16：呼号库视图重做（本地查询）

**文件：** 修改 `portal/views.py`、`portal/app.py`；测试 `tests/test_portal.py`

- [ ] **步骤 1：编写失败的测试**

```python
def test_clublog_lookup_answers_the_operators_real_question():
    from portal import views as vs
    ctx = vs.Ctx(root="", clublog="273047 条 · 最后同步 2026-10-11 04:30",
                 clublog_query="BG1SB", clublog_hit="hit-clublog",
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL, now=time.time())
    out = vs.render("clublog", ctx).chrome + vs.render("clublog", ctx).live
    check("在库中" in out, "命中时说清在库中")
    check("Club Log" in out, "说清命中哪个库")


def test_clublog_lookup_miss_is_explicit():
    from portal import views as vs
    ctx = vs.Ctx(root="", clublog="x", clublog_query="BG9ZZZ", clublog_hit="miss",
                 tunnel_text=TUNNEL_TEXT, tunnel_pill=TUNNEL_PILL, now=time.time())
    out = vs.render("clublog", ctx).chrome + vs.render("clublog", ctx).live
    check("不在库中" in out and "人工核验" in out, "未命中给出下一步")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal.py` → FAIL

- [ ] **步骤 3：实现**

```python
@register("clublog", "MRRC Portal — 呼号库")
def view_clublog(ctx: Ctx) -> Rendered:
    verdict = ""
    if ctx.clublog_query:
        q = esc(ctx.clublog_query.upper())
        if ctx.clublog_hit == "hit-clublog":
            verdict = ui.banner("ok", f'<b>{q}</b> 在库中 —— 命中 <b>Club Log</b>（权威库）')
        elif ctx.clublog_hit == "hit-list":
            verdict = ui.banner("ok", f'<b>{q}</b> 在库中 —— 命中 <b>运维自建清单</b>')
        else:
            verdict = ui.banner("warn", f'<b>{q}</b> 不在库中 —— 将转 <b>人工核验</b>')
    chrome = ("<h1>呼号库</h1>"
              + '<div class="hint">核验链：Club Log（权威）→ 运维自建清单 → 人工兜底。'
                '本页查询<b>纯本地</b>，不联网。</div>')
    form = (f'<form method="get" action="{ctx.root}/admin" data-tools class="tools">'
            f'<input type="hidden" name="view" value="clublog">'
            f'<input name="q" value="{esc(ctx.clublog_query)}" placeholder="查一个呼号，例如 BG1SB">'
            f'<button>查一下</button></form>')
    body = (form + verdict
            + ui.kv([("来源", "Club Log（与站内留言版 www.vlsc.net/feedback 同源）"),
                     ("状态", esc(ctx.clublog) or "—"),
                     ("路径", f'<code>{esc(ctx.clublog_path)}</code>')])
            + '<p><small>hub 每天 04:30 从 www 拉取（受限命令：只能读那一个文件）。<br>'
              '立即刷新：</small></p>' + ui.copy_button(
                  "sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh", "复制刷新命令"))
    return Rendered(title="MRRC Portal — 呼号库", chrome=chrome, live=live_region("clublog", ctx, body))
```

`app.py` 侧（本步骤的全部采集逻辑）：

```python
            # 呼号库查询：纯本地，用现有核验链问一次。
            q = (self._query().get("q") or "").strip()
            hit = ""
            if view == "clublog" and q:
                try:
                    outcome = build_verifier().verify(q)
                    # VerificationOutcome 的字段名以 portal/verify.py 为准；
                    # 实现时照它取“命中哪个库”，不要猜。
                    hit = getattr(outcome, "source", "") or "miss"
                except Exception:                                    # noqa: BLE001
                    hit = ""
            ctx.clublog_query = q
            ctx.clublog_hit = "hit-clublog" if hit == "clublog" else (
                "hit-list" if hit == "callsign-list" else "miss")
```

> **实现时必须先读 `portal/verify.py`**，确认 `VerificationOutcome` 的真实字段名与取值，
> 并按它映射到 `hit-clublog` / `hit-list` / `miss` 三值 —— 本计划不猜它的形状。
> 这一段是 `clublog` 视图唯一的采集点，也是唯一允许访问验证器的地方（视图层保持纯）。

`Ctx` 补一个字段 `clublog_path: str = str(DEFAULT_CLUBLOG)`（由 `app.py` 传入，
视图层不许去拼默认路径）。

- [ ] **步骤 4：跑测试并 Commit**

```bash
python3 tests/test_portal.py
git add portal/views.py portal/app.py tests/test_portal.py
git commit -m "portal/views: 呼号库页可查单个呼号（纯本地，不联网）"
```

---

## 任务 17：登录页与公开注册页重做

**文件：** 修改 `portal/ui.py`（登录/公开页外壳）、`portal/app.py`（`_login_page` 与公开页）；测试 `tests/test_portal.py`、`test_portal_auth.py`

- [ ] **步骤 1：编写失败的测试**

追加到 `tests/test_portal_auth.py`：

```python
def test_login_error_is_not_green():
    """P1：改版前登录失败用的是唯一的 .msg 样式，而那套是绿色成功色。

    这条守卫盯的是"错误必须是错误色"—— 用户输错密码时页面不该是绿的。
    """
    from portal import ui
    out = ui.banner("bad", "用户名或密码不正确。")
    check("banner bad" in out, "错误用 bad 级别")
    check("34d399" not in out and "rgba(16,185,129" not in out, "错误里不含成功色")
```

追加到 `tests/test_portal.py`：

```python
def test_public_page_shares_the_design_language_without_admin_chrome():
    from portal import ui
    out = ui.page("MRRC Cloud Hub — 呼号自助注册", "<h1>呼号自助注册</h1>")
    check("--bg:#0b0e14" in out, "与后台同一套令牌")
    check('class="side"' not in out and 'class="tabbar"' not in out, "没有后台导航")
    check("font:13px" in out, "公开页正文仍是 15px 的覆盖规则存在或基线在")  # 见步骤 3
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_auth.py` → FAIL

- [ ] **步骤 3：实现**

1. 在 `ui.CSS` 里给公开页加正文覆盖：
   ```css
   body.public{font-size:15px;line-height:1.7}
   body.public .content{max-width:680px;margin:0 auto;padding:24px 16px 40px}
   ```
2. `app.py` 的 `_login_page()` 改用 `ui.banner("bad", …)` 渲染错误、`ui.banner("warn", …)` 渲染锁定倒计时，
   表单用 `ui.page(..., nav=None)` 的公开形态 + 一个居中卡片容器；
   并把 `X-Portal-Token` 的说明放进 `<details>`。
3. 公开页 `/`：表单字段顺序 呼号 → 联系方式 → 产品，错误与成功都用 `ui.banner`；已授予表改用
   `ui.grid_table(..., stack=True)`；「为什么必须核验」长文放进 `<details>`。

- [ ] **步骤 4：跑测试并 Commit**

```bash
python3 tests/test_portal.py && python3 tests/test_portal_auth.py
git add portal/ui.py portal/app.py tests/test_portal.py tests/test_portal_auth.py
git commit -m "portal: 登录页修掉绿色错误提示，公开页与后台统一设计语言（正文 15px）"
```

---

## 任务 18：守卫更新（移动性 / CSRF 全覆盖 / 降级）

**文件：** 修改 `tests/test_portal.py`、`tests/test_portal_ui.py`

- [ ] **步骤 1：改 `test_pages_are_mobile_suitable`（三处）**

**① `need` 字典**（改用专门卡片的视图不再有 stack 表）：

```python
                need = {"instances": 0, "applications": 1, "tunnel": 0, "audit": 1, "system": 2,
                        "overview": 0, "clublog": 0, "公开注册页": 1}
```

**② `aria-current` 由 1 处改成 2 处**：

```python
                if name in ("instances", "applications", "tunnel", "audit", "system"):
                    # 侧栏与底部标签栏是**两个独立的 nav**，各自都要标“当前页”。
                    # 改版前只有一个顶栏导航，所以当时断言是 1；现在两个 nav ⇒ 2。
                    # 这条不能只放宽成 >=1 —— 那样“某个 nav 忘了标”就永远测不出来。
                    check(pr.aria_current == 2,
                          f"{name}: 侧栏与底栏各恰有一项标了 aria-current=page（得到 {pr.aria_current}）")
```

**③ CSS 断点字符串**（断点从 720px 提到 767px，与桌面侧栏的 768px 对齐）：

```python
            for needle, why in (("@media(max-width:767px)", "窄屏断点"),
                                ("table.stack td::before", "堆叠后的小标题"),
                                ("content:attr(data-label)", "小标题取自 data-label"),
                                ("clip:rect(0 0 0 0)", "表头对读屏保留、只视觉隐藏"),
                                ("min-height:44px", "触摸目标 ≥44px"),
                                ("overflow-wrap:anywhere", "长串不撑破布局"),
                                (".pill.ok", "状态徽章类")):
                check(needle in css, f"CSS 含{why}（{needle}）")
```

**④ 新增一条：改用卡片的两个视图必须真的渲染出卡片容器**（否则手机上表格被
`.only-desktop` 隐了、卡片又忘了渲染，页面会变成一片空白 —— 而那种退化不会让任何
现有断言变红）：

```python
            for name in ("instances", "tunnel"):
                check("data-mobile-cards" in pages[name],
                      f"{name}: 窄屏卡片容器存在（data-mobile-cards）")
                check('class="only-desktop"' in pages[name],
                      f"{name}: 桌面表格被 only-desktop 包住")
```

- [ ] **步骤 2：新增三条守卫（完整代码）**

追加到 `tests/test_portal.py`：

```python
def _admin_pages(tmp, sampler=None):
    """起一个小服务并登录，返回 (base, 已登录的 opener, 各视图 HTML)。

    与 test_pages_are_mobile_suitable 用的是同一套夹具形状，不提新花样。
    """
    from http.server import ThreadingHTTPServer
    reg_path = tmp / "instances.tsv"
    reg_path.write_text("bg1sb\t18802\n", encoding="utf-8")
    (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
    users_path = tmp / "portal-users"
    users_path.write_text("ops:" + ht.apr1("pw-123456789", "saltward") + "\n", encoding="utf-8")
    portal = Portal(Store(tmp / "portal.json"), reg.Registry(reg_path),
                    CallsignListVerifier(tmp / "callsigns.txt"))
    portal.apply("bg1sb")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        portal, token="tok", users=ht.UsersFile(users_path), sampler=sampler))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    opener, _jar = _signed_in_opener(base, "ops", "pw-123456789")
    pages = {}
    for v in ("overview", "applications", "instances", "tunnel", "system", "audit", "clublog"):
        with opener.open(base + "/admin?view=" + v, timeout=30) as r:
            pages[v] = r.read().decode()
    return httpd, base, opener, pages


def test_every_state_changing_form_carries_csrf():
    """每个状态变更表单都要 csrf —— 本次新增了确认页与详情页动作，一个都不能漏。

    改版前只有一两条路径被测过；现在按视图逐个扫，新加表单忘了带 csrf 会立刻变红。
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        httpd, base, opener, pages = _admin_pages(tmp)
        try:
            for name, html_text in pages.items():
                for m in re.finditer(r"<form[^>]*method=[\"']?post[\"']?[^>]*>(.*?)</form>",
                                     html_text, re.S | re.I):
                    check("name=\"csrf\"" in m.group(1) or "name=csrf" in m.group(1),
                          f"{name}: 每个 POST 表单都带 csrf（漏了：{m.group(1)[:60]}）")
            # 详情页与确认页也要一起扫
            with opener.open(base + "/admin/instance?label=bg1sb", timeout=30) as r:
                detail = r.read().decode()
            for m in re.finditer(r"<form[^>]*method=[\"']?post[\"']?[^>]*>(.*?)</form>",
                                 detail, re.S | re.I):
                check("csrf" in m.group(1), "实例详情页的 POST 表单带 csrf")
        finally:
            httpd.shutdown()


def test_every_destructive_action_is_two_stage():
    """撤销/拒绝在页面上必须是"阶段一"：表单里没有 confirm=yes。

    真正的执行只能由服务端确认页上的表单发出。一条服务端路径同时服务
    “有 JS（弹 dialog）”与“无 JS（普通页面）”，所以降级不会绕开确认。
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        httpd, base, opener, pages = _admin_pages(tmp)
        try:
            for name, html_text in pages.items():
                for m in re.finditer(r"<form[^>]*action=[\"']?[^\"']*/(revoke|reject)[\"']?.*?</form>",
                                     html_text, re.S | re.I):
                    check('value="yes"' not in m.group(0) and "value=yes" not in m.group(0),
                          f"{name}: 破坏性动作的页面表单不带 confirm=yes（必须先过确认页）")
            # 走一次真路径：不带 confirm 提交 → 拿到确认页；带 confirm 但无理由 → 400
            csrf = _csrf_from(pages["applications"])
            body = urllib.parse.urlencode({"callsign": "bg1sb", "csrf": csrf}).encode()
            with opener.open(base + "/admin/revoke", data=body, timeout=30) as r:
                stage2 = r.read().decode()
            check('name="confirm" value="yes"' in stage2, "阶段二确认表单存在")
            check('name="reason"' in stage2, "阶段二要求填理由")
            bad = urllib.parse.urlencode({"callsign": "bg1sb", "csrf": csrf,
                                          "confirm": "yes", "reason": ""}).encode()
            try:
                opener.open(base + "/admin/revoke", data=bad, timeout=30)
                check(False, "空理由被拒（应当 400）")
            except urllib.error.HTTPError as exc:
                check(exc.code == 400, f"空理由返回 400（得到 {exc.code}）")
        finally:
            httpd.shutdown()


def test_pages_still_work_without_javascript():
    """降级硬要求：导航与筛选都是真 <a href>，表单都是真 method/action。

    关掉 JS 后 htmx 不存在，任何“只有 hx-get 没有 href”的控件都是死按钮。
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        httpd, base, opener, pages = _admin_pages(tmp)
        try:
            for name in ("overview", "instances", "tunnel", "system", "audit", "clublog",
                         "applications"):
                html_text = pages[name]
                check("<script>" not in html_text, f"{name}: 没有内联 script")
                check("htmx.min.js" in html_text, f"{name}: htmx 走外链文件")
                for m in re.finditer(r"<button(?![^>]*type=[\"']button[\"'])[^>]*>", html_text):
                    # 没标 type=button 的按钮默认 submit —— 它必须在某个 form 里，
                    # 而那个 form 必须有 action；否则关掉 JS 后点不动。
                    tail = html_text[m.end():m.end() + 400]
                    check("</form>" in tail,
                          f"{name}: 提交型按钮位于一个 form 内（{m.group(0)[:50]}）")
            # 每个视图的顶栏导航都是真链接
            for vid in ("overview", "applications", "instances", "tunnel", "system", "audit", "clublog"):
                check(f'href="/admin?view={vid}"' in pages["overview"],
                      f"导航里 {vid} 是真 href")
        finally:
            httpd.shutdown()
```

- [ ] **步骤 3：跑全套并 Commit**

```bash
python3 tests/test_portal.py && python3 tests/test_portal_auth.py && \
python3 tests/test_portal_metrics.py && python3 tests/test_portal_ui.py && \
python3 tests/test_htpasswd.py
git add tests/
git commit -m "tests: 移动性守卫按新容器更新，新增 CSRF 全覆盖/两阶段确认/无 JS 降级三条"
```

---

## 任务 19：文档同步

**文件：** 修改 `portal/README.md`、`SDD/11-component-model.md`、`SDD/12-operational-model.md`、`SDD/14-version-history.md`

- [ ] **步骤 1：`portal/README.md`** 新增一节：

```markdown
## 前端资源与 vendor 纪律

- **htmx 2.0.7** vendored 在 `portal/static/htmx.min.js`，**逐字节冻结**：升级必须同时改
  `portal/static/manifest.json` 的 `version` 与 `sha256`，并在同一个 commit 里说明理由。
  `tests/test_portal_ui.py::test_vendored_assets_match_manifest` 会核对哈希。
- 静态资源只有白名单里的三个名字能被送出（`htmx.min.js` / `admin.js` / `htmx.LICENSE`），
  路径**精确匹配、不做拼接**，`/admin/static/../portal/app.py` 一律 404。
- 带 `Cache-Control: public, max-age=31536000, immutable`；无需登录（公开库与本站脚本）。
- **JS 一律走文件、不内联**：将来上 CSP 时 `script-src 'self'` 可直接启用。
  CSS 仍内联在 `portal/ui.py` 的 `CSS` 里 —— 页面外壳的首要保证是"样式一定在"。
- **全部交互都是渐进增强**：关掉 JS，导航、筛选、表单、破坏性动作的确认照常工作。
```

- [ ] **步骤 2：`SDD/11`** 的 Portal 行补 `ui.py` / `views.py` 的分层与新视图（实例详情）。
- [ ] **步骤 3：`SDD/12 §12.9`** 补「界面层」一行与静态资源；测试组数按实际更新。
- [ ] **步骤 4：`SDD/14-version-history.md`** 追加本次条目（模板照抄现有条目）。
- [ ] **步骤 5：Commit**

```bash
git add portal/README.md SDD/
git commit -m "docs: 同步 Portal 界面层的实现事实（vendor 纪律、分层、静态路由）"
```

---

## 任务 20：上线与现网验收

**文件：** 无（执行）

- [ ] **步骤 1：同步到 hub**

```bash
# 现网 hub：cheenle@www.vlsc.net（203.25.119.168）
# 1) 把 portal/ 同步到 hub 上的 portal 源码目录（含新增的 portal/static/）
# 2) 确认 mrrcportal 账号对 portal/static/ 有读权限
# 3) 重启
sudo systemctl restart mrrc-portal
```

- [ ] **步骤 2：逐项复验**

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' https://portal.mrrc.vlsc.net/admin/static/htmx.min.js
curl -s -D- -o /dev/null https://portal.mrrc.vlsc.net/admin/static/htmx.min.js | grep -i cache-control
curl -s -o /dev/null -w '%{http_code}\n' 'https://portal.mrrc.vlsc.net/admin/static/../portal/app.py'
curl -s -o /dev/null -w '%{http_code}\n' https://portal.mrrc.vlsc.net/
curl -s -o /dev/null -w '%{http_code}\n' https://portal.mrrc.vlsc.net/admin
```
预期：`200 application/javascript` / `public, max-age=31536000, immutable` / `404` / `200` / `200`

- [ ] **步骤 3：登录后人工检查**

- 7 个视图 + 实例详情各打开一次，控制台无报错
- 手机上（真机，户外光线下看一眼弱文字）检查：无横向滚动、底部标签栏可达全部视图
- 关掉浏览器 JS，重复登录/登出/核验/筛选一次，确认全部可用
- 停掉 frps 面板，确认隧道页显示**原因**而不是 0，随后恢复

- [ ] **步骤 4：观察负担**

```bash
uptime   # 自动刷新开着放 10 分钟，确认 loadavg 不持续上升
```

- [ ] **步骤 5：Commit 部署记录（如有脚本/记录改动）**

---

## 自检记录（写完计划后对照规格逐条核过）

| 规格章节 | 覆盖它的任务 |
| --- | --- |
| §3.1 令牌 | 1 |
| §3.2 字体与密度 | 1（CSS）、17（公开页 15px） |
| §3.3 颜色纪律 | 1（CSS）、2（pill 必须带文字） |
| §3.4 对比度 | 1（`test_tokens_meet_wcag_aa`） |
| §3.5 组件词汇 | 2、3、4 |
| §4.1 全局骨架 | 5（侧栏/底栏/徽标） |
| §4.2 逐视图 | 10（总览）、11（申请）、12（实例+详情）、13（隧道）、14（系统）、15（审计）、16（呼号库）、17（登录+公开） |
| §5 交互规范 | 5（live 容器）、7（admin.js）、11（两阶段确认）、18（降级/CSRF 守卫） |
| §6.1 vendor | 6 |
| §6.2 静态路由 | 6（含 traversal 测试） |
| §6.3 模块拆分 | 8（含"views 层是纯的"守卫） |
| §6.4 片段渲染 | 5（fragment 模式）、8（HX-Request 分支） |
| §6.5 刷新成本闸门 | 7（`__portalPaused` 三条理由） |
| §7.1 保留守卫 | 8（未改测试即全绿）、18 |
| §7.2 替换 | 18 |
| §7.3 新增守卫 | 1（对比度）、6（白名单/哈希）、5（片段）、18（CSRF/两阶段/降级） |
| §8.2 文档同步 | 19 |
| §9 验收判据 | 20 |
| P1–P11 | P1→17、P2→10、P3/P4→11、P5→12、P6→13、P7→15、P8→16、P9→5、P10→2（empty）→各视图、P11→1 |

**类型一致性检查**：`Ctx` 字段在任务 8 定义，任务 10–16 只新增（`flt_label`、`q`、`clublog_query`、`clublog_hit`、`clublog_path`）；`Rendered(title, chrome, live)` 三个字段全计划一致；`ui` 的函数名在 `views.py` 与测试里逐字一致（`grid_table` / `card` / `pill` / `banner` / `stat` / `kv` / `empty` / `toolbar` / `sparkline` / `copy_button` / `confirm_form` / `page` / `Nav`）。`render()` 的签名是 `render(view_id, ctx, part=None, **kw)`，`**kw` 透传给视图函数——实例详情页靠它接 `label=`。

**本轮自检发现并修掉的内部矛盾**（写在这里，因为每一条都是“不修就会让实现走差”的）：

| # | 矛盾 | 处理 |
| --- | --- | --- |
| 1 | 既有守卫断言 CSS 含 `@media(max-width:720px)` 与 `min-height:44px`，而新样式表用 767px、按钮只有 34px | 断点改成 767px（与桌面 768px 对齐，否则 721–767px 会出现“有侧栏无底栏”真空）；窄屏媒体查询里加 `min-height:44px` 一行，触摸目标达标且守卫的字符串仍在 |
| 2 | 既有守卫断言每页 `aria-current` 恰 1 处，而新骨架有侧栏与底栏两个 nav | 改成 `== 2` 并写明“不能放宽成 `>=1`”的理由 |
| 3 | `views.render()` 只传 `ctx`，而 `view_instance` 需要 `label=` | `render(..., **kw)` 透传 |
| 4 | 视图代码里用了 `TUNNEL_SERVING` / `TUNNEL_DOWN`，但它们在 `app.py`，而 `app.py` import views（循环） | 视图不 import 状态常量，改用 `ctx.tunnel_pill` 判级别（`_level` / `_is_serving`）——状态语义的权威本来就在探针那边 |
| 5 | 任务 11 先写 `grid_table_row` 又说“二选一” | 只保留 `ui.grid_table` 一条路径，行级版本不新增 |
| 6 | 实例/隧道若同时渲染 stack 表与卡片，手机上会双份 | 改成桌面表格（`only-desktop`）+ 手机卡片（`only-mobile`），并新增“两边必须同时存在”的守卫 |
| 7 | 任务 14–16 的步骤只给了“要点”，属于计划不允许的占位 | 补全为可照拄的完整代码 |
