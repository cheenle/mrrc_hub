# 静态资源分发：gzip + 两层缓存（hub 边缘 / 实例）

- **日期**：2026-10-17
- **起因**：`https://ba4eg.mrrc.vlsc.net/` 每次加载都慢，大静态件反复全量重传
- **范围**：`mrrc_hub`（边缘 nginx）+ `mrrc_modern`（实例静态服务）
- **状态**：设计已定（方案 C：边缘先落地 + 产品侧随版本），待实现

## 1. 证据（2026-10-17 实测，ba4eg 实例、已登录态）

| 观测 | 值 | 取法 |
| --- | --- | --- |
| 首屏静态件总量 | **816 KB**（未压缩） | 抓 `index.html` 的 13 个引用逐个 `curl -w %{size_download}` 求和 |
| 最大单件 | `modules/opus_wasm.js` **534,520 B**，耗时 0.9–1.1 s | 同上 |
| 响应头 | 只有 `ETag` + `Last-Modified`，**无 `Cache-Control`** | `curl -D -` |
| 条件请求 | `If-None-Match` 与 `If-Modified-Since` **都返回 200 + 完整 body** | 534,520 B 全量回来 —— Starlette `FileResponse` 不实现条件 GET |
| gzip | 只压 `text/html`（nginx 默认 `gzip_types`），JS/CSS 原样 | `curl --compressed /modules/opus_wasm.js` → 无 `content-encoding`，534,520 |
| 边缘日志 | 同一浏览器反复 `GET /modules/opus_wasm.js 200 534520` | hub `/var/log/nginx/mrrc-hub.access.log` |
| 附带 A | `/favicon.png` 不存在 → 每次加载白拿 40 KB 的 `index.html`（SPA 回落） | `curl /favicon.png` → 200 / 40,046 B / `text/html` |
| 附带 B | `static/sw.js` **从未被任何页面注册**（死代码），却有 6 处测试为它钉缓存版本 | `grep -rn serviceWorker static/` 只有 ft8 的 unregister；已部署 `index.html` 里 `serviceWorker` 出现 0 次 |

**根因三条**（缺一条都解释不了"每次都很慢"）：① 实例不发缓存头；② 实例不支持条件请求，重新校验必然全量重传；③ 边缘不压 JS/CSS。

实测预算（同一批文件）：**816 KB → gzip 后 274 KB → 缓存命中后 0 B**。

## 2. 目标 / 非目标

**目标**

- 重复访问不重传大静态件：浏览器缓存命中；即便重新校验，也由边缘用 304 作答，**不穿隧道**。
- 首屏静态件体积降到约 1/3（gzip 由边缘做，不动客户端）。
- 部署后新版本仍然**可立即看到**（见 §3.4 四条路径）；用户**硬刷新**能强制回到实例。
- 每条断言都有 `curl` 或单测，不靠"看起来快了"。

**非目标（明确不做）**

- 不做实例侧 gzip：边缘已压；两端都压会让"上游是否已 `Content-Encoding`"变成一类新的缓存边角。
- 不做 HTML 的边缘缓存：`/` 的响应**取决于 Cookie**（未登录 302 / 已登录 200），缓存它会把"要登录"固化成整个 TTL。
- 不注册也不删除 `static/sw.js`（见 §7）。
- 不改日志格式（AD-H07 / NFR-H014：query 不入日志），不加 `$host`。

## 3. 设计

### 3.1 缓存策略（两层用同一套值，避免"边缘和实例各说各话"）

| 类别 | 判定 | `Cache-Control` | 浏览器 | 边缘 |
| --- | --- | --- | --- | --- |
| 静态件 | URI 扩展名 ∈ `js mjs css map png jpg jpeg gif svg ico webp avif woff woff2 ttf otf wasm wav mp3 m4a` | `public, max-age=3600` | 1 小时内直接用缓存，不发请求 | 缓存 1 小时，**只缓存 200** |
| 文档 | `text/html`（含 SPA 回落）、`application/json` | `no-cache` | 每次重新校验（有 ETag → 廉价 304） | **不缓存** |
| 入口脚本 | `sw.js` | `no-cache` | 同上 | 不缓存 |
| 其余 | `/api/*`、`/WS*`、`/login` | 原样 | 原样 | 不缓存 |

