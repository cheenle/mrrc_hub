# MRRC Cloud Hub — 验证环境部署

> **状态（2026-10-01 复核）：阶段 1 已部署并在真实公网验证通过。** 本目录的脚本是那一次的落地工具。
> 下面「未部署」的叙述是当时的现场记录，保留供追溯。
> **重跑任何脚本前，先读下面的「⚠️ 脚本与现网漂移」—— 其中 X1 会让现网退化（X2/X3 已随 V0.21 失去对象，存史）。**

## 注册表第三列：上游 TLS 校验名（老实例会被它绊住）

`/etc/mrrc-hub/instances.tsv` 每行是 `标签 <tab> 回环端口 <tab> 上游 TLS 名`。
第三列**留空**时生成器按"它自己的入口名"校验（`<标签>.mrrc.vlsc.net`）—— 对自签证书的实例正好 ✓。

但**自带公有证书**的实例（例如早期用 Let's Encrypt 签了 `radio.vlsc.net` 的那台）必须**显式写第三列**，
否则入口会是 502，而 nginx 日志说：

```
upstream SSL certificate does not match "<标签>.mrrc.vlsc.net" while SSL handshaking to upstream
```

**排查顺序**（2026-10-03 实测）：

1. 实例的隧道端口在听 ⇒ 可以**直接从隧道口取证书**（不需要那台机器配合）：
   `openssl s_client -connect 127.0.0.1:<端口> -servername <标签>.mrrc.vlsc.net -showcerts </dev/null`
2. 看 CN/SAN：是 `<标签>.mrrc.vlsc.net` ⇒ 什么都不用写 ✓；是别的名字（如 `radio.vlsc.net`）⇒ 写进第三列 ✓
3. 证书放进 `/etc/mrrc-hub/instance-certs/<标签>.pem`（生成器按**文件名**匹配注册表 ✓）
4. `sudo /usr/local/sbin/gen_hub_routes.py && sudo systemctl reload nginx`
5. 复核入口：`curl -sk -o /dev/null -w '%{http_code}\n' https://<标签>.mrrc.vlsc.net/api/health` ⇒ 401 ✓

## 现行形态（V0.21，2026-10-02）—— 一台机器，只留 8989

**门户、实例入口、静态站点在同一台机器上**（香港 VPS `hub.vlsc.net` = `www.vlsc.net` =
`portal.mrrc.vlsc.net`，203.25.119.168）。原先"hub 一台 + 海外 www 边缘一台"的两级入口
**已删除**：两条路指向同一个 nginx，保留第二套只是多一处会坏的配置。

> **要 SSH 的是 `cheenle@www.vlsc.net`（203.25.119.168），不是 `8.160.161.80`。**
> 本文下方标着「2026-09-30 实测」的拓扑、事实表与部署步骤描述的是**迁移前那台阿里云 ECS**
> （`8.160.161.80` / `iZ0jlaouy9vk8n98wfp3a6Z`）—— 只作历史保留。**2026-10-03 重新取证**发现那台
> 机器并未退役：它上面另跑着一套 frps + portal + nginx，注册表已经**分叉**（标签带 `-mrrc-modern`
> 后缀），且**自 2026-09-30 19:22 起没有任何实例接入过**。它不承载任何现网入口，DNS 也不指向它。
> 当日就因为这个过期段落把排查带错了方向 —— 所以这一条写在最前面。
>
> **现网 hub 的实测事实（2026-10-03）**：Ubuntu，**1 vCPU / 1914 MB 内存 / 磁盘 13721 MB（已用 5823）**；
> `frps`（8989）· `nginx`（443）· `mrrc-portal`（127.0.0.1:8890，`User=mrrcportal`，无 sudo）
> 四个单元常驻；`mrrc-hub-routes.timer`（30 s）见下方「路由重生成」一节。
> SSH 为 `cheenle@www.vlsc.net`，**有 NOPASSWD sudo**（`sudo -n` 可直接用）。

| 用途 | 地址 | 端口 |
| --- | --- | --- |
| 实例入口（统一，标签=裸呼号） | `https://<呼号>.mrrc.vlsc.net/` | **443** |
| 呼号自助门户（挂根） | `https://portal.mrrc.vlsc.net/` | **443** |
| 静态站点与下载 | `https://www.vlsc.net/mrrc_modern/` | **443** |
| 隧道控制（实例出站连它） | `tunnel.mrrc.vlsc.net` | **8989** |

**防火墙只需要放行 8989 与 443**（`:9988` / `:8899` 两个监听已取消）。

## ⚠️ 脚本与现网漂移（2026-10-01 取证，2026-10-02 按 V0.21 复核）

**仓库脚本落后于现网**。2026-10-01 记的是三条；V0.21 删掉海外边缘那条反代路径之后，**X2 / X3 已失去对象**
（保留为记录，不删行），X1 里原先的三项倒退有两项已对齐、只剩两处仍是活的漂移。
重跑 `deploy_hub_routes.sh` 仍会让现网退化，**务必先对齐再跑**：

