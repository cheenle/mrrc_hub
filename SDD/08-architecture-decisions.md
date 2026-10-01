# 8. Architecture Decisions

> AD-H01…AD-H05 与 AD-H11…AD-H13 继承源设计文档 v2.0 的方向；
> **AD-H06…AD-H10、AD-H14 为代码取证后新增/加固**（见
> [`docs/2026-09-30-fleet-hub-design-review.md`](../docs/2026-09-30-fleet-hub-design-review.md)）。

---

## V0.21（2026-10-02）—— 一台机器：门户、入口、站点合并，只留 8989

**背景**：韩国那台 hub 的出站质量不稳定（实测同一时刻从不同链路对 `:8989` 的 TCP 连接一成一败），
运维把整站搬到香港 VPS `hub.vlsc.net`（203.25.119.168）。而 `www.vlsc.net` 本来就在这台机器上。

**决定**：

1. **不再有"两条路"。** 早先为"只放行 80/443 的网络"留了一条海外边缘（`www.vlsc.net/mrrc_modern/<呼号>/`
   反代），并让应用把 hub 直连当主路、边缘当兜底。合并到同一台机器后，两条路指向同一个 nginx，
   保留第二套只是多一处会坏的配置。**边缘路径整体删除**，应用只认一个门户地址。
2. **门户挂在根**：`https://portal.mrrc.vlsc.net/`（不再带 `/mrrc_portal` 前缀；旧路径 301）。
3. **入口不再带端口**：实例入口与其他服务一起在 **443**（`https://<呼号>.mrrc.vlsc.net/`），
   `:9988` / `:8899` 两个监听一并取消。**唯一保留的独立端口是隧道控制 8989**。
4. **标签就是呼号**：一个呼号 = 一台设备 = 一个入口，不再拼产品后缀（应用此前发 `product="mrrc_modern"`，
   与主产品名 `modern` 不等，于是每个入口都长了一截 —— 现在两种写法都归一到裸呼号）。
5. **旧地址自动改道**：配置里写着 `…:8899`、`www.vlsc.net/mrrc_portal` 或带 `/mrrc_portal` 的应用
   （v1.24.3 及更早）会被 v1.24.4 自动改写到新地址，否则它们连门户都到不了。

**代价（写在明处）**：`:8899` 其实**从未**对公网开放过（实测三次不同链路均被拒），
所谓"主路"的说法与事实不符 —— 这也是"申请能提交、状态一直刷新不出来"的根因（申请走了边缘兜底，
其余请求直连 8899 全部失败）。合并后这个反复咬人的错配不再存在。

## AD-H01: 实例主动出站隧道（客户侧零入站）

| Attribute | Value |
| --------- | ------- |
| Type | Architecture |
| Status | Accepted |
| Decision | 每套 MRRC_modern 主动向 Hub 建立持久出站 WSS/mTLS 长连接；客户侧不需要公网 IP、端口映射或 UPnP |

**Problem**: 客户实例位于家庭/站点内网，运营商 NAT、双层 NAT、无稳定端口映射是常态。

**Rationale**: 出站连接穿透所有 NAT 形态且无需客户网络配置；这是 SC-H1 的唯一可行实现方式。

**Consequences**: Tunnel Gateway 成为有状态组件，故障时活动 TCP/WS 会话无法无损迁移（UC-H07）；
必须维护实例→节点归属映射（AD-H03）。

---

## AD-H02: 通配子域，不用端口池或路径前缀

| Attribute | Value |
| --------- | ------- |
| Type | Architecture / Operability |
| Status | Accepted（有现状实锤） |
| Decision | 每实例一个子域 `https://<instance-id>.mrrc.vlsc.net`，通配 DNS + 通配 TLS |

**Problem**: 200 个实例需要统一入口，且不能暴露 200 个公网端口。

**Rationale**: 子域天然隔离实例 Cookie，不需要改写前端资源与 5 个 WS 路径。
**实锤**：现状 B2 的路径前缀方案在 `deploy_listen_proxy.sh` 中为每个前端资源维护一条
`location`（listen / login / listen.js / rx_worklet_processor.js / `/modules/` / `/api/` / `/WS`），
还要 `proxy_redirect /login /mrrc_modern/login` 手工修重定向，并踩过 `^~` 优先级与重复块导致
`nginx -t` 失败的事故 —— 每加一个前端资源都要改中心配置，不可扩展到 200 实例。

