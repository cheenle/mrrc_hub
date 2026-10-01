# 9. Architecture Overview

## 9.1 路由链路（一次远程请求）

1. Agent 与某个 Tunnel Gateway 建立长连接（出站 WSS/mTLS）。
2. Tunnel Gateway 写入带 TTL 的映射：`instance_id → tunnel_node_id / connection_id / last_seen`（心跳续期）。
3. 用户请求到**任意** Access Gateway；Access 解析子域得到 `instance_id`。
4. Access 查询映射，并通过内网 RPC 把会话送到**归属** Tunnel Gateway。
5. Tunnel 在既有实例隧道上打开虚拟流，透明转发 HTTP 或 WebSocket。
6. Tunnel 节点故障时旧映射过期，实例重连其他节点并写入新映射；客户端重建会话（UC-H07）。

**结论**：用户侧**不需要**粘滞到某个 Access 节点；但必须维护准确的实例归属目录（AD-H03）。

## 9.2 透明代理契约

MVP 的代理必须**对 5 个 WebSocket 端点与静态资源完全透明**：

| 端点 | 语义 | 代理注意 |
|---|---|---|
| `/WSradio` | 控制与状态广播 | 长连接；`token` 鉴权（AD-H07 后改为非 URL 传递） |
| `/WSspectrum` | 二进制频谱（1701 B/帧 × 30 fps） | **必须按二进制透传**，不得缓冲/合并；Listener 已按 1/3 帧率 |
| `/WSaudioRX` | Opus RX 音频（64 kbps） | 低延迟优先；不得引入抖动缓冲 |
| `/WSaudioTX` | Opus TX 上行（Operator） | **Listener 会被实例以 4003 拒绝**，代理不得改写该语义 |
| `/WSatr1000` | 外置天调（可选） | 同 TX 语义，Listener 拒绝 |
| 静态资源 | `static/*`、`/listen`、`/login` | 通配子域下无需改写路径（AD-H02） |

**一致性要求**：连接升级、长连接超时（WS 空闲 ≥24 h 视为正常）、关闭语义（含 4001/4003 等自定义关闭码）
必须与直连一致 —— 自定义关闭码尤其容易被代理"规整化"而丢失。

## 9.3 容量与带宽模型

**无 Hub 扇出**

- 实例总上行 ≈ `Σ(B_rx × 会话数_i)`
- Hub 出带宽 ≈ `S × B_rx`

**启用 Hub 扇出（AD-H12 条件触发）**

- 实例总上行 ≈ `I_active × B_rx`（保护客户上行）
- Hub 出带宽仍 ≈ `S × B_rx`（云端省不了用户下行）

**连接数** ≈ `I_online`（隧道） + `S × W`（用户 WS，`W = 5`） + 内部 RPC

**实测参数（NFR-H007/H008）**

| 项 | 值 | 说明 |
|---|---:|---|
| RX Opus | 64 kbps（默认，可配 8–128） | `opus_rx.py` `DEFAULT_BITRATE` |
| 频谱/瀑布 | **≈ 408 kbps** | 1701 B/帧 × 30 fps，二进制 |
| Listener 频谱 | ≈ 136 kbps | 1/3 帧率 |
| Operator TX | 64 kbps（仅 1 个） | 上行 |
| 单会话合计 | 全控 ≈ 0.48 Mbps；Listener ≈ 0.20 Mbps | **频谱占 ~86%**（AD-H14） |

## 9.4 高可用

- Portal、控制面、Access Gateway：无状态多副本，跨可用区（单地域双 AZ）。
- Redis/RDS：高可用形态；Redis 是 ticket/租约/路由的关键路径，优先恢复或切副本。
- Tunnel Gateway：≥2 节点；实例配置主/备用 Hub 地址；归属映射 TTL 由心跳续期。

| 故障 | 预期行为 |
|---|---|
| Access 故障 | 客户端重连任意健康 Access；无隧道迁移 |
| Tunnel 故障 | 实例重连其他节点并更新映射；用户会话重建（不承诺零中断） |
| 控制面短时不可用 | 已建隧道保持；新登录/授权/租约受影响；恢复后继续 |
| Redis 故障 | ticket、租约、节点路由受影响；按高可用预案切换 |
| 客户断网/断电 | 实例离线；**PTT 按第 [15](15-ptt-safety-hub-mode.md) 章本地释放**；Portal 显示最后在线时间 |

## 9.5 安全架构要点（逐条对应可验证约束）

| 要点 | 约束 |
|---|---|
| 客户侧零入站 | NFR-H001 / SC-H1 |
| 一实例一证 + 隧道一对一绑定 | NFR-H012 / NFR-H022 / AD-H11 |
| 一次性 code + 令牌不进 URL/日志 | NFR-H010 / NFR-H014 / NFR-H020 / AD-H07 |
| host-only Cookie + 双会话命名隔离 | NFR-H013 / AD-H09 |
| 公网链路必须校验证书 | NFR-H021（**现状 B2 反例：`proxy_ssl_verify off`**） |
| 三层一致性校验 | NFR-H022 |
| 诊断最小权限 + MFA + 审计 | NFR-H023 |

## 9.9 实况指认（as-built，2026-10-02 更新）

架构图与章节描述的是**目标形态**；目前已实际运行的是：

**一台机器**（香港 VPS `hub.vlsc.net` = `www.vlsc.net` = `portal.mrrc.vlsc.net`，203.25.119.168）
上：呼号子域入口（**443**，通配真证书，nginx 通配 vhost，逐实例上游校验）
＋ 呼号自助门户（根路径 `https://portal.mrrc.vlsc.net/`，回环 8890）
＋ 静态站点（`www.vlsc.net/mrrc_modern/` 下载页）
＋ frps 0.71.0（控制口 **8989**，`proxyBindAddr=127.0.0.1`）
＋ 注册表（`/etc/mrrc-hub/instances.tsv` + `gen_hub_routes.py` 生成 map 与路由）
＋ 实例侧常驻隧道（launchd / systemd / 任务计划）。

**`:9988` 与 `:8899` 两个监听已取消**（V0.21）；海外边缘那条反代路径整体删除。
尚未落地的是设备 mTLS 与 Operator 租约（阶段 2）。

尚未落地的是管理 Portal、设备 mTLS 与 Operator 租约（阶段 2）。
逐项事实（三台主机、两个入口、证书全流程、运维命令、已知退化）见
`12-operational-model.md` §12.8 —— 与本章不一致时以 §12.8 为准并回改本章。

**物理架构图**（机器/进程/文件/端口/cron 一级，2026-10-01 现场读数）：
[`../docs/physical-architecture-2026-10-01.svg`](../docs/physical-architecture-2026-10-01.svg)（同目录 PNG 为渲染件）。

**as-built 校验版总体架构图**（2026-10-01，含对 2026-09-30 目标态旧图的逐条订正记录）：
源为 [`../docs/architecture-2026-10-01-as-built.svg`](../docs/architecture-2026-10-01-as-built.svg)
（同目录 PNG 为其渲染件，HTML 为校验记录页；改图改 SVG 后重渲染）。
