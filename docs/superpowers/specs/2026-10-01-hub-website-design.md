# MRRC Cloud Hub 文档站与文档全面更新 — 设计规格

| 项 | 值 |
| --- | --- |
| 规格 ID | SPEC-HUB-DOCS-2026-01 |
| 日期 | 2026-10-01 |
| 状态 | 已批准（对话式批准）→ 待实现 |
| 关联 SDD | `SDD/03`（SC-H1/SC-H2/SC-H10）、`SDD/06`（UC-H01/UC-H10）、`SDD/12 §12.7 §12.8`、`SDD/13`（R-H12/R-H13、I-H9） |
| 权威边界 | 电台控制/音频/PTT 实现细节的权威是 `mrrc_modern/SDD/`；本规格只覆盖**接入层文档**与文档站 |

---

## 1. 目标与非目标

### 1.1 目标

1. 在 `mrrc_hub/website/` 下产出一套**可发布的静态 HTML 文档站**，视觉与 `www.vlsc.net` 同源。
2. 以**电台主（HAM 用户）为第一读者**，把"如何通过 Hub 访问自己的电台"讲成可照做的任务流（含注册）。
3. 单独**一页**给工程/平台读者把**设计与层层实现**讲清楚。
4. 全面更新仓库内的 markdown 文档，消除与现网实况的矛盾，并把本次取证到的**脚本/现网漂移**记录在案。

### 1.2 非目标

- **不实现** Portal 自助注册、设备 mTLS、Operator 租约（`SDD` 阶段 2）。文档只标注其为目标态。
- **不修改** `deploy/*.sh`（见 §7：漂移只记录、不修）。
- **不修改** `mrrc_modern/` 仓任何文件（其 `website/js/global-nav.js` 被根 README 列为禁改）。
- **不发布**：`deploy.sh` 只编写、不执行；上线由人决定。

---

## 2. 现网实况基线（2026-10-01 现场取证）

> 本节是本次全部文档改写的**事实源**。凡文档与本节冲突，以本节为准。

### 2.1 Hub `8.160.161.80`（阿里云乌兰察布）

`/etc/nginx/sites-available/mrrc-hub` —— **单一通配 vhost**（53 行，一个 server block）：

| 事实 | 值 |
| --- | --- |
| 监听 | `listen 9988 ssl` + `listen [::]:9988 ssl` + **`listen 8899 ssl`** + `listen [::]:8899 ssl`；`http2 on` |
| 8899 的性质 | **第二 TLS 入口**（原明文口，因 R-H13 升级）。**不再是 301 跳转口** |
| server_name | `~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net$` |
| 未知名字 | `if ($mrrc_port = 0) → 404 "unknown instance"`（不猜测别的实例） |
| 上游 | `proxy_pass https://127.0.0.1:$mrrc_port` |
| 上游校验 | `proxy_ssl_verify on`；`depth 2`；`proxy_ssl_name radio.vlsc.net`；`proxy_ssl_server_name on`；信任 `/etc/ssl/certs/ca-certificates.crt` |
| 日志 | `access_log /var/log/nginx/mrrc-hub.access.log hub_safe`（不记 query） |
| WS | `Upgrade`/`Connection: upgrade`；`proxy_read_timeout 86400`；`proxy_buffering off` |
| 证书 | `/etc/mrrc-hub/tls/fullchain.pem` = **真 Let's Encrypt**，`CN=*.mrrc.vlsc.net`，SAN `*.mrrc.vlsc.net, mrrc.vlsc.net`，**2026-09-30 → 2026-12-29** |
| 续期 | root cron `0 8 * * * /usr/local/sbin/mrrc-hub-cert.sh >> /var/log/mrrc-hub-cert.log` |
| 已装脚本 | `/usr/local/sbin/`：`gen_hub_routes.py`、`mrrc-hub-cert.sh`、`mrrc-hub-cert-hook.sh`、`aliyun-acme-dns-hook.py` |

注册表 `/etc/mrrc-hub/instances.tsv`：**当前仅 `bg1sb 18802`**。
生成物 `/etc/nginx/conf.d/mrrc-hub-map.conf`：`default 0; bg1sb 18802;`。

### 2.2 海外边缘 `www.vlsc.net`（193.111.30.163）

`/etc/nginx/sites-available/vlsc.net` 第 314–356 行 = `MRRC Cloud Hub edge (BG1SB)`：