**Consequences**: 需要通配证书与 DNS 管理；实例之间必须严格 host-only Cookie，禁用
`Domain=.mrrc.vlsc.net`（NFR-H013）。

**Port 修订（V0.2）**：入口不用 80/443，改用 **8899（明文跳转）/ 9988（TLS）/ 8989（隧道控制）** ——
国内 ECS 在 80/443 上需要 ICP 备案。代价写在明处，不当成免费选择：

1. **入口 URL 带端口**（`https://<id>.mrrc.vlsc.net:9988`），"统一入口"的语义随之变弱；
2. **只放行 80/443 出站的用户网络完全连不上**（公司/访客 Wi-Fi 常见）—— 新增风险 R-H12。
   注意别与 SC-H1 混为一谈：那条说的是**实例**侧只需出站 443，而现在是**用户浏览器**要能到 9988；
3. **自动签发受信证书的路径被砍掉一半**：HTTP-01 固定 80、TLS-ALPN-01 固定 443，两个口都不开
   ⇒ 只剩 DNS-01。因此真证书/通配证书以 DNS API 凭证为前提（阿里云万网，只带
   `AliyunDNSFullAccess` 的 RAM 用户）；凭证到位前，验证环境用自签证书并明确标注为 smoke test 夹具。

**两级入口修订（V0.4）**：主路仍是 hub 上的 `<id>.mrrc.vlsc.net:9988`（低延迟），另加一条**退化路**：
海外 `www.vlsc.net` 用 443 + 真证书终结 TLS，并把整条会话反代进 hub 的隧道口。理由是 R-H13 ——
境内非标端口的入口既拿不到真证书（HTTP-01 在 80）、又会被只放行 80/443 的网络挡住。
**这不是把子域方案换回路径前缀**：用户可见的名字仍是 `<id>.mrrc.vlsc.net`（显式 A 记录指向海外主机），
实例侧完全无感。

代价写在明处：对"用户在国内、实例也在国内"的场景，海外边缘是绕路，实测 `/login` 从 0.13 s 变 0.69 s，
音频与 PTT 往返多约 0.4–0.6 s。**因此它是退化路径而非主路**：主路应尽快换成 hub 上的 DNS-01 通配真证书
（低延迟 + 免警告），届时退化路只服务受限网络。已同步 NFR-H005。

---

## AD-H03: Access 无状态 / Tunnel 有状态分离

| Attribute | Value |
| --------- | ------- |
| Type | Architecture / Scalability |
| Status | Accepted |
| Decision | Access Gateway 无状态、可任意横向扩展；Tunnel Gateway 有状态、持有实例长连接；二者经 Registry/Redis 的归属映射（带 TTL）协作 |

**Problem**: 长连接终结与公网接入的伸缩特性不同 —— 前者有状态且数量绑定在线实例，后者无状态且随用户流量增长。

**Rationale**: 分离后可独立扩容，且用户侧不需要粘滞到某个 Access 节点。

**Consequences**: 必须维护准确的实例归属节点目录；映射 TTL 与心跳续期是可用性关键路径（UC-H02、UC-H07）。

---

## AD-H04: MVP 透明代理 → 阶段 2 Hub 托管鉴权

| Attribute | Value |
| --------- | ------- |
| Type | Delivery strategy |
| Status | Accepted，**受 AD-H07 制约** |
| Decision | MVP 只做公网入口、实例路由与透明 HTTP/WS 转发，用户继续使用实例自有密码；目标态由 Hub 完成统一鉴权并将签名角色上下文传给实例 |

**Problem**: 一次性把鉴权、租约、配额全部做进 Hub 会拖慢"验证公网可达"这一首要目标。

**Rationale**: 透明代理对 MRRC 核心改造最小，可先验证 NAT、时延与 WS 稳定性。

