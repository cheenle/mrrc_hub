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

1. **阿里云控制台 → 安全组入方向**放行：`80/tcp`、`443/tcp`、`7000/tcp`
   （80/443 给用户入口与 Let's Encrypt HTTP-01；7000 是 frps 的控制端口，实例要出站连它。
   只放行 `7000` 的话用户侧 443 仍然不通。）
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
  nginx :443  server_name test1.mrrc.vlsc.net
     └─ proxy_pass https://127.0.0.1:18888
           proxy_ssl_verify on                       ← 这一步是刻意的：
           proxy_ssl_name radio.vlsc.net                B2 现状是 proxy_ssl_verify off，
           proxy_ssl_trusted_certificate <系统 CA 库>    hub 侧必须开着校验证书
  nginx :80   ACME challenge + 301 → https
  frps :7000  bindPort（实例出站连它；token 鉴权 + TLS）
       :18888 tcp 代理端口（**只绑 127.0.0.1**，不暴露到公网）
       ▲
       │ 出站 WSS/TLS，客户侧零入站
       │
家宽 Mac（实例侧）
  frpc → 8.160.161.80:7000
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
curl -sI https://test1.mrrc.vlsc.net/login            # 期望 200（实例登录页）
curl -s  https://test1.mrrc.vlsc.net/api/health       # 期望 401（鉴权生效）
```

## 这次验证要检查什么（不只是"能连上"）

| # | 检查项 | 期望 | 对应设计主张 |
|---|---|---|---|
| V-a | 登录页可达 | `https://test1.mrrc.vlsc.net/login` 200 | AD-H01 / SC-H1（客户侧零入站） |
| V-b | 五个 WS 端点全通 | `/WSradio` `/WSspectrum` `/WSaudioRX` `/WSaudioTX` `/WSatr1000` 均完成握手（浏览器不复现"控制/频谱在、音频缺席"） | 透明代理契约 |
| V-c | **WS URL 里没有 `?token=`** | 浏览器 DevTools 的 Network→WS 请求 URL 无 token；`journalctl -u nginx` grep `token=` 无命中 | AD-H07 / NFR-H020 |
| V-d | **上游证书校验为真** | nginx 配置无 `proxy_ssl_verify off`；证书不匹配时链路应失败（可临时把 `proxy_ssl_name` 改错验证它真的会失败） | NFR-H021 |
| V-e | 遥测可读 | `GET /api/session_metrics` 返回计数（需会话） | AD-023 / hub I-H1 |
| V-f | 频谱带宽实测 | 一帧 1701 B × 30 fps ≈ 408 kbps（对齐 hub AD-H14 的 86% 结论） | NFR-H007/H008 |
| V-g | `/listen` 角色仍只读发射 | Listener 登录后 `/WSaudioTX` 应以 4003 关闭 | AD-H08 |

**V-d 的做法值得保留**：故意改错 `proxy_ssl_name` 看它失败，是"校验真的开着"的唯一证据——
这正是当初 B2 那行 `proxy_ssl_verify off` 能在生产里活下来的原因（没人验证过它会失败）。

## 尚未覆盖

- 通配证书（`*.mrrc.vlsc.net` 一张覆盖所有实例）需要 DNS-01，即 DNS 服务商 API 凭证；
  本目录用**每个名字一张 HTTP-01 证书**，够验证、不够 200 实例规模化。需要你确认 DNS 托管在哪、
  是否给 API 凭证。
- 多实例（`test2`…）可直接复用：再加一条 frpc 代理 + 一条 nginx server 块。
- Fleet Agent、设备证书、Portal、租约都还没实现（hub SDD 的阶段 2），本次只验证阶段 1 通路。