| # | 漂移 | 后果 |
| --- | --- | --- |
| **X1**（**仍是活的**） | **已对齐的两项**：脚本现在只生成**一个** `listen 443 ssl` 的 vhost（`8899` / `9988` 两个口已随 V0.21 取消，无处可退），并且已经写入 `proxy_ssl_trusted_certificate /etc/mrrc-hub/trust-bundle.pem`。**仍漂移的两处**（读脚本取证）：① `proxy_ssl_name` 用的是写死的 `${MRRC_UPSTREAM_SSL_NAME:-radio.vlsc.net}`（第 24、88 行），**不引用 `gen_hub_routes.py` 生成的 `$mrrc_tls_name`**；② vhost 头部注释仍写 `currently self-signed: a trusted one needs DNS-01`（第 58–59 行），而现网是真 Let's Encrypt（DNS-01 已跑通并每日续期） | 重跑会把逐实例的**校验名压平成 `radio.vlsc.net`** ⇒ 凡按自己入口名 `<标签>.mrrc.vlsc.net` 签证的实例立即 502（`bg1sb` 的第三列本来就写着 `radio.vlsc.net`，反而不受影响）。信任包这一项不再倒退；`$mrrc_tls_name` 的 map 仍会被生成（脚本第 49 行会跑生成器），只是 vhost 不再引用它。② 属注释误导，不影响运行 |
| **X3**（存史，**已失去对象**） | 原漂移：边缘 nginx 里指向 hub 的两处 `proxy_pass`（`/mrrc_modern/BG1SB/` 与 `/mrrc_portal/`）为 **hub 的 IPv4 字面量** `8.160.161.80`，不是脚本里的主机名 | **V0.21 删除了海外边缘那条反代路径**，这两处 `proxy_pass` 连同所在的 vhost 段一起不再存在 ⇒ 本条今天没有对象。**留档理由**：根因（裸主机名 + AAAA ⇒ nginx 无 `resolver` 时只在启动解析一次，于是选中不可达的 IPv6）与旧 hub 的 v6 不可达都还在记录里，而**新机器的 IPv6 可达性未取证**（搬迁后没人复测）；将来若再引入「主机名式 upstream」，同一条会再咬一次（见 `SDD/12 §12.8` 排障增补、`SDD/14` V0.19） |
| **X2**（存史，**已失去对象**） | 原漂移：`deploy_www_edge.sh` 只实现 `redirect` / `proxy`（子域）两种模式；现网实际用的是**第三种** `path proxy`（Host 覆盖 + 路径大小写规范化 301 + `X-Forwarded-Prefix` + `proxy_redirect` 回写） | **V0.21 删除了边缘路径** ⇒ 现网已没有那段手工配置可供降级，整个脚本也就没有落点（脚本仍在仓内，两种模式的代码未动，可复核；当时 www 上的 `/tmp/deploy_www_edge.sh` 与仓库版本**仅空白差异**，说明那段配置是手工落的）。**留档理由**：那段 `path proxy` 从来没有脚本能复现 —— 将来若再需要「另一台机器上的路径入口」，得先把它写回脚本 |

> **X1 现在是唯一需要防的一条**：per-instance 证书链（`make_instance_cert.sh` → `trust-bundle.pem` →
> `proxy_ssl_name $mrrc_tls_name`）里，信任包那一半已经写回脚本，**校验名那一半仍是手工落的**。
> 在 `proxy_ssl_name $mrrc_tls_name` 写回脚本之前，**不要重跑 `deploy_hub_routes.sh`**。
> 参见 `SDD/12 §12.8 「实例证书链」`。

**处置**：只记录，**不改脚本**（改部署脚本的风险与验证成本超出文档任务范围）。对齐留作独立变更。

## 已探明的事实（2026-09-30 实测，**指迁移前那台 `8.160.161.80`，仅作历史**）

> 本节的"Hub 主机"是阿里云 ECS，**不是现网**。现网事实见文首提示框。

| 项 | 事实 |
| --- | --- |
| Hub 主机 | 阿里云 ECS `iZ0jlaouy9vk8n98wfp3a6Z`，公网 `8.160.161.80`，内网 `172.19.95.147` |
| 系统 | Ubuntu 26.04.1 LTS，2 vCPU / 3.6 GB / 40 GB（31 GB 空闲） |
| 已装软件 | **无**（无 nginx / frp / docker / caddy / certbot / node），仅 sshd |
| SSH | `cheenle@8.160.161.80` 可用默认密钥（`~/.ssh/id_*` 与 `~/.ssh/cheenle.pem` 均可） |
| **sudo** | **需要密码**（非 NOPASSWD）→ 装包与绑定低端口都做不了 |
| **安全组** | **只放行 22**。实测：在 18080 起临时监听，本机 `200`、从公网 `000` |
| DNS `hub.vlsc.net` | **不存在**（`vlsc.net` 区里没有这条记录） |
| DNS `*.mrrc.vlsc.net` | **已是通配 A 记录 → 8.160.161.80**（`probe-test.mrrc.vlsc.net` 实测解析成功） |
| DNS `radio.vlsc.net` | 家宽 IPv6（无 A），即实例侧现状入口 |
| 实例证书 | `certs/fullchain.pem` = **真 Let's Encrypt**，`CN=radio.vlsc.net`，SAN 仅 `radio.vlsc.net`，2026-12-10 到期 |