**Consequences**: MVP 期间授权边界仍由实例密码决定 —— **因此 AD-H07（令牌不进 URL/日志）
与 AD-H09（双会话 Cookie）在 MVP 阶段就必须成立**，否则"先透明代理"会以会话凭证泄露为代价。

---

## AD-H05: 单写多读 —— Operator 租约

| Attribute | Value |
| --------- | ------- |
| Type | Safety / Correctness |
| Status | Accepted |
| Decision | 租约状态机 `FREE → HELD → RELEASED / EXPIRED`；按 `instance_id` 原子竞争；每实例同时最多 1 个有效 Operator；冲突默认排队，Owner 可配置降级为 Listener |

**Problem**: 两个控制者同时对一部电台写（CAT/PTT/TX）会产生不可预期的发射行为。

**Rationale**: 串行化写者是最简单且可审计的正确性保证；Listener 只需读+受限调谐，可并发。

**Consequences**: 租约 TTL 20–30 s、续租 5–10 s；**租约回收不得被当作 PTT 释放机制**（AD-H06）。

---

## AD-H06: PTT 本地闭环；云端 TTL 不作释放机制；半开连接由隧道层心跳兜住

| Attribute | Value |
| --------- | ------- |
| Type | Safety（最高优先级） |
| Status | Accepted —— **含一项跨仓变更（实例侧新增远程会话活性闸门）** |
| Decision | PTT 释放的权威永远是实例本地；Hub/云端租约只是授权互斥。**TX 期间会话必须维持应用层心跳，心跳失效即触发本地释放**，不得等待 TCP 断开或租约过期 |

**Problem**: 既有实例机制只覆盖 EOF 型断线。`mrrc_modern/server.py` 的注释明确：
`Opt-in stuck-keyup watchdog (MRRC_PTT_MAX_TX_SECONDS, 0 = off). Covers clients that hang
WITHOUT disconnecting — the dead-man switch and client watchdogs never fire for a zombie-but-connected
socket.`，而该兜底默认关闭（`config.py`: `_env_float("MRRC_PTT_MAX_TX_SECONDS", 0.0)`）。
在 Hub 场景（运营商 NAT、双层 NAT、弱网、换网）中，**"租约还在、TCP 已死"是主路径而非边缘**。

**Rationale**: 只有把"活性"作为应用层契约（而不是 TCP 语义），才能在多层 NAT 下可靠判定操作者已消失。

**Consequences**: 见第 [15](15-ptt-safety-hub-mode.md) 章的完整机制、时限与验证矩阵；
需要 `mrrc_modern` 侧配套变更并在其 SDD 中登记。

---

## AD-H07: 令牌不得进入 URL、不得进入代理日志（MVP 必修）

| Attribute | Value |
| --------- | ------- |
| Type | Security |
| Status | Accepted —— **与 AD-H04 的原始排期冲突，已并入 MVP** |
| Decision | 会话 token 一律经 Cookie 或 `Sec-WebSocket-Protocol` 传递；Hub/Tunnel/nginx/实例访问日志对 `token=`、`code=` 强制脱敏；一次性 code 消费后立即重定向到干净 URL |

**Problem**: 实例会话令牌 30 天有效，且**被前端拼进 URL query**
（`mrrc_modern/static/ft710_main.js`、`static/listen.js` 构造 `?token=`），实例侧
`_verify_auth` 也接受 query 参数；实例跑 uvicorn 默认访问日志（含 query）。
项目已知道该问题（`support_bundle.py` 的脱敏正则备注写着 "a `?token=` inside a URL"），
但**脱敏只发生在导出诊断包时**。透明代理模式下，Hub/Tunnel/nginx 会逐条记录长期令牌明文。

**Rationale**: 40 天级令牌进入代理日志，等于把"统一入口"变成集中式的凭证泄露面，
与 NFR-H014（SC-H6）不可调和；而修法成本极低（改前端传参方式 + 照搬既有脱敏正则）。

**Consequences**: 前端改动进 MVP；日志脱敏成为发布门禁（G2）。阶段 2 上线托管鉴权后，
该约束依然生效（token 与 code 都必须遵守）。

