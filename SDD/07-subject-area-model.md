# 7. Subject Area Model

## 7.1 实体

| 实体 | 关键字段 | 归属/权威 | 生命周期 |
|---|---|---|---|
| `Instance` | `instance_id`、owner、软件版本、电台型号、能力位、LAN 状态、最后在线 | 控制面（归属）；**电台状态归实例** | 绑定 → 在线/离线 → 解绑 |
| `DeviceCredential` | 证书、公钥指纹、私钥引用（不出主机）、状态 | Device CA 签发；私钥仅客户主机持有 | 签发 → 轮换（宽限期）→ 吊销 |
| `BindCode` | 高熵值、TTL ≤10 min、尝试计数 | 控制面 | 签发 → 消费/过期（单次） |
| `User` | 账号、MFA 状态 | IAM | — |
| `Membership` | `(user, instance, role)` | 控制面 ACL | 授权 → 撤销 |
| `LaunchCode` | 不透明值、TTL ≤60 s、已消费标记 | Ticket 服务 | 签发 → 消费/过期（单次） |
| `Session` | `session_id`、`instance_id`、role、cookie 引用、隧道流引用、TX 状态 | Access/Tunnel；**电台侧状态以实例为准** | 建立 → 活跃 → 关闭 |
| `OperatorLease` | `instance_id`、holder、状态、TTL、续租时间 | Lease 服务（**授权互斥**，非释放机制） | `FREE → HELD → RELEASED / EXPIRED` |
| `TunnelConnection` | `connection_id`、`node_id`、协议版本、能力、心跳 | Tunnel Gateway | 建立 → 活跃 → 断开/切换 |
| `InstanceRoute` | `instance_id → {node_id, connection_id, last_seen}`，带 TTL | Registry/Redis | 写入 → 心跳续期 → 过期 |
| `SessionHeartbeat` | 会话活性（TX 期间 500 ms） | **实例与 Tunnel 共同判定** | 见第 [15](15-ptt-safety-hub-mode.md) 章 |
| `TelemetrySample` | RTT、重连次数、活跃会话、上行健康度、租约状态 | 实例上报 | 15 s 周期 |
| `AuditEvent` | 主体、动作、对象、结果、时间 | 控制面（只写） | 保留期策略 |

## 7.2 状态权威矩阵（谁说了算）

> 本表是本 SDD 最重要的边界约束：**跨仓不应出现两个权威**。

| 状态 | 权威 | Hub 的角色 | 常见错误 |
|---|---|---|---|
| 电台频率/模式/增益/记忆 | **实例**（`MRRC_modern`） | 转发与审计 | Hub 缓存并"优化"写序列 |
| **PTT / TX 状态** | **实例**（Layer 0 + 1–8） | 只能关流 + 通知 | Hub 直接下发 TX0（产生第二写者） |
| TX 音频所有权（key-owner） | **实例**（`_ptt_key_ws` 仲裁） | 不参与 | Hub 按"最后一次连接"判定归属 |
| Operator 授权互斥 | **Hub**（租约） | 原子竞争与回收 | 用租约到期替代本地释放 |
| 会话认证（MVP） | **实例**（自有密码） | 透明转发 | Hub 假定自己已授权 |
| 会话认证（阶段 2） | **Hub 签发 + 实例校验** | 签发签名角色上下文 | 实例信任非隧道来源的上下文 |
| 实例归属与在线 | **Hub Registry** | 映射 + TTL | 映射过期仍路由到旧节点 |
| 设备凭证 | **Device CA** | 签发/轮换/吊销 | 全 fleet 共享静态 token |
| 浏览器会话 Cookie | **各自 origin**（Hub 票证 vs 实例会话，见 AD-H09） | 只设置自己的 | 两个会话层同名 Cookie |
| 频谱/音频采集 | **实例**（已是 server-side fan-out） | 可选复制（AD-H12） | 认为 Hub 能减少采集侧的负载 |

## 7.3 关键状态机

**OperatorLease**

```text
FREE ──acquire──► HELD ──release/expire/force──► RELEASED / EXPIRED
                    │
                    ├─ renew（5–10 s，TTL 20–30 s）
                    └─ 冲突：排队 或 降级为 Listener（绝不签发第二个 Operator）
```

**TunnelConnection / InstanceRoute**

```text
(无) ──mTLS 建连──► ESTABLISHED ──REGISTER──► ONLINE(route 写入+续期)
      ▲                                            │
      └── 指数退避 + jitter ◄── 断开/心跳失败 ──────┘
          （认证失败 → 不无限重试，转人工处理）
```

**Session（TX 期间）**

```text
ACTIVE ──TX 开始──► TX_ACTIVE ──500 ms 心跳──► 继续 TX
                       │
                       ├─ EOF/RST ──► 实例 dead-man switch → RX（≤1 s）
                       └─ 心跳缺失 2 期 ──► Tunnel 关流 → 实例活性闸门 → RX（≤1.5 s）
```
