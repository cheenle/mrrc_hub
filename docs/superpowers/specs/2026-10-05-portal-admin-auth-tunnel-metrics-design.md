# Portal 后台管理：用户名/密码认证 + 隧道性能指标 — 设计规格

| 项 | 值 |
| --- | --- |
| 规格 ID | SPEC-HUB-PORTAL-AUTH-METRICS-2026-01 |
| 日期 | 2026-10-05 |
| 状态 | 已批准（对话式批准）→ 待实现 |
| 关联 SDD | `SDD/05`（NFR-H005 延时、NFR-H017 带宽余量）、`SDD/08`（AD-H07 令牌不进 URL、AD-H09 Cookie 命名与属性、AD-H11 隧道/auth 分离）、`SDD/10`、`SDD/11`、`SDD/12 §12.9`、`SDD/14` |
| 权威边界 | 隧道数据的权威是 hub 上 frps 面板的实测应答；实例内部状态（电台/音频/会话数）不在本规格内。行为变更须按 `hub-docs-sync` 同步 SDD 并在同一变更里更新版本历史 |

---

## 0. 决策记录（对话逐条批准）

| # | 问题 | 决定 |
| --- | --- | --- |
| 1 | 改哪里 | `mrrc_hub/portal` 的 `/admin` 运维台 |
| 2 | 谁登录 | 少数运维（2–5 人），一人一账号，审计可归因到人 |
| 3 | 会话方式 | 表单登录 + 服务端会话 + 会话 Cookie（HttpOnly/SameSite=Lax，Secure 见 §3.3）+ CSRF 令牌 |
| 4 | 凭据存储 | htpasswd 兼容文件（`用户名:$apr1$…` 一行一个） |
| 5 | 哈希与校验 | `$apr1$`（`openssl passwd -apr1` / `htpasswd -m` 生成），portal 内置纯 Python 校验 |
| 6 | 旧运维令牌 | **保留**为机器凭据（`X-Portal-Token` 请求头，脚本/curl）；浏览器路径改走会话 |
| 7 | 防爆破 | 固定阈值硬锁定（用户名 5 次 / IP 10 次，锁 5 分钟）；接受"可被恶意触发锁定管理员"的代价 |
| 8 | 带宽数据源 | 给 frps 开 `webServer` 面板（绑 127.0.0.1 + basic auth），portal 读 per-proxy 统计；热重载不重启 |
| 9 | 采集方式 | 后台采样线程 + 每实例内存环形历史（约 1 小时） |
| 10 | 展示位置 | 新增独立「隧道」视图 |
| 11 | 会话时长 | 空闲 8 h / 绝对 24 h |

---

## 1. 目标与非目标

### 1.1 目标

1. `/admin` 运维台从"单一共享令牌"升级为**一人一账号的用户名/密码**登录，审计能回答"谁批的/谁撤的"。
2. 管理台新增**隧道性能可观测面**：每实例的延时、带宽（上行/下行）、今日流量、当前连接数，数据来自 frps 面板的实测值。
3. 不破坏既有的机器路径：脚本/curl 继续用 `X-Portal-Token` 完成 `verify/reject/grant/revoke`。
4. 所有拿不到的数据**如实标注原因**，不用 0 或猜测冒充（延续 V0.24 的可观测面原则）。

### 1.2 非目标

- **不做**远期 hub 票证/成员管理（`SDD/08` AD-H09 的目标态）：本规格只做管理台的人员登录，不签发面向实例的票证，不碰 `<呼号>.mrrc.vlsc.net` 的访问控制。
- **不做**指标持久化、告警推送、图表库；历史只存内存、重启即清。
- **不做** `mrrc_modern` 实例侧任何改动；实例内部状态拿不到是设计使然。
- **不新增** Python 第三方依赖（portal 维持纯标准库）。

---

## 2. 现状基线与取证边界

### 2.1 本轮已核实（本机可复现）

