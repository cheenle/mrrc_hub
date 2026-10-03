# 4. System Context

## 4.1 分层与职责

| 分层 | 组件 | 主要职责 | 状态特征 |
|---|---|---|---|
| 客户内网 | `MRRC_modern`、Fleet Agent、电台、本地访问入口 | 电台控制与媒体处理；主动出站；**本地 PTT 安全**；LAN 模式 | 单实例本地状态（权威） |
| 公网入口层 | 通配 DNS、通配 TLS、WAF、ALB/NLB | Portal 与用户接入、实例隧道入口 | 无业务状态 |
| Fleet 控制面 | Portal、IAM/ACL、Registry、Ticket/Policy、Lease、OTA、诊断、审计 | 实例/用户/策略与生命周期管理 | 状态外置 RDS/Redis |
| 接入与数据面 | Access Gateway、Tunnel Gateway、（可选）RX Relay | 验票、子域路由、长连接终结、透明代理、流量转发 | Access 无状态；Tunnel 有状态 |
| 远程用户 | Operator、Listener、Owner、Fleet Admin | 控制、收听、授权与运维 | 客户端会话状态 |

## 4.2 域名与命名

| 域名 | 用途 |
|---|---|
| `www.vlsc.net/mrrc_modern/` | 产品介绍、下载与现有文档入口（**现状，保留**） |
| `https://portal.mrrc.vlsc.net` | Fleet Portal、账号与实例管理 |
| `<呼号>.mrrc.vlsc.net`（443） | 实例入口（AD-H15：呼号即租户名，如 `BG1SB`）。标签即呼号，不再带产品后缀 |
| `tunnel.mrrc.vlsc.net:8989` | 实例出站隧道的控制端口（**唯一保留的独立端口**）。入口、门户、站点全部合并到同一台机器的 443 |
| ~~`www.vlsc.net/mrrc_modern/<呼号>/`~~ | **退化入口（V0.4，存史）**：海外主机终结 TLS（真证书、443）并把整条会话反代进 `tunnel.mrrc.vlsc.net:9988`，供只放行 80/443 的用户网络使用；代价是多一跳海外往返（实测 +0.56 s）。**该路径已随 V0.21 删除** —— 入口自身就在 443，它要绕开的那条约束已满足（R-H12 / R-H13） |
| `tunnel.mrrc.vlsc.net` **:8989** | 实例出站隧道入口（Agent 连到它；实测已通）。同理 `https://portal.mrrc.vlsc.net` 也在通配内 |

**Cookie 规则**：实例子域会话必须 host-only，不设 `Domain=.mrrc.vlsc.net`；
Hub 票证 Cookie 使用独立名称并遵守 AD-H09 —— 因为 Access 与实例**共享同一 origin**。

## 4.3 接口清单

| 接口 | 方向 | 协议 | 认证 | 备注 |
|---|---|---|---|---|
| 用户 → Access Gateway | 入 | HTTPS / WSS | 会话 Cookie + 一次性 launch code | 覆盖 5 个 WS 端点与静态资源 |
| Access → 实例 | 经 Tunnel | 透明 HTTP/WS 代理 | 隧道内签名角色上下文（阶段 2） | MVP 期间仍由实例密码鉴定 |
| Agent → Tunnel Gateway | **出站** | WSS + mTLS | 设备证书 | 客户侧零入站 |
| Agent → 控制面 | 出站 | HTTPS | 设备证书 | REGISTER、心跳、策略、OTA |
| Agent → OSS/CDN | 出站 | HTTPS | 签名校验 | OTA 包不经数据面（NFR-H018） |
| 控制面 → 实例 | 经 Tunnel | 控制流 | 隧道绑定 | 策略下发、诊断指令 |
| 实例 → 作者服务器（现状 B4） | 出站 | HTTPS | 共享口令 → **将升级为设备证书**（AD-H11） | support receiver |

## 4.4 信任边界

| 边界 | 信任假设 | 必须校验 |
|---|---|---|
| 客户内网 ↔ Hub | 客户网络不可信（NAT/弱网/中间人） | 设备 mTLS；证书校验**不得关闭**（NFR-H021） |
| 用户 ↔ Access | 浏览器不可信；URL/Referer 会外泄 | 一次性 code 单次消费；token/code 不进 URL 与日志（AD-H07） |
| Access ↔ Tunnel（内网） | 内网可信但需最小权限 | 三层校验 `instance_id/session/role` 一致（NFR-H022） |
| 隧道 ↔ 实例 | 隧道来源仍是"外部" | 实例只对可信隧道接受签名上下文；LAN 仍用原密码 |
| Hub ↔ 电台安全 | **Hub 不持有释放权威** | PTT 释放永远在实例本地闭环（AD-H06、第 15 章） |

## 4.5 关键数据流

**A. 用户接入（读为主）**
`浏览器 → DNS(通配) → WAF/ALB → Access(验票/置 Cookie) → 内网 RPC → 归属 Tunnel → 虚拟流 → 实例 → 电台`

**B. 实例上线与保活**
`Agent →(出站 mTLS WSS) Tunnel(写归属映射 TTL) → REGISTER → 控制面(在线) → 每 15 s 心跳`

**C. Operator 发射（安全关键）**
`Operator(500 ms 会话心跳) → Tunnel → 实例(校验 key-owner) → 电台 TX`
失效时：`心跳缺失 → Tunnel 关流 → 实例活性闸门 → 本地 set_ptt(False) → 强制 RX`（详第 15 章）

**D. 遥测与升级**
`Agent 心跳/统计 → 控制面看板与告警`；`控制面按灰度通知 → Agent 拉 latest.json（复用 upgrade_core.py）→ OSS/CDN 下载 → 校验安装 → 回报`
