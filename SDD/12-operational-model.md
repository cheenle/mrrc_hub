# 12. Operational Model

## 12.1 部署拓扑（单地域双可用区起步）

| 资源 | 起步规格 | 说明 |
| --- | --- | --- |
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
| --- | --- | --- |
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
| --- | ---: | --- |
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
| --- | --- |
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
| --- | --- |
| 实例显示离线但客户说在线 | 心跳是否到达、证书是否过期、归属映射是否过期、出站 443 是否被拦 |
| 用户能登录但控制台黑屏 | 5 个 WS 端点中哪个被拒绝（4001 未授权 / 4003 角色拒绝）；是否 Listener 访问了 `/WSaudioTX` |
| 令牌出现在日志 | **回归缺陷**（AD-H07/SC-H6）：检查 `HUB_LOG_REDACT`、nginx log_format、实例 uvicorn 日志 |
| 音频卡顿 | 上行利用率是否 > 60%；按 AD-H14 先降瀑布帧率；查看 Listener 并发是否超过 AD-H12 门槛 |
| PTT 未释放 | **安全事件**：区分 EOF 型 / 半开型（第 15 章 §15.4），核对心跳参数与 `MRRC_PTT_MAX_TX_SECONDS` |
| 升级后行为没变 | 核对清单版本、包 SHA、实例实际运行版本（沿用 `upgrade_core.py` 的 `state.json` 可证明性） |

## 12.8 实况记录（as-built，2026-10-02 / V0.21）

> 机器/进程/文件/端口/cron 一级的物理视图见
> [`../docs/physical-architecture-2026-10-02.svg`](../docs/physical-architecture-2026-10-02.svg)
> （同目录 PNG 为渲染件）；本节与其一致，冲突时以现场为准并回改两处。
> 图按 V0.21 记录重绘；**新主机上的逐项现场读数尚未全部复测**，本节标 2026-10-01 的数字仍是旧机读数。

本节记录**实际部署的事实**，与前面各节的"设计意图"区分；两者不一致时以本节为准并回改设计。

### 主机

| 角色 | 位置 | 说明 |
| ------ | ------ | ------ |
| Hub（含站点与门户） | 香港 VPS `hub.vlsc.net`（203.25.119.168，Ubuntu 26.04） | nginx（`mrrc-instances` 通配 vhost 承载实例入口 **443**；`mrrc-portal-mrrc` 把门户挂在 `portal.mrrc.vlsc.net` 的**根**；`vlsc.net` 承载站点与下载）、frps 0.71.0（控制口 8989，`proxyBindAddr=127.0.0.1`）、`mrrc-portal.service`（呼号注册，仅回环 8890）、`/etc/mrrc-hub/trust-bundle.pem`（系统 CA + 逐实例公钥）。**一台机器同时承担原先 Hub 与 Edge 两个角色**（V0.21） |
| ~~Edge~~ | —（已取消） | 海外边缘 `/mrrc_modern/<呼号大写>/` 反代**随 V0.21 删除**，职责由上面那台机器的 443 直接承担 |
| Instance | 实例归属人自己的机器（macOS / Linux / Windows） | 常驻隧道（launchd / systemd / 计划任务）；MRRC 服务是否常驻取决于是打包版还是源码运行（见下） |

### 入口（当前）

- `https://<呼号>.mrrc.vlsc.net/` —— **唯一的入口**：443、通配真证书、浏览器零警告。
  标签即裸呼号（`bg1sb`），不再带产品后缀；`:9988` 与 `:8899` 两个监听已取消（V0.21）。
- 已取消：原先的 `:8899`「第二 TLS 入口」与 `www.vlsc.net/mrrc_modern/<呼号大写>/` 海外边缘反代
  —— 两者的取消原因与教训见 `08-architecture-decisions.md` 卷首的 **V0.21** 一节
  （该节未编号；本仓没有 AD-H21）与下方「排障增补」
