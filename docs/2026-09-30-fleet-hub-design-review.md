# 评审：MRRC Cloud Hub 远程接入设计 v2.0 —— 代码取证意见

| 项目 | 值 |
|---|---|
| 被评审对象 | `MRRC_modern_远程接入统一设计文档_v2.0_20260930.md`（架构评审稿） |
| 评审日期 | 2026-09-30 |
| 取证基线 | `mrrc_modern` @ `4f385dd`（v1.21.0 Stable，main）；`mrrc`（旧架构，含隧道脚本） |
| 取证方法 | 文档结论逐条与运行代码/部署脚本核对，全部结论附 `file:line`；不采信文档对现有能力的描述 |
| 判定口径 | ✅ 有代码支撑 / ⚠️ 与代码冲突 / ❌ 文档缺口 / 📊 账面假设待实测 |

---

## 0. 总体判定

文档的架构方向成立：**实例主动出站 + 云端统一入口 + 控制面与接入面分离 + 单写多读 + PTT 在实例本地闭环**，与现有代码的演进方向一致，选型理由也站得住。

但文档有 **1 个结构性缺陷** 和 **4 个 P0 级事实错误**，其中两个直接推翻 MVP 的可行性前提。

**结构性缺陷：文档没有"现状基线"章节。** §6.1 选型表列了 frp / Tailscale / Cloudflare / 自研 Agent 四个候选，却没有一行是"现在已经在生产跑的东西"。实际上存在**至少 4 套**远程接入机制，其中一套（IPv6 直连 + nginx 幂等反代）**已经在公网生产环境运行** —— v1.21.0 的发布说明里就写着"公网收听入口改用 DNS 名解析，家中 IPv6 变化自愈"。

后果：§1.2 / §12 的阶段划分把"验证公网可达"当成从零开始的工作，而真实起点是 **"把已经手工做通、但每实例都要作者 SSH 上服务器改 nginx 的方案，变成可自助、可复制、可 200 实例化的方案"**。这是一次真实场景的自然实验，文档把它丢掉了。

---

## 1. 现状基线（文档缺失，应补入 §2.3 / §6.1）

| # | 机制 | 实现载体 | 公网通道 | 认证 | 每实例运维成本 |
|---|---|---|---|---|---|
| **B1** | SSH 反向端口转发 | `mrrc/mrrc_tunnel.sh` + launchd `com.user.mrrc.tunnel.plist`（KeepAlive + 30s throttle）+ `install_tunnel_service.sh` | `ssh -N -R 8891/8892:localhost → www.vlsc.net`，远端 nginx 反代出 `radio1.vlsc.net` | **服务器系统账号** `cheenle` + `ssh-copy-id` 免密 | 手工：装 key、服务器账号、nginx 段 |
| **B2** | **IPv6 直连 + nginx 幂等反代（现役生产）** | `deploy_listen_proxy.sh` → nginx `location = /mrrc_modern/{listen,login,...}` | `https://www.vlsc.net/mrrc_modern/listen` → `proxy_pass https://radio.vlsc.net:8888`（**IPv6，无隧道**） | 实例自身的 admin / listen 密码 | **必须 SSH 到 www.vlsc.net + sudo 改 nginx** |
| **B3** | 路径前缀 Web 代理 | `pi_web_proxy.py`（`AUTH_COOKIE = "pi_web_auth"`，basic auth + cookie） | 同 B2 的 www.vlsc.net 侧 | 独立的 basic auth / cookie（httponly，30 天） | 已存在 |
| **B4** | 实例→作者服务器上报通道 | `deploy_support_receiver.sh` + `tools/support_receiver/server.py`（独立 systemd unit、8098 端口、独立存储 `/var/www/support-modern`、口令走 0600 root-only EnvironmentFile） | 出站 HTTPS | 共享口令（**非设备证书**） | 一次性 |

证据：`mrrc/mrrc_tunnel.sh:5-6,37`；`deploy_listen_proxy.sh:15`；`pi_web_proxy.py:44,159`；`deploy_support_receiver.sh:5-7,30-33`。

