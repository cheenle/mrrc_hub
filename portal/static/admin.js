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
      if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;
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

  function refreshLive() {
    if (!window.htmx) return;
    document.querySelectorAll('[data-live]').forEach(function (el) {
      window.htmx.trigger(el, 'refresh');
    });
  }

  function boot() {
    document.querySelectorAll('[data-pause]').forEach(function (b) {
      b.hidden = false;                       // 关掉 JS 时按钮不出现，免得按了没反应
      b.addEventListener('click', function () { setPaused(!paused); });
    });

    /* 刷新按钮：拿当前视图的 live 区重取一次。没有 JS 时它不存在。 */
    document.querySelectorAll('[data-reload]').forEach(function (b) {
      b.addEventListener('click', refreshLive);
    });

    /* 刷新完成后把"最后更新时间"重置并显示"刚刚"。 */
    if (window.htmx) {
      document.body.addEventListener('htmx:afterSwap', function (ev) {
        var status = document.querySelector('[data-live-status]');
        if (status && !paused && ev.target && ev.target.matches && ev.target.matches('[data-live]')) {
          status.textContent = '实时 · 刚刚';
        }
      });
      document.body.addEventListener('htmx:responseError', function () {
        var status = document.querySelector('[data-live-status]');
        if (status) status.textContent = '刷新失败 · 稍后重试';
      });
    }

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
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
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
      if (typeof dlg.showModal === 'function') {
        try { dlg.showModal(); } catch (e) { /* 已经 open 或不被支持：保持页内显示 */ }
      }
      dlg.querySelectorAll('[data-dialog-close]').forEach(function (b) {
        b.addEventListener('click', function () {
          if (typeof dlg.close === 'function') { dlg.close(); }
          dlg.remove();
        });
      });
    });

    /* 切回前台时立刻补一次，不用等下一个周期。 */
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && !paused) refreshLive();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
