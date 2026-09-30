# MRRC Hub (`mrrc_hub`)

**MRRC Cloud Hub** —— 为 200+ 套运行在客户内网、无公网 IP、无法稳定端口映射的
`MRRC_modern` 实例提供统一、安全、可运营的公网远程接入能力。

## 这个仓库是什么

| 项 | 值 |
|---|---|
| 角色 | 云端控制面 + 数据面（Portal / Registry / Ticket / Lease / Access Gateway / Tunnel Gateway） |
| 不做什么 | **不重做**电台控制与媒体能力。CAT/CI-V、双向 Opus 音频、频谱瀑布、PTT 多层安全释放全部复用 `mrrc_modern` 既有实现 |
| 设计基线 | [`SDD/`](SDD/README.md)（IBM TeamSD 对齐，本仓唯一设计基线） |
| 评审记录 | [`docs/2026-09-30-fleet-hub-design-review.md`](docs/2026-09-30-fleet-hub-design-review.md) |
| 状态 | 架构评审完成；**四项 MVP 前必修项待决策**（见 SDD §13 的 I-H6 与 AD-H07…AD-H10） |

## 仓库关系

```text
/Users/cheenle/HAM/
├── hub/
│   ├── mrrc_hub/        ← 本仓：云端 Hub（SDD 基线）
│   ├── mrrc_modern/     ← 实例侧：当前产品基线 v1.21.0（LAN + 远程接入的既有能力）
│   └── mrrc/            ← 旧架构：含第 0 代 SSH 反向隧道（B1），SDD 已迁至 docs/legacy
└── website/             ← www.vlsc.net 站点：latest.json / support receiver
```

**权威边界**：电台行为（PTT/CAT/音频）的权威是 `mrrc_modern/SDD/`；
远程接入、租约、证书、Portal 的权威是**本仓 `SDD/`**。两者交叉引用，不互相复制。

## 现状基线（为什么需要本仓）

远程接入不是从零开始 —— 已有 4 套机制在生产或历史上存在，详见
[`SDD/01-executive-summary.md`](SDD/01-executive-summary.md#12-现状基线评审新增)。
其中 **B2（IPv6 直连 + nginx 幂等反代）已在公网生产运行**（`www.vlsc.net/mrrc_modern/listen`
→ `radio.vlsc.net:8888`）：它证明了家宽场景下 IPv6 直连可行，也暴露了逐资源改中心
nginx、TLS 校验关闭、令牌进 URL 三条不可扩展的硬伤。本仓的工程目标就是把它
变成**可自助、可复制、可 200 实例化**的能力。

## 工程约定

- 改动前先拉工程简报（SDD + 约束）：
  ```bash
  python3 ~/.pi/agent/skills/sdd-guardian/harness/sdd_context.py brief <files>
  # 或按任务主题：
  python3 ~/.pi/agent/skills/sdd-guardian/harness/sdd_context.py brief --task "<任务>"
  ```
- 提交前必须过闸：
  ```bash
  python3 ~/.pi/agent/skills/sdd-guardian/harness/sdd_context.py check --staged   # 必须 clean
  ```
- 行为变更 → 同步 SDD 章节 + `SDD/14-version-history.md` 条目 + `SDD/README.md` 版本号。
- 项目级铁律见 [`.agents/skills/sdd-guardian/SKILL.md`](.agents/skills/sdd-guardian/SKILL.md)。