### 1.1 B2 的工程细节（MVP 的血肉，文档一字未提）

- `resolver 1.1.1.1 8.8.8.8 valid=300s` + `proxy_pass $变量` → nginx **每 300 s 重解析 AAAA**，家宽 IPv6 前缀变化自愈，无需 reload（`deploy_listen_proxy.sh:39,50,58,66,74,82,96`）
- `proxy_ssl_verify off`（`:43,54,62,70,78,86,100`）→ **公网链路上实例的自签证书校验被关闭**。自签来源见 `ssl_bootstrap.py:1-10`：10 年有效期、SAN 只覆盖 localhost / hostname / LAN IP
- 每个前端资源一条 `location`（listen、login、listen.js、rx_worklet_processor.js、`/modules/`、`/api/`、`/WS`）→ **路径前缀方案的税**，每加一个前端资源就要动中心 nginx
- `location ^~ /mrrc_modern/WS` 的 `^~` 是 load-bearing 的，注释写明 "regex locations（.js 静态规则）outrank a plain prefix match"（`:93,95`）
- 幂等逻辑里留着事故痕迹："an older regex once missed the `^~` form and left a duplicate that **broke nginx -t**"（`:121`）
- `proxy_redirect /login /mrrc_modern/login` 手工修重定向（`:47`）；WS `proxy_read_timeout 86400`（`:105`）

**结论：B2 是自然实验。** 它证明了 IPv6 直连对**收听类**远程访问在中国家宽场景下可行（无需 NAT 穿透、客户不装客户端）；也证明了它的**不可扩展性**（每实例需人工改中心 nginx、TLS 校验被关、令牌明文进 URL）。文档 §1.3 选择"通配子域而非路径前缀"是**正确的**，而 B2 正是这个决策的实锤证据来源 —— 应该把证据写进文档，而不是让读者以为这是纯理论取舍。

---

## 2. P0：与代码冲突的四条

### P0-1 PTT 对"半开连接"不释放 → §5.4 / §9.3 / §13.7 在 Hub 场景下不成立

这是全文最严重的一条，因为它同时踩到**安全不变量**和**场景假设**。

代码事实：

- 断线释放（dead-man switch）**只在 WebSocket 真正断开时触发**。`server.py:134-136` 的注释直说：

  > `Opt-in stuck-keyup watchdog (MRRC_PTT_MAX_TX_SECONDS, 0 = off). Covers clients that hang WITHOUT disconnecting — the dead-man switch and client watchdogs never fire for a zombie-but-connected socket.`

- 唯一兜底 `MRRC_PTT_MAX_TX_SECONDS` **默认 0 = 关闭**（`config.py:263`：`_env_float("MRRC_PTT_MAX_TX_SECONDS", 0.0)`），检查粒度 `MAX_TX_WATCHDOG_INTERVAL = 1.0` s（`server.py:139`）

在 LAN 场景这没问题：断线 ≈ 真断线。但在文档 §2.3 **自己定义的场景**（运营商 NAT、双层 NAT、弱网、频繁换网）里，"**租约还在、TCP 已死**"的半开连接是常态而非例外：

| 失效模式 | 实例本地是否释放 | 现状 |
|---|---|---|
| EOF 型断线（浏览器关闭 / 进程退出 / TCP RST） | ✅ 立即（dead-man switch） | 满足 §9.3 的 ≤1 s |
| **半开型断线**（NAT 掉表、Wi-Fi 切换、CGNAT 静默丢弃、休眠唤醒） | ❌ 不触发 | 只剩云端 TTL —— **而 §5.4 明令禁止依赖它** |
| TX 中进程卡死但仍连着 | ❌ 不触发 | 兜底默认关闭 |

**判定：§13 验收标准第 7 条当前对 EOF 型断线成立、对半开型不成立；而半开在 Hub 模式下比 LAN 下更常见。**

这不是文档写错，而是**文档把 PTT 安全当成"既有能力可复用"（§1 开头、§5.4），实际 Hub 场景需要一个新机制**：