- 注册表 `/etc/mrrc-hub/instances.tsv` —— 三列：`<标签> <回环端口> <上游 TLS 名>`。
  加实例 = 一行 + 重跑 `gen_hub_routes.py`（自 V0.17 起由 30 s 的 root timer 自动做，见 §12.9）。
  **行数未取证，两处记录冲突**：本节 2026-10-01 的机上读数是"仅一行 `bg1sb 18802 radio.vlsc.net`"，
  而 `14-version-history.md` V0.21 记的是"已有两条记录已迁移，端口不变"；那两条的标签没有入档，
  机上读数又早于搬迁 ⇒ 两边都缺证据，此处不臆造呼号。
  **第三列是逐实例证书校验的落点**（见下方「实例证书链」）；`bg1sb` 目前仍指向上游旧证书名，
  尚未迁到它自己的 `<标签>.mrrc.vlsc.net` —— 迁移机制已就位、未施用。
  **标签规则**：主产品用裸呼号（`bg1sb`），附加产品加产品后缀（`bg1sb-legacy`）—— 见 `07-subject-area-model.md` §7.x.1
- `https://portal.mrrc.vlsc.net/` —— **呼号自助注册**（面向公众，另一套 vhost，
  与实例入口同证书）。运维审批台在 `/admin`。详见 §12.9。
  门户与站点、实例入口**同处一台机器**（V0.21，2026-10-02 迁至香港 `hub.vlsc.net`）；门户挂在该名字的根；

### 证书（NFR-H030 的落地）

- 签发：hub 上 `mrrc-hub-cert.sh`，DNS-01，覆盖 `*.mrrc.vlsc.net` 与 `mrrc.vlsc.net`
- 验证方式：certbot `manual` 插件 + **自建 hook** `aliyun-acme-dns-hook.py`（纯标准库自算阿里云 RPC 签名，直接调 DNS API）。**刻意不用 `certbot-dns-aliyun`**：第三方、年久失修，本机 Python 版本已超前
- 凭证：`/root/.secrets/aliyun.ini`（0600）。存在 ⇒ 真证书；不存在 ⇒ 回退自签通配（脚本自动切换）
- 续期：root crontab 每天 8:00 跑 `mrrc-hub-cert.sh`，剩余 <30 天自动续；日志 `/var/log/mrrc-hub-cert.log`；退出码 0/1/2（<14 天为告警）
- 安装：`mrrc-hub-cert-hook.sh` 拷贝证书到 `/etc/mrrc-hub/tls/` 并 reload nginx
- **www 边缘不再需要同步信任锚**（存史）：上游校验信任源是系统 CA。此前钉自签证书的做法咬过两次（换证书未同步 ⇒ 立即 502），已废弃。**V0.21 把海外边缘那条反代路径整体删除，这一跳今天已不存在** —— 本条已无对象，只留作教训记录

### 实例证书链（一机一证，2026-10-01 就位于旧 hub；下表读数为当日所取，V0.21 搬迁后未复测）

通配证书解决的是**入口**；另有一条链解决**hub → 实例**这一跳的身份。

| 环节 | 实况 |
| ------ | ------ |
| 签发 | `deploy/make_instance_cert.sh <标签>`：自签证书，**签给实例自己的入口名**（`<标签>.mrrc.vlsc.net`），默认 3650 天，幂等（CN 匹配则不重签，`FORCE=1` 强制） |
| 交付 | 实例侧设 `MRRC_SSL_CERT` / `MRRC_SSL_KEY`；**私钥永不外传**，只有公钥进 |
| 钉住 | 公钥写入 `/etc/mrrc-hub/trust-bundle.pem`（系统 CA + 各实例证书）。现网 121 个证书块（2026-10-01 在旧 hub 上所取，搬迁后未复测） |
| 校验 | nginx `proxy_ssl_name $mrrc_tls_name` + `proxy_ssl_trusted_certificate …/trust-bundle.pem`，**校验始终开着**；自签证书靠"钉住它"通过，而不是靠关掉 verification |
| 映射 | `$mrrc_tls_name` 由 `gen_hub_routes.py` 从注册表第三列生成；未指定时回落 `radio.vlsc.net`（兼容既有实例） |

**为什么自签而不是给每台实例发真证书**：租户没有自己的域名，入口名在 `*.mrrc.vlsc.net` 下，
而通配证书的私钥不可能下发给每个租户。自签 + 逐实例钉住能得到同一个安全属性（名字绑定的
端到端校验），且不引入新的 CA 依赖。

