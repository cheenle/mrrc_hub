# MRRC Cloud Hub (`mrrc_hub`) SDD — Software Design Description

> 200+ MRRC_modern 实例的远程接入：实例主动出站、云端统一入口、控制面与接入面分离
> IBM Team Solution Design (TeamSD) 对齐文档集

## Purpose

本 SDD 是 `mrrc_hub` 的**唯一设计基线**。它记录需求、成功判据、架构决策、组件边界、
服务契约、运营模型、可行性与演进历史。

**边界**：电台控制与媒体（CAT/CI-V、Opus 音频、频谱瀑布、PTT 多层安全释放）的权威
是 `mrrc_modern/SDD/`；本 SDD 只定义**其外部**的接入、租约、证书、Portal 与可观测性，
通过交叉引用复用，不复制。

**源输入**：`MRRC_modern_远程接入统一设计文档_v2.0_20260930.md`（架构评审稿）。
该稿的结论已全部吸收进本 SDD；其中的估算值已用代码取证替换（见
[`docs/2026-09-30-fleet-hub-design-review.md`](../docs/2026-09-30-fleet-hub-design-review.md)）。

## Document Index

| # | Chapter | File |
| --- | --------- | ------ |
| 1 | Executive Summary | [01-executive-summary.md](01-executive-summary.md) |
| 2 | Business Direction | [02-business-direction.md](02-business-direction.md) |
| 3 | Project Definition（scope, SC-H1…SC-H9） | [03-project-definition.md](03-project-definition.md) |
| 4 | System Context（actors, interfaces, data flows） | [04-system-context.md](04-system-context.md) |
| 5 | Non-Functional Requirements（NFR-H001…NFR-H018） | [05-non-functional-requirements.md](05-non-functional-requirements.md) |
| 6 | Use Case Model（UC-H01…UC-H09） | [06-use-case-model.md](06-use-case-model.md) |
| 7 | Subject Area Model（entities, state ownership） | [07-subject-area-model.md](07-subject-area-model.md) |
| 8 | Architecture Decisions（AD-H01…AD-H14） | [08-architecture-decisions.md](08-architecture-decisions.md) |
| 9 | Architecture Overview（pipelines, routing, failover） | [09-architecture-overview.md](09-architecture-overview.md) |
| 10 | Service Model（Portal/REST, Registry, Tunnel, Ticket, Lease） | [10-service-model.md](10-service-model.md) |
| 11 | Component Model | [11-component-model.md](11-component-model.md) |
| 12 | Operational Model（deploy, config, monitoring, OTA） | [12-operational-model.md](12-operational-model.md) |
| 13 | Feasibility Assessment（risks R-H*, assumptions A-H*, issues I-H*） | [13-feasibility-assessment.md](13-feasibility-assessment.md) |
| 14 | Version History | [14-version-history.md](14-version-history.md) |
| 15 | PTT Safety in Hub Mode | [15-ptt-safety-hub-mode.md](15-ptt-safety-hub-mode.md) |

## Quick Facts

