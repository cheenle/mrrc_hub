# MRRC Cloud Hub 文档站 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 `mrrc_hub/website/` 下产出一套 5 页静态 HTML 文档站（视觉与 `www.vlsc.net` 同源、用户为主 + 单独一页设计），并全面更新仓库内 markdown 文档以消除与现网实况的矛盾。

**架构：** 纯静态、零构建。`octen.css` 从 `mrrc_modern/website/css/` 原样复制（永不 fork），本站新增样式全部隔离在 `hub.css`，行为增强全部隔离在 `hub.js`。内容事实全部取自 `docs/superpowers/specs/2026-10-01-hub-website-design.md` §2 的现场取证基线。

**技术栈：** HTML5 + CSS（复用上游设计令牌）+ 原生 JS（无框架/无打包）；Google Fonts + Font Awesome CDN（与上游一致）；Bash 部署脚本。

**规格：** `docs/superpowers/specs/2026-10-01-hub-website-design.md`

---

## 全局约定（每个任务都适用）

1. **不得出现字面 `?token=` / `?code=` / `?ticket=`**（SDD 金规则 `hub-token-not-in-url` 会扫 `**/*.html`）。讲"令牌不进 URL"时写"查询参数形式的 launch code"，或只写字段名 `code`。
2. **不发明事实**。任何 URL / 端口 / 行为都必须能指回规格 §2。无法取证的写"待核实"。
3. **未实现的东西必须带徽标** `<span class="hub-badge todo">未实现 · 阶段 2</span>`，绝不写成已完成。
4. **不修改** `deploy/*.sh`、`mrrc_modern/` 下任何文件。
5. 每个任务结束后 commit（前缀 `docs(site):` / `docs:`）。

---

## 共享片段（所有页面逐字复用）

### 共享 `<head>` 骨架

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{{PAGE_DESC}}">
<meta name="author" content="BG1SB">
<meta name="theme-color" content="#000000">
<title>{{PAGE_TITLE}} · MRRC Cloud Hub</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="css/octen.css?v=1">
<link rel="stylesheet" href="css/hub.css?v=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect fill='%2322d3ee' width='100' height='100' rx='20'/><text y='.9em' x='50%' text-anchor='middle' font-size='60'>📡</text></svg>">
</head>
```

### 共享导航（`{{ACTIVE}}` 处加 `class="active" aria-current="page"`）

```html
<body>
<a href="#main" class="hub-skip">跳到主要内容</a>
<nav class="navbar">
  <div class="container navbar-content">
    <a href="index.html" class="logo">
      <span class="logo-icon"><i class="fas fa-satellite-dish"></i></span>
      <span>MRRC <span style="color: var(--accent)">Cloud Hub</span></span>
    </a>
    <ul class="nav-links">
      <li><a href="index.html">概览</a></li>
      <li><a href="start.html">接入</a></li>
      <li><a href="use.html">使用与分享</a></li>
      <li><a href="trouble.html">排障</a></li>
      <li><a href="design.html">设计与实现</a></li>
      <li><a href="https://github.com/cheenle/mrrc_hub" target="_blank" rel="noopener"><i class="fab fa-github"></i> 源码</a></li>
    </ul>
    <div class="nav-actions">
      <a href="https://www.vlsc.net/mrrc_modern/" class="lang-btn">MRRC Modern</a>
      <button class="mobile-menu-toggle" aria-label="打开菜单" onclick="toggleMobileMenu()"><i class="fas fa-bars"></i></button>
    </div>
  </div>
</nav>
```

### 共享页脚 + 尾部

```html
<footer class="footer">
  <div class="container">
    <div class="footer-grid">
      <div class="footer-section">
        <h4>MRRC Cloud Hub</h4>
        <p>把 MRRC Modern 实例接入云端统一入口：实例主动出站、一个呼号一个入口、PTT 释放永远在电台本地执行。</p>
      </div>
      <div class="footer-section">
        <h4>文档</h4>
        <ul>
          <li><a href="index.html">概览</a></li>
          <li><a href="start.html">接入四步</a></li>
          <li><a href="use.html">使用与分享</a></li>
          <li><a href="trouble.html">排障</a></li>
          <li><a href="design.html">设计与层层实现</a></li>
        </ul>
      </div>
      <div class="footer-section">
        <h4>相关</h4>
        <ul>
          <li><a href="https://www.vlsc.net/mrrc_modern/">MRRC Modern 产品站</a></li>
          <li><a href="https://github.com/cheenle/mrrc_hub" target="_blank" rel="noopener">源码（GitHub）</a></li>
          <li><a href="https://www.vlsc.net/" target="_blank" rel="noopener">VLSC Projects</a></li>
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <p>© 2026 MRRC Cloud Hub · BG1SB</p>
      <p>事实基线：2026-10-01 现场取证 · 运营事实以 <code>SDD/12 §12.8</code> 为准</p>
    </div>
  </div>
</footer>
<button class="vlsc-to-top" id="backTop" aria-label="回到顶部"><i class="fas fa-arrow-up"></i></button>
<div class="vlsc-scroll-progress" id="scrollProgress"></div>
<script src="js/hub.js"></script>
</body>
</html>
```

---

## 任务 1：脚手架（目录 + octen.css 复制 + hub.css + hub.js）

**文件：**

- 创建：`website/css/octen.css`（复制）
- 创建：`website/css/hub.css`
- 创建：`website/js/hub.js`

- [ ] **步骤 1：复制上游样式表（原样，不 fork）**

> 源文件已取证（2026-10-01）：`mrrc_modern/website/css/octen.css` 与线上
> `https://www.vlsc.net/mrrc_modern/css/octen.css` **逐字节一致**（SHA-256
> `c53bba8c…aa3f4`），所以从仓库复制 == 从生产复制。
> 注意：门户站自己的 `/css/octen.css` 是**另一份**拷贝（`c53b…` vs `6d79…`，
> 差异仅在 `.features-grid` 列定义与 `.vlsc-gn` 移动端段落），**不要从那取**。

```bash
cd /Users/cheenle/HAM/hub
mkdir -p mrrc_hub/website/css mrrc_hub/website/js
cp mrrc_modern/website/css/octen.css mrrc_hub/website/css/octen.css
shasum -a 256 mrrc_modern/website/css/octen.css mrrc_hub/website/css/octen.css
```

预期：两个哈希完全一致。

- [ ] **步骤 2：写 `website/css/hub.css`**

