# 11. Component Model

## 11.1 Hub 侧组件

| 组件 | 职责 | 状态 | 伸缩 |
| --- | --- | --- | --- |
| Portal (Web/API) | 实例列表、成员授权、接入申请、绑定、证书管理、诊断开关 | 无状态 | 水平 |
| IAM / ACL | 账号、MFA、`(user, instance, role)` 判定 | 状态外置 | 水平 |
| Registry | `instance_id → tunnel node` 归属映射与在线状态 | Redis（TTL） | 水平读 |
| Ticket Service | 一次性 launch code 签发/消费 | Redis | 水平 |
| Lease Service | Operator 租约原子竞争、续租、回收 | Redis | 水平 |
| Device CA | 设备证书签发、轮换、吊销 | 私钥受保护 | 主备 |
| Policy Service | 实例策略、配额、地区策略、紧急禁用 | RDS | 水平 |
| OTA Service | 清单与灰度编排、签名校验、失败暂停/回滚 | RDS + OSS/CDN | 水平 |
| Diagnostics | 限时通道、最小权限、审计 | RDS | 水平 |
| Audit | 只写事件流 | RDS/日志 | 水平 |
| Access Gateway | 验票、子域路由、置 Cookie、内网转发 | **无状态** | 水平（核心扩容点） |
| Tunnel Gateway | 长连接终结、归属写入、虚拟流、会话心跳判定 | **有状态** | 纵向 + 节点数；故障靠重连 |
| RX Relay（可选） | 共享 RX 音频/频谱复制 | 有状态 | AD-H12 触发后 |

**as-built 指认（2026-10-01）—— 上表是目标态；下面这些是真正在跑的**：

| 已实现的组件 | 对应目标态 | 实现在哪 |
| ------- | -------- | -------- |
| 呼号注册 Portal | Portal（极简子集） | `portal/`（零第三方依赖，标准库 HTTP）；systemd `mrrc-portal.service`；仅四端点 `apply/verify/grant/revoke` + `/admin` 审批台 |
| 遥号核验 | IAM 的核验部分 | Club Log 全库（27 万条，与站内留言版同源，每日同步）+ 自建呼号库 + 人工兜底 |
| 注册表（静态） | Registry（在线状态版） | `/etc/mrrc-hub/instances.tsv` + `gen_hub_routes.py` 生成 nginx map。**无在线状态、无 Redis、无心跳** |
| 实例证书签发 | Device CA（极简子集） | `deploy/make_instance_cert.sh` + `/etc/mrrc-hub/trust-bundle.pem`。**无轮换、无 CRL** |
| 子域路由 + 透明代理 | Access Gateway | nginx 通配 vhost（无验票、无 Cookie 设置、无内网 RPC） |
| 反向隧道 | Tunnel Gateway（frp 版） | frps 0.71.0，`proxyBindAddr=127.0.0.1` |

**未实现**：IAM/ACL、Ticket、Lease、Policy、OTA、Diagnostics、Audit、RX Relay —— 全部阶段 2 起。
**尤其注意**：本表里的每一行都是“目标态的极简子集”，不是它的实例化。把子集当成目标态已经实现，
是这份设计记录最容易犯的错。

## 11.2 组件间关键依赖

```text
Portal ──► IAM/ACL ──► Ticket ──► Lease
   │                                │
   └──► Registry ◄──────────────────┘
            ▲
Access Gateway ──(内网 RPC)──► Tunnel Gateway ──(mTLS WSS)──► Fleet Agent
                                    │
                                    └──► SessionHeartbeat 判定 ──► TX_ABORT（通知，非 TX0）
```

## 11.3 实例侧（`mrrc_modern`）需要的变更

> 这些变更属于 `mrrc_modern` 仓库，**必须在该仓 SDD 中登记并回归**；本 SDD 只声明契约。