**推论**：SDD 里那套命名（`https://portal.mrrc.vlsc.net` / `tunnel.mrrc.vlsc.net` / `<id>.mrrc.vlsc.net`）
**今天就解析得到**，不需要动 DNS。而你说的 `hub.vlsc.net` 需要新增一条记录（它在 `vlsc.net`
区下，不在那条通配里）。本目录默认用 `test1.mrrc.vlsc.net` 做验证，避开这个前置。

## 解除阻塞（三件，只有你能做）

1. **VPS 控制台 → 安全组入方向**放行：**`8989/tcp`（隧道控制）与 `443/tcp`（入口/门户/站点）**。
   历史端口 `8899` / `9988` 已随 V0.21 取消，无需放行

   | 端口 | 用途 |
   | --- | --- |
   | ~~8899~~ | **已取消**（原为明文 301 口，后升 TLS，V0.21 随合并删除） |
   | ~~9988~~ | **已取消**（原为用户入口 TLS 口；现入口在 443） |
   | **8989** | frps 控制口，实例出站连它 |

   非标端口的代价已写进设计记录（AD-H02 的 port 修订、风险 R-H12）：**入口 URL 带端口**，
   且**只放行 80/443 出站的用户网络完全连不上**。收益是国内 ECS 在 80/443 上需要 ICP 备案。
2. **给 `cheenle` 免密 sudo**（在控制台用 VNC/其它 root 通道执行一次）：

   ```bash
   echo 'cheenle ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/cheenle
   sudo chmod 440 /etc/sudoers.d/cheenle
   ```

   （或者你把密码给我，我在需要时用——但不推荐把口令贴进对话。）
3. （可选，若你要 `hub.vlsc.net` 这个名字）在 `vlsc.net` 区加一条 A 记录 → `8.160.161.80`。
   没有也能跑，用 `test1.mrrc.vlsc.net`。

## 拓扑（本目录脚本实现的就是这张图）

```
用户浏览器
  │  https://test1.mrrc.vlsc.net   ← TLS 由 hub 的 nginx 终结（Let's Encrypt，HTTP-01）
  ▼
Hub ECS 8.160.161.80
  nginx  server_name test1.mrrc.vlsc.net
     └─ proxy_pass https://127.0.0.1:18888
           proxy_ssl_verify on                       ← 这一步是刻意的：
           proxy_ssl_name radio.vlsc.net                B2 现状是 proxy_ssl_verify off，
           proxy_ssl_trusted_certificate <系统 CA 库>    hub 侧必须开着校验证书
  nginx :443（入口、门户、站点同一个端口）
  frps :8989  bindPort（实例出站连它；token 鉴权 + TLS）
       :18888 tcp 代理端口（**只绑 127.0.0.1**，不暴露到公网）
       ▲
       │ 出站 WSS/TLS，客户侧零入站
       │
家宽 Mac（实例侧）
  frpc → tunnel.mrrc.vlsc.net:8989
      local 127.0.0.1:8888  ← MRRC_modern（真的 Let's Encrypt 证书）
```

**为什么不让 frps 直接做 vhost/子域路由**：那样 nginx 就不在链上了，而上游那一跳要么明文、
要么又得关证书校验。让 nginx 持有 443 并做子域路由，**上游那一跳就能开着校验**——一次验证
同时覆盖两项设计主张：AD-H02（通配子域可行）与 NFR-H021（禁止 `proxy_ssl_verify off`）。

## 部署步骤

> **注意**：下面的 `8.160.161.80` 是历史目标。现网重装/迁移走 `cheenle@www.vlsc.net`，步骤相同，
> 但请同时确认 `mrrc-hub-routes.{sh,timer,service}` 三件套都装上了（见下方「路由重生成」）。

```bash
# 1) hub 侧（需要第 1、2 项已解除）
scp deploy/bootstrap-hub.sh cheenle@8.160.161.80:/tmp/
ssh cheenle@8.160.161.80 'sudo bash /tmp/bootstrap-hub.sh test1.mrrc.vlsc.net'
#    脚本会打印实例侧要用的 token 与一段 frpc 配置

# 2) 实例侧（本机 Mac）
brew install frp                     # 或用官方便携包；版本需 ≥ 0.52（v2 配置格式）
cp deploy/frpc-instance.toml.example ~/mrrc-frpc.toml   # 填 token
frpc -c ~/mrrc-frpc.toml

# 3) 验证
curl -sI https://test1.mrrc.vlsc.net/login            # 期望 200（自签阶段加 -k）
curl -s  https://test1.mrrc.vlsc.net/api/health       # 期望 401（鉴权生效）
```

## 这次验证要检查什么（不只是"能连上"）

| # | 检查项 | 期望 | 对应设计主张 |
| --- | --- | --- | --- |
| V-a | 登录页可达 | `https://test1.mrrc.vlsc.net/login` 200 | AD-H01 / SC-H1（客户侧零入站） |
| V-b | 五个 WS 端点全通 | `/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` `/WSatr1000` 均完成握手（浏览器不复现"控制/频谱在、音频缺席"） | 透明代理契约 |
| V-c | **WS URL 里没有 `?token=`** | 浏览器 DevTools 的 Network→WS 请求 URL 无 token；`journalctl -u nginx` grep `token=` 无命中 | AD-H07 / NFR-H020 |
| V-d | **上游证书校验为真** | nginx 配置无 `proxy_ssl_verify off`；证书不匹配时链路应失败（可临时把 `proxy_ssl_name` 改错验证它真的会失败） | NFR-H021 |
| V-e | 遥测可读 | `GET /api/session_metrics` 返回计数（需会话） | AD-023 / hub I-H1 |
| V-f | 频谱带宽实测 | 一帧 1701 B × 30 fps ≈ 408 kbps（对齐 hub AD-H14 的 86% 结论） | NFR-H007/H008 |
| V-g | `/listen` 角色仍只读发射 | Listener 登录后 `/WSaudioTX` 应以 4003 关闭 | AD-H08 |

