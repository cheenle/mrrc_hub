# 1. Executive Summary

## 1.1 核心结论

采用**实例主动出站、云端统一入口、控制面与接入面分离**的总体架构：

1. 每套 MRRC_modern 在客户内网主动建立一条到 MRRC Cloud Hub 的持久出站隧道；客户侧不需要公网 IP、端口映射或 UPnP。
2. 远程用户通过统一 Portal 选择实例，并经独立子域访问：`https://<instance-id>.mrrc.vlsc.net`。
3. 云端用 Fleet Registry 维护"实例 → 当前 Tunnel Gateway 节点"的实时映射；Access Gateway 可无状态横向扩展。
4. 权限模型为"用户 → 实例 → 角色"：Owner、Operator、Listener、Fleet Admin。
5. 每个实例同一时刻最多一个有效 Operator；PTT/CAT/TX 写权限由 operator 租约控制，Listener 为**受限操作角色**（AD-H08，非"只读"）。
6. 本地 LAN 模式与现有远程接入能力永久保留；远程接入是增量能力，不破坏现有用户（SC-H8）。

## 1.2 现状基线（评审新增）

源设计文档 v2.0 的选型比较（其 §6.1）把远程接入当成从零开始。**实际已存在 4 套机制**，
其中 B2 已在公网生产运行 —— 这改变了 MVP 的起点与验收口径（AD-H10）。

| # | 机制 | 实现载体 | 公网通道 | 认证 | 每实例运维成本 | 状态 |
|---|---|---|---|---|---|---|
| **B1** | SSH 反向端口转发 | `mrrc/mrrc_tunnel.sh` + launchd `com.user.mrrc.tunnel.plist` + `install_tunnel_service.sh` | `ssh -N -R 8891/8892:localhost → www.vlsc.net` → 远端 nginx 反代 `radio1.vlsc.net` | **服务器系统账号** + `ssh-copy-id` 免密 | 手工：装 key、开服务器账号、加 nginx 段 | 历史 |
| **B2** | **IPv6 直连 + nginx 幂等反代** | `mrrc_modern/deploy_listen_proxy.sh` → nginx `location = /mrrc_modern/{listen,login,*}` | `https://www.vlsc.net/mrrc_modern/listen` → `proxy_pass https://radio.vlsc.net:8888`（**IPv6，无隧道**） | 实例自身的 admin / listen 密码 | **必须 SSH 到中心机 + sudo 改 nginx** | **生产运行** |
| **B3** | 路径前缀 Web 代理 | `mrrc_modern/pi_web_proxy.py`（`AUTH_COOKIE = "pi_web_auth"`，basic auth + httponly cookie） | 同 B2 的中心机侧 | 独立 basic auth / cookie（30 天） | 已存在 | 现役 |
| **B4** | 实例 → 作者服务器上报 | `mrrc_modern/deploy_support_receiver.sh` + `tools/support_receiver/server.py`（独立 systemd unit、8098、独立存储、0600 口令文件） | 出站 HTTPS | 共享口令（**非设备证书**） | 一次性 | 现役 |

**B2 是 MVP 的对照基准**：它证明了 IPv6 直连对收听类远程访问在中国家宽场景可行
（无需 NAT 穿透、客户不装客户端、无需中心改配置即可自愈 IPv6 前缀变化——
`resolver 1.1.1.1 valid=300s` + `proxy_pass $变量`）；也暴露了三条不可扩展的硬伤：

- 逐前端资源改中心 nginx（listen / login / listen.js / rx_worklet_processor.js / `/modules/` / `/api/` / `/WS` 各一条 `location`），且踩过 `^~` 优先级与重复块导致 `nginx -t` 失败的事故
- `proxy_ssl_verify off` —— 公网链路上实例自签证书校验被关闭
- 实例会话令牌（30 天有效）被前端拼进 URL query（`static/ft710_main.js`、`static/listen.js`），经代理必然进日志

> 详细取证见 [`docs/2026-09-30-fleet-hub-design-review.md`](../docs/2026-09-30-fleet-hub-design-review.md)。

## 1.3 演进策略