1. Tunnel Gateway 在 TX 期间必须做**应用层心跳并主动关流**，不能等 TCP；（和/或）
2. 实例侧把 stuck-keyup watchdog 从"可选上限"改造为"租约心跳失效即释放"。

**此项应进 MVP 必备项，不是阶段 2。**

### P0-2 会话令牌在 URL query 里 × 透明代理 → MVP 就违反 §10.1

- 实例会话令牌是 **30 天有效的长期凭证**，且**被前端拼进 URL query**：`static/ft710_main.js:49,63`（`"?token=" + encodeURIComponent(token)`）、`static/listen.js:26,31`。
- 实例侧同时接受 cookie 与 **query 参数**：`_verify_auth` 认 `request.cookies.get(AUTH_COOKIE)` 与 `request.query_params.get("token")`（`server.py:608-614`）。
- 实例自身跑 **uvicorn 默认访问日志**（`uvicorn.Config(app, log_level="info", ...)`，`server.py:3701,3704-3708`），访问日志包含 query string。
- 项目**已经知道这个问题**：`support_bundle.py:19-20` 的脱敏正则备注写着 "a `?token=` inside a URL"。但脱敏**只发生在导出诊断包时**。

于是：MVP 透明代理模式下，Hub access log、Tunnel Gateway 日志、途中的任何 nginx 都会**逐条记录 30 天令牌明文**；令牌还会进浏览器历史与 Referer。§10.1「日志中不记录密码、私钥、完整 ticket」与 §5.2「不把可复用 JWT 暴露在 URL」**在当前实现下无法同时成立** —— 这与"先透明代理、阶段 2 再上托管鉴权"的排期直接冲突。

三条出路（按成本排序，**任一都必须进 MVP**）：

1. Hub / Tunnel / nginx 全链路访问日志脱敏 `token=`（照搬 `support_bundle.py` 的 `SECRET_VALUE_RE`，成本极低；但浏览器历史 / Referer 仍未解决）
2. 前端改用 Cookie 或 `Sec-WebSocket-Protocol` 传令牌，不再进 URL（根治；改动局限在 `static/*.js` + `_verify_auth`）—— **建议与 MVP 同批**
3. 把 Hub-managed 鉴权从阶段 2 提前到阶段 1

### P0-3 Hub 票证 Cookie 与实例会话 Cookie 同 origin 共存，§5.2 / §3.2 未定义

- 实例登录时设 cookie：`response.set_cookie(AUTH_COOKIE, token, max_age=30*24*3600, httponly=False, samesite="lax")`，注释写明 `httponly=False  # JS needs to read it for WebSocket`（`server.py:2843-2848`）。
- §5.2 第 8 步要求 Access Gateway 设置 "host-only、**HttpOnly**、Secure 会话 Cookie"。

在通配子域方案下，**Access Gateway 与实例共享同一 origin**（`<instance-id>.mrrc.vlsc.net`），两者 cookie 共用命名空间。因此：

- §3.2 的 host-only 隔离是**对的**（跨实例子域确实隔离），但文档**没有讨论同一 origin 内两个会话层如何共存**：Hub 票证 cookie 必须与 MRRC 的 `AUTH_COOKIE` **不同名**，生命周期也不同（票证短时效 vs 实例会话 30 天）。
- 实例 cookie **没有 `Secure` 属性**，且 **30 天不过期** —— 在"远程接入 + MFA + 一次性 code"的安全叙事下，**30 天免登录是事实上的会话时长**，§10.1 的短时效要求会被它整体绕过。
- MVP 透明代理模式下，Hub 的 HttpOnly 票证 cookie **挡不住任何东西**：真正的授权凭证是实例那个 JS 可读的 30 天 cookie。

### P0-4 Listener 语义与代码冲突；"调频是写操作"这件事文档没有处理

- 文档 §1.1 / §5.1：Listener「永远只读」，限制「无 CAT、PTT、TX、实例配置权限」。
- 代码：listen-only 会话**可以改电台频率和模式**。服务端 gate：`LISTEN_ALLOWED_SET_FIELDS = frozenset({"freq", "vfo_a_freq", "vfo_b_freq", "mode"})`，另放行 `memLoadAll`/`memRecall`（会写频率 + 模式），其余全部拒绝（`server.py:249-255,1470-1483`）；`README.md:311` 同样描述。