```css
/* ══════════════════════════════════════════════════════════════════════
   MRRC Cloud Hub 文档站 — 本站专属样式
   ──────────────────────────────────────────────────────────────────────
   upstream 设计系统在 css/octen.css（原样复制，永不 fork —— 上游改版时
   只需重拷一份）。除 octen.css 已有类之外，本站需要的一切都写在这里，
   这样"上游 vs 本站"的差异永远是单一文件、一眼可见。
   设计令牌沿用上游：--accent #22d3ee / --bg-primary #000 / --font-mono。
   ══════════════════════════════════════════════════════════════════════ */

/* ── 跳过导航（a11y） ── */
.hub-skip {
  position: absolute; left: -9999px; top: 0; z-index: 300;
  background: var(--accent); color: #000; padding: 0.6rem 1rem;
  border-radius: 0 0 8px 0; font-weight: 600; font-size: 0.875rem;
}
.hub-skip:focus { left: 0; }

/* ── 文档页 hero（比首页 .hero 矮，抬高是为了让开 fixed navbar） ── */
.hub-hero {
  position: relative; overflow: hidden; text-align: center;
  padding: calc(var(--nav-h) + 3.5rem) 2rem 3rem;
}
.hub-hero::before {
  content: ''; position: absolute; top: -50%; left: -50%;
  width: 200%; height: 200%; pointer-events: none;
  background: radial-gradient(circle at 50% 0%, var(--accent-glow), transparent 50%);
}
.hub-hero > * { position: relative; z-index: 1; }
.hub-hero h1 {
  font-size: 2.6rem; font-weight: 700; letter-spacing: -0.03em;
  line-height: 1.2; margin-bottom: 1rem;
}
.hub-hero p {
  font-size: 1.0625rem; color: var(--text-secondary);
  max-width: 680px; margin: 0 auto; line-height: 1.75;
}
@media (max-width: 768px) {
  .hub-hero { padding: calc(var(--nav-h) + 2.5rem) 1.25rem 2rem; }
  .hub-hero h1 { font-size: 1.9rem; }
}

/* ── 文档外壳：正文列 + 粘性目录 ── */
.hub-shell {
  display: grid; grid-template-columns: minmax(0, 1fr) 230px;
  gap: 3.5rem; max-width: 1200px; margin: 0 auto; padding: 0 2rem 5rem;
}
.hub-toc {
  position: sticky; top: calc(var(--nav-h) + 2rem);
  align-self: start; max-height: calc(100vh - var(--nav-h) - 4rem);
  overflow-y: auto; padding-left: 1.25rem;
  border-left: 1px solid var(--border); font-size: 0.8125rem;
}
.hub-toc h4 {
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-muted); font-weight: 600; margin-bottom: 0.9rem;
}
.hub-toc ul { display: flex; flex-direction: column; gap: 0.15rem; }
.hub-toc a {
  display: block; color: var(--text-secondary); padding: 0.3rem 0;
  line-height: 1.5; transition: color 0.2s var(--ease);
}
.hub-toc a:hover { color: var(--text-primary); }
.hub-toc a.active { color: var(--accent); font-weight: 600; }
@media (max-width: 1100px) {
  .hub-shell { grid-template-columns: 1fr; gap: 0; }
  .hub-toc {
    position: static; max-height: none; overflow: visible;
    border-left: 0; border-bottom: 1px solid var(--border);
    padding: 0 0 1.25rem; margin-bottom: 2.5rem;
  }
}

/* ── 正文排版（octen.css 把 ul 的 list-style 清空了，这里恢复） ── */
.hub-prose { min-width: 0; }
.hub-prose > section { margin-bottom: 4rem; }
.hub-prose h2 {
  font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em;
  margin-bottom: 1.25rem; padding-bottom: 0.6rem;
  border-bottom: 1px solid var(--border);
}
.hub-prose h3 { font-size: 1.15rem; font-weight: 600; margin: 2.25rem 0 0.9rem; }
.hub-prose h4 { font-size: 1rem; font-weight: 600; margin: 1.75rem 0 0.6rem; }
.hub-prose p { color: var(--text-secondary); line-height: 1.85; margin: 0.9rem 0; }
.hub-prose ul { list-style: disc; padding-left: 1.4rem; margin: 0.9rem 0; }
.hub-prose ol { list-style: decimal; padding-left: 1.4rem; margin: 0.9rem 0; }
.hub-prose li { color: var(--text-secondary); line-height: 1.8; margin: 0.3rem 0; }
.hub-prose li > ul, .hub-prose li > ol { margin: 0.3rem 0; }
.hub-prose strong { color: var(--text-primary); }

/* 行内代码：注意顺序 —— .hub-code 内的一律还原 */
.hub-prose code, .hub-shell code, .footer code {
  font-family: var(--font-mono); font-size: 0.85em;
  background: rgba(34, 211, 238, 0.09); color: #7dd3fc;
  padding: 0.12em 0.4em; border-radius: 5px;
  overflow-wrap: anywhere;
}

/* ── 代码块 ── */
.hub-code { position: relative; margin: 1.1rem 0; }
.hub-code pre {
  background: #080d12; border: 1px solid var(--border);
  border-radius: 10px; padding: 1rem 1.15rem; overflow-x: auto;
  font-family: var(--font-mono); font-size: 0.8125rem;
  line-height: 1.75; color: #c9d6e2;
}
.hub-code pre code {
  background: none; color: inherit; padding: 0;
  font-size: inherit; border-radius: 0; overflow-wrap: normal;
}
.hub-code .hub-copy {
  position: absolute; top: 0.55rem; right: 0.55rem;
  background: rgba(255, 255, 255, 0.04); border: 1px solid var(--border);
  color: var(--text-secondary); border-radius: 6px;
  padding: 0.25rem 0.6rem; font-size: 0.72rem; cursor: pointer;
  transition: all 0.2s var(--ease); font-family: var(--font-sans);
}
.hub-code .hub-copy:hover { color: var(--accent); border-color: var(--border-hover); }
.hub-code .hub-copy.done { color: #10b981; border-color: rgba(16, 185, 129, 0.4); }

/* ── 调用框 ── */
.hub-callout {
  border-left: 3px solid var(--accent); background: var(--bg-card);
  border-radius: 0 10px 10px 0; padding: 1rem 1.25rem; margin: 1.5rem 0;
}
.hub-callout > :first-child { margin-top: 0; }
.hub-callout > :last-child { margin-bottom: 0; }
.hub-callout .hub-callout-title {
  display: block; font-weight: 600; color: var(--text-primary);
  font-size: 0.9375rem; margin-bottom: 0.35rem;
}
.hub-callout p, .hub-callout li { font-size: 0.9375rem; }
.hub-callout.warn { border-left-color: #f59e0b; }
.hub-callout.warn .hub-callout-title { color: #fbbf24; }
.hub-callout.danger { border-left-color: #ef4444; }
.hub-callout.danger .hub-callout-title { color: #f87171; }
.hub-callout.ok { border-left-color: #10b981; }
.hub-callout.ok .hub-callout-title { color: #34d399; }

/* ── 状态徽标 ── */
.hub-badge {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.72rem; font-weight: 600; line-height: 1;
  padding: 0.22rem 0.6rem; border-radius: 999px; border: 1px solid;
  white-space: nowrap; vertical-align: 0.08em;
}
.hub-badge.live { color: #34d399; border-color: rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.08); }
.hub-badge.todo { color: #fbbf24; border-color: rgba(245, 158, 11, 0.35); background: rgba(245, 158, 11, 0.08); }
.hub-badge.gap  { color: #f87171; border-color: rgba(248, 113, 113, 0.35); background: rgba(248, 113, 113, 0.08); }

/* ── 纵向编号步骤（详细版，与上游 .steps 网格版并存） ── */
.hub-steps { counter-reset: hubstep; list-style: none; padding: 0; margin: 2rem 0; }
.hub-steps > li {
  counter-increment: hubstep; position: relative;
  padding: 0 0 2.75rem 3.5rem;
}
.hub-steps > li:last-child { padding-bottom: 0; }
.hub-steps > li::before {
  content: counter(hubstep); position: absolute; left: 0; top: 0;
  width: 36px; height: 36px; border-radius: 50%;
  background: var(--accent); color: #000; font-weight: 800; font-size: 0.9375rem;
  display: flex; align-items: center; justify-content: center;
}
.hub-steps > li::after {
  content: ''; position: absolute; left: 17px; top: 42px; bottom: 6px;
  width: 2px; background: var(--border);
}
.hub-steps > li:last-child::after { display: none; }
.hub-steps h3 { margin: 0.35rem 0 0.75rem; font-size: 1.1rem; }
@media (max-width: 768px) {
  .hub-steps > li { padding-left: 3rem; }
  .hub-steps > li::before { width: 30px; height: 30px; font-size: 0.85rem; }
  .hub-steps > li::after { left: 14px; top: 36px; }
}

/* ── 层叠图（设计与层层实现） ── */
.hub-stack { display: grid; gap: 0.6rem; margin: 2rem 0; }
.hub-layer {
  display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 1.15rem;
  align-items: start; background: var(--bg-card); border: 1px solid var(--border);
  border-left: 3px solid var(--accent); border-radius: 0 12px 12px 0;
  padding: 1.05rem 1.25rem;
}
.hub-layer .hub-layer-id {
  font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600;
  color: var(--accent); padding-top: 0.15rem;
}
.hub-layer .hub-layer-body strong {
  display: block; color: var(--text-primary); font-size: 0.9375rem;
  margin-bottom: 0.3rem;
}
.hub-layer .hub-layer-body span {
  display: block; color: var(--text-secondary); font-size: 0.85rem; line-height: 1.7;
}
.hub-layer.cross { border-left-style: dashed; border-left-color: var(--text-muted); }
.hub-layer.cross .hub-layer-id { color: var(--text-muted); }
@media (max-width: 768px) {
  .hub-layer { grid-template-columns: 1fr; gap: 0.4rem; }
  .hub-layer .hub-layer-id { padding-top: 0; }
}

/* ── 表格：窄屏横向滚动 ── */
.hub-table-wrap { overflow-x: auto; margin: 1.5rem 0; }
.hub-table-wrap table { margin: 0; min-width: 540px; }
@media (max-width: 768px) {
  .hub-table-wrap { margin: 1.25rem -1.25rem; padding: 0 1.25rem; }
}

/* ── 权限矩阵 ── */
.hub-perm th:not(:first-child), .hub-perm td:not(:first-child) { text-align: center; }
.hub-perm .yes { color: #34d399; font-weight: 700; }
.hub-perm .no  { color: #f87171; font-weight: 700; }

/* ── 事实表（两列，左列不折行） ── */
.hub-facts td:first-child { color: var(--text-secondary); white-space: nowrap; width: 32%; }

/* ── 页脚小注 ── */
.hub-note {
  font-size: 0.8125rem; color: var(--text-muted);
  border-top: 1px solid var(--border); padding-top: 1rem; margin-top: 2.5rem;
  line-height: 1.75;
}

/* ── 锚点让开 fixed navbar ── */
[id] { scroll-margin-top: calc(var(--nav-h) + 1rem); }
```

- [ ] **步骤 3：写 `website/js/hub.js`**