| 事实 | 值 |
| --- | --- |
| 模式 | **`path proxy`**（脚本注释原文），即 443 上做**整会话反代**，不是 302 跳转 |
| 路径 | `location ^~ /mrrc_modern/BG1SB/` → `rewrite ^/mrrc_modern/BG1SB/?(.*)$ /$1 break; proxy_pass https://tunnel.mrrc.vlsc.net:9988;` |
| Host 覆盖 | `proxy_set_header Host bg1sb.mrrc.vlsc.net`（**关键**：hub 按 Host 路由；转发 `$host` 会撞 hub 的未知实例 404） |
| 前缀告知 | `X-Forwarded-Prefix: /mrrc_modern/BG1SB`（与 `mrrc_modern` 的路径前缀能力配对） |
| 大小写 | `/mrrc_modern/bg1sb` 等小写变体 → **301** 到规范大写 `/mrrc_modern/BG1SB/` |
| 重定向回写 | `proxy_redirect` 把实例的绝对重定向（含 `next=` 的嵌套值）拉回前缀下 |
| 上游校验 | `proxy_ssl_verify on`；`proxy_ssl_name tunnel.mrrc.vlsc.net`；**系统 CA**，**无 pin**（与 §12.8 "已废弃钉证书"一致） |

### 2.3 由此确定的**正确用户入口**（本次文档统一采用）

| 入口 | URL | 特点 |
| --- | --- | --- |
| **主路** | `https://<呼号>.mrrc.vlsc.net:9988/` | 低延迟（实测 118–168 ms），真证书 |
| 主路（等价） | `https://<呼号>.mrrc.vlsc.net:8899/` | 同一张证书、同一个 vhost；仅供只放行该端口的场景 |
| **退化路** | `https://www.vlsc.net/mrrc_modern/<呼号大写>/` | 443 标准端口 + 真证书；多一跳海外往返，约 +0.4–0.6 s。**路径用大写呼号** |
| 局域网 | `http://<内网IP>:8888/`（实例自带） | 不经过 Hub |

### 2.4 实例侧（`mrrc_modern`）

| 事实 | 值 / 出处 |
| --- | --- |
| 默认端口 | `MRRC_WEB_PORT=8888`，`MRRC_WEB_HOST=::` |
| 口令 | 首次启动自动生成随机口令（登录页横幅 + 菜单栏 Show Password…）；`MRRC_WEB_PASSWORD` 可改 |
| Listener 口令 | 可选 `LISTEN_PASSWORD`；为空则**无法进入 listen 角色**（`_listen_password_matches`：空值永不匹配） |
| Listener 入口 | `GET /listen`；token 由 `_role_for_token` 判定为 `listener` |
| Listener 权限 | REST 只读：中间件拒绝 `/api/` 下一切非 GET/HEAD/OPTIONS（`/api/auth/logout` 例外）；可听、可看频谱、可调频换模式；发射被服务端拒绝 |
| WS 端点 | `/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` `/WSatr1000` |
| 登录限流 | 5 次失败 / 300 秒（`_check_login_rate_limit`） |
| 遥测 | `GET /api/session_metrics` |
| PTT 安全 | 实例本地多层释放（Layer 0 + 1–8）；TX 活性闸门 `MRRC_REMOTE_SESSION_TX_HEARTBEAT_S`（"声明能力才受管"）；TOT 上限 |
| TX 仲裁 | **实例侧** key-owner（`_assign_tx_owner_on_connect` / `_promote_tx_owner` / `_claim_tx_owner_for_token`）；Hub 侧租约（AD-H05）**未实现** |
| 路径前缀 | 已支持（`X-Forwarded-Prefix` 配对）；令牌不进 URL 已实现；会话遥测已实现 |

### 2.5 运行时形态（用户最容易踩的坑）

- **隧道**：launchd 常驻 `com.mrrc.fleet-tunnel.<呼号>`，`KeepAlive`，重启/换网自恢复；配置 `~/Library/Application Support/mrrc-fleet/frpc-<name>.toml`（0600）。
- **实例服务本身不是常驻服务**（当前以源码方式运行）。重启后必须手动起，起法见 §3.2 步骤 4。
- env 文件 `~/Library/Application Support/MRRC-Modern/mrrc_modern.env` 含 `USB Audio Device` 这类**带空格的值**，因此必须用 `while IFS='=' read` 循环加载，**不能 `source`**。

---

## 3. 站点设计

### 3.1 文件结构