**V-d 的做法值得保留**：故意改错 `proxy_ssl_name` 看它失败，是"校验真的开着"的唯一证据——
这正是当初 B2 那行 `proxy_ssl_verify off` 能在生产里活下来的原因（没人验证过它会失败）。

## 通配真证书：`*.mrrc.vlsc.net`（就差一个 AccessKey）

**先说清为什么绕不过 DNS-01**：现有的续订是标准 certbot + **HTTP-01**（www 上 `/etc/cron.d/certbot`
与 `certbot.timer`，renewal 配置里是 `authenticator = nginx/webroot`），**产不出通配证书** ——
Let's Encrypt 的通配只走 DNS-01。而 hub 在境内，80/443 本来就不可用（R-H13），所以 DNS-01 是唯一路径。

**也不需要跨机分发**：www→hub 没有免密 SSH，但 **DNS-01 不用任何入站端口**，所以让 **hub 自己签发和续订**
最干净 —— 证书正好就是它自己 nginx 要用的（www 现在只是跳转，用自己那张 `www.vlsc.net` 证书即可）。

**你要给的一样东西**：一个阿里云 **RAM 用户**（访问控制 → 用户），**只挂 `AliyunDNSFullAccess`**，
不要用主账号 key。拿到后：

```bash
# 在 hub 上
sudo install -d -m 700 /root/.secrets
sudo sh -c 'printf "dns_aliyun_access_key = %s\ndns_aliyun_access_key_secret = %s\n" \
    "<AccessKeyId>" "<AccessKeySecret>" > /root/.secrets/aliyun.ini && chmod 600 /root/.secrets/aliyun.ini'
sudo bash deploy/mrrc-hub-cert.sh     # 有凭证签真证书，无凭证自签（见 §证书）
```

脚本会：装 `certbot-dns-aliyun` → 签 `*.mrrc.vlsc.net` + 裸域 → 写一个 **deploy hook** 把证书装到
`/etc/mrrc-hub/tls/`（nginx 已在读这个路径，**无需改任何 nginx 配置**）并 reload → 之后由
`certbot.timer` 每 90 天自动续订，hook 自动生效。

**不想建 key 的话**：`certbot certonly --manual --preferred-challenges dns -d '*.mrrc.vlsc.net'`
在任何机器上跑，把打印出的 TXT 记录加到阿里云 DNS 控制台即可 —— 但**每 90 天要手工来一次**，
manual 模式不会自动续订（脚本的错误信息里也写了这条退路）。

## 正式形态（2026-09-30 落地）

**hub 侧：一条通配 vhost 服务所有实例，注册表是唯一的每实例事实。**

| 文件 | 作用 |
| --- | --- |
| `/etc/mrrc-hub/instances.tsv` | 注册表：`<名字> <回环端口>`，一行一个实例（权威） |
| `/usr/local/sbin/gen_hub_routes.py` | 把注册表生成成 nginx `map`（`/etc/nginx/conf.d/mrrc-hub-map.conf`），并校验端口落在 frps 的 `allowPorts` 内 |
| `/etc/nginx/sites-available/mrrc-hub` | **唯一**的 vhost：`~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net$` → `https://127.0.0.1:$mrrc_port`；未知名字 **404**（不回退到别的实例）。上游校验：`proxy_ssl_name $mrrc_tls_name` + `proxy_ssl_trusted_certificate /etc/mrrc-hub/trust-bundle.pem`（**逐实例**，见下） |
| `/etc/mrrc-hub/trust-bundle.pem` | 系统 CA + 各实例的自签证书公钥。自签证书靠"钉住它"通过校验，而不是靠关掉 verification |
| `/etc/nginx/sites-available/mrrc-portal-mrrc` | 呼号自助注册站点：`https://portal.mrrc.vlsc.net/`（**挂在该名字的根**；旧 `/mrrc_portal/` 301 到根），带 `limit_req` |

**加实例 = 注册表加一行 + 重跑生成器 + reload**，不再"每实例改 nginx"—— 那正是 B2 的痛
（每加一个前端资源就要动中心配置、还踩过正则优先级）。

**实例侧：launchd 常驻服务**（`deploy/install_instance_tunnel.sh`）。配置落在
`~/Library/Application Support/mrrc-fleet/frpc-<name>.toml`（0600，token 只在这里），
LaunchAgent 带 `KeepAlive`，崩溃/重启/换网自恢复；脚本拒绝在"已有手工 frpc 在跑"时启动，
避免两个客户端抢同一个名字导致抖动。**实例自己的电台服务不归它管** —— 隧道照常连，实例没起来就 502。

**实测**：服务日志 `login to server success` + `start proxy success`；
经通配 vhost `test1.mrrc.vlsc.net` → `/api/health` **401**、`/login` **200**；
`nope.mrrc.vlsc.net` → **404**（未知实例不误路由，NFR-H022）。

