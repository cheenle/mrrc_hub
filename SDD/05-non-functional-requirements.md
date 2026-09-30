# 5. Non-Functional Requirements

> 数值来源：客户侧带宽与帧预算为 `mrrc_modern` v1.21.0 代码实测（见每行 Verification 与
> [`docs/2026-09-30-fleet-hub-design-review.md`](../docs/2026-09-30-fleet-hub-design-review.md) §3），
> 非账面估算。

## 5.1 Performance Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H004 | 新会话建立（Hub 控制路径，不含互联网 RTT） | P95 ≤ 2 s | High | 会话建立计时埋点 |
| NFR-H005 | Hub 引入的控制路径额外延迟（同地域） | P95 ≤ 50 ms | High | 端到端 RTT 对比（同地域直连 vs 经 Hub） |
| NFR-H007 | 单会话带宽预算 | 全控 ≈ 0.48 Mbps（RX Opus 64 kbps + 频谱 408 kbps）；Listener ≈ 0.20 Mbps | Critical | 代码实测：`opus_rx.py` `DEFAULT_BITRATE=64000`；`server.py` `/WSspectrum` 1701 B/帧 × 30 fps |
| NFR-H008 | 频谱帧预算 | 1701 B/帧（1 B 版本 + 850 B wf1 + 850 B wf2）、~30 fps、二进制 `send_bytes`（无 base64 膨胀）；Listener 按 `LISTEN_SPECTRUM_DIVIDER=3` 降为 1/3 帧率 | Critical | `server.py` `/WSspectrum` docstring 与 `LISTEN_SPECTRUM_DIVIDER` |
| NFR-H009 | 客户上行护栏 | 实例上行利用率告警线 60%，扩容/降级线 80% | High | 实例侧 `send_bytes` 计数上报（AD-H13） |
| NFR-H010 | 一次性 launch code | 有效期 ≤ 60 s，单次消费，消费即失效 | Critical | 重放测试 |
| NFR-H011 | 绑定码强度 | 有效期 ≤ 10 min，随机熵 ≥ 128 bit，尝试次数受限并审计 | Critical | 绑定流程安全测试 |

## 5.2 Availability & Recovery Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H002 | 实例离线识别 | ≤ 45 s（心跳 15 s，连续 3 次失败判离线） | High | 断网注入测试 |
| NFR-H003 | Tunnel 故障重连 | P95 ≤ 30 s（指数退避 + jitter + 多 Hub 地址） | High | 杀 Tunnel 节点测试 |
| NFR-H015 | Hub 远程接入月可用性 | ≥ 99.9%（不含客户网络/设备故障） | High | 月度 SLO 看板 |
| NFR-H016 | 隧道协议兼容窗口 | Hub 保留 N-2 客户端兼容；认证失败不无限重试，转入需人工处理状态 | High | 版本矩阵回归 |
| NFR-H017 | 容量设计余量 | 500 在线隧道 / 1000 活跃会话 / 5000 用户 WS；公网出带宽起步 200 Mbps，70% 预警、80% 扩容 | High | 压测报告（SC-H9） |
| NFR-H018 | OTA 包分发 | 经 OSS + CDN，不经数据面 ECS；签名校验，失败可暂停与回滚 | Medium | 灰度批次演练 |

## 5.3 Safety Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H006 | **PTT 释放（含半开连接）**：Operator 通道断开或 TX 期间心跳失效，实例必须在本地释放 PTT，不等待云端租约 TTL | **EOF 型 ≤ 1 s**（现状已满足）；**半开型 ≤ 1.5 s**（待实现，MVP 必需） | Critical | 两组注入：①关闭浏览器（EOF 型）②拔网线/切 Wi-Fi/静默丢弃（半开型）；完整矩阵见第 [15](15-ptt-safety-hub-mode.md) 章 §15.5 |
| NFR-H019 | TX 期间会话心跳 | TX 期间心跳间隔 **500 ms**；隧道层连续 **2 次**未达（≈1.0 s）主动关流；实例侧活性闸门阈值 **1.0 s**（与隧道层一致） | Critical | 心跳丢失与单包抖动注入（V3/V4/V7/V10） |

## 5.4 Security & Privacy Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H012 | 设备凭证 | 一实例一证，私钥不出客户主机；支持轮换与吊销；禁用 fleet 共享静态 token | Critical | 证书轮换/吊销演练 |
| NFR-H013 | Cookie 策略 | 实例子域会话 host-only（不设 `Domain=.mrrc.vlsc.net`）；**Hub 票证 Cookie 名不得与实例 `AUTH_COOKIE` 冲突**；远程模式下加 `Secure` | Critical | Cookie 隔离与命名检查 |
| NFR-H014 | 日志隐私 | 密码、私钥、完整 ticket、一次性 code、会话 token、音频内容均不得进入实例/Hub/Tunnel/nginx 日志 | Critical | 日志检索（SC-H6） |
| NFR-H020 | 令牌传输方式 | 会话 token 不得出现在 URL query、Referer 或浏览器历史中 | Critical | 静态检查 + 抓包 + 日志检索 |
| NFR-H021 | 传输安全 | 公网链路必须校验对端证书；**禁止 `proxy_ssl_verify off` 出现在生产配置** | Critical | 配置审计 |
| NFR-H022 | 三层一致性 | Access / Tunnel / 实例三层校验 `instance_id` / `session` / `role` 一致；隧道与实例一对一绑定 | Critical | 越权与错绑测试 |
| NFR-H023 | 运维权限 | Owner/Fleet Admin 强制 MFA；远程诊断默认关闭，Owner 授权后限时开启并全量审计；Fleet Admin 默认无权进入控制台或收听音频 | High | 权限矩阵测试 |
| NFR-H024 | 合规提示 | 首次启用 Operator 能力时提示用户确认执照与遥控台站合规；保留地区策略与紧急禁用入口 | Medium | UI 流程检查 |

## 5.5 Maintainability Requirements

| ID | Requirement | Target | Priority | Verification |
| --- | --- | --- | --- | --- |
| NFR-H025 | 文档同步 | 行为变更必须同步 SDD 章节 + 第 14 章版本历史 + SDD README 版本号 | Medium | `sdd check` + 评审 |
| NFR-H026 | 复用优先 | 遥测/OTA 复用 `upgrade_core.py` 与 support receiver，不重复建设 | Medium | 设计评审 |
| NFR-H027 | 单位可替换性 | fuzzing/测试在硬件-free 边界 mock（隧道、Registry、Lease 均可用内存实现替换） | Medium | 单元测试覆盖 |