| 事实 | 证据 |
| --- | --- |
| `/admin` 现为单一令牌登录，无用户名概念 | `portal/app.py` L1048-1060；`_operator_ok()` 常数时间比较 |
| 六个视图（总览/申请/实例/系统/审计/呼号库）；系统页③已展示隧道层端口差集 | `portal/app.py` `_admin()` |
| 管理页"采集不到的"明确列了 frps 每代理统计 | `portal/app.py` L965-966；`SDD/14` V0.24 |
| 隧道四态探测 = 对回环端口的 TLS 握手（穿越 frps→frpc→实例） | `_tunnel_state()`；`SDD/14` V0.23 |
| frps 由 `bootstrap-hub.sh` 生成配置，pin 0.71.0；未开 `webServer`，日志 root-only | `deploy/bootstrap-hub.sh` L106-131；`SDD/14` V0.24 表 |
| frpc 代理名 = 注册表实例名（label） | `deploy/install_instance_tunnel.sh` L133 `name = "${NAME}"` |
| Python 3.13+ 已移除 `crypt` 模块 ⇒ 纯 stdlib 无法直接校验任何 crypt 哈希 | 本机 3.14 实测；hub 为 Ubuntu 26.04 |
| `$apr1$` 测试向量（盐固定时可复现） | `openssl passwd -apr1 -salt 8aaVXyz9 'S3cret-pass!'` → `$apr1$8aaVXyz9$ibFv5KrTL/uJnYuHKvW6I0` |
| `htpasswd -i -v` 支持 stdin 传密码（不进 argv/ps） | 本机实测；仅作为**可选**的账号管理工具 |
| 测试约定：`make_handler(portal, token=…)` + `ThreadingHTTPServer(("127.0.0.1", 0))` | `tests/test_portal.py` |

### 2.2 需上机核验（部署前置检查，写进 §8 检查单）

| 待核验 | 为什么重要 |
| --- | --- |
| frps 0.71.0 面板 API 的真实字段名（`trafficIn/trafficOut/curConns/todayTrafficIn…`） | 采集器按假设解析；字段缺失必须诚实降级而不是显示错数 |
| frps 0.71.0 是否响应 `SIGHUP` 热重载 | 决定部署是否要短暂中断隧道 |
| hub 上 `mrrc-portal.service` 的 ExecStart 现状 | 加 `--users-file` 等参数或在默认路径即可 |
| nginx `mrrc-portal-mrrc` vhost 是否透传 `X-Forwarded-For`/`X-Real-IP` | 缺了则 IP 锁定退化成全局桶（`SDD/12 §12.8` 的同款教训） |
| `/etc/mrrc-hub/portal-users` 是否已存在 | 不存在则部署时创建空文件并要求先加账号，否则管理台无人能登录 |

---

## 3. 认证与会话设计

### 3.1 账号文件

- 默认路径 `/etc/mrrc-hub/portal-users`（`--users-file` 可覆盖），htpasswd 兼容格式：`用户名:$apr1$盐$哈希`，一行一个；空行与 `#` 注释跳过；重复用户名取**最后一条**并记警告。
- 权限：`0640 root:mrrcportal`（沿用 `/etc/mrrc-hub/frps.token.portal` 的服务账号可读副本模式）。生成建议：

```bash
printf '%s:%s\n' "$USER_NAME" "$(openssl passwd -apr1)" | sudo tee -a /etc/mrrc-hub/portal-users
sudo chown root:mrrcportal /etc/mrrc-hub/portal-users && sudo chmod 640 /etc/mrrc-hub/portal-users
```

（`htpasswd -m /etc/mrrc-hub/portal-users <用户名>` 等价，可选依赖 `apache2-utils`。）

- 文件不可读 ⇒ 用户名登录一律失败并明确报"账号文件不可读"；**令牌路径不受影响**（不会把运维锁死）。
- 账号增删改**在每次登录时读文件**（不缓存在内存），改密码/删人不需重启 portal；已建立的会话不因改密而失效（接受，列为边界）。

### 3.2 `$apr1$` 校验（新模块 `portal/htpasswd.py`）

- 纯 stdlib 实现 Apache MD5-crypt（apr1）：解析 `$apr1$<盐(≤8)>$<22 字符哈希>`；按算法重算 16 字节摘要，用 crypt 字母表 `./0-9A-Za-z` 的固定字节序输出，最后 `hmac.compare_digest` 比较。
- 用户不存在时**也跑一次固定假哈希**，响应时间不泄露用户是否存在。
- 未知哈希前缀（bcrypt `$2*`、SHA1 `{SHA}`、`$1$` 等）⇒ **拒绝登录**并写审计事件，绝不静默通过。
- 测试向量固化 §2.1 那条；实现阶段用 `openssl passwd -apr1 -salt <随机盐>` 做随机交叉验证（≥20 组）。