| Attribute | Value |
| ----------- | ------- |
| Document ID | SDD-MRRC-HUB-2026-001 |
| SDD Version | V0.8 |
| Baseline Date | 2026-09-30 |
| Status | **阶段 1 通路已在真实公网跑通**（`test1.mrrc.vlsc.net:9988` → 隧道 → 实例，118–168 ms）。MVP 前必修项：I-H6/AD-H07/AD-H09 已实现（mrrc_modern V2.62/V2.63）；剩余为通配真证书（DNS-01）与备案 |
| Instance baseline | `mrrc_modern` v1.21.0 Stable（`4f385dd`）—— 5 个 WS 端点、`/listen` 角色、PTT 8 层 + Layer 0 |
| 客户侧前提 | 实例仅需出站 TCP **8989**（隧道口）；无公网 IP、无端口映射、无 UPnP（SC-H1）。**用户侧需能出站 9988** —— 两条不同的约束，见 NFR-H001 / R-H12 |
| 入口规划 | **两级**：主路 `<instance-id>.mrrc.vlsc.net:9988`（hub，低延迟）；退化路 `www.vlsc.net` 反代（443 + 真证书，供只放行 80/443 的网络，+0.4~0.6 s）。隧道 `tunnel.mrrc.vlsc.net:8989`；明文 8899 不可依赖（R-H13） |
| 租户标识 | **无线电呼号**（AD-H15）：`<呼号>.mrrc.vlsc.net`；注册实例与注册用户都必须提供真实呼号并核验；大小写不敏感（内部小写、路径规范大写） |
| 角色 | Owner / Operator / Listener / Fleet Admin（**语义以 AD-H08 为准**） |
| 单实例写者 | 同时最多 1 个有效 Operator 租约（AD-H05） |
| 安全基线 | 一实例一证（设备 mTLS）、一次性 launch code、host-only Cookie、令牌不进 URL/日志（AD-H07、AD-H11） |
| 数据面 | Access Gateway（无状态）×N + Tunnel Gateway（有状态）×≥2，归属映射经 Registry/Redis（AD-H03） |
| 阶段 1 现网形态 | hub：**一条通配 vhost** + `/etc/mrrc-hub/instances.tsv` 注册表（名字→回环端口，生成器产出 nginx map）；实例：**launchd 常驻 frpc**（0600 配置 + KeepAlive）|
| 复用而非新建 | OTA 拉取侧 `mrrc_modern/upgrade_core.py`；诊断上报 `deploy_support_receiver.sh`（AD-H13） |
| 规模设计余量 | 500 在线隧道 / 1000 活跃会话 / 5000 用户 WS / 公网出带宽起步 200 Mbps（NFR-H017） |

## System at a Glance

```text
远程用户 (Operator / Listener / Owner / Fleet Admin)
  | HTTPS + WSS: https://<instance-id>.mrrc.vlsc.net
  v
DNS(通配) → WAF → ALB
  v
Access Gateway (无状态 ×N)  ←→  Fleet 控制面 (Portal/IAM/ACL/Registry/Ticket/Lease/OTA/审计)
  | 内网 RPC（按 Registry 归属映射转发）        ↑
  v                                            | instance_id → tunnel_node 映射 (Redis + TTL)
Tunnel Gateway (有状态 ×≥2)  ───────────────────┘
  ^ WSS + mTLS（实例主动出站建立，客户侧零入站）
  |
MRRC Fleet Agent（客户内网）
  → MRRC_modern (FastAPI/Uvicorn, :8888)
     · /WSradio /WSspectrum /WSaudioRX /WSaudioTX (+/WSatr1000)   ← 透明代理，不改协议
     · 本地 PTT 安全释放（最高优先级，不依赖云端租约 TTL）
  → 电台 (FT-710 / IC-7300 / …)
```

## Capability Summary

| 能力 | 状态 | 说明 |
| ------ | -------- | ------- |
| 实例出站隧道 | 待实现 | MVP 可用成熟反向隧道验证（frp），目标态为内置 Fleet Agent（AD-H01、AD-H04） |
| 通配子域接入 | 待实现 | 取代现状的路径前缀方案（AD-H02） |
| 实例目录 / 在线状态 | 待实现 | Registry + 心跳 TTL；离线识别 ≤45 s（NFR-H002） |
| 透明 HTTP/WS 代理 | 待实现 | 覆盖全部 5 个 WS 端点，升级/长连接/关闭语义一致 |
| Hub 托管鉴权 | 阶段 2 | 一次性 launch code + 角色上下文签名（AD-H04，受 AD-H07 制约） |
| Operator 租约 | 待实现 | 单写多读；冲突默认排队（AD-H05） |
| Listener 受限角色 | 语义已定稿 | **可调频/换模式，禁发射** —— 与实例现状一致，非"只读"（AD-H08） |
| PTT 半开释放 | **待实现（MVP 必需）** | 隧道层 TX 期间心跳 + 主动关流（AD-H06、第 15 章） |
| 令牌不进 URL | **待实现（MVP 必需）** | 需改实例前端；见 AD-H07 |
| OTA 灰度 | 部分复用 | 拉取侧复用 `upgrade_core.py`，补签名/灰度/回滚（AD-H13） |
| RX 扇出 | 条件启用 | 触发门槛见 AD-H12；带宽杠杆在频谱（408 kbps，占 86%） |