即 Listener 的实际语义是「**受限操作**（可调谐 / 换模式，禁发射）」，不是「只读」。两个后果：

1. 若 Hub 按文档把 Listener 实现为只读，会**收窄现有能力**（现网用户已在用 listen 角色调频）；若按代码实现，文档的"只读"承诺是假的，Owner 会按错误预期授权。
2. **更要紧：调频本身是对射频状态的写操作**，而"写"在文档里被 Operator 租约独占（§5.3 单写多读）。于是产生一个未定义状态：**两个 Listener 同时调频，谁赢？** 现状是"谁都能 set，最后写的赢"（LAN 下令无问题，通常同一人）。在 Hub 多租户下这是真实的冲突域，而**文档的租约模型完全没有覆盖 Listener 的调谐写**。

---

## 3. 📊 账面假设：可以立刻换成实测值的（§8.2）

文档 §8.2 自己标注"需 PoC 实测"。好消息是其中两项**现在就能换成确定值**，而且**分解方式与文档不同**：

| 项目 | 文档估算 | 代码事实 | 证据 |
|---|---:|---|---|
| RX Opus | 48-64 kbps | **默认 64000 bps**（MIN 8000 / MAX 128000，48 kHz，20 ms 帧，fullband）；码率经 `opus_encode` 的 `max_data_bytes` cap 实现 | `opus_rx.py:52-59,69-71,255-259` |
| 频谱/瀑布 | 100-300 kbps | **≈ 408 kbps**：帧格式固定 `1 字节版本 + 850 B wf1 + 850 B wf2 = 1701 B/帧`，**~30 fps**，走 `send_bytes` 二进制（无 base64 膨胀）→ 1701 × 30 = 51 030 B/s ≈ 408 kbps（未计 WS/TCP 头） | `server.py:3357-3362,1220` |
| Listener 频谱 | — | `LISTEN_SPECTRUM_DIVIDER = 3` → 帧率降为 1/3（30 → ~10 fps）→ ≈ 136 kbps | `server.py:117-127` |
| CAT/PTT/状态 | < 10 kbps | 合理，无需修正 | — |

**修正后的单会话带宽：**

- 全控会话 ≈ 64（RX 音频）+ 408（频谱）+ 少量状态 ≈ **0.48 Mbps**
- Listener ≈ 64 + 136 ≈ **0.20 Mbps**

文档 §8.2 的"单活跃会话 0.2-0.5 Mbps"**碰巧落在区间内，但分解是错的**：频谱占 **86%**，音频只占 **14%**。分解错误的代价是优化方向错误 —— §7.2 说"弱网或高并发时优先保音频，降低瀑布帧率 / 分辨率"**方向对**，现在有了量化依据（动瀑布是 6 倍杠杆）。

同时：`LISTEN_SPECTRUM_DIVIDER = 3` 说明**"按角色降瀑布帧率"在实例侧已经实现**，§7.3 的第一道缓解可以**零成本先调这个常数**，不必等 RX Relay。

§7.1「多 Listener 会成倍消耗客户上行」**正确** —— 实例侧频谱已是 server-side fan-out（`spectrum_clients` 是集合，一份采集广播给 N 个客户端，`server.py:115`），所以瓶颈精确地说是**实例的重复上行发送**，而非重复采集，与 §7.2 结论一致。

---

## 4. ✅ 有代码支撑的结论（不必改）