### 3.3 会话与 Cookie

- 新模块 `portal/sessions.py`：内存 `dict[会话 ID] → {user, csrf, created, last_seen}` + 锁；`threading.Lock` 保护；进程重启即失效（接受、文档明说）。
- 会话 ID：`secrets.token_urlsafe(32)`；登录成功时新发（防会话固定）。
- Cookie：`mrrc_portal_session`（与实例 `mrrc_auth` 无命名冲突，满足 `hub-cookie-name-not-instance-auth`）；`Path=<base 或 />`、`HttpOnly`、`SameSite=Lax`。
- `Secure` 策略（`--cookie-secure auto|on|off`，默认 `auto`）：**auto = 除非请求 Host 是回环名（127.0.0.1/localhost/[::1]），否则一律加 Secure**。这样：公网经 nginx 访问必然带 Secure（不依赖 nginx 是否记得 `X-Forwarded-Proto`）；本机 SSH 隧道直连 8890 仍可登录。`off` 仅供本地开发。
- 时限：空闲 8 h（`last_seen` 超时即失效）、绝对 24 h（自 `created`）；均可由 `--session-idle-hours` / `--session-max-hours` 覆盖。每次请求顺带清理过期会话。

### 3.4 路由与 CSRF

| 路由 | 方法 | 认证 | 说明 |
| --- | --- | --- | --- |
| `/admin` | GET | 无（未登录→登录页）/ 会话 | 视图切换用 `?view=<六视图之一>`；不是状态变更，无 CSRF |
| `/admin/login` | POST | 无 | 用户名+密码在请求体；成功 303 到 `/admin` |
| `/admin/logout` | POST | 会话 + CSRF | 销毁会话、清 Cookie，303 到 `/admin` |
| `/verify` `/reject` `/grant` `/revoke` | POST | 会话 + CSRF，**或** `X-Portal-Token` 请求头 | 浏览器表单走前者，脚本走后者 |
| `/apply` `/status` `/enroll` `/claim` `/` | 不变 | 无 | 租户自助面不动 |

- CSRF：每会话一个随机令牌，管理台所有**状态变更**表单带隐藏字段 `csrf`；服务端常数时间比较，失败 403。登录表单本身不带（登录 CSRF 无状态可劫持，接受）。
- 导航从"每页表单 POST 隐藏令牌"改为 GET 链接（视图名不是秘密；`noindex` 保持）。
- 表单动作不再接受 body 里的 `token` 字段（浏览器已无此需要；机器路径只认请求头，保持"凭据不进表单/URL"）。

### 3.5 登录防爆破（按决策 7）

- `sessions.py` 内的 `LoginGuard`：用户名维度 5 次失败 / 5 分钟 ⇒ 锁 5 分钟；来源 IP 维度 10 次失败 / 5 分钟 ⇒ 锁 5 分钟；两条独立、到期自解；登录成功清空该用户名与该 IP 的计数。
- 锁定期返回 `429` + `Retry-After`；账号不存在与密码错误返回**同一文案**，只写事件不泄露。
- 来源 IP：仅当对端是回环时信任 `X-Forwarded-For`（取最后一个）/`X-Real-IP`，否则用 socket 对端地址。nginx 未透传时退化为 `127.0.0.1` 全局桶——**这是已记录的退化，部署检查单强制核对**（§8）。
- 明确接受：按用户名锁可被恶意触发，把管理员锁在门外最多 5 分钟；解锁手段 = 等待或重启 portal。

### 3.6 机器路径（不变的部分）

- `X-Portal-Token` 请求头继续授权四个运维动作，常数时间比较，令牌文件路径不变（`/etc/mrrc-hub/portal.token`）。
- 令牌执行的动作在审计里记 `actor=token`；会话执行记 `actor=<用户名>`。

---

## 4. 隧道指标采集

### 4.1 数据源与 hub 侧改动

- `frps.toml` 增加（由 `bootstrap-hub.sh` 幂等生成）：