```js
/* ══════════════════════════════════════════════════════════════════════
   MRRC Cloud Hub 文档站 — 渐进增强
   ──────────────────────────────────────────────────────────────────────
   无框架、无构建。每一项都是纯增强：JS 不执行时页面仍然完全可读可用。
   移动菜单、回到顶部、滚动进度条复用 octen.css 里已有的上游类名
   （.nav-links.active / .vlsc-to-top.show / .vlsc-scroll-progress /
   .vlsc-reveal.in），所以本站的观感与 www.vlsc.net 同源。
   ══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── 移动菜单（navbar 上用的是 onclick="toggleMobileMenu()"，保持上游约定） ── */
  window.toggleMobileMenu = function () {
    var nav = document.querySelector('.nav-links');
    if (nav) nav.classList.toggle('active');
  };

  document.addEventListener('DOMContentLoaded', function () {

    /* ── navbar 滚动加深 ── */
    var navbar = document.querySelector('.navbar');
    var progress = document.getElementById('scrollProgress');
    var backTop = document.getElementById('backTop');

    function onScroll() {
      var y = window.scrollY || document.documentElement.scrollTop;
      if (navbar) navbar.classList.toggle('scrolled', y > 8);
      if (backTop) backTop.classList.toggle('show', y > 500);
      if (progress) {
        var max = document.documentElement.scrollHeight - window.innerHeight;
        progress.style.width = (max > 0 ? (y / max) * 100 : 0) + '%';
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    if (backTop) {
      backTop.addEventListener('click', function () {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }

    /* ── 滚动入场（上游 .vlsc-reveal / .in） ── */
    var reveals = document.querySelectorAll('.vlsc-reveal');
    if (reveals.length && 'IntersectionObserver' in window) {
      var ro = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { e.target.classList.add('in'); ro.unobserve(e.target); }
        });
      }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
      reveals.forEach(function (el) { ro.observe(el); });
    } else {
      reveals.forEach(function (el) { el.classList.add('in'); });
    }

    /* ── 目录高亮（只在有 .hub-toc 的页面生效） ── */
    var tocLinks = Array.prototype.slice.call(document.querySelectorAll('.hub-toc a'));
    if (tocLinks.length && 'IntersectionObserver' in window) {
      var byId = {};
      var targets = [];
      tocLinks.forEach(function (a) {
        var id = (a.getAttribute('href') || '').replace(/^#/, '');
        var el = id ? document.getElementById(id) : null;
        if (el) { byId[id] = a; targets.push(el); }
      });
      var so = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          tocLinks.forEach(function (a) { a.classList.remove('active'); });
          var a = byId[e.target.id];
          if (a) a.classList.add('active');
        });
      }, { rootMargin: '-15% 0px -70% 0px', threshold: 0 });
      targets.forEach(function (el) { so.observe(el); });
    }

    /* ── 代码块一键复制 ── */
    document.querySelectorAll('.hub-code').forEach(function (box) {
      var pre = box.querySelector('pre');
      if (!pre || !navigator.clipboard) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hub-copy';
      btn.textContent = '复制';
      btn.addEventListener('click', function () {
        navigator.clipboard.writeText(pre.innerText).then(function () {
          btn.textContent = '已复制';
          btn.classList.add('done');
          setTimeout(function () {
            btn.textContent = '复制';
            btn.classList.remove('done');
          }, 1600);
        });
      });
      box.appendChild(btn);
    });
  });
})();
```

- [ ] **步骤 4：验证脚手架**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
shasum -a 256 css/octen.css ../mrrc_modern/website/css/octen.css 2>/dev/null || \
  shasum -a 256 css/octen.css /Users/cheenle/HAM/hub/mrrc_modern/website/css/octen.css
node --check js/hub.js && echo "hub.js syntax OK"
wc -l css/hub.css js/hub.js
```

预期：哈希一致；`hub.js syntax OK`。

- [ ] **步骤 5：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/css website/js
git -c commit.gpgsign=false commit -q -m "docs(site): 脚手架 — 复制上游 octen.css，新增 hub.css/hub.js

octen.css 原样复制不 fork；本站新增样式与行为全部隔离在
hub.css / hub.js，使上游 vs 本站的差异永远是单一文件。"
```

---

## 任务 2：`index.html`（概览）

**文件：** 创建 `website/index.html`

- [ ] **步骤 1：写页面**

结构（用共享片段组装）：

1. `.hero`（上游首页版，非 `.hub-hero`）：
   - `.hero-badge`：`<i class="fas fa-tower-broadcast"></i> MRRC Cloud Hub · 阶段 1 已跑通`
   - `.hero-title`：`把你的电台<br><span class="gradient">挂到云端</span>`
   - `.hero-subtitle`：`你的 MRRC Modern 继续跑在自己家里，不需要公网 IP、不需要端口映射。实例主动出站连上 Hub，你就能从任何地方用浏览器操作同一台电台。`
   - `.hero-actions`：`btn-primary` → `start.html`「开始接入」；`btn-secondary` → `design.html`「看设计与实现」；`btn-secondary` → GitHub `mrrc_hub`
   - `.hero-stats` 四项：`118–168 ms` 公网往返 / `5` 个 WS 端点透明转发 / `0` 客户端入站端口 / `8 层` PTT 本地释放

2. `<section class="section">`「三条主张」→ `.features-grid` + 3× `.feature-card`：
   - **客户侧零入站** —— `只出站一条隧道；无公网 IP、无端口映射、无 UPnP 也能被远程访问。`
   - **一个呼号一个入口** —— `入口就是 <code>&lt;呼号&gt;.mrrc.vlsc.net</code>；呼号即租户名，也是账号标识。`
   - **PTT 释放永远在本地** —— `Hub 只是通道，从不写下 PTT。断线、掉网、半开连接都由电台本机强制回 RX。`

3. `<section class="section">`「30 秒看懂走到哪」→ `.arch-diagram` 内放一个 `.hub-stack`，5 行 `.hub-layer`：
   - `你的电台` → `FT-710 / IC-7300 / IC-7300MK2，接在你自己的电脑上`
   - `你的电脑` → `MRRC Modern 在本机 127.0.0.1:8888（局域网也能用）`
   - `出站隧道` → `一条常驻出站连接，你不需要开任何入站端口`
   - `Hub` → `统一入口 <code>&lt;呼号&gt;.mrrc.vlsc.net:9988</code>，真 Let's Encrypt 证书`
   - `你的浏览器` → `从任何地方打开同一个网址（也能从 www.vlsc.net 的 443 退化入口进）`

4. `<section class="section section-cta">`「现在能到什么程度」→ `.perf-grid` + 3× `.perf-card`：
   - `已跑通`（`hub-badge live`）：通配子域入口 + 真证书 + 隧道 + 5 个 WS 端点透明转发
   - `MVP 必修`（`hub-badge todo`）：PTT 半开释放（隧道层心跳）、令牌不进 URL 的前端侧
   - `阶段 2`（`hub-badge todo`）：自助注册 Portal、设备 mTLS、Operator 租约

5. `<section class="section">`「该去哪」→ 两列 `.steps`：
   - `还没装 MRRC Modern` → 去 `https://www.vlsc.net/mrrc_modern/` 下载并先把局域网跑通
   - `局域网已经能用` → 直接进 `start.html`

6. `.hub-note`：`本页事实基线 2026-10-01。入口与运营事实以 SDD/12 §12.8 为准。`

**特别要求**：不要在页面上放 `bg1sb` 的真实入口链接作为"示例"（会把个人实例暴露成样板）；用 `<呼号>` 占位。

- [ ] **步骤 2：验证**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
python3 -c "
import re,sys
h=open('index.html',encoding='utf-8').read()
assert h.count('<html')==1 and h.count('</html>')==1, 'html 标签不闭合'
for c in ['class=\"navbar\"','class=\"footer\"','js/hub.js','css/hub.css','css/octen.css']:
    assert c in h, '缺 '+c
for a in re.findall(r'href=\"([^\"#][^\"]*)\"', h):
    if a.startswith(('http','mailto')) or a.endswith('.css') or a.endswith('.js'): continue
    import os; assert os.path.exists(a), '本地链接断链: '+a
print('index.html OK')
"
grep -cE '[?&](token|code|ticket)=' index.html || echo "金规则: 0 命中"
```

- [ ] **步骤 3：本地起服务目视**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website && python3 -m http.server 8099
# 浏览器打开 http://localhost:8099/index.html，对照 http://localhost:8099/css/octen.css 同名类
# 检查：黑底 + 青色 accent、hero 居中、卡片 hover 有青色描边、导航固定、窄屏菜单可开
```

- [ ] **步骤 4：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/index.html
git -c commit.gpgsign=false commit -q -m "docs(site): 概览页 — 三条主张 + 30 秒架构 + 能力现状"
```

---

## 任务 3：`start.html`（接入四步）

**文件：** 创建 `website/start.html`

- [ ] **步骤 1：写页面**

页头用 `.hub-hero`；正文用 `.hub-shell` + `.hub-toc`（目录项：前提自检 / 注册 / 装隧道 / 验证 / 重启之后）+ `.hub-prose`，内容是一个 `<ol class="hub-steps">`：

**步骤 1 — 前提自检**（`id="step0"`）

`.hub-facts` 表格：

| 检查 | 期望 |
| --- | --- |
| 局域网能打开 | `http://<你的内网IP>:8888/` —— 默认端口 `8888`，默认监听 `::` |
| 能登录 | 首次启动自动生成随机口令（登录页横幅 + 菜单栏 Show Password… 可见） |
| 有音频、能 PTT | 本地先跑通再谈远程 |
| 知道设备 | 串口（如 `/dev/cu.usbserial-*`）与音频设备名（如 `USB Audio Device`） |
| 出站可达 | 隧道口 `8989` 出站不被拦（公司网/访客 Wi-Fi 常拦非标端口） |