| 文档结论 | 证据 |
|---|---|
| 「4+1 WebSocket」 | `/WSradio`、`/WSspectrum`、`/WSaudioRX`、`/WSaudioTX`、`/WSatr1000`（`server.py:3246,3357,3394,3422,3545`）= 4 核心 + 1 外置天调 |
| `/listen` 与 Listener **服务端强制**（UI 隐藏不是强制） | `server.py:2872`；`/WSaudioTX`、`/WSatr1000` 直接以 4003 关闭；`LISTEN_ONLY_MESSAGE` 回错 |
| PTT 多层释放 | `SDD/15-ptt-safety-architecture.md`；**但术语需纠正**：文档说"七层"，SDD 实为 **Layer 0 前置 + Layer 1-8** |
| PTT 安全观与既有约束一致 | AD-007（`SDD/08`）、NFR-012（`SDD/05`）、SC8（`SDD/03`）、R4（`SDD/13`） |
| §11.1 版本管理 | **拉取侧已存在**：`upgrade_core.py`（读 `latest.json`、版本比较、`state.json` 使升级"可证明"）；发布侧 `dev_tools/make_latest_json.py`；线上清单 `website/downloads/latest.json`（`latest/installer/previous/minSupported/mandatory/releasedAt/notes`）。应写成"复用 + 补灰度/签名/回滚"，不是新建 |
| §11.1 远程诊断 | **上报通道已存在**：`deploy_support_receiver.sh`（独立 systemd unit + 8098 + 独立存储 + 0600 口令文件），报告侧已有脱敏流水线（`support_bundle.py`）。是 Registry / 诊断的既有种子 |
| §3.2 host-only Cookie 隔离 | 方向正确 |
| §1.3 通配子域优于路径前缀 | **正确且有实锤**，见 §1.1（逐资源 location、`proxy_redirect` 手工修补、`^~` 踩坑、重复块事故） |

---

## 5. 待实测项：补上"怎么测"

| 待测 | 建议测法 | 现在能否测 |
|---|---|---|
| 单实例典型 / 峰值 Listener 并发 | 实例侧已有 `spectrum_clients` / `audio_rx_clients` / `_listen_tokens` 集合，加一条定期打点到 support receiver 即可 | **能，且应现在做**（§7.3 触发门槛依赖它） |
| 每会话真实流量 | 频谱 408 kbps 已是定值，剩余变量是实际帧率与 WS/TCP 头开销 | 能（抓包） |
| 客户上行利用率 | 统计 `send_bytes` 计数 × 时间 | 能 |
| 跨洲用户占比 | Portal 登录 IP 归属 | 阶段 2 后 |
| Tunnel 重连 P95 / 新会话 P95（§9.3 SLO） | 需先有隧道实现 | 阶段 1 后 |
| **半开连接的 PTT 未释放率** | TX 中拔网线 / 切 Wi-Fi，测 PTT 是否在 ≤1 s 释放 | **能，现在就能复现（LAN 下即可）** |

---

## 6. 需决策项清单（按阻塞程度）

| # | 决策项 | 文档现状 | 必须定在 |
|---|---|---|---|
| **D1** | Hub 场景下 PTT 半开释放机制（隧道层 TX 期间心跳 + 主动关流 / 或把 `MRRC_PTT_MAX_TX_SECONDS` 改造为租约心跳失效释放）。注意二者语义不同：前者是"1 秒释放"，后者是"最长连续发射上限" | 未提，默认可复用 | **MVP 前** |
| **D2** | 令牌传递方式（URL query / Cookie / WS subprotocol）；是否把 Hub-managed 鉴权提前到阶段 1 | 阶段 2 才做托管鉴权 | **MVP 前** |
| **D3** | Listener 语义定稿：受限操作（可调频换模式）还是严格只读；**Listener 调谐的并发仲裁** | 文档"永远只读"，代码是受限操作 | **MVP 前** |
| **D4** | 同一 origin 内 Hub 票证 cookie 与实例 `AUTH_COOKIE` 的命名 / 生命周期 / `Secure` 策略；实例 30 天会话在远程模式下是否缩短 | 未提 | **MVP 前** |
| **D5** | 现状基线处置：B2（IPv6 + nginx）作为过渡期主力并自动化，还是直接跳隧道；B1（SSH 隧道）是否废弃 | 未提，等同不存在 | 阶段 1 前 |
| **D6** | MVP 隧道选型：frp vs 直接 Fleet Agent POC | §14 已列为待决策 | 阶段 1 前 |
| **D7** | `MRRC_PTT_MAX_TX_SECONDS` 的产品默认值（当前 0 = off） | 未提 | 阶段 1 前 |
| **D8** | 频谱帧率 / 分辨率的产品策略（408 kbps 是当前固定值；是否按网络自适应） | §7.2 提了方向 | 阶段 2 |
| **D9** | 私有部署 / 自建 Hub 是否作为开源承诺（GPLv3 边界，§10.3） | 提出未决策 | 阶段 2 前 |

