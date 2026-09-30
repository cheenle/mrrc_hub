# 6. Use Case Model

## 6.1 Actor 定义

| Actor | 说明 |
|---|---|
| Instance Owner | 实例归属人：绑定实例、授权成员、配额、模式开关、吊销证书 |
| Operator | 远程控制者：控制台、CAT、PTT、TX/RX 音频、频谱操作（每实例最多 1 个） |
| Listener | 远程受限操作者：RX 音频、频谱/瀑布、状态查看、**频率/模式调谐**（AD-H08） |
| Fleet Admin | 平台运维：版本、在线状态、告警、经授权的限时诊断 |
| MRRC Fleet Agent | 客户内网进程：主动出站、携带实例上下文、执行动作 |
| MRRC_instance | `MRRC_modern` 本体：权威的电台状态与 PTT 安全释放 |

## 6.2 Use Cases

### UC-H01: 首次绑定（零接触开通）

| Field | Description |
|-------|-------------|
| Goal | 把一台客户内网实例归属到 Owner 并签发设备凭证 |
| Preconditions | 实例已安装并首次启动；Owner 有 Portal 账号 |
| Basic Flow | Agent 生成本地密钥对（私钥不出主机）→ 向控制面申请短时效高熵绑定码 → Owner 登录 Portal 扫码/输入并确认归属 → Registry 原子绑定 Owner 与 instance → 绑定码立即失效 → Device CA 对 Agent 公钥签发实例证书与 `instance_id` → Agent 轮询领取证书、信任链、Hub 地址列表与初始策略，加密落盘 |
| Exceptions | 绑定码过期/已消费 → 拒绝并审计；尝试次数超限 → 限流；Owner 取消 → 密钥对被丢弃 |
| Safety | 绑定码不写入长期日志；私钥不离开客户主机 |
| Postconditions | 实例持有唯一设备证书；Portal 显示实例已归属 |
| Refs | `SC-H2` `NFR-H011` `NFR-H012` `AD-H11` `UC-H08` |

### UC-H02: 日常上线（隧道建立与注册）

| Field | Description |
|-------|-------------|
| Goal | 实例在无人值守下接入 Hub 并保持可被路由 |
| Preconditions | 设备证书有效；出站 443 可用 |
| Basic Flow | Agent 依次尝试 Hub 地址列表，建立 WSS/mTLS 长连接 → 协商隧道协议版本与能力集合 → Tunnel Gateway 写入 `instance_id → tunnel_node_id / connection_id / last_seen`（带 TTL）→ Agent 发送 REGISTER（软件版本、电台型号、能力位、LAN 状态）→ 控制面标记在线并返回策略差量与 OTA 通知 → Agent 每 15 s 心跳（RTT、重连次数、活跃会话、上行健康度、租约状态） |
| Exceptions | 认证失败 → 不无限重试，转入需人工处理状态；主 Hub 失败 → 切备用 Hub；连续 3 次心跳失败 → 判离线（≤45 s） |
| Safety | 隧道与实例一对一绑定，禁止跨实例复用（`NFR-H022`） |
| Postconditions | Registry 中映射有效；实例可被 Access 路由 |
| Refs | `SC-H1` `NFR-H002` `NFR-H003` `NFR-H016` `AD-H01` `AD-H03` `UC-H07` |

### UC-H03: 远程接入 — Operator 获取租约并控制

| Field | Description |
|-------|-------------|
| Goal | 授权用户获得独占控制权并操作电台 |
| Preconditions | 用户有该实例 Operator 授权；实例在线 |
| Basic Flow | 用户登录 Portal 选择实例 → 申请 Operator → 控制面复核 ACL、在线状态与配额 → **原子获取租约**（`FREE → HELD`）→ Ticket 签发一次性短时效 launch code → 浏览器访问 `https://<instance-id>.mrrc.vlsc.net/?code=<opaque>` → Access 消费 code、复核权限与租约、设置 host-only 会话 Cookie、**立即重定向到不含 code 的干净 URL** → Access 按 Registry 找到归属 Tunnel Gateway 并转发 → Tunnel 在既有隧道上开虚拟流并携带签名角色上下文 → 建立控制台会话 → 客户端按 5–10 s 续租（TTL 20–30 s） |
| Exceptions | 租约已被占用 → 按实例策略排队，或降级为 Listener，**绝不签发第二个 Operator 凭证**；code 过期/重放 → 拒绝并审计 |
| Safety | `NFR-H020`：token 与 code 均不得进 URL 留存、Referer 或日志 |
| Postconditions | 用户持有 Operator 租约与只读或可写会话 |
| Refs | `SC-H3` `SC-H6` `NFR-H010` `NFR-H013` `NFR-H020` `AD-H04` `AD-H05` `AD-H07` `AD-H09` `UC-H06` |

