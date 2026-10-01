/* ══════════════════════════════════════════════════════════════════════
   MRRC Cloud Hub 文档站 — 渐进增强
   ──────────────────────────────────────────────────────────────────────
   无框架、无构建。每一项都是纯增强：JS 不执行时页面仍然完全可读可用。
   移动菜单、目录高亮、代码复制在本站实现；回到顶部、滚动进度条、
   全局顶 nav、GA 由门户共享的 global-nav.js 提供（每页 <script> 引入），
   与 www.vlsc.net 各子站同源，不在这里重复实现。
   ══════════════════════════════════════════════════════════════════════ */
(() => {
	/* ── 移动菜单（navbar 上用的是 onclick="toggleMobileMenu()"，保持上游约定） ── */
	window.toggleMobileMenu = () => {
		var nav = document.querySelector(".nav-links");
		if (nav) nav.classList.toggle("active");
	};

	document.addEventListener("DOMContentLoaded", () => {
		/* ── navbar 滚动加深（回到顶部与进度条由 global-nav.js 负责） ── */
		var navbar = document.querySelector(".navbar");

		function onScroll() {
			var y = window.scrollY || document.documentElement.scrollTop;
			if (navbar) navbar.classList.toggle("scrolled", y > 8);
		}
		window.addEventListener("scroll", onScroll, { passive: true });
		onScroll();

		/* 注：不用 octen.css 的 .vlsc-reveal。它默认 opacity:0、必须靠 JS 加 .in 才可见，
       JS 一旦加载失败正文会整段隐形。入场动画改用纯 CSS 的 .animate（octen.css 已有）。 */

		/* ── 目录高亮（只在有 .hub-toc 的页面生效） ── */
		var tocLinks = Array.prototype.slice.call(
			document.querySelectorAll(".hub-toc a"),
		);
		if (tocLinks.length && "IntersectionObserver" in window) {
			var byId = {};
			var targets = [];
			tocLinks.forEach((a) => {
				var id = (a.getAttribute("href") || "").replace(/^#/, "");
				var el = id ? document.getElementById(id) : null;
				if (el) {
					byId[id] = a;
					targets.push(el);
				}
			});
			var so = new IntersectionObserver(
				(entries) => {
					entries.forEach((e) => {
						if (!e.isIntersecting) return;
						tocLinks.forEach((a) => {
							a.classList.remove("active");
						});
						var a = byId[e.target.id];
						if (a) a.classList.add("active");
					});
				},
				{ rootMargin: "-15% 0px -70% 0px", threshold: 0 },
			);
			targets.forEach((el) => {
				so.observe(el);
			});
		}

		/* ── 代码块一键复制 ── */
		document.querySelectorAll(".hub-code").forEach((box) => {
			var pre = box.querySelector("pre");
			if (!pre || !navigator.clipboard) return;
			var btn = document.createElement("button");
			btn.type = "button";
			btn.className = "hub-copy";
			btn.textContent = "复制";
			btn.addEventListener("click", () => {
				navigator.clipboard.writeText(pre.innerText).then(() => {
					btn.textContent = "已复制";
					btn.classList.add("done");
					setTimeout(() => {
						btn.textContent = "复制";
						btn.classList.remove("done");
					}, 1600);
				});
			});
			box.appendChild(btn);
		});
	});
})();
