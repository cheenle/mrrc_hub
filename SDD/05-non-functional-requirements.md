# 5. Non-Functional Requirements

> 数值来源：客户侧带宽与帧预算为 `mrrc_modern` v1.21.0 代码实测（见每行 Verification 与
> [`docs/2026-09-30-fleet-hub-design-review.md`](../docs/2026-09-30-fleet-hub-design-review.md) §3），
> 非账面估算。

## 5.1 Connectivity Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H001 | 客户侧零入站：实例只需**出站**连接（隧道口 **8989/tcp**，V0.2 port 修订），不需要公网 IP、端口映射或 UPnP。**用户侧另需能出站访问入口 9988/tcp** —— 这是两条不同的约束，别并成一条（见 R-H12） | 出站可达即在线 | Critical | 无公网 IP、UPnP 关闭的家宽环境完成 10 实例试点；用户侧至少覆盖一家公司/访客网络实测 |

## 5.2 Performance Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H004 | 新会话建立（Hub 控制路径，不含互联网 RTT） | P95 ≤ 2 s | High | 会话建立计时埋点 |
| NFR-H005 | Hub 引入的控制路径额外延迟（同地域） | P95 ≤ 50 ms | High | 端到端 RTT 对比（同地域直连 vs 经 Hub） | **（V0.4：该目标针对同地域直连路径；经海外 www 边缘的退化路径实测多一跳 0.4–0.6 s，仅用于只放行 80/443 的网络）**
| NFR-H007 | 单会话带宽预算 | 全控 ≈ 0.48 Mbps（RX Opus 64 kbps + 频谱 408 kbps）；Listener ≈ 0.20 Mbps | Critical | 代码实测：`opus_rx.py` `DEFAULT_BITRATE=64000`；`server.py` `/WSspectrum` 1701 B/帧 × 30 fps |
| NFR-H008 | 频谱帧预算 | 1701 B/帧（1 B 版本 + 850 B wf1 + 850 B wf2）、~30 fps、二进制 `send_bytes`（无 base64 膨胀）；Listener 按 `LISTEN_SPECTRUM_DIVIDER=3` 降为 1/3 帧率 | Critical | `server.py` `/WSspectrum` docstring 与 `LISTEN_SPECTRUM_DIVIDER` |
| NFR-H009 | 客户上行护栏 | 实例上行利用率告警线 60%，扩容/降级线 80% | High | 实例侧 `send_bytes` 计数上报（AD-H13） |
| NFR-H010 | 一次性 launch code | 有效期 ≤ 60 s，单次消费，消费即失效 | Critical | 重放测试 |
| NFR-H011 | 绑定码强度 | 有效期 ≤ 10 min，随机熵 ≥ 128 bit，尝试次数受限并审计 | Critical | 绑定流程安全测试 |

## 5.3 Availability & Recovery Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H002 | 实例离线识别 | ≤ 45 s（心跳 15 s，连续 3 次失败判离线） | High | 断网注入测试 |
| NFR-H003 | Tunnel 故障重连 | P95 ≤ 30 s（指数退避 + jitter + 多 Hub 地址） | High | 杀 Tunnel 节点测试 |
| NFR-H015 | Hub 远程接入月可用性 | ≥ 99.9%（不含客户网络/设备故障） | High | 月度 SLO 看板 |
| NFR-H016 | 隧道协议兼容窗口 | Hub 保留 N-2 客户端兼容；认证失败不无限重试，转入需人工处理状态 | High | 版本矩阵回归 |
| NFR-H017 | 容量设计余量 | 500 在线隧道 / 1000 活跃会话 / 5000 用户 WS；公网出带宽起步 200 Mbps，70% 预警、80% 扩容 | High | 压测报告（SC-H9） |
| NFR-H018 | OTA 包分发 | 经 OSS + CDN，不经数据面 ECS；签名校验，失败可暂停与回滚 | Medium | 灰度批次演练 |

## 5.4 Safety Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H006 | **PTT 释放（含半开连接）**：Operator 通道断开或 TX 期间心跳失效，实例必须在本地释放 PTT，不等待云端租约 TTL | **EOF 型 ≤ 1 s**（现状已满足）；**半开型 ≤ 1.5 s**（待实现，MVP 必需） | Critical | 两组注入：①关闭浏览器（EOF 型）②拔网线/切 Wi-Fi/静默丢弃（半开型）；完整矩阵见第 [15](15-ptt-safety-hub-mode.md) 章 §15.5 |
| NFR-H019 | TX 期间会话心跳 | TX 期间心跳间隔 **500 ms**；隧道层连续 **2 次**未达（≈1.0 s）主动关流；实例侧活性闸门阈值 **1.0 s**（与隧道层一致） | Critical | 心跳丢失与单包抖动注入（V3/V4/V7/V10） |