---

## AD-H08: Listener = 受限操作角色（可调频换模式，禁发射），并定义其写并发仲裁

| Attribute | Value |
| --------- | ------- |
| Type | Product semantics / Correctness |
| Status | Accepted |
| Decision | Listener 的语义是"受限操作"，**不是只读**：允许 `freq` / `vfo_a_freq` / `vfo_b_freq` / `mode` 与 `memRecall`（写频率+模式），禁止 PTT/TUNE/CQ/录音/设备设置/记忆写入；服务端强制。**并发仲裁：Listener 的调谐为"共享可写"，但 Operator 持租约期间以 Operator 的调谐为权威，Listener 调谐不得改变 Operator 会话的权威状态** |

**Problem**: 源设计文档称 Listener「永远只读」，但实例实现是受限操作
（`server.py`: `LISTEN_ALLOWED_SET_FIELDS = frozenset({"freq", "vfo_a_freq", "vfo_b_freq", "mode"})`

+ 放行 `memLoadAll`/`memRecall`，其余一律拒绝）。按文档实现会**收窄现有能力**；
按代码实现则文档的"只读"承诺是假的。更关键的是：**调谐本身就是对射频状态的写**，
而文档把"写"独占给 Operator 租约 —— 两个 Listener 同时调谐的冲突域在文档中完全未定义。

**Rationale**: 与现网行为一致（不破坏现有用户），同时把"是谁的调谐生效"这件事从隐式变成显式契约。

**Consequences**: 需要 UI 明示 Listener 可调谐；审计记录 Listener 调谐来源与时间；
Owner 可配置是否允许 Listener 调谐（默认允许）。

---

## AD-H09: 同 origin 双会话 Cookie 的命名与生命周期

| Attribute | Value |
| --------- | ------- |
| Type | Security / Correctness |
| Status | Accepted |
| Decision | Hub 票证 Cookie 使用独立名称（不得等于实例的 `AUTH_COOKIE`），短时效（≤ 会话时长），`Secure` + `SameSite=Lax`；实例子域会话保持 host-only；远程模式下实例会话 Cookie 加 `Secure`，并评估缩短 30 天有效期 |

**Problem**: 通配子域方案下 Access Gateway 与实例**共享同一 origin**
（`<instance-id>.mrrc.vlsc.net`），Cookie 命名空间是公用的。实例登录设置的是
`httponly=False`（注释写明 `# JS needs to read it for WebSocket`）、`max_age=30 天`、无 `Secure`。
文档要求 Access 设置 "host-only、HttpOnly、Secure" 票证 Cookie，却未讨论两个会话层如何共存。

**Rationale**: 同名 Cookie 会互相覆盖或让实例读到 Hub 的票证；而 30 天免登录会在
"短时效 + MFA"的安全叙事之外留一个后门。

**Consequences**: Cookie 命名与属性成为发布门禁（G4）；MVP 透明代理下必须明确
"授权凭证是哪一个"，否则 HttpOnly 票证形同虚设。

---

## AD-H10: 现状基线不回退（B2/B3 保留为过渡期与退化路径）

| Attribute | Value |
| --------- | ------- |
| Type | Migration / Risk |
| Status | Accepted |
| Decision | 保留 LAN 直连、实例自有密码、B2（IPv6 直连 + nginx）与 B3（路径前缀代理）作为过渡期与退化路径；Hub 是增量能力，不是替换 |

**Problem**: 源设计文档未把现状列为基线，隐含"远程接入从零开始"，会导致 MVP 把
"验证公网可达"当成首要风险，而实际上 B2 已生产运行并已验证了 IPv6 通路。

**Rationale**: 不破坏现有用户（SC-H8）；同时把 B2 的失效场景（无 IPv6、运营商封 8888、
需要多用户授权与 Operator 互斥）作为 Hub 的确切价值主张。

**Consequences**: 迁移路径为 **B2（单实例、单用户、收听为主）→ Hub（多实例、多角色、含控制）**；
B2 的 `proxy_ssl_verify off` 与令牌进 URL 问题**必须在 Hub 侧避免复现**，且建议同期修正（R-H2）。