| 层次 | 范围 | 目的 |
|---|---|---|
| **MVP 必选** | 反向隧道、透明 HTTP/WS 代理、实例目录、在线状态、基础监控、**PTT 半开释放（AD-H06）**、**令牌不进 URL（AD-H07）** | 尽快验证 200 个内网实例的公网可达与用户体验，且不以安全为代价 |
| **目标态必选** | 内置 Fleet Agent、设备 mTLS、Hub 托管鉴权、operator 租约、审计 | 形成可交付、可运营的正式产品能力 |
| **条件启用** | RX Relay/Fan-out、跨地域接入、WebTransport/WebRTC 音频通道 | 由并发监听、跨洲延迟和弱网实测触发，不阻塞前两阶段 |

## 1.4 关键架构决策索引

| 决策 | 内容 | 章 |
|---|---|---|
| AD-H01 | 实例主动出站隧道（客户侧零入站） | [08](08-architecture-decisions.md) |
| AD-H02 | 通配子域，不用端口池或路径前缀（有 B2 实锤） | [08](08-architecture-decisions.md) |
| AD-H03 | Access 无状态 / Tunnel 有状态分离，归属映射经 Registry | [08](08-architecture-decisions.md) |
| AD-H04 | MVP 透明代理 → 阶段 2 Hub 托管鉴权 | [08](08-architecture-decisions.md) |
| AD-H05 | 单写多读：每实例最多 1 个 Operator 租约 | [08](08-architecture-decisions.md) |
| AD-H06 | **PTT 本地闭环；云端 TTL 不作释放机制；半开连接必须由隧道层心跳兜住** | [08](08-architecture-decisions.md)、[15](15-ptt-safety-hub-mode.md) |
| AD-H07 | **令牌不得进入 URL、不得进入代理日志（MVP 必修）** | [08](08-architecture-decisions.md) |
| AD-H08 | **Listener = 受限操作角色（可调频换模式，禁发射），并定义其写并发仲裁** | [08](08-architecture-decisions.md) |
| AD-H09 | **同 origin 双会话 Cookie：命名、生命周期与 Secure 策略** | [08](08-architecture-decisions.md) |
| AD-H10 | **现状基线不回退：B2/B3 保留为过渡期与退化路径** | [08](08-architecture-decisions.md) |
| AD-H11 | 一实例一证（设备 mTLS），禁 fleet 共享静态 token | [08](08-architecture-decisions.md) |
| AD-H12 | RX 扇出条件启用（含触发门槛） | [08](08-architecture-decisions.md) |
| AD-H13 | 遥测/OTA 复用既有 `upgrade_core.py` 与 support receiver | [08](08-architecture-decisions.md) |
| AD-H14 | 频谱带宽是首要优化杠杆（408 kbps ≈ 单会话 86%） | [08](08-architecture-decisions.md) |

## 1.5 与源设计文档的差异（已用代码取证修正）

| 源文档 | 本 SDD | 依据 |
|---|---|---|
| 场景假设"没有公网 IP"隐含"目前无远程接入" | 已有 4 套机制，B2 生产运行 | §1.2、AD-H10 |
| Listener「永远只读」 | Listener = 受限操作（可调频/换模式） | AD-H08 |
| 单活跃会话 0.2–0.5 Mbps（分解：音频 48-64k + 频谱 100-300k） | **同区间但分解修正**：音频 64 kbps、频谱 **408 kbps**（占 86%） | NFR-H007、NFR-H008、AD-H14 |
| 「PTT 安全由既有七层机制复用」 | 既有机制只兜 EOF 型断线；**半开型需新增隧道层心跳** | AD-H06、第 15 章 |
| 「MVP 透明代理，阶段 2 再做托管鉴权」 | 令牌进 URL 使该排期不可成立 —— 前端改造必须进 MVP | AD-H07 |
| 「七层 PTT 安全释放」 | **Layer 0 前置 + Layer 1–8**（与 `mrrc_modern/SDD/15` 对齐） | AD-H06 |
| §11.1 版本管理/诊断需新建 | 复用 `upgrade_core.py` + support receiver | AD-H13 |
