# 15. PTT Safety in Hub Mode

> **原则**：释放比键控更安全关键。在 Hub 模式下，**"连接已死但 TCP 未断"是最典型的失效模式**，
> 而既有实例机制只覆盖真正断开的连接。本章定义 Hub 模式下补齐这一缺口的机制、时限与验证。

## 15.1 既有模型（引用，不重复）

`mrrc_modern` 的本地安全模型见其 `SDD/15-ptt-safety-architecture.md`：
**Layer 0（未验证机型发射闸门，前置）+ Layer 1–8**（触摸释放、WS 命令、浏览器 watchdog、
服务器 dead-man switch、`beforeunload` beacon、`pagehide`、停止 TX 音频与清队列、一次性 CQ 播放器）。

**关键边界**：`mrrc_modern` 是 PTT 释放的**唯一权威**。Hub、Tunnel Gateway、租约服务
都不得成为释放路径的必要环节（AD-H06）。

## 15.2 缺口：半开连接

`mrrc_modern/server.py` 的注释已明确记录该缺口：

> `Opt-in stuck-keyup watchdog (MRRC_PTT_MAX_TX_SECONDS, 0 = off). Covers clients that hang WITHOUT
> disconnecting — the dead-man switch and client watchdogs never fire for a zombie-but-connected socket.`

| 失效模式 | 既有机制是否覆盖 | 原因 |
|---|---|---|
| 关闭浏览器 / 杀进程 / TCP RST | ✅ dead-man switch 立即强制 RX | 连接真的断了 |
| **拔网线 / 换 Wi-Fi / NAT 掉表 / 静默丢弃（iptables DROP）** | ❌ **不覆盖** | TCP 未断，socket 是 zombie-but-connected |
| 实例进程卡死但仍连着 | ⚠️ 仅当 `MRRC_PTT_MAX_TX_SECONDS` 非零（默认 0 = off） | 用户可选项、粒度 1.0 s |

在 LAN 场景下这不致命（断线 ≈ 真断线）。但在 Hub 场景（运营商 NAT、双层 NAT、弱网、频繁换网）
半开是**主路径**：此时租约仍在、云端 TTL 未到期，而唯一能释放的本地机制不会触发 ——
**恰是 NFR-H006 与 SC-H4 禁止依赖的那条路径**。

## 15.3 新增机制：TX 期间的会话活性契约

**核心思想**：把"操作者是否还在"从 TCP 语义提升为**应用层活性契约**，并由隧道层与实例共同守护。

### 15.3.1 参数

| 参数 | 值 | 依据 |
|---|---|---|
| TX 期间心跳间隔 `TX_HEARTBEAT_INTERVAL` | **500 ms** | 与实例既有 `TX-status` 500 ms 轮询、浏览器 PTT watchdog 500 ms 对齐，不引入新节拍 |
| 隧道层判定阈值 `TX_HEARTBEAT_MISS` | **连续 2 次未达（≈1.0 s）** | 容忍单包抖动，同时满足 ≤1.5 s 端到端目标 |
| 实例侧活性闸门阈值 | **1.0 s** | 与隧道层一致，避免双阈值打架 |
| 兜底 `MRRC_PTT_MAX_TX_SECONDS` | Hub 模式**推荐非零，建议 120 s** | 语义是"最长连续发射上限"，**不是释放机制**，不得用它替代本节机制 |

### 15.3.2 责任分配

| 层 | 职责 | 绝不做什么 |
|---|---|---|
| 浏览器（Operator） | TX 期间每 500 ms 发送会话心跳（可与既有 TX 音频流复用通道，不额外建连） | 不把心跳当授权凭证 |
| Tunnel Gateway | 转发心跳；TX 期间连续 2 个周期未见心跳 → **主动关闭虚拟流**（不等 TCP），并通知 Access/Lease 回收租约 | **不直接下发 TX0**（避免出现第二个写者） |
| MRRC 实例（新增） | **远程会话活性闸门**：TX 期间若会话心跳缺失 ≥1.0 s → `set_ptt(False)` + 清 TX 音频队列 | 不释放**别人**的载波（尊重 key-owner 仲裁） |
| Lease 服务 | 回收租约、清理会话、写审计 | 不把租约到期当释放手段（AD-H05/AD-H06） |

### 15.3.3 实例侧活性闸门必须遵守的仲裁

