# 3. Project Definition

## 3.1 建设目标

- **公网可达**：只要求客户网络允许出站 HTTPS/WSS，即可访问实例（SC-H1）。
- **零接触开通**：安装后扫码或输入绑定码，完成实例归属与设备凭证签发（SC-H2）。
- **统一入口**：不暴露 200 个公网端口，不要求用户记 IP/端口。
- **多租户隔离**：A 用户不能发现或访问未授权实例；A 实例流量不能被路由到 B 实例（SC-H5）。
- **单写多读**：Operator 独占控制权，Listener 并发受限操作（SC-H3）。
- **可运营**：可观察在线状态、版本、隧道健康、会话、流量、租约、PTT 和升级状态（SC-H7）。
- **可演进**：MVP 可使用成熟隧道，目标态无缝迁移至内置 Fleet Agent（AD-H04）。

## 3.2 非目标

- 不重构 MRRC 的 5 个 WebSocket 业务通道（`/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` `/WSatr1000`）。
- 不把音频迁移到 WebRTC/QUIC（本期）。
- 不强制云端录音；QSO 录音默认保留在客户本地。
- 不做全球多地域部署；先做单地域双可用区。
- 不以 RX Relay/Fan-out 为上线前置条件（AD-H12）。

## 3.3 范围边界

| 属于本仓 | 属于 `mrrc_modern`（引用而非实现） |
|---|---|
| Portal、IAM/ACL、Registry、Ticket、Lease、证书签发/轮换 | CAT/CI-V 编解码、电台后端、模型档案 |
| Access Gateway、Tunnel Gateway、可选 RX Relay | 音频采集/Opus 编解码/回放、频谱采集 |
| 隧道协议与 Fleet Agent（目标态） | **PTT 本地安全释放（8 层 + Layer 0）** |
| Hub 侧可观测性、OTA 分发与灰度、审计 | 实例侧 UI、`/listen` 角色 gate、实例密码 |

## 3.4 Success Criteria

| ID | Criterion | Verification |
|---|---|---|
| SC-H1 | 客户侧仅需出站 TCP 443（或产品明确的隧道端口），无需公网 IP、端口映射与 UPnP | 在无公网 IP、UPnP 关闭的家宽环境完成 10 实例试点 |
| SC-H2 | 实例绑定零接触：绑定码高熵短时效单次使用，Owner 确认即完成归属与设备证书签发 | 绑定码重放被拒；未授权 Owner 无法完成绑定 |
| SC-H3 | 每实例同时最多 1 个有效 Operator；第二个写请求只能排队、降级或拒绝 | 并发申请租约测试：无第二个 Operator 凭证签发 |
| SC-H4 | **PTT 不粘键（Hub 语义）**：EOF 型与半开型断线都在 NFR-H006 时限内释放，不依赖云端租约 TTL | TX 中执行「关闭浏览器」与「拔网线/切 Wi-Fi/静默丢弃」两组测试 |
| SC-H5 | 未授权用户无法发现或访问实例；实例间不存在 Cookie、会话或路由串扰 | 跨实例越权测试；子域 Cookie 隔离检查 |
| SC-H6 | **会话凭证不进入 URL、不进入任何代理或实例访问日志** | 抓取 Hub/Tunnel/nginx/实例访问日志，检索 `token=`/`code=` 无明文 |
| SC-H7 | 可运营：在线状态、版本、隧道健康、会话、租约、PTT 事件、升级状态可查询与告警 | 运营看板 + 告警演练 |
| SC-H8 | 现状不回退：LAN 直连、实例自有密码、B2 IPv6 直连与 `/listen` 公开入口不受 Hub 模式影响 | 启用 Hub 前后逐项回归 |
| SC-H9 | 规模达标：500 在线隧道 / 1000 活跃会话 / 5000 用户 WS 压测满足 NFR 与扩容阈值 | 压测报告对照 NFR-H017 |

## 3.5 MVP 前必修（Release Gate）

以下四项**不是阶段 2 优化项，而是 MVP 成立的前提**，未决不开工：

| # | 必修项 | 关联 |
|---|---|---|
| G1 | Hub 场景下的 PTT 半开释放机制定稿 | AD-H06、第 15 章、I-H6 |
| G2 | 令牌传递方式改造（不再进 URL），并完成 Hub/Tunnel/nginx 日志脱敏 | AD-H07 |
| G3 | Listener 语义与调谐并发仲裁定稿 | AD-H08 |
| G4 | 同 origin 双会话 Cookie 命名与实例会话时长策略 | AD-H09 |