| # | 变更 | 目的 | 关联 |
| --- | --- | --- | --- |
| C1 | 远程会话活性闸门（`MRRC_REMOTE_SESSION_TX_HEARTBEAT_S`，默认 1.0 s，0=关） | 半开连接下本地释放 PTT | AD-H06、第 15 章、I-H6 |
| C2 | 前端停止把 token 放 URL（改 Cookie 或 `Sec-WebSocket-Protocol`） | 令牌不进日志/Referer/历史 | AD-H07、NFR-H020 |
| C3 | 会话 Cookie 加 `Secure`（远程模式） | 与短时效票证叙事一致 | AD-H09 |
| C4 | （评估）远程模式下缩短 30 天会话有效期 | 限制长期免登录 | AD-H09 |
| C5 | Hub 模式下推荐 `MRRC_PTT_MAX_TX_SECONDS=120` | 卡死进程的兜底上限 | 第 15 章 §15.3.1 |
| C6 | Listener 调谐的审计来源标注 | AD-H08 的可审计性 | AD-H08 |

> **对账注（2026-10-01，V0.16，同日修正）**：C1–C6 在 `mrrc_modern` **origin/feat/hub** 上
> **已实现**（CHANGELOG v1.22.0/v1.23.0：C1 心跳在 server.py 有 6 处消费；C2 改纯 Cookie
> 传递，`?token=` 仅存于注释；前缀感知见 listen.js/ft710_main.js），**但该分支未合并进 main**
> （ahead 25 commits），Stable 渠道与产品站仍是 v1.21.0（仍拼 `?token=`）。
> 因此"已实现"叙事只对 feat/hub 成立；hub as-built 实例跑在哪个 ref 上是 §12.8 的运营待确认项。
> 残留：Cookie 仍 `httponly=False`（C2 之后"JS 要读它"的理由已不成立，可改 True）、无 `Secure`（C3 仍 open）。

**交付状态（2026-10-01）**：C1–C6 已随 **mrrc_modern v1.22.0** 进打包版
（C1 的阈值以 `MRRC_REMOTE_SESSION_TX_HEARTBEAT_S` 实现，默认 0 = 关，Hub 模式建议 3–5 s）。
注意：**进包 ≠ 默认开启** —— C1 默认是关的，需要实例侧显式打开。

**新增 C7：实例开通脚本**（与 C1–C6 不同，它在 `mrrc_hub/deploy/` 而非 `mrrc_modern`）：
`install_instance_tunnel.{sh,ps1}` 把“取回隧道客户端 + 校验哈希 + 装成常驻服务 +
（Windows）签实例证书并写环境变量” 收成一步。契约上它只依赖：出站网络、一个端口号、一个凭证。

## 11.4 Agent（Fleet Agent）组件

| 子模块 | 职责 | 约束 |
| --- | --- | --- |
| 凭证存储 | 私钥（DPAPI / Keychain / root-only 文件，预留 TPM） | 私钥不出主机（AD-H11） |
| 隧道客户端 | WSS + mTLS、多路复用、重连（退避 + jitter、多 Hub 地址） | 不自研拥塞控制 |
| 注册与心跳 | REGISTER、15 s HEARTBEAT | 不携带业务敏感内容 |
| 会话心跳中继 | TX 期间 500 ms 会话心跳 | 第 15 章机制载体 |
| 策略执行 | 版本化策略差量应用 | 认证失败转人工状态 |
| OTA 客户端 | 复用 `upgrade_core.py` 语义；OSS/CDN 下载 + 签名校验 | 不经数据面 ECS（NFR-H018） |
| 诊断上报 | 复用 support receiver 通道，鉴权升级为设备证书 | AD-H11、AD-H13 |

## 11.5 复用清单（避免重复建设）

| 既有资产 | 位置 | 复用方式 |
| --- | --- | --- |
| OTA 拉取/校验/状态编排 | `mrrc_modern/upgrade_core.py` | 直接复用为 Agent OTA 核心 |
| 发布清单与站点 | `website/downloads/latest.json`、`dev_tools/make_latest_json.py` | 扩展签名与灰度字段 |
| 诊断上报接收端 | `mrrc_modern/deploy_support_receiver.sh`、`tools/support_receiver/` | 复用部署形态（独立 unit/端口/存储/0600 凭据） |
| 诊断包脱敏 | `mrrc_modern/support_bundle.py`（含 `?token=` 正则） | 照搬到 Hub/Tunnel/nginx 日志层 |
| PTT 本地安全 | `mrrc_modern/SDD/15-ptt-safety-architecture.md` | 复用 + 新增一层 |