```
mrrc_hub/website/
├── index.html        ① 概览
├── start.html        ② 接入四步（注册 → 隧道 → 验证 → 自启）
├── use.html          ③ 使用与分享
├── trouble.html      ④ 排障
├── design.html       ⑤ 设计与层层实现（工程侧唯一一页）
├── css/octen.css     ← 从 mrrc_modern/website/css/octen.css 原样复制，不 fork
├── css/hub.css       ← 本站新增组件（层叠图/步骤条/权限矩阵/锚点 TOC/调用框）
├── js/hub.js         ← 移动菜单 / 滚动高亮 / 一键复制；无框架、无构建
├── README.md         ← 站点维护说明：哪页对应哪个事实源、如何发布
└── deploy.sh         ← 幂等发布到 www:/var/www/vlsc.net/mrrc_hub/（**不自动执行**）
```

**发布目标与前置**：部署后站点位于 `https://www.vlsc.net/mrrc_hub/`。现网 `vlsc.net` vhost 未为 `/mrrc_hub/` 单独写 location，预期落入通用静态根 `root /var/www/vlsc.net` 即可开箱服务 —— **但这是预期，不是取证结论**：`deploy.sh` 写完后的第一步必须是实测 `curl -sI https://www.vlsc.net/mrrc_hub/index.html`；若 404，则需在 www 上补一条 `location ^~ /mrrc_hub/`（补配置属独立变更，不在本规格授权范围内，需另行确认）。

**为什么这样分**：`octen.css` 原样复制而非 fork —— 上游改设计时只需重拷一份，本站永远不会成为设计系统的分叉。新增样式一律进 `hub.css`，保证"上游 vs 本站"的差异永远是一眼可见的单一文件。

### 3.2 各页职责与内容骨架

#### ① `index.html` — 概览

- Hero：一句话说清价值（"把你的电台挂到云端，从任何地方用浏览器操作"）
- 三张主张卡：**客户侧零入站**（无公网 IP / 无端口映射 / 无 UPnP，只需出站）/ **一个呼号一个入口** / **PTT 释放永远在本地**
- 30 秒架构图（文字 + CSS，非图片）；节点：你的电台 → 你的电脑（MRRC_modern）→ 出站隧道 → Hub → 你的浏览器
- 分流条：还没装 MRRC_modern → 去 `www.vlsc.net/mrrc_modern/`；已装好 → `start.html`
- 底部：呼号 `bg1sb` 的**真实可点示例入口**（主路 + 退化路），让读者一眼看到目标

#### ② `start.html` — 接入四步

| 步 | 标题 | 内容要点 |
| --- | --- | --- |
| 0 | 前提自检 | 局域网 `http://<内网IP>:8888` 能登录、有音频、能 PTT；知道串口与音频设备；**出站 8989 可达**（公司网可能拦）；记下呼号 |
| 1 | **注册** | **今天（可用）**：联系 Hub 管理员报呼号 → 得到 ①呼号标签 ②隧道端口 `188xx` ③frps token。**目标态（未实现，明确标注）**：Portal 自助注册，四步 = 规范化 → 查重 → 核验 → 分配（UC-H10）。附**为什么必须核验**：呼号是公开标识、入口可被枚举（I-H9 有意接受），所以核验发生在**授予访问之前**，不是事后追责 |
| 2 | 装隧道 | `brew install frp` → `MRRC_HUB_TOKEN=… bash mrrc_hub/deploy/install_instance_tunnel.sh <呼号> <端口>`。说明它**做了什么**（写 0600 配置、装 LaunchAgent+KeepAlive、拒绝与手工 frpc 抢同一名字）与**不做什么**（实例服务不归它管；实例没起就是 502） |
| 3 | 验证 | `tail -5 "…/frpc-<呼号>.log"` → 应见 `login to server success` + `start proxy success`；`curl -sk https://<呼号>.mrrc.vlsc.net:9988/api/health` → **401**；浏览器开 `/login` → **200** |
| 4 | 重启之后 | 隧道自动回来；**实例服务不常驻** → 给出那 3 行 `nohup` 命令 + 必须用 `read` 循环而非 `source` 的原因 |

#### ③ `use.html` — 使用与分享

- **入口对照表**（§2.3 三行 + 局域网行），每行给适用场景
- **两把口令 = 两个角色**（用户最易搞错处）：