`.hub-callout.warn`：`出站 9898 与 443 是两件事` —— 主路入口用 `:9988`/`:8899`，隧道口是 `:8989`，三者都要出站可达。

**步骤 2 — 注册（拿到你的名字与端口）**（`id="register"`）

- `.hub-callout.ok` + `<span class="hub-badge live">今天可用</span>`：**人工开通**。联系 Hub 管理员报上你的呼号，会得到三样东西：① 呼号标签 ② 隧道端口（`188xx`）③ 隧道凭证。
- `<span class="hub-badge todo">未实现 · 阶段 2</span>` **目标态：自助注册 Portal**。四步流水线：**规范化**（去空格、大小写不敏感，`BG1SB` 与 `bg1sb` 视为同一呼号）→ **查重**（同一呼号同一时刻只能有一个归属人）→ **核验**（呼号库比对，或执照材料人工审核）→ **分配**（实例标签 + 隧道端口）。
- `.hub-callout.warn`「为什么必须**先核验**」：呼号是公开信息，入口存在性本来就可被枚举（这一点在设计上被**有意接受**）。所以核验必须发生在**授予访问之前**，而不是事后追责。

**步骤 3 — 装隧道**（`id="tunnel"`）

`.hub-code`：

```bash
brew install frp          # 或用官方便携包；版本需 ≥ 0.52

MRRC_HUB_TOKEN='<隧道凭证>' \
  bash mrrc_hub/deploy/install_instance_tunnel.sh <呼号> <端口>
```

下面 `.hub-facts` 表说明"它做了什么 / 它不做什么"：

| | |
| --- | --- |
| 做了什么 | 写 `~/Library/Application Support/mrrc-fleet/frpc-<呼号>.toml`（0600）；装 LaunchAgent `com.mrrc.fleet-tunnel.<呼号>` 带 `KeepAlive` |
| 不做什么 | **不管你的 MRRC 服务**。实例没起来，隧道照常在，访问会得到 502 |
| 安全 | 隧道本身加密；凭证不进命令行参数、不进世界可读文件 |
| 幂等 | 已有手工 `frpc` 在跑时它会拒绝启动（两个客户端抢同一个名字会抖动） |

**步骤 4 — 验证**（`id="verify"`）

`.hub-code` + 期望输出：

```bash
tail -5 "~/Library/Application Support/mrrc-fleet/frpc-<呼号>.log"
# 期望看到：login to server success / start proxy success

curl -sI https://<呼号>.mrrc.vlsc.net:9988/login       # 期望 200
curl -s  https://<呼号>.mrrc.vlsc.net:9988/api/health  # 期望 401（鉴权生效）
```

`.hub-callout`：`401 是好事` —— 说明隧道、Hub 路由、实例鉴权三层都通了。

**步骤 5 — 重启之后**（`id="restart"`）

- 隧道：**自动回来**（LaunchAgent `KeepAlive`）
- MRRC 服务：**当前不常驻**（源码运行），重启后要手动起：

```bash
cd mrrc_modern
while IFS='=' read -r k v; do case "$k" in ''|\#*) continue;; esac; export "$k=$v"; done \
    < "$HOME/Library/Application Support/MRRC-Modern/mrrc_modern.env"
nohup venv/bin/python server.py > /tmp/mrrc-src/server.log 2>&1 &
```

`.hub-callout.danger`：环境文件里有 `USB Audio Device` 这类**带空格的值**，所以必须用上面这个 `while ... read` 循环加载，**不能 `source`** —— `source` 会把值里的单词当命令执行。

页面末尾 `.hub-note`：`下一步 → 使用与分享`。

- [ ] **步骤 2：验证（含两条真命令实跑）**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
grep -cE '[?&](token|code|ticket)=' start.html || echo "金规则: 0 命中"
# 页面里给出的验证命令必须真能跑（用现网实例 bg1sb 实跑）
curl -sI -o /dev/null -w "login  → %{http_code}\n" https://bg1sb.mrrc.vlsc.net:9988/login
curl -s  -o /dev/null -w "health → %{http_code}\n" https://bg1sb.mrrc.vlsc.net:9988/api/health
```

预期：`login → 200`、`health → 401`。（若 200/401 之外的码，说明页面写的期望值与现网不符 —— 停下来核实，不要改页面去迎合。）

- [ ] **步骤 3：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/start.html
git -c commit.gpgsign=false commit -q -m "docs(site): 接入四步 — 前提自检/注册/隧道/验证/重启"
```

---

## 任务 4：`use.html`（使用与分享）

**文件：** 创建 `website/use.html`

- [ ] **步骤 1：写页面**

`.hub-hero` + `.hub-shell`（目录：三个入口 / 两把口令 / 分享给朋友 / 现状与已知退化 / 手机上用）+ `.hub-prose`：

**① 三个入口**（`id="entries"`）—— `.hub-table-wrap` + `table`：

| 入口 | URL | 适用 |
| --- | --- | --- |
| 主路 | `https://<呼号>.mrrc.vlsc.net:9988/` | 绝大多数场景；实测公网往返 118–168 ms |
| 主路备用口 | `https://<呼号>.mrrc.vlsc.net:8899/` | 同一个 vhost、同一张证书；只放行该端口时用 |
| 退化路 | `https://www.vlsc.net/mrrc_modern/<呼号大写>/` | 只放行 80/443 的网络（公司/访客 Wi-Fi）。多一跳海外，音频与 PTT 多约 0.4–0.6 s |
| 局域网 | `http://<内网IP>:8888/` | 在家；不经过 Hub |

`.hub-callout.warn`：退化路**路径用大写呼号**。URL 路径大小写敏感，写成小写会被 301 到规范形式（多一次跳转）。

**② 两把口令 = 两个角色**（`id="roles"`）—— `.hub-table-wrap` + `table class="hub-perm"`：

| 口令 | 进入 | 听 | 看频谱 | 调频/换模式 | 发射 |
| --- | --- | --- | --- | --- | --- |
| 主口令 | `/` | ✅ | ✅ | ✅ | ✅ |
| 监听口令 | `/listen` | ✅ | ✅ | ✅ | ❌ **服务端拒绝** |

- `<span class="hub-badge gap">注意</span>` 监听角色的发射拒绝是**服务端**行为（不是界面隐藏），所以把监听口令给别人是安全的。
- `<span class="hub-badge gap">注意</span>` **监听口令默认为空 = 监听角色无法进入**。想分享给朋友之前，先在实例上设置它。
- 参考：`mrrc_modern` 的监听角色在 REST 层只读（`/api/` 下一切非 GET 都被拒），并且它连接的是 `/WSradio` `/WSspectrum` `/WSaudioRX` 三个端点，**不连** `/WSaudioTX`。

**③ 分享给朋友**（`id="share"`）—— 两列 `.hub-callout`：

- `.hub-callout.ok`「给」：入口 URL + **监听口令**
- `.hub-callout.danger`「别给」：主口令 —— 那等于把发射权交出去

**④ 现状与已知退化**（`id="gaps"`）—— 诚实清单：

| 事项 | 状态 |
| --- | --- |
| Hub 侧 Operator 租约（每实例同时最多一个写者） | <span class="hub-badge todo">未实现 · 阶段 2</span> |
| 多人同时用主口令登录时谁在发射 | 由**实例侧**仲裁：`WSradio` 连接上只有一个 key-owner，谁按下 PTT 谁占有 |
| 登录限流在隧道路径下 | <span class="hub-badge gap">已知退化</span> 所有登录在 Hub 看来都是同一来源，限流退化为**全局桶**（5 次失败 / 300 秒）。已决定暂缓 |
| PTT 释放 | <span class="hub-badge live">已实现</span> **不依赖云端**：断线、掉网、半开连接一律由实例本地强制回 RX |

`.hub-callout.danger`：`别把主口令放进群里` —— 上面那条"全局桶"意味着：别人反复输错主口令，会把你自己的登录一起锁 5 分钟。

**⑤ 手机上用**（`id="mobile"`）—— `.hub-prose ul`：把入口"添加到主屏幕"当 PWA 用；原生 App 见 MRRC Modern 产品站。