**本阶段已知限制（阶段 2 替换）**：**隧道自身的认证**仍是 frp 的**单个共享 token** ——
这是 frp 的模型，也是 hub SDD 把 frp 定位为 MVP 验证通道、把设备 mTLS 留给自研 Agent 的原因（AD-H11/AD-H13）。

但不要把这与另一件事混起来：**hub → 实例这一跳的 TLS 身份已经是一机一证**
（`make_instance_cert.sh` 签自签证书 → 钉进 `trust-bundle.pem` → nginx 按 `$mrrc_tls_name` 逐实例校验）。
两者层次不同：前者是"谁能接入隧道"，后者是"这台实例是不是它声称的那台"。
详见 `../SDD/12-operational-model.md` §12.8 「实例证书链」与「实例开通链」。

## 后台管理台账号与 frps 面板（V0.28）

部署新版 portal 前先看这份检查单（代码在 `portal/`，行为细节见 `../portal/README.md`）：

1. **账号文件**（`/etc/mrrc-hub/portal-users`，htpasswd `$apr1$`）：

   ```bash
   printf '%s:%s\n' <用户名> "$(openssl passwd -apr1)" | sudo tee -a /etc/mrrc-hub/portal-users
   sudo chown root:mrrcportal /etc/mrrc-hub/portal-users && sudo chmod 640 /etc/mrrc-hub/portal-users
   ```

   文件为空 = 没人能登管理台（令牌机器路径仍可用）。`bootstrap-hub.sh` 只创建占位，不覆盖。
2. **frps 面板**：`frps.toml` 的 `webServer` 段只绑 `127.0.0.1:7100`，凭据
   `/etc/mrrc-hub/frps-web.credentials`（0640 root:mrrcportal，bootstrap 自动生成）。
   改完用 **`systemctl reload frps`**（`ExecReload` = SIGHUP，frp ≥0.52 热重载，隧道不断）；
   若实测该版本对 SIGHUP 不生效，再退化到维护窗口内 restart。
3. **核验面板字段**：`curl -u "$(cut -d: -f1- /etc/mrrc-hub/frps-web.credentials)" http://127.0.0.1:7100/api/proxy/tcp`
   —— 确认真实字段名（本文档按 0.71 的 `trafficIn/Out`、`todayTrafficIn/Out`、`curConns` 假定）。
4. **来源 IP 透传**：portal vhost 必须设 `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`
   （与 `X-Real-IP`）。**缺了它登录锁定会退化成 127.0.0.1 全局桶**——与 §12.8 的实例侧同款教训。
5. **重启 portal**：`sudo systemctl restart mrrc-portal`；随后逐项复验：登录/登出、无 CSRF 动作被拒、
   隧道视图出数、停掉面板时页面显示原因而不是 0。

> frps 那个单共享 token 仍然存在（见上）；本面板只是**只读统计**，不是第二套认证。

## 两级入口：主路走 hub，退化路走海外 www（迂回方案）

境内地域的 80/443 在没有备案时不可用，而**明文 HTTP 到未备案域名会被途中改写**（实测见 R-H13）。
所以入口分两级，脚本对应用户所处的网络：

| | 主路（低延迟） | 退化路（兼容性） |
| --- | --- | --- |
| URL（历史） | `https://<呼号>.mrrc.vlsc.net:9988` / `:8899` | `https://www.vlsc.net/mrrc_modern/<呼号大写>/` |
| 落点（历史） | hub | 海外 <www.vlsc.net> 的 443 路径代理，反代回 hub 的 9988 |
| 证书 | **真 Let's Encrypt**（`*.mrrc.vlsc.net`，DNS-01，2026-09-30 → 2026-12-29，每日续期） | **真证书**（www 上 certbot HTTP-01，80/443 在此可用） |
| 实测 RTT | **0.13 s**（`/login`） | **0.69 s**（`/login`，多一跳海外往返） |
| 适用 | 绝大多数用户 | 只放行 80/443 出站的网络（公司/访客 Wi-Fi） |
| 可用性 | 多次实测均正常 | ⚠️ **2026-10-01 复测为间歇可用**（6 次中 3 次 20 s 无响应）；失败在 `www → hub` 这一跳，详见 `SDD/12 §12.8` 排障增补 |

> 脚本里的 `proxy`（**子域**）模式 **不是**现网形态 —— 现网用的是第三种 `path proxy`。
> 见上方「⚠️ 脚本与现网漂移」X2。

**为什么要"反代"而不是"302 跳转"**：跳转只换了个好看的地址，浏览器最终仍落在非标端口上、仍看到
不信任的证书。只有把整条会话（HTTP + 5 个 WS）反代进来，才同时解决"标准端口"和"真证书"两件事。

**代价必须写在明处**：境外边缘对"用户在国内、实例也在国内"的场景是绕路，音频与 PTT 的往返
多约 **0.4–0.6 s**。因此它定位为**退化路径**，不是主路 —— 主路应当是 hub 上的 DNS-01 真证书
（低延迟），这样两级都能免掉证书警告。

### 部署退化路径