### UC-H04: 远程接入 — Listener 加入（含调谐）

| Field | Description |
|-------|-------------|
| Goal | 在不占用 Operator 租约的前提下收听并调谐 |
| Preconditions | 用户有该实例 Listener 授权；实例在线 |
| Basic Flow | 同 UC-H03 的准入流程，但按 Listener 配额检查并发 → 建立会话 → 客户端连接 `/WSradio` `/WSspectrum` `/WSaudioRX`（**不连** `/WSaudioTX`）→ 频谱按 `LISTEN_SPECTRUM_DIVIDER=3` 降为 1/3 帧率 → 允许 `freq` / `vfo_a_freq` / `vfo_b_freq` / `mode` 与 `memRecall`（写频率+模式），**其余写操作一律拒绝**（服务端 gate，非 UI 隐藏） |
| Exceptions | 并发超配额 → 拒绝或排队；试图 PTT/TX/设备设置 → 服务端拒绝并记审计 |
| Safety | Listener 调谐与 Operator 调谐的并发仲裁见 `AD-H08`：不得让 Listener 的调谐写破坏 Operator 的会话一致性 |
| Postconditions | Listener 会话可听可看可调谐，无法发射 |
| Refs | `SC-H3` `NFR-H008` `AD-H08` `UC-H03` |

### UC-H05: Operator 断线 — PTT 本地释放（含半开连接）

| Field | Description |
|-------|-------------|
| Goal | 任何授权通道失效都不留下发射中的电台 |
| Preconditions | 用户正在 TX（或刚释放） |
| Basic Flow（EOF 型） | 浏览器关闭/进程退出/TCP RST → 实例侧 dead-man switch 立即强制 RX → Hub 因会话断开回收租约并清理虚拟流 |
| Basic Flow（半开型） | NAT 掉表/换网/静默丢弃 → **实例与应用层心跳不再到达，但 TCP 未断** → 隧道层判定心跳失效 → 主动关流 → 实例释放 PTT 并强制 RX |
| Exceptions | 客户端主动释放 → 仅 keying 的会话可释放（实例侧 key-owner 仲裁） |
| Safety | **不得依赖云端租约 TTL 释放 PTT**；七层（实际为 Layer 0 + Layer 1–8）本地机制保持最高优先级 |
| Postconditions | 电台回到 RX；租约被回收；事件入审计 |
| Refs | `SC-H4` `NFR-H006` `NFR-H019` `AD-H06` `R-H1` `I-H6`（详第 [15](15-ptt-safety-hub-mode.md) 章） |

### UC-H06: 租约冲突与回收

| Field | Description |
|-------|-------------|
| Goal | 在竞争下保持"每实例最多一个写者" |
| Preconditions | 已有有效租约或用户申请中 |
| Basic Flow | 租约状态机 `FREE → HELD → RELEASED / EXPIRED`；获取按 `instance_id` 原子竞争 → 冲突时默认排队（Owner 可配置自动降级为 Listener）→ 回收触发：用户主动释放、实例离线、管理员强制回收、续租失败 |
| Exceptions | 管理员强制回收 → 通知当前持有者并全量审计 |
| Safety | 租约回收不替代本地 PTT 释放（`AD-H06`） |
| Postconditions | 至多一个有效 Operator 租约 |
| Refs | `SC-H3` `AD-H05` `UC-H05` |

### UC-H10: 呼号注册与核验（实例与用户）