---

## AD-H11: 一实例一证（设备 mTLS），禁用共享静态 token

| Attribute | Value |
| --------- | ------- |
| Type | Security |
| Status | Accepted |
| Decision | 每实例独立密钥对与证书；私钥不出客户主机（Windows DPAPI / macOS Keychain / Linux root-only 文件，预留 TPM）；支持轮换与吊销；禁止全 fleet 共用静态 token |

**Problem**: 共享凭证一旦泄露即全 fleet 失守，且无法定点吊销。

**Rationale**: 一机一证使吊销、审计与归属都成为可执行的运维动作（UC-H08）。

**Consequences**: 需要 Device CA 与轮换窗口；现有 B4 的共享口令模式不作为 Hub 的鉴权基础。

**as-built 指认（2026-10-01）—— 本 AD 目前只实现了一半，且是有意分层的**：

| 层面 | 本 AD 要求 | 现网实况 |
| ------ | ------- | ------- |
| **hub → 实例这一跳的 TLS 身份** | 每实例独立密钥对与证书；私钥不出客户主机 | ✅ **已符合**：`make_instance_cert.sh` 签一张签给实例**自己入口名**的自签证书，公钥钉进 `/etc/mrrc-hub/trust-bundle.pem`，nginx 按 `$mrrc_tls_name` 逐实例校验。私钥不出实例 |
| **隧道自身的认证** | 禁用全 fleet 共用静态 token | ⚠️ **未符合**：仍用 frp 的单个共享 token。这是**对 AD-H11 字面的有意偏离**，不是遗漏 |

**偏离的理由与退出条件**：frp 的鉴权模型就是单个共享 token；要真正一机一证需要换掉隧道层，
那是内置 Fleet Agent（AD-H13）的事。把 frp 定位为**过渡通道**而不是目标态，正是为了让这条偏离
有时限。**退出条件 = Fleet Agent 上线**；在那之前，任何把共享 token 当成“已解决”的叙述都是错的。

> 写文档时请把这两层分开说。把“一机一证”当成一句笼统的“阶段 2”，正是这个偏离
> 被埋没、两次被写错（一次说“不是一机一证”，一次说“阶段 2”）的原因。

---

## AD-H12: RX 扇出条件启用

| Attribute | Value |
| --------- | ------- |
| Type | Scale optimization |
| Status | Accepted（条件启用） |
| Decision | 满足任一门槛再实施 Hub 侧 RX Relay/Fan-out：单实例 P95 并发 Listener ≥ 3；客户上行利用率频繁 > 60%；因监听并发导致的音频卡顿投诉达阈值；俱乐部/教学/直播成为主场景 |

**Problem**: 多 Listener 会成倍消耗客户上行（§ NFR-H009）。

**Rationale**: 频谱已是实例侧 server-side fan-out（`spectrum_clients` 集合），瓶颈是**重复上行发送**
而非重复采集；在并发数据未知前重构 5 个 WS 通道是过早优化。

**Consequences**: 需要先落地并发观测（I-H1）；触发后再抽 RX 音频与频谱到 Hub 复制，
TX 音频/CAT/PTT 仍按会话独立。

---

## AD-H13: 遥测与 OTA 复用既有实现，不重复建设

| Attribute | Value |
| --------- | ------- |
| Type | Engineering efficiency |
| Status | Accepted |
| Decision | OTA 拉取侧复用 `mrrc_modern/upgrade_core.py`（清单校验、版本比较、`state.json` 可证明升级）；诊断/遥测复用 `deploy_support_receiver.sh` + `tools/support_receiver`；Hub 只补灰度、签名、回滚与集中看板 |

**Problem**: 源设计文档 §11.1 把"版本管理/远程诊断"当作从零建设的新能力。

**Rationale**: 两项能力已存在且已有事故沉淀（脱敏正则、独立 systemd unit、独立存储、
0600 口令文件），重建会丢失这些经验并产生并行事实。

**Consequences**: Hub 的 Agent 必须与既有 upgrade channel 兼容；诊断通道需从"共享口令"
升级为设备证书鉴权（AD-H11）。