实例已有 key-owner 仲裁（`_ptt_key_ws` / `_ptt_release_allowed`：只有键控的那个 socket 的释放被采纳）。
新闸门**必须复用该仲裁**，否则会产生新的安全问题：

- LAN 直连客户端正在发射 + 某个远程 Listener 会话半开 → 闸门**不得**因此释放 LAN 的载波
- 远程 Operator 正在发射 + 其会话心跳失效 → 闸门**应当**释放
- 两个远程会话（同一 token 的多标签/重连）→ 以实例侧现存的 owner 判定为准

**三个不变量：**

1. **唯一权威**：任何释放动作最终都由实例本地执行；Hub 只能"关流 + 通知"。
2. **单写者**：任何时刻只有一个会话可以键控/释放载波（key-owner 仲裁）。
3. **不依赖云端**：租约 TTL、Hub 可达性、Portal 可用性都不是释放的必要条件。

## 15.4 时限矩阵

| 失效模式 | 检测者 | 检测延迟 | 端到端释放目标 | 现状 |
|---|---|---|---|---|
| 关闭浏览器 / 杀进程 / TCP RST | 实例 dead-man switch | 立即 | **≤ 1 s** | ✅ 已满足 |
| 拔网线 / 换 Wi-Fi / NAT 掉表 / DROP | 隧道层 + 实例活性闸门 | 2 × 500 ms ≈ 1.0 s | **≤ 1.5 s** | ❌ 待实现（MVP） |
| Tunnel Gateway 节点被杀 | 连接随节点消失 + 实例侧闸门 | ≈1.0 s | ≤ 1.5 s | ❌ 待实现 |
| Hub 整体不可用 | 连接断开（RST/EOF）→ dead-man switch | 立即 | ≤ 1 s | ✅ 已满足 |
| 实例进程卡死但仍连着 | 实例自身 stuck-keyup watchdog | ≤1.0 s 粒度 | ≤ 2 s | ⚠️ 需 `MRRC_PTT_MAX_TX_SECONDS` 非零 |
| 客户端主动释放 | 实例 key-owner 仲裁 | 立即 | 立即 | ✅ 已满足 |
| 云端租约到期 | —— | 20–30 s | **明确不作为释放机制** | — |

## 15.5 验证矩阵（发布门禁）

每一行都是**必做注入测试**，结果入审计与版本历史：

| # | 注入方式 | 期望 |
|---|---|---|
| V1 | TX 中关闭浏览器 | 实例 ≤1 s 释放；租约被回收 |
| V2 | TX 中 `kill -9` 浏览器进程 | 同 V1 |
| V3 | TX 中拔网线（或 `iptables -A FORWARD -j DROP` 静默丢弃） | 隧道层 ≤1 s 关流；实例 ≤1.5 s 释放 |
| V4 | TX 中切换 Wi-Fi（IP 变化，TCP 半开） | 同 V3 |
| V5 | TX 中杀掉归属 Tunnel Gateway 节点 | 同 V3；实例重连后不恢复发射 |
| V6 | TX 中停掉整个 Hub | 实例 ≤1 s 释放（连接 RST/EOF 路径） |
| V7 | TX 中暂停 Hub 与实例**两端**网络（深度半开） | 实例 ≤1.5 s 释放 |
| V8 | LAN 客户端发射 + 远程 Listener 会话半开 | **LAN 载波不被释放**（仲裁正确） |
| V9 | 实例进程 SIGSTOP（卡死但连接活着） | `MRRC_PTT_MAX_TX_SECONDS` 生效时 ≤2 s 释放 |
| V10 | 心跳单包丢失（非连续） | **不误释放**（不抖动） |

## 15.6 跨仓影响

本机制需要在 `mrrc_modern` 侧落地，因此**必须在该仓 SDD 中同步登记**：

- 新增配置：`MRRC_REMOTE_SESSION_TX_HEARTBEAT_S`（默认 1.0 s，0 = 关闭）
- 新增行为：TX 期间的远程会话活性闸门（复用 key-owner 仲裁）
- 默认值变更评估：`MRRC_PTT_MAX_TX_SECONDS` 在 Hub 模式下推荐 120 s
- 回归：`mrrc_modern` 的 `SDD/15` Layer 表需要新增一层（远程会话活性），并同步测试计数

> 关联：`AD-H06` `NFR-H006` `NFR-H019` `SC-H4` `UC-H05` `R-H1` `I-H6`