> 现网 `bg1sb` 仍在用 `radio.vlsc.net` 那张旧证书（注册表第三列未改）—— **能力已到位，迁移未做**。
> 这条同样是 2026-10-01 在旧 hub 上的读数，V0.21 搬迁后**未复测**（未取证）。
> 写文档时不要把"机制存在"写成"已在跑"。

### 实例开通链（安装器，2026-10-01 就位）

`deploy/install_instance_tunnel.sh`（macOS / Linux）与 `.ps1`（Windows）把开通变成一步：

| 环节 | 实况 |
| ------ | ------ |
| frpc 来源（按优先级） | ① 安装包内嵌副本（与脚本同级或 `.frpc/`）→ ② 系统 `PATH` → ③ 从 frp 官方 release 下载**并校验 SHA-256**，不符即拒绝使用 |
| 版本对齐 | `MRRC_FRP_VERSION` 默认 `0.71.0`，**与 hub 上的 frps 对齐（pin 死）** —— 客户端比服务端新可能握手失败 |
| 缓存 | `~/.local/share/mrrc-fleet`（`MRRC_FRP_DIR` 可改） |
| 常驻 | macOS = LaunchAgent + `KeepAlive`；Linux = systemd user unit（**登出后仍活**）；Windows = 计划任务 |
| 载荷构建 | `deploy/fetch_installer_payload.sh` 逐个校验哈希；**openssl 的 URL/哈希不硬编码**，从 lock 读，缺条目就跳过 —— *宁可不打包，也不把来路不明的二进制塞进安装包* |

**现阶段的边界**：安装器仍是**仓内脚本**，没有公开发布的安装包下载地址
（已试 `www.vlsc.net/mrrc_hub/install.sh` 等路径均 404）。用户今天仍需先拿到仓库。
安装包分发是下一步。

### 实例侧运行（重要运维事实）

frpc 隧道是 **常驻服务**（macOS `com.mrrc.fleet-tunnel.<呼号>`，Linux systemd user unit），重启自动恢复。
**MRRC 服务本身取决于跑的是哪个版本**：

- **打包版**：mrrc_modern 的 **feat/hub 分支** CHANGELOG 有 v1.22.0/v1.23.0（含 Hub 前置能力
  C1–C6，见第 11 章 §11.3），但**未合并进 main、无 tag**；Stable 渠道与产品站仍 v1.21.0。
  **运营待确认**：现网 bg1sb 实例跑在哪个 ref —— 它决定 as-built 链路是否含 C1/C2。
  V0.15 的"v1.22.0 及以后已带入安装包"叙述缺分支限定，V0.16 订正。
- **源码运行**：仍非常驻，重启后要手动起：

```bash
cd mrrc_modern
while IFS='=' read -r k v; do case "$k" in ''|\#*) continue;; esac; export "$k=$v"; done \
    < "$HOME/Library/Application Support/MRRC-Modern/mrrc_modern.env"
nohup venv/bin/python server.py > /tmp/mrrc-src/server.log 2>&1 &
```

用 `read` 循环而不是 `source`：env 文件含 `USB Audio Device` 这类带空格的值，`source` 会把它当命令执行。

### 已知退化（有意接受，见 ch13）

- **登录限流在隧道路径下退化为全局桶**：所有登录共享 `::ffff:127.0.0.1`（5 次失败 / 300 秒）。修法：边缘 `limit_req` 或实例信任 `X-Forwarded-For`（随下次发版）。用户已明确暂缓
- **实例存在性可枚举**：I-H9 已结案接受（呼号是公开信息）；防御重心前移到"授予访问之前核验呼号"（UC-H10）

### 排障增补