| 口令 | 进入 | 听 | 看频谱 | 调频/换模式 | 发射 |
| --- | --- | --- | --- | --- | --- |
| 主口令 | `/` | ✅ | ✅ | ✅ | ✅ |
| `LISTEN_PASSWORD` | `/listen` | ✅ | ✅ | ✅ | ❌ **服务端拒绝**（不是 UI 隐藏） |

  并说明：`LISTEN_PASSWORD` **为空时 listen 角色不可进入** —— 必须先设置才能分享。

- **分享给朋友**：给什么（URL + listener 口令）；**别**给什么（主口令 = 发射权）
- **现状直说（不是设计）**：Hub 侧 Operator 租约（AD-H05）**未实现**；多人同时用主口令登录时，由**实例侧** key-owner 仲裁谁在发射
- **安全须知**：PTT 释放不依赖云端（断线/掉网由实例本地强制回 RX）；登录限流在隧道路径下退化为**全局桶**（已知退化，用户已决定暂缓）
- 手机上用：PWA 加到主屏 / 原生 App

#### ④ `trouble.html` — 排障

一张主表（症状 → 优先检查），来源：`SDD §12.7` + `§12.8 排障增补` + `deploy/README` 实测抓到的问题：

| 症状 | 优先检查 |
| --- | --- |
| 浏览器打不开 / 证书警告 | 用的是不是 `:9988`（或 `:8899`）；退化路是否用大写呼号；是否用了明文口 |
| 502 | 隧道在不在（`frpc-*.log`）；实例服务在不在（8888 是否 listen） |
| 登录页出来但控制台黑屏 | 5 个 WS 端点哪个被拒：`4001` 未授权 / `4003` 角色拒绝；Listener 是否连了 `/WSaudioTX` |
| 能听不能发 | 用的是不是主口令；是不是走了 `/listen` |
| 登录反复 429 | 限流 5 次/300 秒；隧道路径下是**全局桶**（已知退化） |
| 音频卡顿 | 上行利用率；Listener 并发；按 AD-H14 先降瀑布帧率 |
| 退化路慢 | 正常：多一跳海外，+0.4–0.6 s；优先用主路 |
| 边缘 502 而直连正常 | www 的上游校验信任源是否被改回**钉证书**（应保持系统 CA） |
| 重启后连不上 | 实例服务未起（不常驻）→ 步骤 4 |

#### ⑤ `design.html` — 设计与层层实现（工程侧唯一一页）

六节，自上而下一条论证线：

1. **层叠图**（CSS 画，不用图片）：`L0 电台硬件` → `L1 实例本地 MRRC_modern` → `L2 隧道（frpc 出站 / frps 只绑回环）` → `L3 Hub 入口（nginx 通配 vhost + TLS + map 路由）` → `L4 海外边缘（443 路径代理）` → `L5 用户客户端`；右侧横切条：证书 / 身份（呼号）/ 审计 / 遥测
2. **每层一张卡**：职责 · 实现在哪个文件 · **边界在哪（这层不做什么）** · 失效时的表现
3. **关键决策表**（每条配"当时为什么不选另一种"）：`AD-H01` 实例主动出站、`AD-H02` 通配子域、`AD-H03` 控制/数据面分离、`AD-H05` 单写者租约、`AD-H06` **PTT 释放权威在实例本地**、`AD-H07` 令牌不进 URL、`AD-H08` Listener 语义、`AD-H15` 呼号即身份
4. **三条安全不变量**：Hub 永不是 PTT 写者 / token 与 code 不进 URL 与日志 / 禁止关闭上游证书校验
5. **实况 vs 目标态差距表**：✅ 已跑通（通配子域、真证书、隧道、透明代理、上游校验）/ ⚠️ MVP 必修（PTT 半开释放、令牌不进 URL 的前端侧）/ ⏳ 阶段 2（Portal、设备 mTLS、Operator 租约）
6. **边界声明 + 深度指引**：电台控制/音频/PTT 的权威在 `mrrc_modern/SDD/`；本页只讲接入层；给出指向 `SDD/` 各章的链接

---

## 4. 视觉与工程约定