---

## 7. 对文档的最小修订建议

1. §2.3 / §6.1 增加**"现状基线"**一节（B1-B4），把 B2 的 IPv6 实测当作 MVP 的对照基准。
2. §8.2 用 `opus_rx.py` / `server.py:3357` 的确定值替换估算，并给出**分解百分比**（频谱 86%）。
3. §5.4 增加**"半开连接"**失效模式，并说明它在 Hub 场景下是主路径而非边缘。
4. §10.1 增加"令牌不得进入 URL 与代理日志"的具体约束，并**注明现状未满足**。
5. §9.3 的 "Operator 连接丢失后本地 PTT 释放 ≤1 s" 拆成两行：EOF 型断线（**当前已满足**）与半开型断线（**当前不满足，待 D1**）。
6. §11.1 明确"版本管理复用 `upgrade_core.py`、诊断复用 support receiver"，避免重复建设。
7. 术语：**七层 → 8 层 + Layer 0 前置**（与 `SDD/15` 对齐）。
8. §7.2 补一句：**降瀑布帧率是 6 倍杠杆，且 `LISTEN_SPECTRUM_DIVIDER` 已是现成的第一道闸**。

---

## 8. 一句话结论

> 架构方向不用改；但文档必须补上"现状基线（已有 4 套机制，其中 IPv6 直连已生产在跑）"，并把 PTT 半开释放、令牌进 URL、同 origin 双会话、Listener 语义这四项当成 **MVP 前必须解决**的问题 —— 它们不是阶段 2 的优化项，而是决定 MVP 能不能成立的前提。

## 结案状态（2026-09-30 更新）

本评审提出的四项 P0 与实测修正，**当前状态**：

| 评审发现 | 状态 | 落在哪 |
|----------|------|--------|
| P0-1 PTT 半开不释放（客户端失联后仍处发射态） | **已实现**（实例侧） | 活性闸门 `MRRC_REMOTE_SESSION_TX_HEARTBEAT_S`，复用 key-owner 仲裁；Hub 模式建议设 3–5 秒。与 `MRRC_PTT_MAX_TX_SECONDS` 构成两条独立防线。测试 `tests/test_tx_liveness.py` |
| P0-2 令牌进 URL（uvicorn 访问日志留痕） | **已实现**（实例侧） | AD-024：cookie/Bearer 优先，query 形式仅兼容并告警；`tests/test_ws_token_transport.py` |
| P0-3 同 origin 双实例共享 Cookie | **呼号子域方案下结构性解决**；**www 路径入口仍未解决** | 每个租户独占主机名 ⇒ Cookie 天然按主机隔离 ✓。但路径反代入口（`www.vlsc.net/mrrc_modern/<呼号>/`）所有租户**共享同一 origin** ⇒ 该入口只应作迂回/临时用途，或需实例侧配合（独立 Cookie 名/路径）。**列为未结项** |
| P0-4 Listener 实为受限操作（非"只读旁观"） | **已在设计中限定** | 见 `../SDD`（Listener 的能力边界与 Operator 租约的关系）；一期靠人工授权，自动化在阶段 2 |
| 实测修正：Opus 64 kbps、频谱 1701 B/帧 × 30 fps ≈ 408 kbps（占 86%） | **已入档** | 该数字是 AD-H12（RX 扇出决策）的触发依据 |

**尚未做（有意）**：登录限流在隧道路径下退化为全局桶（用户明确暂缓）；管理 Portal、设备 mTLS、
Operator 租约（阶段 2）。逐项运维事实见 `../SDD/12-operational-model.md` §12.8。