```toml
webServer.addr = "127.0.0.1"
webServer.port = 7100
webServer.user = "<生成>"
webServer.password = "<生成>"
```

- 面板凭据文件：`/etc/mrrc-hub/frps-web.credentials`（`user:password` 一行，`0640 root:mrrcportal`，`openssl rand -hex 24` 生成，不入 git）。
- `frps.service` 增加 `ExecReload=/bin/kill -HUP $MAINPID`；部署用 `systemctl reload frps`。若实测 0.71.0 对 SIGHUP 不生效，则退化为 `restart`（隧道瞬断、frpc 自动重连），在维护窗口执行并记录。
- 面板只绑回环，不新增对外暴露面；nginx 不代理它。

### 4.2 采集器（新模块 `portal/metrics.py`，时钟/取数可注入）

- portal 启动时（`main()`，`--dry-run` 除外）起一个 daemon 线程，默认每 **30 s** 一轮（`--metrics-interval`）：
  1. `GET http://127.0.0.1:7100/api/proxy/tcp`（HTTP Basic）一次拿到全部代理；按注册表 label 匹配，取 `trafficIn`、`trafficOut`、`todayTrafficIn`、`todayTrafficOut`、`curConns`。字段缺失时不猜、标"面板未给出该字段"。
  2. 与上一轮累计值差分 → 上行/下行速率（bps）；检测计数器回绕/重置（当前值 < 上轮）⇒ 本轮速率标空并附原因。
  3. 对每个实例做一次隧道探测并计时（复用现有 `_tunnel_state` 的 TLS 握手；并发探测，总预算 ≤ 采样间隔的一半）→ 延时 ms + 隧道态。
  4. 每实例写进 `deque(maxlen=--metrics-history，默认 120)`，即约 1 小时。
  5. hub 网卡速率：`/proc/net/dev` 非回环接口合计的差分（Linux；取不到就标不可得）。
- 凭据每轮重新读取（支持轮换不重启）；文件不可读 ⇒ 整轮标"凭据不可读"。
- 环形缓冲与采样状态在锁内替换；视图只读取快照，绝不在请求线程里访问面板。

### 4.3 失败语义（诚实降级，逐条可渲染）

| 情况 | 呈现 |
| --- | --- |
| 面板连不上/拒绝 | `面板不可用：<原因>` |
| 凭据文件不可读 | `凭据不可读：<路径>` |
| 面板 401 | `面板凭据错误` |
| 注册表里的 label 不在面板列表 | `frps 里没有这个代理（租户隧道未连）` |
| 采样过旧（> 3×间隔） | `采样停滞 <n>s` |
| 延时探测失败 | 隧道四态文案 + `无应答`，延时显示 `—` |
| 平台不支持（macOS 开发机无 `/proc/net/dev`） | `本平台不适用` |

任何情况下都**不显示 0 冒充测量值**。

### 4.4 新增配置项（全部有默认值，hub 不必显式传）

`--users-file`、`--cookie-secure`、`--session-idle-hours`、`--session-max-hours`、`--frps-api-url`、`--frps-credentials`、`--metrics-interval`、`--metrics-history`。

---

## 5. 界面呈现

### 5.1 新「隧道」视图（导航第 4 项）

| 列 | 内容 |
| --- | --- |
| 标签 | 注册表实例名（`<code>`） |
| 隧道 | 四态 pill（复用现有文案/颜色） |
| 延时 | 当前 · 均值 · 峰值（ms，取内存历史窗口） |
| 下行 / 上行 | 最近采样速率 · 窗口均值（bps，自动转 kbps/Mbps） |
| 今日流量 | `todayTrafficIn` / `Out` |
| 连接数 | `curConns` |
| 采样 | 最近采样时刻 + 新鲜度（`<n>s 前`）；不可用则显示 §4.3 的原因 |

### 5.2 系统页③（隧道层，替换现文案）

- frps 面板：状态（可用/原因）、`serverinfo` 合计流量（若面板给出）。
- 全部代理合计上下行速率；hub 网卡出入速率。
- 保留现有端口差集与 frpc 控制连接信息。

### 5.3 总览页