- **样式**：`octen.css` 原样复制；新组件只进 `hub.css`。设计令牌沿用上游：`--bg-primary:#000`、`--accent:#22d3ee`、`Inter` / `JetBrains Mono`、`--accent-glow`。
- **零构建**：纯静态 HTML/CSS/JS。无 npm、无打包、无框架。外部依赖仅 Google Fonts + Font Awesome CDN（与 `www.vlsc.net` 一致）。
- **导航**：与上游同构 —— `.navbar` + `.nav-links` + `.nav-actions` + `.mobile-menu-toggle`；站内 5 页互为导航；移动断点 `960px`。
- **无障碍**：语义标签；导航 `<nav>`；表头 `<th scope>`；`aria-current="page"` 标当前页；跳过导航链接。
- **响应式**：层叠图在窄屏改为纵向堆叠；表格加横向滚动容器。
- **金规则合规（关键）**：`.agents/skills/sdd-guardian/harness/constraints.json` 的 `hub-token-not-in-url` 规则会扫 `**/*.html`，模式为 `[?&](token|code|ticket)=`。因此**本站 HTML 中不得出现字面 `?code=` / `?token=` / `?ticket=` 串**。写法：讲这个决策时用"查询参数形式的 launch code"或只写字段名 `code`。**不通过 `exclude_scope` 削弱规则**，靠写法合规。
- **验收**：`python3 .agents/skills/sdd-guardian/harness/sdd_context.py check --staged` 必须 `clean`。

---

## 5. 事实源映射（站点维护的核心约定）

站点每一页的每个事实，都必须能指回一个权威出处。`website/README.md` 记录这张表：

| 站点内容 | 事实源 |
| --- | --- |
| 入口 URL、端口、TLS | 现网 `nginx -T`；本文档 §2.1 §2.2 §2.3 |
| 实例侧行为（口令、角色、WS、PTT） | `mrrc_modern` 源码 + `mrrc_modern/SDD/` |
| 注册流程与核验理由 | `SDD/06 UC-H10`、`SDD/03 SC-H10` |
| 安全不变量 | `SDD/08` AD-H06/07/11、`SDD/15` |
| 排障 | `SDD/12 §12.7 §12.8`、`deploy/README.md` |
| 运营事实 | `SDD/12 §12.8` |

**规则**：站点不发明事实。无法取证的内容一律写"待核实"，不猜。

---

## 6. Markdown 文档更新清单

### 6.1 修正与现网/自相矛盾处

| # | 文件 | 问题 | 修法 |
| --- | --- | --- | --- |
| D1 | `SDD/README.md` 能力表 | "实例出站隧道 **待实现**"、"通配子域接入 **待实现**"，与本仓 `SDD/12 §12.8` 及 `deploy/README.md` 实测已跑通**直接矛盾** | 按 §2 改为「**已跑通（阶段 1，frp 通道）**」，并注明目标态是内置 Fleet Agent |
| D2 | `deploy/README.md` 第 3 行 | "**状态：未部署。**"，与同文件后半 "已验证（2026-09-30 真实公网）" 自相矛盾 | 改为「阶段 1 已部署并在真实公网验证」，保留历史段落但标注日期与阶段 |
| D3 | `deploy/README.md` 退化路表 | 写 `https://test1.mrrc.vlsc.net`（443 子域代理），与现网 `https://www.vlsc.net/mrrc_modern/BG1SB/`（**路径**代理）不符 | 按 §2.2 §2.3 改写；说明脚本的 `proxy`（子域）模式**不是**现网形态 |
| D4 | `deploy/README.md` "还差你一条 DNS 记录" | 仍指 `test1`；现网实例是 `bg1sb` | 标注为历史，指向 §2.1 注册表实况 |
| D5 | `deploy/README.md` 证书表 | "自签 → 待 DNS-01 通配真证书" | 已兑现：改记为真 LE，`2026-09-30 → 2026-12-29`，cron 每日 8:00 |
| D6 | `SDD/12 §12.8`、`SDD/07 §7.x.1`、根 `README.md` | 只写 `:8899`，未说明其性质**已从明文口改为第二 TLS 入口** | 补一句：9988 与 8899 现均为 TLS 入口；8899 原为明文 301 口，因 R-H13 升级 |
| D7 | 根 `README.md`、`SDD/12 §12.8` | www 路径入口未写**大写呼号**规范 | 补：路径大小写敏感，小写会被 301 到大写规范形式 |

> 撤回说明：本规格起草前的口头简报曾把"文档写 `:8899`"判为错误。现场取证后确认**现网 8899 已是 TLS**，文档**并未写错**（见 D6：缺的是"为什么"而不是"是什么"）。此处以现场为准。

### 6.2 漂移记录（**记录，不修脚本**）