**为什么是 1 小时**：`index.html` 里的 `?v=` 是**手工** bump 的（实测 `ft710_main.js?v=44`）。漏 bump 时，1 小时是用户最长踩到旧代码的窗口；换来的是重复访问零传输。要更快看到新版就走 §3.4 的硬刷新/版本号路径。**不写 `immutable`**：`?v=` 的纪律靠人，`immutable` 会把漏 bump 的代价从 1 小时放大到一年。

### 3.2 hub 边缘（`mrrc_hub/deploy/`，脚本安装，幂等）

`/etc/nginx/conf.d/mrrc-hub-cache.conf`（新增，脚本写出）

```nginx
proxy_cache_path /var/cache/nginx/mrrc-assets levels=1:2 keys_zone=mrrc_assets:32m
                 max_size=1g inactive=7d use_temp_path=off;

# 只有 200/304 才带缓存头。307（未登录）与 404 若带上 max-age，
# 浏览器会把"要登录"或"没有这个文件"记下来 —— 这是本设计最危险的一处。
map $status $mrrc_asset_cc { default ""; 200 "public, max-age=3600"; 304 "public, max-age=3600"; }

# 客户端明确要求别用缓存（硬刷新 / DevTools 禁用缓存）→ 绕过边缘缓存回源
map $http_cache_control $mrrc_client_nocache {
    default 0;
    "~*no-cache" 1;
    "~*no-store" 1;
}
```

`/etc/nginx/snippets/mrrc-hub-upstream.conf`（新增，两处 `include`）

把 `proxy_pass` + 逐实例 TLS 校验 + 转发头放进一个片段，让 `location /` 与资源 location **共用同一份**上游定义。理由是现成的：`deploy/README.md` X1 那条漂移正是"同一件事在两处写、漏改一处"——资源 location 若漏抄 `proxy_ssl_verify on`，就等于 NFR-H021 被悄悄关掉。

```nginx
if ($mrrc_port = 0) { return 404 "unknown instance\n"; }
proxy_pass https://127.0.0.1:$mrrc_port;
proxy_ssl_verify on;
proxy_ssl_verify_depth 2;
proxy_ssl_name $mrrc_tls_name;
proxy_ssl_server_name on;
proxy_ssl_trusted_certificate /etc/mrrc-hub/trust-bundle.pem;
proxy_ssl_session_reuse on;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400;
```

vhost（`/etc/nginx/sites-available/mrrc-instances`）三处改动：

