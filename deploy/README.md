# MRRC Cloud Hub — 验证环境部署

> **状态：未部署。** 主机已就位、DNS 通配已就位、SSH 可达，但有三件只有你能做的事阻塞着
> （见下面"解除阻塞"）。本目录的脚本就是为了那一刻：一条命令跑完。

## 已探明的事实（2026-09-30 实测）

| 项 | 事实 |
|---|---|
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

**推论**：SDD 里那套命名（`portal.mrrc.vlsc.net` / `tunnel.mrrc.vlsc.net` / `<id>.mrrc.vlsc.net`）
**今天就解析得到**，不需要动 DNS。而你说的 `hub.vlsc.net` 需要新增一条记录（它在 `vlsc.net`
区下，不在那条通配里）。本目录默认用 `test1.mrrc.vlsc.net` 做验证，避开这个前置。

## 解除阻塞（三件，只有你能做）

1. **阿里云控制台 → 安全组入方向**放行：**`8899/tcp`、`9988/tcp`、`8989/tcp`**

   | 端口 | 用途 |
   |---|---|
   | **8899** | 用户入口的明文口（只做 301 跳转；**不能**用于 ACME，见下） |
   | **9988** | 用户入口的 TLS 口 —— 用户实际访问 `https://test1.mrrc.vlsc.net:9988` |
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
  nginx :9988 server_name test1.mrrc.vlsc.net
     └─ proxy_pass https://127.0.0.1:18888
           proxy_ssl_verify on                       ← 这一步是刻意的：
           proxy_ssl_name radio.vlsc.net                B2 现状是 proxy_ssl_verify off，
           proxy_ssl_trusted_certificate <系统 CA 库>    hub 侧必须开着校验证书
  nginx :8899 301 → https://…:9988（明文口只跳转）
  frps :8989  bindPort（实例出站连它；token 鉴权 + TLS）
       :18888 tcp 代理端口（**只绑 127.0.0.1**，不暴露到公网）
       ▲
       │ 出站 WSS/TLS，客户侧零入站
       │
家宽 Mac（实例侧）
  frpc → 8.160.161.80:8989
      local 127.0.0.1:8888  ← MRRC_modern（真的 Let's Encrypt 证书）
```

**为什么不让 frps 直接做 vhost/子域路由**：那样 nginx 就不在链上了，而上游那一跳要么明文、
要么又得关证书校验。让 nginx 持有 443 并做子域路由，**上游那一跳就能开着校验**——一次验证
同时覆盖两项设计主张：AD-H02（通配子域可行）与 NFR-H021（禁止 `proxy_ssl_verify off`）。

## 部署步骤

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
curl -sI https://test1.mrrc.vlsc.net:9988/login            # 期望 200（自签阶段加 -k）
curl -s  https://test1.mrrc.vlsc.net:9988/api/health       # 期望 401（鉴权生效）
```

## 这次验证要检查什么（不只是"能连上"）

| # | 检查项 | 期望 | 对应设计主张 |
|---|---|---|---|
| V-a | 登录页可达 | `https://test1.mrrc.vlsc.net:9988/login` 200 | AD-H01 / SC-H1（客户侧零入站） |
| V-b | 五个 WS 端点全通 | `/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` `/WSatr1000` 均完成握手（浏览器不复现"控制/频谱在、音频缺席"） | 透明代理契约 |
| V-c | **WS URL 里没有 `?token=`** | 浏览器 DevTools 的 Network→WS 请求 URL 无 token；`journalctl -u nginx` grep `token=` 无命中 | AD-H07 / NFR-H020 |
| V-d | **上游证书校验为真** | nginx 配置无 `proxy_ssl_verify off`；证书不匹配时链路应失败（可临时把 `proxy_ssl_name` 改错验证它真的会失败） | NFR-H021 |
| V-e | 遥测可读 | `GET /api/session_metrics` 返回计数（需会话） | AD-023 / hub I-H1 |
| V-f | 频谱带宽实测 | 一帧 1701 B × 30 fps ≈ 408 kbps（对齐 hub AD-H14 的 86% 结论） | NFR-H007/H008 |
| V-g | `/listen` 角色仍只读发射 | Listener 登录后 `/WSaudioTX` 应以 4003 关闭 | AD-H08 |

**V-d 的做法值得保留**：故意改错 `proxy_ssl_name` 看它失败，是"校验真的开着"的唯一证据——
这正是当初 B2 那行 `proxy_ssl_verify off` 能在生产里活下来的原因（没人验证过它会失败）。

## 两级入口：主路走 hub，退化路走海外 www（迂回方案）

境内地域的 80/443 在没有备案时不可用，而**明文 HTTP 到未备案域名会被途中改写**（实测见 R-H13）。
所以入口分两级，脚本对应用户所处的网络：

| | 主路（低延迟） | 退化路（兼容性） |
|---|---|---|
| URL | `https://test1.mrrc.vlsc.net:9988` | `https://test1.mrrc.vlsc.net`（443） |
| 落点 | 阿里云 hub（乌兰察布） | 海外 www.vlsc.net → 反代回 hub 的 9988 |
| 证书 | 自签 → 待 DNS-01 通配真证书 | **真证书**（www 上 certbot HTTP-01，80/443 在此可用） |
| 实测 RTT | **0.13 s**（`/login`） | **0.69 s**（`/login`，多一跳海外往返） |
| 适用 | 绝大多数用户 | 只放行 80/443 出站的网络（公司/访客 Wi-Fi） |

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
ssh www 'sudo bash /tmp/deploy_www_edge.sh test1.mrrc.vlsc.net tunnel.mrrc.vlsc.net:9988'
```

**验证结果（经 www 全程实测，2026-09-30）**：`/login` 200、`/api/health` 401、`/listen` 302；
**五个 WS 端点全部 `101 Switching Protocols`**（Cookie 鉴权，无凭据对照 403）。

### 还差你一条 DNS 记录

```
test1.mrrc.vlsc.net  →  A  193.111.30.163   （即 www，显式记录会覆盖 *.mrrc.vlsc.net 通配）
```

加完之后我可以 `certbot certonly --webroot -w /var/www/html -d test1.mrrc.vlsc.net`（www 上 80 口可用，
HTTP-01 没问题），重跑脚本即换成**真证书**、浏览器零警告。加之前用 `--resolve` 模拟已可全程验证。

## 已验证（2026-09-30 真实公网，安全组放行后）

安全组放行 8899/9988/8989 之后，**真实公网路径**（本机 → hub nginx:9988 → frps:8989 → frpc → 实例）
实测通过，无 SSH 转发、无端口映射、客户侧零入站：

| 检查 | 结果 |
|---|---|
| 命名 | 实例入口 `test1.mrrc.vlsc.net:9988`；隧道控制 `tunnel.mrrc.vlsc.net:8989`（均走 `*.mrrc.vlsc.net` 通配） |
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

安全组当时仍未放行，所以两条腿走了 SSH 本地转发（本地 18989→hub 8989、18988→hub 9988）。
**被验证的软件链条与真实部署完全一致**，只有"公网能不能到 hub"这一层没被覆盖。

| 检查 | 结果 |
|---|---|
| 隧道建立 | frpc `login to server success` + `[mrrc-test1] start proxy success` ✓ |
| TLS 终结 + 子域 vhost | `https://test1.mrrc.vlsc.net:9988/login` → **200**；`/api/health` → **401** ✓ |
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