```bash
# 1) 把 hub 的自签证书作为信任锚送到 www（不关校验，而是 pin 住它）
ssh hub 'sudo cat /etc/mrrc-hub/tls/fullchain.pem' | ssh www 'sudo tee /etc/nginx/mrrc-hub-ca.pem'
# 2) 推送并执行（幂等、marker 分块替换、改前备份、nginx -t 后才 reload）
scp deploy/deploy_www_edge.sh www:/tmp/
ssh www 'sudo bash /tmp/deploy_www_edge.sh test1.mrrc.vlsc.net tunnel.mrrc.vlsc.net'
```

**验证结果（经 www 全程实测，2026-09-30）**：`/login` 200、`/api/health` 401、`/listen` 302；
**五个 WS 端点全部 `101 Switching Protocols`**（Cookie 鉴权，无凭据对照 403）。

### 还差你一条 DNS 记录

> 历史记录 —— 当时用 `test1` 做验证。**现网实例是 `bg1sb`**，且边缘已改为路径代理（见上方两级入口表），
> 下面这条子域记录的方案已被取代。当前实况见 `SDD/12 §12.8`。

```
test1.mrrc.vlsc.net  →  A  193.111.30.163   （即 www，显式记录会覆盖 *.mrrc.vlsc.net 通配）
```

加完之后我可以 `certbot certonly --webroot -w /var/www/html -d test1.mrrc.vlsc.net`（www 上 80 口可用，
HTTP-01 没问题），重跑脚本即换成**真证书**、浏览器零警告。加之前用 `--resolve` 模拟已可全程验证。

## 已验证（2026-09-30 真实公网，安全组放行后）

安全组放行 443/8989 之后，**真实公网路径**（本机 → hub nginx → frps:8989 → frpc → 实例）
实测通过，无 SSH 转发、无端口映射、客户侧零入站：

| 检查 | 结果 |
| --- | --- |
| 命名 | 实例入口 `test1.mrrc.vlsc.net`；隧道控制 `tunnel.mrrc.vlsc.net:8989`（均走 `*.mrrc.vlsc.net` 通配） |
| 边缘 | `/login` **200**、`/api/health` **401**、`/listen` **302**（未鉴权跳登录） |
| 公网往返 | 家宽 → 乌兰察布 → 隧道 → 家宽，**118–168 ms** |
| 上游证书校验 | 对实例的**真 LE 证书**校验通过（校验关闭时才可能拿到 502 之外的结果） |
| 前端令牌 | 送达浏览器的 `ft710_main.js` / `listen.js` 中 `?token=` **0 次** |
| 边缘日志脱敏 | 本 vhost 改用 `hub_safe` 日志格式（**只记路径、不记 query**），实测带 `token=` 的请求在日志里 **0 命中** |

### 这次抓到的三个真问题（全部已修）

1. **frp 默认把代理端口绑在 `0.0.0.0`** —— 设计说"只绑回环"，frp 的默认不是。
   `frps.toml` 必须显式写 `proxyBindAddr = "127.0.0.1"`（脚本与 hub 运行配置均已同步）。
2. **未备案域名在大陆地域的明文 HTTP 会被拦/替换**：对 8899 发请求，客户端收到
   `Server: Beaver` 的 403（阿里云未备案拦截页），而 hub 的 nginx 日志显示它对同一请求回了 **301**。
   —— 响应在途中被打包替换了。TLS 口不受影响（内容改不了）。**结论：入口必须 HTTPS，
   8899 明文口在备案前不能承载任何功能依赖**；这也是"办 ICP 备案后回到 443"的硬论据（新增 R-H13）。
3. **日志脱敏必须做，而且立刻就见效**：我在验证 WS 透明性时用 `?token=` 发过两次请求，
   64 位真令牌当场写进了边缘 access log。这正是 AD-H07 预言的失效模式 —— 唯一原因是
   前端已经不发了，但**任何**客户端（含已安装的原生 App）仍能触发它。已改为不记录 query。

顺带说明：实例登录接口限流 **5 次/300 秒**，反复探测会拿到 429（正常工作，非缺陷）；
`websockets` 客户端的 `additional_headers` 送 Cookie 会**静默不生效**，安全结论请用**裸 TCP 握手**取。

## 已验证（早前一轮：安全组未放行时用 SSH 转发绕开）

安全组当时仍未放行，所以两条腿走了 SSH 本地转发（本地 18989→hub 8989、18988→hub 9988（当时还有 9988））。
**被验证的软件链条与真实部署完全一致**，只有"公网能不能到 hub"这一层没被覆盖。

| 检查 | 结果 |
| --- | --- |
| 隧道建立 | frpc `login to server success` + `[mrrc-test1] start proxy success` ✓ |
| TLS 终结 + 子域 vhost | `https://test1.mrrc.vlsc.net/login` → **200**；`/api/health` → **401** ✓ |
| **上游证书校验为真（V-d）** | 直连一个"CN 错误的自签上游"→ 200，经 nginx → **502**；换成实例的**真 LE 证书**后 → **401/200 正常通过**。两向都测过：该校验既会拦、也不会误拦 ✓ |
| **WS 透明性（V-b）** | 裸握手矩阵（直连 vs 经隧道）：无凭据 **403 / 403**、Cookie **101 / 101**、`?token=` **101 / 101** —— 升级与自定义关闭语义完全一致 ✓ |
| **令牌传输（V-c 部分）** | 前端已不再拼 `?token=`；本次 WS 用 Cookie 头即可通过（AD-024 的 cookie 路径经隧道有效）✓ |