---

## AD-H14: 频谱带宽是首要优化杠杆

| Attribute | Value |
| --------- | ------- |
| Type | Performance |
| Status | Accepted |
| Decision | 带宽优化优先动频谱（帧率/分辨率/按角色降级），而非音频；`LISTEN_SPECTRUM_DIVIDER` 是现成的第一道闸 |

**Problem**: 源设计文档把单会话带宽分解为"音频 48–64 kbps + 频谱 100–300 kbps"，两者量级相当。

**Rationale**: 代码实测为 **音频 64 kbps（`opus_rx.py` `DEFAULT_BITRATE = 64000`）
与频谱 408 kbps（`/WSspectrum` 1701 B/帧 × 30 fps）** —— 频谱占单会话约 **86%**，
是 6 倍杠杆。分解错误的代价是优化方向错误。

**Consequences**: 弱网/高并发时先降瀑布（已有按角色 1/3 帧率机制），音频保持；
频谱自适应策略进阶段 2（D8）。

## AD-H15: 呼号即租户身份（命名、注册与验证）

| Attribute | Value |
| ----------- | ------- |
| Type | Product / Identity |
| Status | Accepted（命名部分已实现，注册与验证属阶段 2） |
| Decision | 实例的对外标识就是**无线电呼号**：入口 `https://<呼号>.mrrc.vlsc.net/`（443；V0.21 前写作 `:8899`）（子域）与 `https://www.vlsc.net/mrrc_modern/<呼号>/`（前缀，海外真证书）。**注册实例与注册用户都必须提供真实呼号**；呼号即账号标识符，大小写不敏感（`BG1SB` ≡ `bg1sb`），同一呼号在同一时刻只能绑定一个 Owner。 |
| Alternatives | ①**自增/随机 instance-id**（如 `inst-7f3a2c`）：不泄露身份、天然防枚举，但用户认不出、客服排障要查表、呼号与实例的对应关系还得另建索引；②**邮箱/手机号作标识**：与业余无线电场景无关，且要处理实名与隐私；③**呼号即身份**（采纳）。 |
| Consequences | ①**命名规范化**：DNS 标签与 Host 头大小写不敏感（hub 的 vhost 用 `server_name ~*` 匹配），而 URL **路径**大小写敏感 ⇒ 规范形式用呼号原样大写，小写输入 301 到规范形式（实测 `/mrrc_modern/bg1sb/` → 301 → `/mrrc_modern/BG1SB/`）；注册表内部统一按小写标签存储，避免同一台出现两个名字。②**存在性可枚举**：呼号是公开且可猜的，`<呼号>.mrrc.vlsc.net` 存在与否可被探测（登记名 → 401/502，未登记 → 404）。这是本方案的**已知代价**，见开放问题 I-H9 与 SC-H5 的措辞争议。③**每个实例独占子域** ⇒ Cookie/会话天然隔离；对比路径前缀方案（同一 origin 下多实例会争用同名 Cookie，见 AD-H09）。④**注册必须验证呼号**：阶段 2 的 Portal 需要呼号核验手段（上传执照 / 呼号库比对 / 人工审核），否则任何人都能冒用他人呼号抢注子域 —— 这是"呼号即身份"成立的前提，不是可选项。 |
| Status detail | 命名与大小写规范化已实现（registry + `gen_hub_routes.py` + nginx `~*`）；呼号验证、Owner 绑定与抢注保护属阶段 2 Portal |

**Problem**: 多租户需要给每个实例一个稳定、可读、可运营的标识。自造 ID 能做到防枚举，但把"这是谁的台"这件事推到了产品之外 —— 用户记不住、客服要查表、社区里也无法用"我的呼号"交流。而业余无线电本身就有全行业公认的唯一身份：呼号。

**Rationale**: 呼号是公开、稳定、行业公认的标识，用户自己就以此自称，因此它天然适合做租户名与账号名。代价（可枚举）换来的收益（可读、可自证、不需要映射表）在这个场景里划算 —— 但**前提是注册时要真的验证呼号**，否则"身份"这一层就是空的：任何人都能抢注 `BG1SB`。