| Field | Description |
|-------|-------------|
| Goal | 以真实呼号建立租户身份：实例获得 `<呼号>.mrrc.vlsc.net`，用户以呼号作为账号标识 |
| Preconditions | 注册人持有该呼号；Portal 具备核验手段（呼号库比对 / 执照材料审核） |
| Basic Flow | 提交呼号 → **规范化**（去空格、大小写不敏感：`BG1SB` 与 `bg1sb` 视为同一呼号）→ 查重（同一呼号同一时刻只能有一个 Owner）→ **核验**（呼号库比对，或执照材料人工审核）→ 绑定 `(呼号, 账号)` → 分配实例标签与隧道端口（注册表一行）→ 实例侧 `install_instance_tunnel.sh <呼号> <端口>` 上线 → 入口生效 |
| Exceptions | 核验失败 → 拒绝并审计；呼号已被绑定 → 拒绝，或走申诉/转移流程，**绝不静默覆盖**；大小写变体 → 同一呼号；冒用被举报并核实 → 撤销绑定并停用入口 |
| Safety | 呼号是**公开**标识，入口存在性可被枚举（AD-H15 有意接受）。因此核验必须发生在**授予访问之前**，而不是事后追责 |
| Postconditions | 租户名 = 呼号；账号标识 = 呼号；审计记录了核验依据 |
| Refs | `AD-H15` `NFR-H028` `NFR-H029` `SC-H10` `UC-H01` `I-H9` |

### UC-H07: Tunnel Gateway 故障切换

| Field | Description |
|-------|-------------|
| Goal | 单节点故障后实例自动恢复可达 |
| Preconditions | 至少 2 个 Tunnel 节点；实例配置主/备用 Hub 地址 |
| Basic Flow | 节点故障 → 实例长连接断开 → Agent 指数退避 + jitter 重连其他节点 → 写入新归属映射（旧映射因 TTL 过期失效）→ 客户端重连并重建会话 |
| Exceptions | 活动 TCP/WS 会话**无法无损迁移** → 目标是快速重连与状态恢复，不承诺零中断 |
| Safety | 重连期间不得重复计费/重复授权；PTT 按 `UC-H05` 本地释放 |
| Postconditions | 实例恢复可达；P95 重连 ≤30 s |
| Refs | `NFR-H003` `NFR-H015` `AD-H01` `AD-H03` `UC-H02` |

### UC-H08: 证书轮换与吊销

| Field | Description |
|-------|-------------|
| Goal | 凭证生命周期可控（泄露或换机可止损） |
| Preconditions | Owner 已登录并完成 MFA |
| Basic Flow | 轮换：控制面下发轮换窗口 → Agent 生成新密钥对并申请签发 → 新证书生效后旧证书进入宽限期 → 宽限期结束吊销；吊销：Owner 在 Portal 主动吊销 → 隧道被切断 → 实例转需重新绑定状态 |
| Exceptions | 宽限期内新旧并存 → 只允许一个有效 RE/REGISTER 会话 |
| Safety | 吊销必须立即断连且不可被 Agent 绕过 |
| Postconditions | 旧凭证不再可用 |
| Refs | `NFR-H012` `AD-H11` `UC-H01` |

### UC-H09: OTA 灰度升级

| Field | Description |
|-------|-------------|
| Goal | 在不破坏在线运营的前提下推进版本 |
| Preconditions | 发布侧已产出签名包与清单 |
| Basic Flow | 控制面按灰度比例（5% → 25% → 100%）下发通知 → Agent 拉取清单（复用 `upgrade_core.py` 的版本比较与 `state.json` 编排）→ 从 OSS/CDN 下载签名包并校验 → 安装 → 回报状态（`ok` / `failed`） |
| Exceptions | 批次失败率 > 5% → 暂停灰度并回滚；实例正在 TX/会话中 → 延后升级 |
| Safety | 升级不得中断 PTT 安全释放路径；升级期间实例应拒绝新的 Operator 租约 |
| Postconditions | 实例版本可查、升级结果可审计 |
| Refs | `NFR-H018` `AD-H13` `R-H9` |