**测试期发现的两个真问题**（都已修）：

1. **frp 默认把代理端口绑在 `0.0.0.0`** —— 设计里说"只绑回环"，但 frp 的默认不是。
   `frps.toml` 必须显式写 `proxyBindAddr = "127.0.0.1"`（脚本已加，hub 上的运行配置也已同步）。
2. 验证方法本身：`websockets` 客户端用 `additional_headers` 送 Cookie 会**静默不生效**，
   我一度据此怀疑 AD-024 有回归；改用**裸 TCP 握手**才定界清楚 ——
   结论是 cookie 路径正常，问题在测试客户端。**用一层客户端库做安全结论之前先降到裸协议。**

顺带说明：实例登录接口有 **5 次/300 秒** 的限流，反复登录会拿到 429（正常工作，非缺陷）。

## 尚未覆盖

- **证书当前是自签的**（脚本在无 DNS 凭证时明确吼一声并生成自签证书，SAN 覆盖
  `test1.mrrc.vlsc.net` + `*.mrrc.vlsc.net` + `*.vlsc.net`）。这是硬约束，不是偷懒：
  **Let's Encrypt 的 HTTP-01 固定走 80、TLS-ALPN-01 固定走 443**，两个口都不开就没有自动签发路径。
- `vlsc.net` 的 DNS 托管在**阿里云万网**（`dns25/dns26.hichina.com`）。要真证书/通配证书：
  建一个只带 `AliyunDNSFullAccess` 的 RAM 用户，把 AccessKey 写进 `/etc/mrrc-hub/aliyun.ini`
  （0600），重跑 `bootstrap-hub.sh` —— 脚本自动切 DNS-01，那时可一次签 **`*.mrrc.vlsc.net` 通配**，
  200 个实例共用一张。
- 多实例（`test2`…）可直接复用：再加一条 frpc 代理 + 一条 nginx server 块。
- Fleet Agent、设备证书、Portal、租约都还没实现（hub SDD 的阶段 2），本次只验证阶段 1 通路。

## 证书（实况，2026-09-30 起）

`deploy/mrrc-hub-cert.sh` 是唯一入口；`mrrc-hub-cert.sh` 已被它取代并删除。

| 文件 | 作用 |
| ------ | ------ |
| `mrrc-hub-cert.sh` | 体检 / 签发 / 续期；退出码 0/1/2（<14 天告警）；供每日 cron 调用 |
| `aliyun-acme-dns-hook.py` | certbot `manual` 插件的 auth/cleanup hook；DNS-01 调阿里云 DNS API（纯标准库自算签名） |
| （hub 上）`mrrc-hub-cert-hook.sh` | `--deploy-hook`：拷贝证书到 `/etc/mrrc-hub/tls/` 并 reload nginx |

前置：`/root/.secrets/aliyun.ini`（0600，`access_key_id` / `access_key_secret`，兼容 certbot 插件命名）。
**有它走真证书，没它回退自签通配** —— 脚本自行判断，无需改配置。

三条会复发的坑（今天各付了一次失败的签发）：

1. **certbot 调用 hook 不带参数**。phase 靠环境变量：auth 有 `CERTBOT_VALIDATION`，cleanup 有 `CERTBOT_AUTH_OUTPUT`。
   假定 argv ⇒ 每次调用都以 usage 退出，表现为"有些挑战失败"，而手动 `hook auth` 却成功。
2. **cleanup 不保证收到 `CERTBOT_VALIDATION`**。auth 把值写入状态文件，cleanup 按值精确删除自己的记录，绝不误删通配与裸域并存的兄弟记录。
3. **只等权威解析不够**。CA 经公共解析器验证，hook 需轮询 DoH 直到可见。

www 边缘的上游校验用**系统 CA**（不再钉自签证书），故**续期后无需任何跨机同步**。

## 开通链脚本（V0.15 收录）

| 脚本 | 在哪台机器 | 做什么 |
| --- | --- | --- |
| `make_instance_cert.sh <呼号> [目录]` | 实例（租户机） | 签 `<呼号>.mrrc.vlsc.net` 自签证书（幂等，`FORCE=1` 重签），并**把公钥登记到 hub**（`MRRC_ENROLL_SECRET` / `MRRC_ENROLL_URL`，缺口令则跳过并说明后果） |
| `install_instance_tunnel.sh` / `.ps1` | 实例（macOS/Linux ／ Windows） | 取件、校验 SHA-256、装常驻隧道、跑通自检；Windows 侧同时签证书并登记 |
| `fetch_installer_payload.sh` | 实例 | 免预装取件器：无第三方依赖，**必校 SHA-256**，不符即拒绝（不降级） |
| `gen_hub_routes.py` | hub（**root**） | 按注册表生成通配 vhost 路由 + 把 `instance-certs/` 并成一册信任包；**原子替换，`nginx -t` 过了才 reload**，校验不通过就回滚且**不回退到关闭校验** |
| `mrrc-hub-cert.sh` | hub（root） | 通配证书（DNS-01）签发与续期 —— **由 `issue_wildcard_cert.sh` 改名而来** |