- [ ] **步骤 2：验证**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
grep -cE '[?&](token|code|ticket)=' use.html || echo "金规则: 0 命中"
# 权限矩阵必须与 mrrc_modern 源码一致：确认监听角色 REST 只读的那段中间件仍在
grep -n "LISTEN_ONLY_MESSAGE\|_is_listen_request" /Users/cheenle/HAM/hub/mrrc_modern/server.py | head
```

预期：金规则 0 命中；`server.py` 里 `_is_listen_request` 与只读拒绝逻辑仍在（若已改，停下来改页面）。

- [ ] **步骤 3：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/use.html
git -c commit.gpgsign=false commit -q -m "docs(site): 使用与分享 — 入口对照/权限矩阵/已知退化"
```

---

## 任务 5：`trouble.html`（排障）

**文件：** 创建 `website/trouble.html`

- [ ] **步骤 1：写页面**

`.hub-hero` + `.hub-shell`（目录：一张表 / 两条诊断命令 / 日志在哪）+ `.hub-prose`。

**主表**（`id="symptoms"`，`.hub-table-wrap` + `table`）：

| 症状 | 优先检查 |
| --- | --- |
| 浏览器打不开 / 证书警告 | 用的是不是 `:9988` 或 `:8899`；退化路是否用了**大写**呼号；有没有误用明文口 |
| 502 Bad Gateway | ① 隧道在不在（`frpc-<呼号>.log` 有没有 `start proxy success`）② 实例服务在不在（本机 `8888` 有没有在听） |
| 登录页出来了但控制台黑屏 | 5 个 WS 端点哪个被拒：**4001** 未授权 / **4003** 角色拒绝。监听角色连 `/WSaudioTX` 必然被拒（这是设计） |
| 能听不能发 | 用的是不是主口令；是不是走了 `/listen` |
| 登录反复 429 | 限流 5 次 / 300 秒。**隧道路径下这是全局桶** —— 别人输错会连带锁你 |
| 音频卡顿 | 上行利用率是否过高；同时收听人数；先降瀑布帧率再谈带宽 |
| 退化路明显慢 | 正常。多一跳海外，约 +0.4–0.6 s。优先用主路 |
| 边缘 502 而直连正常 | www 的上游校验信任源是否被改回**钉证书** —— 应保持系统 CA |
| 重启电脑后连不上 | 隧道会自动回来；**MRRC 服务不会**（当前不常驻），按接入页"重启之后"手动起 |
| 换了网络/路由器后掉线 | 隧道 `KeepAlive` 会重连；实例侧 PTT 在断链瞬间已本地释放，不需要担心 |

**两条诊断命令**（`id="diag"`）：

```bash
# 1) 隧道这一跳健康吗
tail -20 ~/Library/Application\ Support/mrrc-fleet/frpc-<呼号>.log

# 2) 从公网看这一跳健康吗（401 表示隧道+Hub+实例三层都通，鉴权也生效）
curl -sI https://<呼号>.mrrc.vlsc.net:9988/api/health
```

**日志在哪**（`id="logs"`，`.hub-facts` 表）：

| 位置 | 内容 |
| --- | --- |
| `~/Library/Application Support/mrrc-fleet/frpc-<呼号>.log` | 隧道 |
| `/tmp/mrrc-src/server.log` | 实例（若按接入页那种方式启动） |
| Hub 上 `/var/log/nginx/mrrc-hub.access.log` | Hub 侧访问日志，**只记路径不记查询串** |

- [ ] **步骤 2：验证**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
grep -cE '[?&](token|code|ticket)=' trouble.html || echo "金规则: 0 命中"
grep -c "4001\|4003" trouble.html   # 期望 ≥ 1
```

- [ ] **步骤 3：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/trouble.html
git -c commit.gpgsign=false commit -q -m "docs(site): 排障 — 症状表/诊断命令/日志位置"
```

---

## 任务 6：`design.html`（设计与层层实现）

**文件：** 创建 `website/design.html`

- [ ] **步骤 1：写页面**

`.hub-hero`（标题：`设计与层层实现`；副标题：`从电台到浏览器，六层各自负责什么、边界画在哪、失效时表现什么。`）

- `.hub-shell`（目录：分层 / 每层职责 / 关键决策 / 安全不变量 / 现状与目标 / 边界声明）+ `.hub-prose`。

**§1 `id="layers"` 层叠图** —— `.hub-stack`，6 个 `.hub-layer` + 1 个 `.hub-layer.cross`：

| id | body |
| --- | --- |
| `L0 电台` | **硬件**：FT-710 / IC-7300 / IC-7300MK2。产生射频，提供 CAT/CI-V 状态 |
| `L1 实例本地` | **MRRC Modern**（FastAPI/Uvicorn，本机 `8888`）。CAT/CI-V 控制、双向音频、频谱，以及**PTT 释放的权威** |
| `L2 隧道` | **frpc 出站 → frps :8989 → 回环端口 `188xx`**。客户侧零入站；Hub 侧代理口只绑 `127.0.0.1` |
| `L3 Hub 入口` | **nginx 通配 vhost（:9988 / :8899，TLS）**。TLS 终结、按 Host 取实例名、查 map 得端口、**校验上游证书**、WS 透明转发 |
| `L4 海外边缘` | **<www.vlsc.net> 443 路径入口**。标准端口 + 真证书 + 前缀透明；定位为退化路 |
| `L5 客户端` | **浏览器 / PWA / iOS**。展示与交互，**不是 PTT 释放的依赖** |
| `横切`（`.cross`） | **证书 · 身份 · 审计 · 遥测**：Let's Encrypt 通配（DNS-01，每日 8:00 续期）；呼号即租户名与账号名；访问日志只记路径不记查询串；`/api/session_metrics` 上报并发 |

**§2 `id="perlayer"` 每层一张卡** —— `.arch-grid` + 6× `.arch-card`，每张卡用 `.label` 放层号、`.endpoint` 放关键实现位置、`.dir` 放**边界（这层不做什么）**、`.payload` 放**失效时的表现**：

| 层 | 实现位置 | 边界（不做什么） | 失效表现 |
| --- | --- | --- | --- |
| L1 | `server.py`；`/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` `/WSatr1000` | 不做用户/成员管理（那在 Hub，且尚未实现）；**不把 PTT 释放托付给云端** | 本地页打不开；局域网 502 |
| L2 | `deploy/install_instance_tunnel.sh`；`frpc-<呼号>.toml`（0600）；launchd `com.mrrc.fleet-tunnel.<呼号>` | 不做 TLS 终结、不做路由决策、不知道实例名以外的任何业务 | Hub 侧 502；日志里 `login to server success` 消失 |
| L3 | `/etc/nginx/sites-available/mrrc-hub` + `/etc/nginx/conf.d/mrrc-hub-map.conf`（由 `gen_hub_routes.py` 从注册表生成） | **不保存会话状态**（无状态）；**永不写 PTT** | 未知实例 → 404（不猜测别的实例）；上游证书不符 → 502 |
| L4 | www 上 `vlsc.net` vhost 的 `MRRC Cloud Hub edge` 块 | 不是主路（多一跳，+0.4–0.6 s） | 502（上游信任源被改回钉证书时） |

**§3 `id="decisions"` 关键决策** —— `.hub-table-wrap` + `table`，每行 = 决策 + 一句话理由 + **当时为什么不选另一种**：

| 决策 | 内容 | 为什么不选另一种 |
| --- | --- | --- |
| `AD-H01` 实例主动出站 | 客户侧只出站，零入站 | 反过来的"Hub 连进来"需要在每家路由器上做端口映射 —— 家庭宽带做不到 |
| `AD-H02` 通配子域 | 一条通配 vhost + 注册表映射 | 每实例一个 vhost 是上一版的做法：加一个实例就要改中心配置，还得处理正则与前缀优先级 |
| `AD-H03` 控制面/数据面分离 | 无状态入口 ×N + 有状态隧道网关 ×≥2 | 合成一个进程后，入口的横向扩容会牵着会话归属一起搬 |
| `AD-H05` 单写者租约 | 每实例同时最多一个写者 | 允许多写者会让两个人同时按 PTT —— 冲突在电台侧无法仲裁 |
| `AD-H06` PTT 权威在实例本地 | Hub 只能关流通知，**从不写下 PTT** | 依赖云端 TTL 释放，意味着云端一断网电台就一直发射 |
| `AD-H07` 令牌不进 URL | 会话凭据走 Cookie / 握手，不进查询串 | 查询串必然落进代理与实例的访问日志 —— 这个失效模式在之前的产品里真实发生过 |
| `AD-H08` 监听者语义 | 可听、可看频谱、**可调频换模式**、禁发射 | 简单做成"只读"会让人没法帮忙找台，而调频不改变"谁在发射"这一根本约束 |
| `AD-H15` 呼号即身份 | 租户名 = 呼号；入口 = `呼号.域名` | 另一套用户名体系会让"这是谁家的电台"变成一个要查表的问题 |

**§4 `id="invariants"` 三条安全不变量** —— 3× `.hub-callout`：

- `.hub-callout.danger`「Hub 永远不是 PTT 写者」—— 任何"云端直接置 RX"的实现都违反此条。
- `.hub-callout.danger`「令牌不进程 URL 与日志」—— 包括 Hub、实例、以及任何代理的访问日志。
- `.hub-callout.danger`「禁止关闭上游证书校验」—— 逐跳校验；关掉它就等于把中间人攻击做成默认配置。