| 现象 | 先查什么 |
| ------ | ---------- |
| 边缘 502 而直连正常 | www 的上游校验信任源是否被改回钉证书（应为系统 CA）；hub 证书是否刚换（现已无需同步） |
| **边缘路径间歇性无响应**（2026-10-01，2026-10-02 定根因；该路径已随 V0.21 删除，本条存史） | 6 次请求 3 次 20 s 无响应，当时只定到 `www → hub:9988` 这一跳、猜是云厂商入方向限流。**真因**：边缘 nginx 那两处指向 hub 的 `proxy_pass` 写的是**裸主机名**（无 `resolver` ⇒ 启动时解析一次），而 hub 已加 AAAA、边缘的 `getaddrinfo` 又按 RFC6724 把 IPv6 排前 ⇒ nginx 选了 hub 的 IPv6，而**该地址当时不可达**（实测 0/4 超时，同机 v4 4/4 通；边缘自身 v6 正常，google 0.1 s）。**修法**：两处 `proxy_pass` 钉为 hub 的 IPv4 `8.160.161.80:9988` 并 reload —— 复测 `/mrrc_portal/` **8/8 200**（修前 3/6 挂死），实例入口 4/4 302。**复现判据**：`getent ahosts https://portal.mrrc.vlsc.net` 首行是 v6 就说明任何一次 reload 都会踩中。**待办**：hub 的 IPv6 入站仍不可达（阿里云安全组/IPv6 公网带宽，见 V0.19），且 hub 上 `net.ipv6.conf.eth0.accept_ra=0` ⇒ RA 派生的地址与默认路由约 2.5 h 后过期不续（要设 `accept_ra=2` 并持久化）；v6 端到端验通后可改成 upstream 双地址（v6 优先 + 连接超时 3 s 退 v4） |
| 证书签发失败 | `/var/log/letsencrypt/letsencrypt.log`；hook 的 phase 判定依据环境变量（`CERTBOT_VALIDATION`=auth，`CERTBOT_AUTH_OUTPUT`=cleanup），**certbot 不给 hook 传参数** |
| 记录存在但 CA 看不见 | hook 已轮询 DoH 等公共解析器可见；仍失败则查 `_acme-challenge` 下是否有重复 TXT |
| `curl -sI .../login` 得到 405 | **不是故障**。`-I` 发 HEAD，而登录页只接受 GET。用 `curl -s -o /dev/null -w '%{http_code}'` 拿状态码 |

### 12.8.1 第二产品 `mrrc` 的接入现状（2026-09-30）

除主产品 `mrrc_modern` 外，站点侧产品 `mrrc`（Tornado 应用，默认端口 **8877**，`auth = FILE`）
也已具备接入条件，按标签规则以**附加产品**形式出现（如 `bg1sb-legacy`，见 §7.x.1）：

| 能力 | 状态 |
| ------ | ------ |
| 子域根路径入口 | **开箱即用** —— 无需改造；其认证走会话（无 URL 令牌），故 fleet 评审的 P0-2 对它不适用 |
| 路径前缀能力 | **已实现**（`mrrc` 分支 `feat/hub`）：`base_path.py` + `[SERVER] base_path`，**默认空 = 行为与改造前完全一致**；含 **Cookie path 限定**（路径入口下同 origin 多产品不再互踩会话，即 P0-3 在该产品上的落点）、HTML 8 处 / `fetch` 3 处 / WebSocket 10 处 / `sw.js` 预缓存的前缀化。守卫：`dev_tools/test_path_prefix.py` |
| 会话遥测 | **已实现**：`GET /api/session_metrics` + `[SERVER] metrics_interval_s`（默认 60s 打印一行；0 = 关闭）；连接数直读既有 `*Clients` 列表，**不侵入 WS 生命周期** |
| PTT 安全 | **已具备三层，无需新增**：① 活性闸门（连续未收帧 ≈5s 即收回，`[CTRL] tx_liveness_s` 可配，默认即原行为）② TOT 硬上限（`[CTRL] ptt_tot_seconds`，默认 120s）③ 释放失败每 2s 重试 |

**尚未上线**：注册表条目、实例侧隧道、以及 www 的产品段（形如 `/mrrc_legacy/<呼号>/`）。
前置条件是**一个能独立运行该产品的站点** —— 它要占用电台/音频/串口，不能与主产品同机并行，
因此上线验证需独立硬件或经同意的停机窗口。

改造记录与逐步计划：`../../mrrc/docs/current/design/hub-parity-plan.md`。

## 12.9 Portal 自助（UC-H10 的落地）

