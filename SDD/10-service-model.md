# 10. Service Model

> 契约以"能力"描述，不绑定具体语言/框架。所有错误响应必须包含机器可读 `code` 与人类可读 `message`。

## 10.1 Portal（用户与管理面，REST）

| 能力 | 方法/路径（建议） | 说明 | 约束 |
| --- | --- | --- | --- |
| 实例列表 | `GET /api/instances` | 返回已授权实例与在线状态、版本、电台型号 | 只返回授权集合（SC-H5） |
| 实例详情 | `GET /api/instances/{id}` | 最后在线、当前 Tunnel 节点、活跃角色、租约状态 | Fleet Admin 默认不可读内容（NFR-H023） |
| 成员授权 | `POST /api/instances/{id}/members` | `(user, role)` 授权 | Owner + MFA |
| 申请接入 | `POST /api/instances/{id}/access` | `{role: operator\|listener}` → 返回 `launch_code` | 复核 ACL/在线/配额；Operator 走租约（AD-H05） |
| 释放租约 | `POST /api/instances/{id}/lease/release` | 主动释放 | 幂等 |
| 强制回收 | `POST /api/instances/{id}/lease/force-release` | 管理员收回 | 全量审计 |
| 绑定确认 | `POST /api/bind` | `{bind_code}` → 绑定 Owner 与实例 | 单次消费；审计（UC-H01） |
| 证书吊销 | `POST /api/instances/{id}/certificates/revoke` | 吊销设备证书 | Owner + MFA；立即断连（UC-H08） |
| 诊断开关 | `POST /api/instances/{id}/diagnostics` | 限时开启 | Owner 同意 + 审计 |

> 上表是**目标态契约**。实际在跑的 Portal 只实现了其中“接入申请 + 呼号核验 + 分配”一段，
> 且路径不同 —— 见 `12-operational-model.md` §12.9。**不要拿上表的路径去调现网**。
>
> **as-built（2026-10-01）**：`POST /apply`（规范化→查重→核验，应答里交付**申请令牌**）、
> `POST /status`（申请方凭该令牌查自己那一条）、`POST /verify`、`POST /grant`、
> `POST /enroll`、`POST /revoke`，加一个 `/admin` 审批台。
> 运维动作两种传令方式：请求头 `X-Portal-Token`（curl/脚本）或表单同名字段（浏览器）——
> **两者都不进 URL**，因为 URL 会进访问日志与浏览器历史（AD-H07）。

## 10.2 Ticket / Lease 服务

| 能力 | 契约 | 约束 |
| --- | --- | --- |
| 签发 launch code | 输入 `(user, instance_id, role, lease_id?)`；输出不透明 `code`（TTL ≤60 s，单次消费） | NFR-H010；不得是可解析的 JWT 直接放 URL |
| 消费 launch code | 原子消费；返回 `(session_id, role, lease_id)` | 重放/过期 → 拒绝 + 审计 |
| 获取租约 | `acquire(instance_id, holder)` → `HELD \| QUEUED \| DENIED` | **原子**；绝不返回第二个 Operator（SC-H3） |
| 续租 | `renew(lease_id)`（5–10 s） | TTL 20–30 s |
| 回收 | `release / expire / force` | **不得作为 PTT 释放机制**（AD-H06） |

## 10.3 Registry（实例目录）

| 能力 | 契约 | 约束 |
| --- | --- | --- |
| 写入归属 | `route(instance_id, node_id, connection_id, ttl)` | Tunnel Gateway 心跳续期 |
| 查询归属 | `lookup(instance_id)` → 节点或 `MISS` | `MISS` 时必须**明确失败**，不得回退到旧节点 |
| 在线状态 | `presence(instance_id)` → `online/offline/last_seen` | 离线识别 ≤45 s（NFR-H002） |
| 一致性断言 | `route` 必须与隧道连接一对一 | 跨实例错绑是 Critical 缺陷（NFR-H022） |

## 10.4 Tunnel 协议（Agent ↔ Tunnel Gateway）

| 帧 | 方向 | 载荷 | 说明 |
| --- | --- | --- | --- |
| `HELLO` / `WELCOME` | ↔ | 协议版本、客户端版本、能力位 | Hub 保留 N-2 兼容（NFR-H016） |
| `REGISTER` | Agent→Hub | 软件版本、电台型号、能力、LAN 状态 | 上线（UC-H02） |
| `HEARTBEAT` | Agent→Hub | RTT、重连次数、活跃会话、上行健康度、租约状态 | 15 s；**连接健康而非业务敏感内容** |
| `POLICY` | Hub→Agent | 策略差量、OTA 通知 | 版本化 |
| `OPEN_STREAM` / `STREAM_DATA` / `CLOSE_STREAM` | ↔ | HTTP 或 WS 帧 | 虚拟流；与 `instance_id` 严格绑定 |
| `SESSION_HEARTBEAT` | 双向 | 会话活性（TX 期间 **500 ms**） | **第 15 章的机制载体** |
| `TX_ABORT` | Hub→实例 | 关流通知（**不是 TX0**） | 实例据此执行本地释放 |

**多路复用**：一条物理隧道承载控制流与多个 HTTP/WS 虚拟流，采用成熟多路复用库，
**不自行发明拥塞控制**。

## 10.5 与实例侧的接口（`mrrc_modern` 契约）

| 既有能力 | Hub 如何使用 | 不得做 |
| --- | --- | --- |
| 5 端点 WS | 透明代理 | 改写帧格式、合并/缓冲二进制帧、规整自定义关闭码 |
| `/listen` 角色 gate | 复用为 Listener 语义（AD-H08） | 把 Listener 实现成严格只读而与实例行为分叉 |
| `_verify_auth`（cookie 或 `?token=`） | **阶段 2 改为信任隧道签名上下文；MVP 期必须停止把 token 放 URL** | 继续把 token 放 URL（AD-H07） |
| PTT Layer 0 + 1–8 | 直接复用，并为 Hub 增加一层（远程会话活性） | 让 Hub 成为释放路径的必要环节 |
| `upgrade_core.py` | 复用为 OTA 客户端核心 | 另建并行升级通道（AD-H13） |

## 10.8 实况指认（as-built，2026-09-30）

**已上线的服务面**：隧道网关（frps 0.71.0，控制口 8989，代理端口显式绑回环）、
入口 nginx（**一条**呼号通配 vhost，443，Let's Encrypt 真证书；海外边缘路径反代已随 V0.21 删除）、
注册表与路由生成（`/etc/mrrc-hub/instances.tsv` ＋ `gen_hub_routes.py`）、
证书服务（DNS-01，自建 hook，每日 8:00 cron 自动续期）。

**尚未实现**：实例清单服务、Operator 租约、配额与计费 —— 属阶段 2/3。
租户管理 Portal **已实现并上线公网入口**（2026-10-01，`https://portal.mrrc.vlsc.net`，见 §12.9）。
本节与 §12.8 分工：本节只列"服务面有没有"，运维细节在 §12.8。