## 5.5 Security & Privacy Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H012 | 设备凭证 | 一实例一证，私钥不出客户主机；支持轮换与吊销；禁用 fleet 共享静态 token | Critical | 证书轮换/吊销演练 |
| NFR-H013 | Cookie 策略 | 实例子域会话 host-only（不设 `Domain=.mrrc.vlsc.net`）；**Hub 票证 Cookie 名不得与实例 `AUTH_COOKIE` 冲突**；远程模式下加 `Secure` | Critical | Cookie 隔离与命名检查 |
| NFR-H014 | 日志隐私 | 密码、私钥、完整 ticket、一次性 code、会话 token、音频内容均不得进入实例/Hub/Tunnel/nginx 日志 | Critical | 日志检索（SC-H6） |
| NFR-H020 | 令牌传输方式 | 会话 token 不得出现在 URL query、Referer 或浏览器历史中 | Critical | 静态检查 + 抓包 + 日志检索 |
| NFR-H021 | 传输安全 | 公网链路必须校验对端证书；**禁止 `proxy_ssl_verify off` 出现在生产配置**。实况分两跳：www 边缘对 hub 上游的信任源为**系统 CA**；**hub → 实例这一跳的信任源是 `/etc/mrrc-hub/trust-bundle.pem`（系统 CA + 各实例自签证书公钥）**，自签证书靠“钉住它”通过校验 | Critical | 配置审计 |
| NFR-H030 | 证书生命周期 | 入口证书必须是**浏览器信任的真证书**；续期无需人工干预，且**不得要求跨机同步信任材料**；到期前 30 天自动续，剩余 <14 天告警 | 证书链校验 + 到期告警演练 | 证书链校验 + 到期告警演练 |
| NFR-H022 | 三层一致性 | Access / Tunnel / 实例三层校验 `instance_id` / `session` / `role` 一致；隧道与实例一对一绑定 | Critical | 越权与错绑测试 |
| NFR-H023 | 运维权限 | Owner/Fleet Admin 强制 MFA；远程诊断默认关闭，Owner 授权后限时开启并全量审计；Fleet Admin 默认无权进入控制台或收听音频 | High | 权限矩阵测试 |
| NFR-H024 | 合规提示 | 首次启用 Operator 能力时提示用户确认执照与遥控台站合规；保留地区策略与紧急禁用入口 | Medium | UI 流程检查 |

## 5.6 Identity & Tenancy Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H028 | **呼号即身份**：注册实例与注册用户都必须提供真实呼号；呼号即账号标识符，大小写不敏感；同一呼号同一时刻只能绑定一个 Owner | 无呼号不得注册；重复绑定被拒 | Critical | 阶段 2 注册流程测试：伪呼号/重复呼号/大小写变体 |
| NFR-H029 | 呼号核验手段：注册时以呼号库比对或执照材料人工审核为准，并保留审计记录；冒用他人呼号的账号可被撤销 | 核验失败即拒绝 | High | 审核流程演练 + 撤销演练 |
| NFR-H031 | **实例证书生命周期**：每实例证书签给**它自己的入口名**；私钥**永不出实例主机**；只有公钥进信任包；信任包变更必须**原子替换 + nginx `-t` 通过后才 reload**，不得出现“换了一半”的中间态；因信任包丢失而回退到关校验是**禁止**的 | 信任包更新不中断在跑实例、不引入关校验回退 | High | 信任包替换演练（含 nginx -t 失败时的回滚） |
| NFR-H032 | **安装在无预装环境可完成**：实例侧只需出站网络，不得要求用户预先安装隧道客户端；若需下载二进制，**必须校验发布方的 SHA-256**，不符即拒绝使用而非降级；宁可不安装，也不能用来历不明的二进制 | 新机器到隧道在线无手工预装步骤 | High | 安装演练（干净机器 + 断网 + 哈希不符三种情况） |
| NFR-H033 | **文档的事实可追溯**：文档中的每个入口、端口、证书、行为都必须能指回一个可复现的取证动作（读配置 / 实测 / 读源码），不得凭设计意图措辞；无法取证时写“待核实” | 陈述与现网一致 | Medium | 文档站发布前复验清单 |

## 5.6 Maintainability Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H025 | 文档同步 | 行为变更必须同步 SDD 章节 + 第 14 章版本历史 + SDD README 版本号 | Medium | `sdd check` + 评审 |
| NFR-H026 | 复用优先 | 遥测/OTA 复用 `upgrade_core.py` 与 support receiver，不重复建设 | Medium | 设计评审 |
| NFR-H027 | 单位可替换性 | fuzzing/测试在硬件-free 边界 mock（隧道、Registry、Lease 均可用内存实现替换） | Medium | 单元测试覆盖 |
