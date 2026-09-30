# 12. Operational Model

## 12.1 部署拓扑（单地域双可用区起步）

| 资源 | 起步规格 | 说明 |
|---|---|---|
| Access/Tunnel 数据面 | 2 × 4C8G，高网络基线 | 可先同进程部署；到触发线后拆分。**实际更可能先受公网出带宽、连接数与 fd 限制，而非 CPU** |
| 控制面 | 2 × 4C8G | Portal/IAM/Registry/Ticket/OTA/审计，无状态 |
| RDS MySQL HA | 1 套 4C8G | 用户、实例、ACL、版本、审计索引 |
| Redis HA | 1 套 ≥4 GB | 会话、一次性 code、租约、实例→节点映射 |
| ALB/WAF/EIP | 1 套跨 AZ | 用户公网入口；隧道入口按协议选 ALB/NLB 或直连 |
| OSS + CDN | 按量 | OTA 包与可选云备份；**不经数据面 ECS**（NFR-H018） |
| 日志/监控 | 按量 | 指标、日志、告警 |

> 本表是**压测前起步估算**，不是采购承诺。扩容阈值见 NFR-H017。

## 12.2 部署形态约定（沿用现状经验）

现状的 `deploy_listen_proxy.sh`（B2）与 `deploy_support_receiver.sh`（B4）已经确立了本项目的
部署风格，Hub 沿用：

- **幂等脚本**：可重复执行；块级替换而非追加（避免 B2 踩过的"重复块导致 `nginx -t` 失败"）
- **远端前置探测**：部署前先验证后端可达性，再动配置
- **独立 systemd unit + 独立端口 + 独立存储**：不与其他服务共用目录
- **凭据 0600、root-only EnvironmentFile**：不打印、不入 git
- **`nginx -t && reload`**：配置变更必须先验证再重载

## 12.3 配置项（建议命名）

| 配置 | 默认 | 说明 |
|---|---|---|
| `HUB_TUNNEL_HOST` / `HUB_TUNNEL_PORT` | `tunnel.mrrc.vlsc.net:443` | Agent 隧道入口（支持多地址列表） |
| `HUB_HEARTBEAT_INTERVAL_S` | 15 | 实例心跳周期（NFR-H002） |
| `HUB_LEASE_TTL_S` | 25 | Operator 租约 TTL（20–30） |
| `HUB_LAUNCH_CODE_TTL_S` | 60 | 一次性 code（NFR-H010） |
| `HUB_BIND_CODE_TTL_S` | 600 | 绑定码（NFR-H011） |
| `HUB_TX_HEARTBEAT_INTERVAL_MS` | 500 | TX 期间会话心跳（第 15 章） |
| `HUB_TX_HEARTBEAT_MISS` | 2 | 连续未达即关流（第 15 章） |
| `HUB_LOG_REDACT` | `1` | 访问日志脱敏（`token=`/`code=`），**禁止关闭**（NFR-H014） |
| `HUB_TLS_VERIFY_UPSTREAM` | `1` | 上游证书校验，**禁止关闭**（NFR-H021） |

## 12.4 可观测性与告警

| 指标 | 告警线 | 动作 |
|---|---:|---|
| 实例在线率 | < 95%（5 min 窗口） | 输出离线清单并区分客户侧/Hub 侧 |
| 单实例隧道重连 | > 3 次/小时 | 检查客户网络、证书与 Tunnel 节点 |
| 新会话建立成功率 | < 99% | 检查节点映射、验票与代理链路 |
| Ticket/code 验证失败率 | > 1%/分钟 | 安全告警 + 来源限流 |
| Operator 租约冲突率 | > 设定阈值 | 调整队列/最长占用策略 |
| 数据面连接数/fd | > 70% 预警，> 80% 扩容 | 水平扩数据面 |
| Hub 公网出带宽 | > 70% 预警，> 80% 扩容/限流 | 扩带宽或按 AD-H14 降瀑布 |
| **PTT 异常释放事件** | **任意关键异常** | 安全事件跟踪（第 15 章 V 矩阵口径） |
| **半开连接检测次数** | 环比突增 | 检查客户网络与心跳参数 |
| OTA 失败率 | > 5%/批次 | 暂停灰度并回滚 |

**必须优先建立的三项观测**（都是 I-H1/I-H2 的数据来源，成本极低）：

1. 每实例典型/峰值 Listener 并发（实例侧已有 `spectrum_clients` / `audio_rx_clients` / `_listen_tokens` 集合）
2. 每会话真实流量与实例上行利用率
3. TX 会话的心跳缺失与释放时延分布

## 12.5 配额

| 配额 | 说明 |
|---|---|
| 每实例 Listener 并发上限 | Owner 可配；默认建议 3（与 AD-H12 门槛对齐） |
| 每用户并发会话数 | 防滥用 |
| Operator 单次最长占用 | 需定值（源文档 §14 待决策项） |
| 带宽护栏 | 实例上行 60%（预警）/ 80%（扩容或降级） |

## 12.6 发布与回滚

1. 构建 → 签名 → 上传 OSS/CDN → 更新清单（含 `minSupported` / `mandatory`）
2. 灰度 5% → 观察失败率与 PTT 异常指标 → 25% → 100%
3. 失败率 > 5%/批次：暂停并按 UC-H09 回滚
4. **TX 中或会话活跃的实例延后升级**；升级期间拒绝新 Operator 租约

## 12.7 排障快速索引

| 症状 | 优先检查 |
|---|---|
| 实例显示离线但客户说在线 | 心跳是否到达、证书是否过期、归属映射是否过期、出站 443 是否被拦 |
| 用户能登录但控制台黑屏 | 5 个 WS 端点中哪个被拒绝（4001 未授权 / 4003 角色拒绝）；是否 Listener 访问了 `/WSaudioTX` |
| 令牌出现在日志 | **回归缺陷**（AD-H07/SC-H6）：检查 `HUB_LOG_REDACT`、nginx log_format、实例 uvicorn 日志 |
| 音频卡顿 | 上行利用率是否 > 60%；按 AD-H14 先降瀑布帧率；查看 Listener 并发是否超过 AD-H12 门槛 |
| PTT 未释放 | **安全事件**：区分 EOF 型 / 半开型（第 15 章 §15.4），核对心跳参数与 `MRRC_PTT_MAX_TX_SECONDS` |
| 升级后行为没变 | 核对清单版本、包 SHA、实例实际运行版本（沿用 `upgrade_core.py` 的 `state.json` 可证明性） |