- 注册表实例行追加一行摘要：`n 在线 / 平均延时 / 当前总出带宽`；数据不可用时同 §4.3 文案。

### 5.4 约定

- 沿用 `_PORTAL_CSS` 与 `class=stack` 窄屏堆叠；无 JS、无外链资源、无图表库。
- 登录页显示用户名+密码；管理台导航栏显示"当前用户 + 登出"。
- 所有管理页维持 `noindex`。

---

## 6. 审计与安全

- `store.audit()` 增加 `actor` 字段（用户名 / `token` / 空）：`_audit(data, callsign, event, detail, actor="")`；旧条目没有该字段 ⇒ 渲染 `—`。四个运维动作与登录事件都带 actor。
- 新增审计事件：`login_ok`、`login_failed`（含来源 IP）、`login_locked`；不记密码、不记哈希。
- 安全不变量复核：
  - 令牌/会话值不进 URL、不进 Location、不进日志（满足 `hub-token-not-in-url`）；
  - Cookie 名独立于实例（满足 `hub-cookie-name-not-instance-auth`）；
  - Cookie `HttpOnly`，公网路径带 `Secure`（满足 `hub-ticket-cookie-httponly` 的意图）；
  - 凭据文件 0640、现成命令生成、不入 git（满足 `hub-secrets-hardcoded`）。
- 明文密码只存在于登录请求体与 apr1 重算的瞬时内存中，不落盘、不进日志。

---