| # | 漂移 | 后果 |
| --- | --- | --- |
| X1 | `deploy/deploy_hub_routes.sh` 生成**两个** server block：`listen 8899;`（明文）+ 301，以及 `listen 9988 ssl`。现网是**一个** block 且 `8899` 为 **TLS** | **重跑脚本会把 8899 从 TLS 退回明文** → 在境内被阿里云改写（R-H13 的失效模式）。另：脚本头部注释仍写 "TLS … currently self-signed"，现网已是真 LE |
| X2 | `deploy/deploy_www_edge.sh` 只实现 `redirect` 与 `proxy`（子域）两种模式；现网用的是**第三种 `path proxy`**（Host 覆盖 + 路径大小写规范化 301 + `X-Forwarded-Prefix` + `proxy_redirect` 回写） | 重跑脚本会把现网形态**降级**为 302 或子域代理，丢掉"标准端口 + 真证书 + 前缀透明"三项收益。www 上的 `/tmp/deploy_www_edge.sh` 与仓库版本**仅空白差异**，说明那段配置是手工落的 |

**处置**：在 `deploy/README.md` 顶部加"⚠️ 脚本与现网漂移"警示块，明确"**重跑前先读 X1/X2**"；本次**不改脚本**（改部署脚本的风险与验证成本超出文档任务范围），把对齐留给独立变更。

### 6.3 同步维护

- `SDD/14-version-history.md`：追加本次条目（文档站建立 + 文档与现网对齐 + 漂移记录）
- `SDD/README.md`：版本号 V0.8 → V0.9，索引补 `website/` 指向
- 根 `README.md`：文档在哪一节补"面向用户的文档站在 `mrrc_hub/website/`"

---

## 7. 验收判据

| # | 判据 | 怎么验 |
| --- | --- | --- |
| AC-1 | 5 个 HTML 页面在 `file://` 与 HTTP 下均可正常打开、导航互通、无断链 | 本地起 `python3 -m http.server` 后逐页点检 |
| AC-2 | 视觉与 `www.vlsc.net` 同源（黑底 + `#22d3ee`、Inter/JetBrains Mono、同样的 navbar/card 语汇） | 与 `mrrc_modern/website/zh/index.html` 并排目视 |
| AC-2b | 若执行发布：`https://www.vlsc.net/mrrc_hub/index.html` 可达且 5 页均 200 | `curl -sI` 逐页；404 时按 §3.1 前置说明处理（需另行确认补 nginx location） |
| AC-3 | `start.html` 的四步可被一个"只装了 MRRC_modern、局域网正常"的用户照做走通，且每步都有**可执行的验证命令与期望输出** | 逐条命令在本机实跑（步骤 3 的两条验证命令用 `bg1sb` 实跑） |
| AC-4 | 站点中**不存在**字面 `?token=` / `?code=` / `?ticket=` | `grep -rnE '[?&](token\|code\|ticket)=' mrrc_hub/website --include=*.html` 命中 0 |
| AC-5 | `sdd_context.py check --staged` 输出 `clean` | 直接跑 |
| AC-6 | 站点不含"发明的事实"：每个 URL / 端口 / 口令语义都能指回 §2 或 SDD | 逐页对照 §5 映射表 |
| AC-7 | 移动端（≤960px）无横向溢出、层叠图纵向堆叠正常 | 浏览器 devtools 断点检查 |

---

## 8. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 现网随时间漂移，站点写的事实过期 | 文档失真（本项目的既有顽疾） | §5 事实源映射 + `website/README.md` 写明"复验清单"；站点每页脚注日期 |
| 把目标态（Portal）误写成已完成 | 用户照做失败 | 所有未实现项一律带 **⚠️ 未实现（阶段 2）** 徽标 |
| `octen.css` 与上游分叉 | 设计系统漂移 | 原样复制；新样式只进 `hub.css`；`website/README.md` 记复拷步骤 |
| 触及金规则导致 `check` 非 clean | 提交被拦 | AC-4 的 grep 作为写前/写后双重闸门 |
| 站点发布后与 `mrrc_modern` 站导航不一致 | 用户迷路 | 本站不做跨站导航改造（不改 modern 仓）；两站互相独立，各自完整 |

---

## 9. 交付物

1. `mrrc_hub/website/` 下 5 个 HTML + `css/hub.css` + `css/octen.css` + `js/hub.js` + `README.md` + `deploy.sh`
2. 本规格文档
3. `docs/superpowers/plans/2026-10-01-hub-website.md` 实现计划
4. 按 §6 更新的 markdown（`SDD/README.md`、`SDD/12`、`SDD/07`、`SDD/14`、`deploy/README.md`、根 `README.md`）