**§5 `id="status"` 现状 vs 目标态** —— `.hub-table-wrap` + `table`：

| 能力 | 状态 |
| --- | --- |
| 实例出站隧道（frp 通道） | <span class="hub-badge live">已跑通</span> 阶段 1 |
| 通配子域接入 + 真证书 | <span class="hub-badge live">已跑通</span> `*.mrrc.vlsc.net`，Let's Encrypt |
| 5 个 WS 端点透明转发 | <span class="hub-badge live">已跑通</span> 升级/长连接/关闭语义与直连一致 |
| 上游证书校验 | <span class="hub-badge live">已开启</span> 逐跳校验、未关闭 |
| 令牌不进 URL（前端侧） | <span class="hub-badge live">已实现</span> 前端不再拼查询串 |
| PTT 半开连接释放（隧道层心跳） | <span class="hub-badge todo">MVP 必修</span> |
| 自助注册 Portal | <span class="hub-badge todo">阶段 2</span> |
| 设备 mTLS（一机一证） | <span class="hub-badge todo">阶段 2</span> 现状 frp 用共享令牌 |
| Operator 租约 | <span class="hub-badge todo">阶段 2</span> 现状由实例侧仲裁 |

**§6 `id="boundary"` 边界声明** —— `.hub-prose p`：电台控制、音频、PTT 安全释放的设计权威在 MRRC Modern 的设计记录里；本页只讲**其外部**的接入层。要看更深，访问 MRRC Modern 产品站的 SDD 章节页。

`.hub-note`：`本页事实基线 2026-10-01 现场取证（hub 与 www 的实际 nginx 配置、证书有效期、注册表内容）。`

- [ ] **步骤 2：验证**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
grep -cE '[?&](token|code|ticket)=' design.html || echo "金规则: 0 命中"
# 页面里"已跑通"的每一项都必须有证据；"阶段 2"的每一项都不得写成已完成
grep -c 'hub-badge live' design.html   # ≥ 5
grep -c 'hub-badge todo' design.html   # ≥ 3
# 目录锚点全部存在
python3 -c "
import re
h=open('design.html',encoding='utf-8').read()
ids=set(re.findall(r'id=\"([^\"]+)\"',h))
anchors=set(re.findall(r'href=\"#([^\"]+)\"',h))
missing=anchors-ids
assert not missing, '目录锚点缺目标: '+str(missing)
print('anchors OK:', sorted(anchors))
"
```

- [ ] **步骤 3：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/design.html
git -c commit.gpgsign=false commit -q -m "docs(site): 设计页 — 六层职责/决策表/安全不变量/现状与目标"
```

---

## 任务 7：`website/README.md`（站点维护说明）

**文件：** 创建 `website/README.md`

- [ ] **步骤 1：写文件**

内容包含六节：

1. **这是什么** —— 5 页静态站，用户为主 + 单独一页设计；零构建。
2. **文件职责** —— 每个文件一行。
3. **事实源映射**（逐字取自规格 §5）：站点每一页的每个事实都必须能指回一个权威出处；**站点不发明事实**，无法取证的写“待核实”。
4. **怎么改** ——
   - 改文案 → 直接改对应 HTML
   - 上游设计系统改了 → `cp ../../mrrc_modern/website/css/octen.css css/octen.css`（并复核 `hub.css` 是否有被覆盖的类）
   - 现网变了 → 先复核，再改 §3 这张表
5. **发布** —— `bash deploy.sh`（**会问确认**）；发布后必须实测 5 页 `curl -sI`。
6. **复验清单**（每次发布前跑）：

```bash
# 金规则：不得有字面查询串形式的令牌字段
grep -rnE '[?&](token|code|ticket)=' *.html && echo "违反 hub-token-not-in-url" || echo "clean"
# 断链
python3 - <<'PY'
import re, os
bad = []
for f in os.listdir('.'):
    if not f.endswith('.html'): continue
    h = open(f, encoding='utf-8').read()
    for a in re.findall(r'href="([^"#][^"]*)"', h):
        if a.startswith(('http', 'mailto')) or a.endswith(('.css', '.js')): continue
        if not os.path.exists(a): bad.append(f + ' → ' + a)
print('断链:', bad or '无')
PY
# 现网入口仍然符合站点描述
curl -sI -o /dev/null -w "main  %{http_code}\n" https://bg1sb.mrrc.vlsc.net:9988/login
curl -sI -o /dev/null -w "edge  %{http_code}\n" https://www.vlsc.net/mrrc_modern/BG1SB/
# SDD 约束
python3 ../.agents/skills/sdd-guardian/harness/sdd_context.py check --staged
```

- [ ] **步骤 2：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/README.md
git -c commit.gpgsign=false commit -q -m "docs(site): 站点维护说明 — 事实源映射与发布前复验清单"
```

---

## 任务 8：`website/deploy.sh`（幂等发布脚本，**只写不执行**）

**文件：** 创建 `website/deploy.sh`

- [ ] **步骤 1：写脚本**

```bash
#!/usr/bin/env bash
# MRRC Cloud Hub 文档站 — 发布到 www.vlsc.net/mrrc_hub/
#
# 幂等：可重复执行；先备份、再校验、最后 reload。
# 本脚本**不会**被自动执行 —— 上线由人决定（规格 §1.2 非目标）。
#
# 学到的教训（源自 mrrc_modern/website/deploy.sh，逐条保留）：
#   * 备份保留按**名字**排序而不是 mtime（mtime 会继承源目录时间戳，
#     曾导致刚做的备份被当成最旧的删掉）
#   * scp 之前先清掉服务器上的旧包，避免解包 glob 匹配到截断的包
#   * 解包只覆盖不删除，所以要显式 prune 掉不该出现在 DocumentRoot 的构建产物
#   * nginx 配置改完必须先 nginx -t 再 reload
set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_HOST="www.vlsc.net"
REMOTE_USER="cheenle"
REMOTE_WEBROOT="/var/www/vlsc.net/mrrc_hub"
SITE_URL="https://www.vlsc.net/mrrc_hub"
STAMP="$(date +%Y%m%d_%H%M%S)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

cd "$LOCAL_DIR"

echo "=========================================="
echo "MRRC Cloud Hub 文档站 发布"
echo "=========================================="
echo "本地: $LOCAL_DIR"
echo "远端: $REMOTE_USER@$REMOTE_HOST:$REMOTE_WEBROOT"
echo "URL : $SITE_URL/"
echo ""

echo "检查必需文件..."
REQUIRED_FILES=(
 "index.html" "start.html" "use.html" "trouble.html" "design.html"
 "css/octen.css" "css/hub.css" "js/hub.js" "README.md"
)
for f in "${REQUIRED_FILES[@]}"; do
 [[ -f "$f" ]] || { echo -e "${RED}缺文件: $f${NC}"; exit 1; }
 echo -e "${GREEN}✓${NC} $f"
done