| 项 | 实况 |
| ---- | ------ |
| 代码 | `portal/`（零第三方依赖，标准库 HTTP；与 HTTP 层解耦便于测试） |
| 数据 | `/etc/mrrc-hub/portal.json`（申请/授予 + 追加式审计，原子写） |
| 注册表 | 与 hub 同一份 `/etc/mrrc-hub/instances.tsv`（Portal 只追加一行） |
| 呼号库（权威） | `/var/lib/mrrc-hub/portal/clublog_users.json` —— **Club Log** 全库（273,047 条），与站内留言版 `www.vlsc.net/feedback` **同源**；hub 每天 04:30 从 www 拉取（`mrrc-portal-sync-clublog.sh`，晚于 www 的 03:00 刷新） |
| 呼号库（自建） | `/etc/mrrc-hub/callsigns.txt`（一行一个）—— 用于权威库暂未收录的新执照 |
| 核验链 | `ClubLogVerifier → CallsignListVerifier → ManualVerifier`（能给出**确定结论**的依据先问，人工始终兜底） |
| 运维令牌 | `/etc/mrrc-hub/portal.token`（0600），常数时间比较 |
| 监听 | **仅 127.0.0.1**（管理面）。对外自助需经 nginx 暴露并在那层加限流 |
| 测试 | `python3 tests/test_portal.py` |
| 入口 | `https://portal.mrrc.vlsc.net/`（通配证书已覆盖；精确 server_name 压过通配 vhost） |
| **主机** | **与 hub 同一台机器**：香港 VPS `hub.vlsc.net`（203.25.119.168），门户挂在该名字的**根**（见 §12.8 主机表）。V0.20 把它迁到阿里云 `47.80.243.9` 的那次拆分只存续了几个小时，**已被 V0.21 取代**；那台机器不再承载门户（其后续处置**未取证**） |
| 运行方式 | systemd `mrrc-portal.service`（`User=mrrcportal`、`NoNewPrivileges`、`PrivateTmp`、`Restart=on-failure`） |
| 自维护 | **跨机同步已随 V0.21 失去对象**：V0.20 那条 `mrrc-portal-sync.timer`（每日 08:30 从 hub 拉通配证书 + 呼号库）不再需要 —— 证书与呼号库现在就在本机同一批目录（存史）。**仍在跑的**是每天 04:30 的 `mrrc-portal-sync-clublog.sh`：拉 `clublog_users.json`（来源 www 侧，V0.21 后即本机），**规模门 ≥10 万条**，换库后重启 portal |
| ~~**仍耦合在 hub**~~ | **V0.21 后三条耦合都已消失**（同一台机器、同一批目录）：`grant` 写的注册表就是入口 nginx 读的那一份，30 s timer 直接接手重生成；`/enroll` 落的实例证书就在逐实例校验要读的 `instance-certs/` 里；边缘的 `/etc/nginx/mrrc-hub-trust.pem` 随反代路径一起删除，**已无归属**。这三条正是"合并值得一做"的理由，保留为记录 |
| 限流 | `/apply` 上 `limit_req zone=mrrc_portal_apply burst=5 nodelay`（10 r/m/来源）。**这里能用真实客户端 IP** —— 与被隧道合并来源的实例侧不同 |

**要记住的一条**：`grant` 只写注册表并打印实例侧命令，**路由与信任包的重生成自 V0.17 起是自动的** ——
root 的 `mrrc-hub-routes.timer` 每 30 s 触发一次 `mrrc-hub-routes.sh`（单元在 `deploy/systemd/`，
脚本在 `deploy/mrrc-hub-routes.sh`）：哈希 map 与信任包 → `gen_hub_routes.py` → 再哈希，
**只有生成物真的变了**才 `nginx -t` + `systemctl reload nginx`（`nginx -t` 不过就保持运行中的配置不动
并报错退出）。**仍需人工的只有运维那一步**：在 `/admin` 里核验并批准。Portal 服务本身没有
reload nginx 的权限，这是有意的分工（接收公网输入的服务不该持有它）。
**实测落差（2026-10-03，已修复）**：上面这段描述的是**设计**，而现网直到 2026-10-03 才真的成立：
那台 hub 上只装了 `.service`，包装脚本与 timer 都缺 ⇒ 单元指向不存在的脚本、每次 `203/EXEC` ⇒ **路由自 2026-10-02 01:07 起从未重生成**，新实例全部 404（而 frps、证书、注册表都已就绪）。
补齐包装脚本 + timer 后实测：入口 404 → 302，邻居 `bg1sb`/`bg9aaa` 不受影响，
常态每 ~35 s 输出 `nothing changed; not reloading`。验收方式：`systemctl is-enabled mrrc-hub-routes.timer`
应为 `enabled`，且 `/usr/local/sbin/mrrc-hub-routes.sh` 的 sha256 应与仓库 `deploy/mrrc-hub-routes.sh` 一致。
**文案滞后已修**：`portal/app.py` 的 `grant()` 对 `mrrc_modern` 的 `next_step` 原写"点「刷新状态」即自动完成"；客户侧 v1.25.0 起应用自己轮询完成接入，文案已改为"无需操作"。

