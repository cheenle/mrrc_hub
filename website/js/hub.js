/* ══════════════════════════════════════════════════════════════════════
   MRRC Cloud Hub 文档站 — 渐进增强
   ──────────────────────────────────────────────────────────────────────
   无框架、无构建。每一项都是纯增强：JS 不执行时页面仍然完全可读可用。
   移动菜单、回到顶部、滚动进度条复用 octen.css 里已有的上游类名
   （.nav-links.active / .vlsc-to-top.show / .vlsc-scroll-progress /
   .vlsc-reveal.in），所以本站的观感与 www.vlsc.net 同源。
   ══════════════════════════════════════════════════════════════════════ */
(() => {
  

  /* ── 移动菜单（navbar 上用的是 onclick="toggleMobileMenu()"，保持上游约定） ── */
  window.toggleMobileMenu = () => {
    var nav = document.querySelector('.nav-links');
    if (nav) nav.classList.toggle('active');
  };

  document.addEventListener('DOMContentLoaded', () => {

    /* ── navbar 滚动加深 + 进度条 + 回到顶部 ── */
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
      backTop.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }

    /* ── 滚动入场（上游 .vlsc-reveal / .in） ── */
    var reveals = document.querySelectorAll('.vlsc-reveal');
    if (reveals.length && 'IntersectionObserver' in window) {
      var ro = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) { e.target.classList.add('in'); ro.unobserve(e.target); }
        });
      }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
      reveals.forEach((el) => { ro.observe(el); });
    } else {
      reveals.forEach((el) => { el.classList.add('in'); });
    }

    /* ── 目录高亮（只在有 .hub-toc 的页面生效） ── */
    var tocLinks = Array.prototype.slice.call(document.querySelectorAll('.hub-toc a'));
    if (tocLinks.length && 'IntersectionObserver' in window) {
      var byId = {};
      var targets = [];
      tocLinks.forEach((a) => {
        var id = (a.getAttribute('href') || '').replace(/^#/, '');
        var el = id ? document.getElementById(id) : null;
        if (el) { byId[id] = a; targets.push(el); }
      });
      var so = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          tocLinks.forEach((a) => { a.classList.remove('active'); });
          var a = byId[e.target.id];
          if (a) a.classList.add('active');
        });
      }, { rootMargin: '-15% 0px -70% 0px', threshold: 0 });
      targets.forEach((el) => { so.observe(el); });
    }

    /* ── 代码块一键复制 ── */
    document.querySelectorAll('.hub-code').forEach((box) => {
      var pre = box.querySelector('pre');
      if (!pre || !navigator.clipboard) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hub-copy';
      btn.textContent = '复制';
      btn.addEventListener('click', () => {
        navigator.clipboard.writeText(pre.innerText).then(() => {
          btn.textContent = '已复制';
          btn.classList.add('done');
          setTimeout(() => {
            btn.textContent = '复制';
            btn.classList.remove('done');
          }, 1600);
        });
      });
      box.appendChild(btn);
    });
  });
})();