```nginx
server {
    …原有 server_name / ssl / access_log 不动…

    # nginx 默认只压 text/html；实例自己也不压 ⇒ JS/CSS 原样过隧道。
    gzip on;
    gzip_vary on;
    gzip_min_length 256;
    gzip_proxied any;
    gzip_types text/css application/javascript text/plain application/json image/svg+xml;

    location / {
        include snippets/mrrc-hub-upstream.conf;   # 原 location 内容改为 include
        proxy_buffering off;                       # WS 与单向流仍不缓冲
        # 这里刻意不加任何 Cache-Control：该路径会返回 no-store 的敏感响应，
        # 覆盖它比不优化更糟。HTML 的 no-cache 由实例侧（§3.3）负责。
    }

    # 静态件：唯一的缓存路径。正则 location 优先于 location /。
    location ~* \.(?:js|mjs|css|map|png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|wasm|wav|mp3|m4a)$ {
        include snippets/mrrc-hub-upstream.conf;
        proxy_buffering on;

        proxy_cache mrrc_assets;
        proxy_cache_key "$mrrc_instance$uri$is_args$args";   # 实例 + URI + query
        proxy_cache_valid 200 1h;              # 只列 200：302/307/401 永不落盘
        proxy_cache_revalidate on;             # 过期后用 If-Modified-Since 回源复验
        proxy_cache_lock on;                   # 冷缓存并发只放一个回源
        proxy_cache_lock_timeout 5s;
        proxy_cache_background_update on;      # 过期条目先在后台更新
        proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
        proxy_cache_bypass $mrrc_client_nocache;

        proxy_hide_header Cache-Control;       # 只发一份，避免与实例侧重复
        add_header Cache-Control $mrrc_asset_cc always;
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

设计取舍（写明理由，免得下次被"顺手改成更激进"）：

- **按扩展名判定，不按响应 Content-Type**：Content-Type 要在收到响应后才知道，而 `proxy_cache` 是否启用是 location 级的；按 URI 判定才能在同一个 location 里既开缓存又保持判断简单。
- **缓存按 `$mrrc_instance` 分键**：同一台 hub 服务所有实例，不能串味（SC-H5 的跨实例错绑是 Critical）。
- **未登录也能从边缘拿到静态件**：这是本设计的**唯一行为变化**。这些文件本来就是安装包里公开的前端代码（无密钥），代价可接受；换来的是"登录页之后的一切都不再穿隧道"。反向的代价（把 302 缓存给已登录用户）由 `proxy_cache_valid 200` 与 `map $status` 两道挡住。
- **不做 HTML 边缘缓存**：见 §2。

### 3.3 实例侧（`mrrc_modern`）

`server.py::serve_static` 三件事：

1. **缓存头**：`_cache_control_for(path)` → `.html` / `.json` / `sw.js`：`no-cache`；其余静态件：`public, max-age=3600`。SPA 回落返回的 `index.html` 也走同一条判定。
2. **条件请求 → 304**：按 Starlette `FileResponse` 的同一公式算 `ETag`（`md5(f"{mtime}-{size}")`，换成别的公式会让所有已缓存用户重新下载，且与框架自带头不一致），`If-None-Match` 命中或 `If-Modified-Since` ≥ mtime → `304 Not Modified`（带 `ETag` / `Last-Modified` / `Cache-Control`，不带 body）。
3. **有扩展名的缺失文件 → 404**（不再回落 `index.html`）：`/favicon.png`、`/favicon.ico`、`/nope.js` 这类请求目前拿回 40 KB 的 HTML。规则收敛到一句：**无扩展名才回落**（`/`、`/settings`、`/ft8` 等 SPA 路由全部不受影响）。

不做实例侧 gzip（§2）；不改 `?v=` 生成与清单（手工 bump 的纪律不动）。

### 3.4 四条路径（都要能说清"新版本怎么到达用户"）

| 场景 | 走哪条路 | 结果 |
| --- | --- | --- |
| 首次访问（或缓存过期） | 浏览器 → hub → 隧道 → 实例 | 静态件 gzip 后 ~274 KB |
| 正常重复访问 | 浏览器缓存（<1 h） | 0 请求；只 `/`（9 KB gzip）回源 |
| 浏览器缓存过期后的重新校验 | 浏览器 → hub，边缘命中 | **304，不穿隧道** |
| 硬刷新（Cmd/Ctrl+Shift+R） | `Cache-Control: no-cache` → 边缘 BYPASS → 实例 | 强制拿到实例当前版本 |
| 部署新版 | `index.html` 是 `no-cache`（每次校验）→ 引用 `?v=` 新号 → 新 URL ⇒ 必然重新取 | 新版本立即生效 |

## 4. 失败模式与回滚

| 失败模式 | 表现 | 处置 |
| --- | --- | --- |
| 资源 location 漏抄上游 TLS 设置 | 全部实例 502 / `certificate verify failed` | 上游定义只存在于 snippet 一处（§3.2）；`nginx -t` + 抽查 3 个实例 |
| 307/404 被缓存 | 用户被"要登录"卡住 | `proxy_cache_valid 200` + `map $status`；验收脚本专门测这条 |
| 边缘缓存与实例内容不一致 | 用户拿到旧 JS | `proxy_cache_bypass $mrrc_client_nocache` + 1 h 窗口 + 硬刷新；`X-Cache-Status` 可现场判读 |
| 缓存盘写满 | `/var` 告警 | `max_size=1g`（根分区剩 5 G）；`inactive=7d` 自动淘汰 |
| 需要整体回滚 | — | 备份原 vhost → 恢复 + `rm -f /etc/nginx/conf.d/mrrc-hub-cache.conf` + `rm -rf /var/cache/nginx/mrrc-assets` + `nginx -t && systemctl reload nginx` |

## 5. 验收清单

**边缘**（`deploy/verify_hub_cache.sh <instance>`，新增脚本，逐条打印 PASS/FAIL）

1. 资源（带 Cookie）：200 + `Cache-Control: public, max-age=3600`；第二次 `X-Cache-Status: HIT`。
2. 资源 + `If-None-Match`：**304**，且 `Content-Length` 为空。
3. 资源 + `Cache-Control: no-cache`：`X-Cache-Status: BYPASS`，body 完整。
4. `--compressed`：`opus_wasm.js` 从 534,520 降到 ~198,494，且 `Vary: Accept-Encoding` 在。
5. **未登录**请求冷资源：307；随后携带 Cookie 的请求仍拿到 200 与文件字节（证明 307 没被缓存）。
6. `/` 与 `/api/status`：**没有** `X-Cache-Status`、也没有新增 `Cache-Control`（不因本改动被缓存）；`/api/status` 现在会带 `Content-Encoding: gzip`（`gzip_types` 里的 `application/json`，预期变化）。
7. `nginx -t` 通过；`nginx -T` 里的 vhost 与仓库脚本渲染结果一致（防"改了现网没进仓"）。

**实例**（`tests/`，本仓测试约定）

1. `no-cache` vs `public, max-age=3600` 的分类，逐扩展名钉死。
2. `If-None-Match` 命中 → 304；不命中 → 200；`If-Modified-Since` 两条同理。
3. 有扩展名的缺失路径 → 404；无扩展名 → `index.html`（现状不回归）。
4. 未带 Cookie 取静态件仍然 307（鉴权顺序不因缓存头而变）。

## 6. 仓库与文档同步

- `mrrc_hub`：`deploy/README.md`（X1 漂移收口 + 新增"缓存与压缩"一节）、`SDD/12-operational-model.md`、`SDD/14-version-history.md`、`SDD/README.md` 版本号；脚本与 snippet 入库（**现网的改动必须同时进仓**，否则重跑脚本就把边缘改动抹掉）。
- `mrrc_modern`：`server.py` + `tests/` + `CHANGELOG.md`（入当前未发布的 v1.28.1 段）+ 按本仓 doc-sync 规则同步 SDD 与 `tests/README.md`。
- 产品侧落地后，实例即使不经 hub（局域网直连、B2/B3 退化路径、别的反代）也拿到同样的缓存语义。

## 7. 待决与后续（本次不做，记录在案）

1. **`sw.js` 是死代码**：没有任何页面注册它，却有 6 处测试为它的 `CACHE` 版本号钉值，`tests/test_static_cache_busting.py` 的整套推理建立在"它是已安装用户唯一的可见性通道"这个错误前提上。要么注册它（多一层 cache-first，与实时控制类应用风险相抵），要么删掉它并重写那批测试。**本次不动**，但这条必须有人认领。
2. **`favicon.png` 仍然不存在**：`manifest.json` 与 `apple-touch-icon` 都指向它；本次只保证它 404 不再拖 40 KB。要真图标得先有品牌资产（仓库里只有 Android 的矢量 drawable）。
3. **HTML 的边缘缓存**：若 `no-cache` 的每次校验（~0.4 s 隧道 RTT）仍嫌慢，可在边缘按"是否带 `mrrc_auth` Cookie"分键、TTL 60 s 缓存 HTML，并把 `Cache-Control` 只加在 200 上。本次刻意不做。
4. **`?v=` 的自动生成**：把手工 bump 换成内容摘要（构建期注入），才能安全地用长 TTL / `immutable`。