## 装机后才暴露的三个缺陷（2026-10-01，VM 实测；v1.23.1 待带）

在干净的 Win11 VM 上**装线上包并真跑接入脚本**才发现的，三个都不是"没写对"，而是"写完没在那个环境下跑过"：

| # | 症状 | 根因 | 状态 |
| --- | --- | --- | --- |
| 1 | `openssl req` 报 `Can't open "…/MRRC Modern/etc/ssl/openssl.cnf"` ⇒ 签不出证书 | msys2 的 `openssl.exe` 按**编译前缀**找默认配置，租户机上没有该前缀 | **已修** ✓：随包带 `openssl.cnf` + 脚本显式 `-config`，缺文件即报错（不再回退） |
| 2 | shell 侧在 stock macOS 上同样签不出 | 用了 `-addext` —— OpenSSL 3 有、**LibreSSL 没有**（`/usr/bin/openssl` 就是 LibreSSL） | **已修** ✓：改用 `-config` 形式（两边都认） |
| 3 | 脚本在签名一步抛异常中断，日志只有 `+++…+++` | PowerShell 5.1 在 `$ErrorActionPreference="Stop"` 下把**原生程序写 stderr**（openssl 进度点）当成 terminating error | **已定位** ✗ 未修：把原生调用包起来（局部降级为 Continue + 用 `$LASTEXITCODE` 判成败） |

**给自己的判据教训**（第 1 条）：我当时的"自足性证明"证的是"**带 `-config`** 能签" ✓，而脚本**没传 `-config`** ✗ ⇒ 判据比结论窄一点，就差出一次事故。
**验证方式教训**：`build.ps1` 与租户脚本都必须**在装上之后**跑一次；`fleet/` 不在热修覆盖面内 ⇒ 这类缺陷**只能重打包**，热修救不了。

## hub 侧两条运维铁律（2026-10-01 各踩一次）

1. **改了 Portal 代码，必须重新部署到 hub 才算修好**。`import re` 的修复在仓库里躺了一整天，
   hub 上跑的还是旧代码 ⇒ 端点把一张**完全正确**的证书报成"名字不符"。部署后自检：
   **不带口令**请求 `/enroll` 应得 403/400（不是 200）。
2. **`/etc/mrrc-hub/instance-certs` 的属主必须是服务账号**（本仓 `mrrc-hub-cert.sh:104` 写的就是
   `install -d -o mrrcportal -g mrrcportal -m 750`）。手工建成 `root:mrrcportal 750` ⇒ 服务**写不了**
   登记上来的证书 —— 而它会以 **409** 的形式出现（看起来像"你自己提交的冲突"，误导性极强）。
   核对：`stat -c '%a %U:%G' /etc/mrrc-hub/instance-certs` ⇒ 期望 `750 mrrcportal:mrrcportal`。

## 路由重生成现在是自动的（2026-10-01 起）

`gen_hub_routes.py` 过去要人手工跑一次（脚本会把那条 root 命令交给运维）。现在 hub 上装的是
**root 的 systemd timer**（`deploy/systemd/mrrc-hub-routes.{timer,service}` + `mrrc-hub-routes.sh`）：

```
证书或注册表一变 → mrrc-hub-routes.service（oneshot，root）
  ⇒ gen_hub_routes.py（幂等；没变化也算成功 ✓）
  ⇒ nginx -t **过了才** systemctl reload nginx（不过就保持运行中的配置不动并报错退出）
```

- 为什么不放进 Portal 服务里：它接收公网提交，**不该有** reload nginx 的权限（AD 里的分工）。
- 为什么是 **timer** 而不是 path 单元：systemd 的 `PathChanged` 也包含**属性变化（含 atime）**，
  而服务本来就要读证书目录 ⇒ 会不断触发自己（实测 2 分钟 232 次 ✗）。30 秒一次的 timer 只花一次
  glob + 一次哈希比较 ✓，脚本**只在生成物真的变了**才 `nginx -t` + reload ✓（所以常态下不 reload ✓）。
- 新装 hub：`bootstrap-hub.sh` 会一并安装（`install -m 755/644` + `systemctl enable --now`）。
  **但 2026-10-03 实测到一次装配缺失，所以别把这句话当保证**：现网那台 hub 上**只有**
  `mrrc-hub-routes.service`，**包装脚本与 timer 都没装** ⇒ 该 unit 指向的
  `/usr/local/sbin/mrrc-hub-routes.sh` 不存在 ⇒ 每次执行 `status=203/EXEC` ⇒ **自 2026-10-02 01:07
  起路由从未重生成过**。症状：新实例的一切都就绪（frps 已在 `127.0.0.1:<端口>` 监听、
  `instance-certs/<标签>.pem` 已登记、注册表有行），**只有入口 404**，因为 nginx 的
  label→端口表里没有它。
  确认方式：`systemctl is-enabled mrrc-hub-routes.timer`（期望 `enabled`）+ `sha256sum /usr/local/sbin/mrrc-hub-routes.sh`
  与仓库 `deploy/mrrc-hub-routes.sh` 比对。
- **验收**：① `touch /etc/mrrc-hub/instance-certs/<名>.pem` ⇒ `journalctl -u mrrc-hub-routes.service`
  出现 `nginx -t passed; reloading`；② 常态下每 30 s 一行 `nothing changed; not reloading`。
