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
| SDD Version | V0.17 |
| Baseline Date | 2026-10-01 |
| Status | **阶段 1 通路已在真实公网跑通**（`bg1sb.mrrc.vlsc.net:9988` → 隧道 → 实例，118–168 ms）。通配真证书（DNS-01）就位并每日续期；令牌不进 URL：**hub 侧已实现**（日志不记 query）；**实例侧在 mrrc_modern feat/hub 已改纯 Cookie 传递（C2），未合并 main**，Stable v1.21.0 仍拼 `?token=`（11 §11.3 对账注）；**呼号注册已上线公网自助**（`portal.mrrc.vlsc.net:8899`，见 §12.9）；**实例证书链已闭环并在真实租户机上验证（签发 → 登记 200 → 信任包 → 入口可达）。剩余：隧道层 PTT 半开释放（MVP，I-H6 open）、Operator 租约、设备 mTLS、安装包分发、ICP 备案 |
| Instance baseline | `mrrc_modern` v1.21.0 Stable（`4f385dd`）—— 5 个 WS 端点、`/listen` 角色、PTT 8 层 + Layer 0 |
| 客户侧前提 | 实例仅需出站 TCP **8989**（隧道口）；无公网 IP、无端口映射、无 UPnP（SC-H1）。**用户侧需能出站 9988** —— 两条不同的约束，见 NFR-H001 / R-H12 |
| 入口规划 | **两级**：主路 `<呼号>.mrrc.vlsc.net:9988`（hub，低延迟；`:8899` 同服务备用口）；退化路 `www.vlsc.net/mrrc_modern/<呼号大写>/` 反代（443 + 真证书，供只放行 80/443 的网络，+0.4~0.6 s，2026-10-01 实测间歇）。隧道 `tunnel.mrrc.vlsc.net:8989`；明文口不可依赖（R-H13） |
| 租户标识 | **无线电呼号**（AD-H15）：`<呼号>.mrrc.vlsc.net`；注册实例与注册用户都必须提供真实呼号并核验；大小写不敏感（内部小写、路径规范大写） |
| 角色 | Owner / Operator / Listener / Fleet Admin（**语义以 AD-H08 为准**） |
| 单实例写者 | 同时最多 1 个有效 Operator 租约（AD-H05） |
| 安全基线 | 一实例一证（设备 mTLS）、一次性 launch code、host-only Cookie、令牌不进 URL/日志（AD-H07、AD-H11） |
| 数据面 | Access Gateway（无状态）×N + Tunnel Gateway（有状态）×≥2，归属映射经 Registry/Redis（AD-H03） |
| 阶段 1 现网形态 | hub：**一条通配 vhost** + `/etc/mrrc-hub/instances.tsv` 注册表（名字→回环端口，生成器产出 nginx map）；实例：**launchd 常驻 frpc**（0600 配置 + KeepAlive） |
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
| 实例出站隧道 | **已跑通（阶段 1，frp 通道）** | 客户侧零入站；macOS/Linux/Windows 均为常驻服务、自恢复；目标态为内置 Fleet Agent（AD-H01、AD-H04） |
| 通配子域接入 | **已跑通（阶段 1）** | 一条通配 vhost + 注册表映射（AD-H02）；`*.mrrc.vlsc.net` 真 Let's Encrypt 证书已签发并每日自动续期 |
| 实例证书一机一证 | **已闭环（阶段 1）** | 自签 + 信任包钉住；`make_instance_cert.sh` → `POST /enroll`（一次性口令 + 名字必须等于本入口名）→ `gen_hub_routes.py` 并入信任包；nginx 校验始终保持开启（NFR-H031） |
| 实例目录 / 在线状态 | 待实现 | Registry + 心跳 TTL；离线识别 ≤45 s（NFR-H002）。现状只有**静态**注册表，无在线状态 |
| 透明 HTTP/WS 代理 | **已跑通** | 覆盖全部 5 个 WS 端点，升级/长连接/关闭语义与直连一致 |
| 呼号注册与核验（UC-H10） | **已上线公网** | `https://portal.mrrc.vlsc.net:8899/` 自助申请 + `/admin` 审批台；核验走 Club Log 全库（与站内留言版同源），未命中转人工。见 §12.9 |
| 实例证书链（一机一证） | **已施用并跑通（2026-10-01 真实租户机实测）** | `make_instance_cert.sh` 签自签证书 → 钉进 `trust-bundle.pem` → nginx 按 `$mrrc_tls_name` 逐实例校验。现网 `bg1sb` 仍用旧证书名 `radio.vlsc.net` |
| 实例安装器 | **脚本就位，分发未做** | `deploy/install_instance_tunnel.{sh,ps1}`：自取 frpc 并校验 SHA-256、与 frps 版本 pin 死、三平台常驻。仍是仓内脚本，无公开发布的安装包下载 |
| 实例侧 Hub 前置能力 | **已进打包版** | mrrc_modern v1.22.0：路径前缀 / 令牌不进 URL / 会话遥测 / PTT 活性闸门 |
| Hub 托管鉴权 | 阶段 2 | 一次性 launch code + 角色上下文签名（AD-H04，受 AD-H07 制约）。**注意与上面的呼号注册是两件事** |
| Operator 租约 | 待实现 | 单写多读；冲突默认排队（AD-H05）。现由实例侧仲裁谁在发射 |
| Listener 受限角色 | **已实现** | **可调频/换模式，禁发射** —— 实例侧服务端强制（AD-H08），非"只读" |
| PTT 半开释放 | **实例侧已实现（opt-in）；隧道层待做** | 实例侧 `MRRC_REMOTE_SESSION_TX_HEARTBEAT_S`（默认 0 = 关，Hub 模式建议 3–5 s）；隧道层心跳 + 主动关流仍属 MVP 必修（AD-H06、第 15 章） |
| 令牌不进 URL | **已实现** | 前端不再拼接查询串；hub 侧访问日志也不记查询串（AD-H07） |
| OTA 灰度 | 部分复用 | 拉取侧复用 `upgrade_core.py`，补签名/灰度/回滚（AD-H13） |
| RX 扇出 | 条件启用 | 触发门槛见 AD-H12；带宽杠杆在频谱（408 kbps，占 86%） |