echo ""
echo "发布前复验（金规则 + 断链）..."
if grep -rnE '[?&](token|code|ticket)=' ./*.html; then
 echo -e "${RED}以上命中违反 SDD 金规则 hub-token-not-in-url —— 拒绝发布${NC}"
 exit 1
fi
echo -e "${GREEN}✓${NC} 金规则 clean"

PACKAGE="/tmp/mrrc_hub_website_${STAMP}.tar.gz"
tar -czf "$PACKAGE" \
 --exclude='deploy.sh' --exclude='.DS_Store' --exclude='.__*' \
 --exclude='__pycache__' -C "$LOCAL_DIR" .
echo -e "${GREEN}✓${NC} 打包 $PACKAGE"

echo ""
read -rp "继续发布？(y/N): " confirm
[[ "$confirm" == [yY] ]] || { echo "已取消"; rm -f "$PACKAGE"; exit 0; }

ssh "$REMOTE_USER@$REMOTE_HOST" <<EOF
set -e
# 1) 备份（保留最新 3 份，按名字排序 —— 见文件头教训）
if [ -d "$REMOTE_WEBROOT" ] && [ -n "\$(ls -A $REMOTE_WEBROOT 2>/dev/null)" ]; then
 sudo mkdir -p /var/tmp
 BK="/var/tmp/mrrc_hub_backup_${STAMP}"
 sudo rsync -a "$REMOTE_WEBROOT/" "\$BK"/
 sudo touch "\$BK"
 ls -1d /var/tmp/mrrc_hub_backup_* 2>/dev/null | sort -r | tail -n +4 \
  | xargs -r -d '\n' sudo rm -rf || true
 echo "已备份: \$BK"
fi

# 2) 清掉旧包，保证解包 glob 只匹配到一个文件
sudo rm -f /var/tmp/mrrc_hub_website_*.tar.gz

# 3) nginx: 幂等确保 /mrrc_hub/ location 存在
NGINX_SITE=/etc/nginx/sites-available/vlsc.net
if [ -f "\$NGINX_SITE" ]; then
 sudo python3 - "\$NGINX_SITE" <<'PYEOF'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
if "location ^~ /mrrc_hub/" in text:
    print("nginx: /mrrc_hub/ location 已存在")
else:
    block = """    # ── MRRC Cloud Hub 文档站 (/mrrc_hub/) ──
    location ^~ /mrrc_hub/ {
        try_files \$uri \$uri/ =404;
        autoindex off;
    }
    location = /mrrc_hub {
        return 301 /mrrc_hub/;
    }
"""
    marker = "    # ── MRRC Cloud Hub edge ("
    if marker in text:
        text = text.replace(marker, block + "\n" + marker, 1)
    else:
        text = text.rstrip() + "\n\n" + block
    open(path, "w", encoding="utf-8").write(text)
    print("nginx: 已添加 /mrrc_hub/ location")
PYEOF
 sudo nginx -t && sudo systemctl reload nginx && echo "nginx reloaded"
else
 echo -e "${YELLOW}警告: \$NGINX_SITE 不存在，跳过 nginx 配置${NC}"
fi

sudo mkdir -p "$REMOTE_WEBROOT"
EOF

scp "$PACKAGE" "$REMOTE_USER@$REMOTE_HOST:/var/tmp/"

ssh "$REMOTE_USER@$REMOTE_HOST" <<EOF
set -e
TARBALL=\$(ls -1t /var/tmp/mrrc_hub_website_*.tar.gz | head -1)
sudo mkdir -p "$REMOTE_WEBROOT"
sudo tar -xzf "\$TARBALL" -C "$REMOTE_WEBROOT" --overwrite

# 解包只覆盖不删除：把不属于站点的东西从 DocumentRoot 里清掉
sudo rm -f "$REMOTE_WEBROOT/deploy.sh" 2>/dev/null || true

sudo chown -R www-data:www-data "$REMOTE_WEBROOT"
sudo chmod -R 755 "$REMOTE_WEBROOT"
sudo find "$REMOTE_WEBROOT" -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' \) \
 -exec chmod 644 {} \;
rm -f "\$TARBALL"

echo ""
echo "发布完成。逐页实测："
for p in index start use trouble design; do
 code=\$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/\$p.html")
 echo "  /\$p.html → \$code"
done
echo "  /          → \$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/")"
EOF

rm -f "$PACKAGE"
echo ""
echo -e "${GREEN}完成${NC} → $SITE_URL/"
```

- [ ] **步骤 2：验证（只做静态检查，不执行）**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
bash -n deploy.sh && echo "deploy.sh 语法 OK"
grep -n 'reload nginx\|nginx -t' deploy.sh   # 必须两处都在
grep -n 'hub-token-not-in-url' deploy.sh     # 发布前闸门必须在
```

- [ ] **步骤 3：Commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add website/deploy.sh && chmod +x website/deploy.sh
git -c commit.gpgsign=false commit -q -m "docs(site): 发布脚本 — 幂等、备份按名字保留、发布前跑金规则闸门

只写不执行：上线由人决定。"
```

---

## 任务 9：markdown 文档全面更新

**文件：**

- 修改：`SDD/README.md`（能力表 + 版本 + 索引）
- 修改：`deploy/README.md`（状态行 + 退化路表 + 漂移警示块）
- 修改：`SDD/12-operational-model.md`（§12.8 入口段）
- 修改：`SDD/07-subject-area-model.md`（§7.x.1）
- 修改：`README.md`（入口段 + 文档在哪）
- 修改：`SDD/14-version-history.md`（追加条目）

- [ ] **步骤 1：`SDD/README.md` 能力表**（规格 §6.1 D1）

把这两行的状态从"待实现"改为已跑通，并在其后加一句目标态说明：

```markdown
| 实例出站隧道 | **已跑通（阶段 1，frp 通道）** | 目标态是内置 Fleet Agent（AD-H01、AD-H04）；当前以成熟反向隧道 frp 验证通路 |
| 通配子域接入 | **已跑通（阶段 1）** | 一条通配 vhost + 注册表映射（AD-H02）；`*.mrrc.vlsc.net` 真证书已签发 |
```

同时把 `SDD Version` 从 `V0.8` 提到 `V0.9`（含 Baseline Date 更新为 2026-10-01），并在 `### 索引补充` 表下再加一行：

```markdown
| 面向用户的文档站（5 页，用户为主 + 单独一页设计） | `website/`（`website/README.md` 有事实源映射与发布前复验清单） |
```

- [ ] **步骤 2：`deploy/README.md` 三处**（规格 §6.1 D2/D3/D4/D5 + §6.2 X1/X2）

(a) 顶部状态行改为：

```markdown
> **状态（2026-10-01 复核）：阶段 1 已部署并在真实公网验证通过。** 本目录的脚本是那一次的
> 落地工具；下面的"未部署"段落是当时的现场记录，保留供追溯。**重跑脚本前务必先读
> 「⚠️ 脚本与现网漂移」一节** —— 其中两条会让现网退化。
```

(b) 在文件靠前位置插入漂移警示块：

```markdown
## ⚠️ 脚本与现网漂移（2026-10-01 取证）

以下两处**仓库脚本落后于现网**。重跑对应脚本会让现网退化，**务必先对齐再跑**：

| # | 漂移 | 后果 |
|---|---|---|
| X1 | `deploy_hub_routes.sh` 生成**两个** server block（`listen 8899;` 明文 + 301、`listen 9988 ssl`）；现网是**一个** block 且 `8899` 已是 **TLS** 入口 | 重跑会把 8899 从 TLS 退回明文 → 境内被改写（R-H13 的失效模式）。脚本头部注释"currently self-signed"也已过期（现网是真 LE） |
| X2 | `deploy_www_edge.sh` 只实现 `redirect` / `proxy`（子域）两种模式；现网实际用的是**第三种** `path proxy`（Host 覆盖 + 路径大小写规范化 301 + `X-Forwarded-Prefix` + `proxy_redirect` 回写） | 重跑会把现网形态降级为 302 或子域代理，丢掉"标准端口 + 真证书 + 前缀透明"三项收益。www 上的 `/tmp/deploy_www_edge.sh` 与仓库版本**仅空白差异**，说明那段配置是手工落的 |

**处置**：本次只记录，**不改脚本**（改部署脚本的风险与验证成本超出文档任务范围）。对齐留作独立变更。
```

(c) 把"两级入口"表的退化路一行改为现网事实：

```markdown
| URL | `https://<呼号>.mrrc.vlsc.net:9988`（或 `:8899`） | `https://www.vlsc.net/mrrc_modern/<呼号大写>/` |
| 落点 | 阿里云 hub（乌兰察布） | 海外 www.vlsc.net 的 443 路径代理，反代回 hub 的 9988 |
| 证书 | **真 Let's Encrypt**（`*.mrrc.vlsc.net`，DNS-01，2026-09-30 → 2026-12-29） | 真证书（www 上 certbot HTTP-01） |
```

并在该节补一句：`脚本里的 proxy（子域）模式不是现网形态，见「⚠️ 脚本与现网漂移」X2。`

(d) "还差你一条 DNS 记录"整节前加一行 `> 历史记录（当时用 test1 验证）。现网实例是 bg1sb，见 SDD/12 §12.8。`

- [ ] **步骤 3：`SDD/12-operational-model.md` §12.8 入口段**（规格 §6.1 D6/D7）

把"入口（当前）"两条改为（**核心是补上 8899 的性质与大写规范，而不是改 URL**）：

```markdown
- `https://<呼号>.mrrc.vlsc.net:9988/` —— 直连 hub，真证书，浏览器零警告
- `https://<呼号>.mrrc.vlsc.net:8899/` —— **同上：这也是 TLS 入口**（原明文口，
  因 R-H13 已升级为 TLS，两端口同一个 vhost、同一张证书）
- `https://www.vlsc.net/mrrc_modern/<呼号>/` —— 海外边缘，真证书（境内无备案域名的迂回入口）。
  **路径大小写敏感，规范形式是大写呼号**（`/mrrc_modern/BG1SB/`），小写会被 301 到规范形式
```

- [ ] **步骤 4：`SDD/07-subject-area-model.md` §7.x.1**

把示例 URL 的端口与说明补齐：主产品标签为裸呼号时，入口是 `https://bg1sb.mrrc.vlsc.net:9988/`（**9988 与 8899 都是 TLS 入口**）。

- [ ] **步骤 5：根 `README.md`**

(a) 线上系统段：把 `nginx 通配 vhost(8899/9988 TLS)` 保留（它是对的），但把两个入口补全：

```markdown
- `https://<呼号>.mrrc.vlsc.net:9988/` —— 直连 hub（TLS）
- `https://<呼号>.mrrc.vlsc.net:8899/` —— 同一 vhost 的第二个 TLS 入口（原明文口，因 R-H13 升级）
- `https://www.vlsc.net/mrrc_modern/<呼号大写>/` —— 海外边缘 443 路径代理（+0.4~0.6 s，退化路）
```

(b) "文档在哪"表增加一行：

```markdown
| **面向用户的文档站**（5 页：概览/接入/使用/排障 + 单独一页设计） | `mrrc_hub/website/`（先看 `website/README.md` 的事实源映射） |
```

(c) "当前待办"里删除/更新已过期的条目，并把新发现列为待办：

```markdown
5. **脚本与现网对齐**：`deploy_hub_routes.sh`（8899 会退回明文）与 `deploy_www_edge.sh`
   （缺 `path proxy` 模式）落后于现网 —— 见 `mrrc_hub/deploy/README.md`「⚠️ 脚本与现网漂移」
```

- [ ] **步骤 6：`SDD/14-version-history.md` 追加条目**

```markdown
## V0.9 — 2026-10-01：文档站建立与文档-现网对齐

**新增**：`website/` 面向用户的文档站（5 页：概览 / 接入四步 / 使用与分享 / 排障 /
设计与层层实现），视觉与 `www.vlsc.net` 同源（`octen.css` 原样复制 + `hub.css` 隔离新增）。

**修正（文档 vs 现网）**：
- `SDD/README.md` 能力表把"实例出站隧道""通配子域接入"记为**已跑通（阶段 1）** —— 原文写
  "待实现"，与本仓 §12.8 及 `deploy/README.md` 的实测记录直接矛盾。
- `deploy/README.md` 顶部"状态：未部署"改为已部署；退化路 URL 从 `test1.mrrc.vlsc.net`（子域代理）
  改为现网的 `www.vlsc.net/mrrc_modern/<呼号大写>/`（**路径代理**）。
- §12.8 与 §7.x.1 补明 **8899 已是 TLS 入口**（原明文 301 口，因 R-H13 升级），并补上路径入口的
  **大写呼号**规范。

**记录（未修）**：`deploy_hub_routes.sh` 与 `deploy_www_edge.sh` 落后于现网，重跑会让现网退化
（X1 明文回归 / X2 缺失 `path proxy` 模式）。已在 `deploy/README.md` 加警示块，对齐留作独立变更。

**取证**：hub 与 www 的实际 nginx 配置、证书有效期（2026-09-30 → 2026-12-29）、注册表内容
（仅 `bg1sb 18802`）均于 2026-10-01 现场读取。
```

- [ ] **步骤 7：验证并 commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
grep -n "已跑通（阶段 1" SDD/README.md && grep -n "脚本与现网漂移" deploy/README.md
grep -n "8899" SDD/12-operational-model.md | head
python3 .agents/skills/sdd-guardian/harness/sdd_context.py check --staged
git add SDD/README.md SDD/12-operational-model.md SDD/07-subject-area-model.md SDD/14-version-history.md deploy/README.md
git -C /Users/cheenle/HAM/hub/mrrc_hub add README.md 2>/dev/null || git add ../README.md 2>/dev/null || true
git -c commit.gpgsign=false commit -q -m "docs: 与现网对齐 —— 能力表/入口/退化路/漂移警示

- SDD/README.md 能力表：隧道与通配子域改为已跑通（原文与 §12.8 矛盾）
- deploy/README.md：状态行更新；退化路改为现网的路径代理形态；
  新增「⚠️ 脚本与现网漂移」块记录 X1/X2（只记录不修脚本）
- §12.8 / §7.x.1：补明 8899 已是 TLS 入口、路径入口用大写呼号
- 14-version-history：V0.9 条目"
```

> 注意：根 `README.md` 在 `mrrc_hub` 的**上层目录**（`/Users/cheenle/HAM/hub/README.md`），不在本仓内。若 `git add` 报错说明它不属于任何仓 —— 那就只改文件不提交，并在交付说明里注明。

---

## 任务 10：终验

- [ ] **步骤 1：跑规格 §7 的全部验收判据**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
echo "── AC-4 金规则：不得出现查询串形式的令牌字段 ──"
grep -rnE '[?&](token|code|ticket)=' website/*.html && echo "FAIL" || echo "PASS (0 命中)"

echo "── AC-1 断链 ──"
cd website && python3 - <<'PY'
import re, os
bad = []
for f in sorted(os.listdir('.')):
    if not f.endswith('.html'): continue
    for a in re.findall(r'href="([^"#][^"]*)"', open(f, encoding='utf-8').read()):
        if a.startswith(('http', 'mailto')) or a.endswith(('.css', '.js')): continue
        if not os.path.exists(a): bad.append(f'{f} → {a}')
print('PASS' if not bad else f'FAIL {bad}')
PY

echo "── 5 页齐全、导航互通 ──"
for p in index start use trouble design; do [ -f "$p.html" ] && echo "✓ $p.html"; done
grep -c 'href="design.html"' index.html start.html use.html trouble.html

cd .. && echo "── AC-5 SDD 约束 ──"
python3 .agents/skills/sdd-guardian/harness/sdd_context.py check --staged
```

- [ ] **步骤 2：AC-3 用真实例实跑页面给出的验证命令**

```bash
curl -sI -o /dev/null -w "主路 login  → %{http_code}\n" https://bg1sb.mrrc.vlsc.net:9988/login
curl -s  -o /dev/null -w "主路 health → %{http_code}\n" https://bg1sb.mrrc.vlsc.net:9988/api/health
curl -sI -o /dev/null -w "8899 login  → %{http_code}\n" https://bg1sb.mrrc.vlsc.net:8899/login
curl -sI -o /dev/null -w "退化路      → %{http_code}\n" https://www.vlsc.net/mrrc_modern/BG1SB/
```

预期：`200` / `401` / `200` / `200`（或 302）。任何不符 → 停下来核实是站点写错还是现网变了。

- [ ] **步骤 3：AC-7 移动端目视**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website && python3 -m http.server 8099
# devtools 切到 375px 宽：五页均无横向滚动；design.html 的 .hub-stack 变纵向堆叠；
# 表格在 .hub-table-wrap 内可横滑；导航菜单可展开
```

- [ ] **步骤 4：最终 commit**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git status --short
git log --oneline -12
```

---

## 自检记录

**1. 规格覆盖度**

| 规格章节 | 对应任务 |
| --- | --- |
| §3.1 文件结构（10 个文件） | 任务 1（3 个）、2–6（5 页）、7、8 |
| §3.2 ① 概览 | 任务 2 |
| §3.2 ② 接入四步 | 任务 3 |
| §3.2 ③ 使用与分享 | 任务 4 |
| §3.2 ④ 排障 | 任务 5 |
| §3.2 ⑤ 设计（6 节） | 任务 6 |
| §4 视觉与工程约定（金规则/零构建/无障碍/响应式） | 任务 1（CSS/JS）+ 每个任务步骤 2 的 grep 闸门 + 任务 10 |
| §5 事实源映射 | 任务 7 |
| §6.1 D1–D7（7 处修正） | 任务 9 步骤 1–5 |
| §6.2 X1/X2（漂移记录） | 任务 9 步骤 2(b) |
| §6.3 同步维护（14/README 版本/根 README） | 任务 9 步骤 1、5、6 |
| §7 AC-1…AC-7 | 任务 10 + 各任务验证步骤 |
| §8 风险缓解（未实现带徽标 / 事实源 / 复拷步骤） | 全局约定 3；任务 1 步骤 1；任务 7 步骤 1 第 4 节 |

**遗漏检查**：无。

**2. 占位符扫描**：无 `TODO`/`待定`/`后续实现`/`补充细节`；每个 HTML 任务都给了逐节的结构、类名、文案要点与验证命令。

**3. 类型一致性**：

- CSS 类名前缀统一 `hub-*`；复用的上游类名（`.navbar` `.nav-links` `.nav-actions` `.mobile-menu-toggle` `.footer` `.footer-grid` `.footer-section` `.footer-bottom` `.feature-card` `.perf-card` `.arch-card` `.hub-steps` 之外用 `.steps .step`、`.arch-diagram`、`.vlsc-to-top`、`.vlsc-scroll-progress`、`.vlsc-reveal`）**逐一在 `octen.css` 中确认存在**。
- 徽标类名三态统一：`hub-badge live` / `hub-badge todo` / `hub-badge gap`，`hub.css` 与任务 2/3/4/6 中使用一致。
- `.hub-layer` 的子元素固定为 `.hub-layer-id` + `.hub-layer-body`（内含 `strong` + `span`），`hub.css` 与任务 2/6 一致。
- `.hub-callout` 变体四态 `info` / `warn` / `danger` / `ok` 在 `hub.css` 中定义，任务 3/4/6 使用一致。
- 步骤条两套并存且不冲突：上游 `.steps`（`.step`，网格 + `counter-reset: step`）用于网格场景；本站 `.hub-steps`（`counter-reset: hubstep`）用于纵向编号场景 —— 计数器名不同，不互相干扰。

---

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-10-01-hub-website.md`。两种执行方式：

1. **子代理驱动（推荐）** —— 每个任务调度一个新子代理，任务间审查
2. **内联执行** —— 在当前会话中用 executing-plans 批量执行并设检查点

选哪种方式？