## 7. 测试计划

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_htpasswd.py`（新） | 固定向量（§2.1）正/负例；随机盐 × 随机密码与 `openssl passwd -apr1` 交叉验证（openssl 不在则跳过并说明）；未知前缀拒绝；畸形行/重复用户名/注释行；UTF-8 密码 |
| `tests/test_portal_auth.py`（新） | 登录成功/失败/锁定/解锁（假时钟）；会话过期（空闲/绝对）；登出后旧 Cookie 失效；登录换发新会话 ID；CSRF 缺失/错误 403；未登录访 `/admin` 见登录页；`X-Portal-Token` 路径**不回归**；`Secure` Cookie 策略（回环 Host vs 公网 Host）；审计 actor 落盘；用户不存在时的时序等价（同一假哈希路径） |
| `tests/test_portal_metrics.py`（新） | 差分速率；计数器重置；环形缓冲上限；各失败语义；面板字段缺失降级；`SIGHUP` 无关（纯采集逻辑）；渲染端到端：假采样器 → 「隧道」视图列真的拼对（延续 V0.24 的"拼接也要测"教训） |
| `tests/test_portal.py`（改） | `make_handler` 新参数带默认值，既有 26 组不回归；系统页文案断言更新 |

- 运行方式沿用 `python3 tests/test_portal.py`（兼容 pytest）。
- 采集器的时钟、frps 取数、探测函数全部注入替身（`hub-testing-conventions`），不依赖宿主是不是 Linux/systemd。

---

## 8. 部署与文档同步

### 8.1 部署步骤（hub，逐条可执行）

1. 建账号文件（§3.1），先加至少一个账号；`chown root:mrrcportal` + `chmod 640`。
2. `bootstrap-hub.sh` 更新后重跑或手工落 frps 面板段 + 凭据文件；`systemctl daemon-reload`；`systemctl reload frps`（先按 §2.2 核验 SIGHUP；不行则维护窗口内 restart 并核对隧道全部恢复）。
3. 核验 nginx portal vhost 透传 `X-Forwarded-For`/`X-Real-IP`；缺则补 `proxy_set_header` 并 `nginx -t && systemctl reload nginx`。
4. 重启 `mrrc-portal.service`；核对启动日志无异常、`/admin` 登录页可达。
5. 端到端复验：登录→（新）隧道视图出数→日志出→锁定→登出→curl 令牌动作仍成功。

### 8.2 文档同步（同一变更内完成）

| 文件 | 改什么 |
| --- | --- |
| `portal/README.md` | 账号文件与生成命令、会话/Cookie/CSRF/锁定、四路由表、机器路径说明、新视图与数据源 |
| `deploy/README.md` | frps 面板段与凭据文件、`ExecReload`、账号文件权限、nginx 头检查项 |
| `deploy/bootstrap-hub.sh` | frps.toml 面板段 + 凭据生成 + 单元 `ExecReload` + 账号文件占位（不覆盖已有） |
| `SDD/10-service-model.md` | 运维动作两种传令方式更新（会话+CSRF / 令牌头） |
| `SDD/11-component-model.md` | Portal 组件描述加认证与采集模块 |
| `SDD/12 §12.9` | 账号、Cookie、采集器、部署检查单实况 |
| `SDD/14-version-history.md` | 新条目（动机、边界、测试数、实测） |
| `SDD/README.md` | 版本号 bump |

- 提交前跑 `python3 .agents/skills/sdd-guardian/harness/sdd_context.py check --staged`，必须 `clean`。

---

## 9. 验收判据

| # | 判据 | 怎么验 |
| --- | --- | --- |
| AC-1 | `tests/test_portal.py` + 三个新测试文件全绿 | 直接跑 |
| AC-2 | apr1 实现在固定向量与 ≥20 组随机交叉验证上与 `openssl passwd -apr1` 完全一致 | 测试输出 |
| AC-3 | 用户名/密码登录可用；错误密码与不存在用户响应一致；5 次失败后 429 且 5 分钟后自解 | 端到端 + 测试 |
| AC-4 | 公网经 nginx 的响应带 `HttpOnly` + `SameSite=Lax` + `Secure`；登录/登出/CSRF 行为符合 §3 | `curl -i` 对照 |
| AC-5 | `X-Portal-Token` 的 curl 动作不回退：`/verify` 等仍 200 | 端到端 |
| AC-6 | 「隧道」视图出现每实例延时与带宽，数值与 frps 面板 `/api/proxy/tcp` 现场读数一致 | 面板 curl 与页面并排比对 |
| AC-7 | 面板停用/凭据不可读时页面显示对应原因而不是 0 或旧值冒充 | 临时改错凭据实测后还原 |
| AC-8 | 审计能回答"谁批的"：新动作条目带正确用户名，令牌动作带 `token` | 查看 audit 视图/`portal.json` |
| AC-9 | `sdd_context check --staged` = `clean`；§8.2 文档全部同步 | 直接跑 + 逐项核对 |
| AC-10 | 既有 26 组测试与租户自助面无回归（`/`、`/apply`、`/status`、`/enroll`、`/claim`） | 测试 + 端到端 |

---

## 10. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| frps 0.71.0 面板字段名与假设不符 | 采集显示错数 | §2.2 先核验真响应；字段缺失/类型不符一律标原因，不用 0 冒充 |
| SIGHUP 不生效 | 部署需断隧道 | 先核验；不生效则维护窗口 restart，并记录在 SDD/12 |
| nginx 未透传来源 IP | IP 锁定退化全局桶 | §8 检查单强制核对；退化时文档明说 |
| `$apr1$` 抗暴力弱 | 离线撞库风险高于 bcrypt | 强密码 + 固定阈值锁定 + nginx `limit_req`；该取舍已在决策记录中明确 |
| 按用户名锁定可被恶意触发 | 管理员被关门外 ≤5 分钟 | 已接受；解锁=等待/重启；审计必留 `login_locked` |
| 内存历史重启即空 | 短暂无历史可看 | 视为可接受（非目标明确不做持久化）；页面显示新鲜度 |
| apr1 自实现有微妙字节序错误 | 登录全挂或放行错误密码 | 固定向量 + 随机交叉验证；未知格式拒绝 |
| 多会话并行改同一仓库 | 冲突/覆盖 | 开工前 `git -C mrrc_hub log --oneline -5`；提交前再查 |

---

## 11. 交付物

1. `portal/htpasswd.py`、`portal/sessions.py`、`portal/metrics.py`（新）；`portal/app.py`、`portal/store.py`（改）。
2. `tests/test_htpasswd.py`、`tests/test_portal_auth.py`、`tests/test_portal_metrics.py`（新）；`tests/test_portal.py`（改）。
3. `deploy/bootstrap-hub.sh`、`deploy/README.md`（改）。
4. `portal/README.md` 与 §8.2 所列 SDD 章节（改）。
5. 本规格文档 + 对应实现计划（`docs/superpowers/plans/2026-10-05-portal-admin-auth-tunnel-metrics.md`）。