> 本表的状态列区分**已跑通/已实现**与**设计目标**；与 §12.8 的实况记录冲突时以 §12.8 为准。
> 下次修改前先按 §12.8 复核，不要按本表的旧值反推。
> 尤其注意「机制就位」与「已在跑」是两回事 —— 实例证书链已于 2026-10-01 在真实租户机上跑通
> （签证书 → 登记 200 → 信任包 → 入口可达），现网 `bg1sb` 仍用旧证书名，尚未逐个迁移。

## 索引补充（V0.13，2026-10-01）

| 想找什么 | 去哪 |
| ---------- | ------ |
| 呼号注册与核验流程（含四种异常分支） | `06-use-case-model.md` **UC-H10** |
| 呼号即身份的成功判据 | `03-project-definition.md` **SC-H10** |
| 证书生命周期要求（真证书 / 自动续期 / 禁止跨机同步） | `05-non-functional-requirements.md` **NFR-H030** |
| **实况部署事实**（主机、入口、证书全流程、运维命令、已知退化） | `12-operational-model.md` **§12.8** |
| 架构/服务模型的实况指认 | `09-architecture-overview.md` §9.9、`10-service-model.md` §10.8 |
| 开放问题与已结案 | `13-feasibility-assessment.md`（I-H9 已结案） |
| 现状取证评审（四项 P0）与其结案状态 | `../docs/2026-09-30-fleet-hub-design-review.md` §结案 |
| 呼号注册的**可运行实现**（四端点、为何核验必须在授予之前） | `portal/README.md`、`12-operational-model.md` **§12.9** |
| **实例证书链**（一机一证、信任包、逐实例校验） | `12-operational-model.md` **§12.8 「实例证书链」**；决策与偏离见 `08` **AD-H11 as-built 指认** |
| **实例证书生命周期 / 可信安装的要求** | `05` **NFR-H031**（信任包原子替换）、**NFR-H032**（无预装可安装 + 必校哈希） |
| **文档事实可追溯**（不凭设计意图措辞） | `05` **NFR-H033**；站点侧落地见 `../website/README.md` 的复验清单 |
| **组件模型里“目标态 vs 在跑的”对照** | `11` **§11.1 as-built 指认**（逐行给出子集 vs 目标态） |
| **服务模型里“目标态契约 vs 现网路径”** | `10` **§10.1 as-built 指认**（实跑四端点与两种传令方式） |
| **实例开通链 / 安装器**（自取 frpc 并校验哈希、三平台常驻） | `12-operational-model.md` **§12.8 「实例开通链」** |
| as-built 总体架构图（含对目标态旧图的逐条订正） | `../docs/architecture-2026-10-01-as-built.svg`（同目录 PNG / HTML） |
| **面向用户的文档站**（5 页：概览/接入/使用/排障 + 单独一页设计） | `../website/`（先看 `../website/README.md` 的事实源映射与发布前复验清单） |
| **部署脚本与现网的漂移**（重跑会让现网退化） | `../deploy/README.md` 的「⚠️ 脚本与现网漂移」 |