**核验为何必须在授予之前**：呼号是公开标识、入口可枚举（I-H9 接受），
所以防线只能放在"核验通过才给访问"，不能放在"别人猜不到"。完整论证见
`../portal/README.md` 与 `../portal/callsign.py`。

### 12.9.1 Portal 上线的端到端验收（2026-10-01）

| 项 | 实测 |
| ---- | ------ |
| 入口与证书 | `GET https://portal.mrrc.vlsc.net/` → 200，**不带 `-k` 亦通过**（通配证书覆盖） |
| 自助申请（库外呼号） | `POST /apply` `bg1test` → `applied`，理由"呼号库中未收录，转人工核验" |
| 自动核验（库内呼号） | `POST /apply` `bg1sb` → `verified`，"命中呼号库" |
| 未核验不得授予 | 无令牌 `POST /grant` → **403**；状态未到 `verified` 亦拒绝（代码硬前置） |
| 限流 | 14 连击 → `200×4` 后持续 **429**（按来源 IP，真实生效） |
| **申请令牌交回申请方（V0.18）** | 公网 `POST /apply` `bg1prb` → 应答含 32 字符 `request_token`；`POST /status` 用它 → `200 applied`（未批准时 label/port/secret 全空）；错令牌 → **403**。客户端据此才能自动等到批准 |
| 既有服务未受影响 | `bg1sb` 实例入口 401 ✓、www 边缘 401 ✓、未知名字 404 unknown instance ✓ |

运维动作两种用法：脚本/curl 用请求头 `X-Portal-Token`；浏览器用表单里的同名字段
（**令牌走请求体，不进 URL** —— URL 会进访问日志与浏览器历史）。
验收当时授予之后仍需 root 手工执行 `gen_hub_routes.py` + `nginx reload`；**自 V0.17 起这一步由 30 s 的
root timer 自动完成**（有意分工，见 §12.9）。

### 12.9.2 核验依据：与留言版同源（2026-10-01）

站内留言版（`www.vlsc.net/feedback`，其代码在 `/home/cheenle/feedback/`）早已解决"呼号有效性"：
`callsign.py` 做归一化与基准呼号格式校验，判定则查 **Club Log 呼号库**（27 万条，每日从
clublog.org 刷新，与 RumLogNG 同源）。Portal **直接采用同一套规则与同一份数据**，理由是：
两个入口若对同一呼号给出不同结论，比只有一个入口更糟。

采用的规则（逐条对齐留言版）：

| 项 | 规则 |
| ---- | ------ |
| 格式 | `^[0-9]?[A-Z]{1,2}[0-9][A-Z]{1,3}$`（可选 1 位数字前缀 + 1-2 字母 + 分区数字 + 1-3 字母） |
| 便携/前缀 | **拒绝** `BG1SB/P`、`4X/BG1SB` 等 —— 注册的是身份，便携是操作状态；且标签要当 DNS 名用 |
| 基准呼号提取 | `4X/BG1SB`→`BG1SB`、`BG1SB/P`→`BG1SB`、`1A0C_14`→`1A0C`、`SOS`→'' |
| 判定语义 | 命中 = 已核验；**未命中 ≠ 冒用**（新执照、低活跃、未上传 Club Log 都可能不在库里）⇒ 转人工，只有人能拒绝 |

**拉取的授权方式是受限命令**：hub 上那把钥匙在 www 的 `authorized_keys` 里绑定了
`command="cat .../clublog_users.json"`，因此它**只能读这一个文件**，拿不到 shell（已实测：
请求执行 `id` 仍只返回 JSON）。同步脚本还带**规模校验门**（<10 万条即拒绝替换），
避免把好索引换成空索引。
