# 实例生命周期与端口占用：一次 502 的完整取证（2026-10-11）

**一句话**：`bg7ifp.mrrc.vlsc.net` 的 502 不是网络、不是 nginx、也不是证书配置写错，而是
**一个已撤销（revoked）的旧实例仍在运行，并占住了门户刚刚分配给别人的隧道端口**；
而 hub 按"逐实例证书校验"拒绝它出示的旧呼号证书。当晚修好三台（bg1sb / ba4eg / bg7ifp），
并由此暴露两个真缺陷与两条审计口径问题。

---

## 1. 现象

| 入口 | 状态 | 解释 |
| --- | --- | --- |
| `bg7ifp.mrrc.vlsc.net` | 502 | 路由 → 18803；但 18803 上坐着的不是 bg7ifp |
| `bg8aaa.mrrc.vlsc.net` | 404 | 该呼号 2026-10-06 已撤销，路由随之删除 |
| `bg1sb` / `ba4eg` / `bg7kxr` / `bh7hcu` | 502 / 502 / 502 / 502 | 见 §4 的三类 |
| 其余 6 台（ba4slm / bh2xjd / bi6okx / bg7zhs / bg7zsb-legacy / bg6lh-legacy） | 502 | frpc 未连接（盒子未开），hub 侧无需处理 |

## 2. 时间线（全部取自 frps / nginx / 门户 audit）

```text
10-04 09:02–09:03  BG8AAA 申请→核验→granted（label=bg8aaa, port=18803）
10-04 09:1x        用户 MacBook 上的 MRRC-Modern.app 以 bg8aaa 身份连上，一直运行
10-06 07:41:22     门户登录（cheenle, ip=120.244.221.189）
10-06 07:50:54     BG8AAA revoked（actor=cheenle）          ← 授权撤销了，但机器没停
10-07 21:03:37     BG7IFP 申请（contact=7261808@qq.com）+ Club Log 自动核验
10-08 08:20:06     门户登录（cheenle, ip=223.104.41.24）
10-08 08:20:30     BG7IFP granted（label=bg7ifp, port=18803）← 同一端口被重新分配给另一个人
10-08 22:56        bg7ifp 的实例证书落到 hub（instance-certs/bg7ifp.pem）
11:17:41（10-11）  bg7ifp 的 Windows 机最后一次成功占住 18803
11:52:08（10-11）  MacBook 的 bg8aaa frpc 重连并抢走 18803
12:42 起（10-11）  bg7ifp 每 ~33 秒重试，new proxy [bg7ifp] error: port already used（当日 885 次）
20:1x（10-11）     排查与修复（见 §6）
```

**关键事实**：撤销发生在 10-06，而抢端口发生在 10-11 —— 之间隔了 5 天，说明**撤销不会切断机器**。

## 3. 诊断链（五步分诊，任何实例 502 都按这个顺序）

```bash
# ① hub：nginx 拒绝上游的真实原因（含 host 字段；hub_safe 记 URI 不记 Host）
sudo tail -200 /var/log/nginx/error.log | grep -E 'host: "|self-signed|Connection refused|certificate verify'

# ② hub：frps 上"哪个代理名占着哪个远端端口"（只读 dashboard，凭据在 /etc/frp/frps.toml）
U=$(sudo sed -n 's/.*webServer.user *= *"\([^"]*\)".*/\1/p' /etc/frp/frps.toml)
P=$(sudo sed -n 's/.*webServer.password *= *"\([^"]*\)".*/\1/p' /etc/frp/frps.toml)
curl -s -u "$U:$P" http://127.0.0.1:7100/api/proxy/tcp | python3 -m json.tool | head -40

# ③ hub：隧道对面到底是谁（IP / 主机名 / 系统 / frp 版本）与端口争夺
sudo grep -E 'client login info|new proxy \[' /var/log/frps.log | tail -40

# ④ hub：实例出示的证书 vs hub 手上那张（指纹比对，决定性）
echo | openssl s_client -connect 127.0.0.1:<端口> 2>/dev/null | openssl x509 -noout -subject -fingerprint -sha256
sudo openssl x509 -in /etc/mrrc-hub/instance-certs/<呼号小写>.pem -noout -subject -fingerprint -sha256

# ⑤ hub：门户的权威登记与审计（**注意：活档在 /var/lib/mrrc-hub/portal/**，见 §5）
sudo python3 -c "import json;d=json.load(open('/var/lib/mrrc-hub/portal/portal.json'));
v=d['applications'].get('<大写呼号>');print(v and {k:v[k] for k in ('status','port','label','history')})"
```

## 4. 三类根因（当晚五台在线实例的实测归类）

| 类别 | 表现 | 判据 | 实例 |
| --- | --- | --- | --- |
| **A. 端口被旧实例占用** | 路由指向 18803，但占着的是别的代理名 | ② 里代理名 ≠ 路由名；④ 里出示旧呼号证书 | bg7ifp（被 bg8aaa 占） |
| **B. 证书未生效** | 隧道在、代理名对，但出示的证书不是 hub 手上那张 | ④ 指纹不等；实例侧 env 已指向新证书但**进程没重启** | ba4eg（重启即修） |
| **C. 上游根本没有 TLS** | nginx 报 `peer closed connection in SSL handshake` | ④ 取不到证书 | bg7kxr、bh7hcu |

**B 类的机理**（最容易踩）：TLS 上下文只在进程启动时构建一次；Cloud Hub 的
enroll/重签发生在其后，于是进程继续出示旧证书 —— 盒子上一行
`systemctl restart mrrc-modern` 即可；桌面版需要"退出并重新打开应用"。

## 5. 两个真缺陷（建议立项，未在此修复）

### 5.1 撤销 ≠ 吊销 ≠ 断线（设计缺陷）

- 10-06 撤销 BG8AAA 后，那台机器**照旧连回**（10-11 11:52），并且**把门户已分配给 BG7IFP 的 18803 占住**。
- 机制：`frps` 不校验"这个名字有没有被授权"，只限制端口区间
  （`allowPorts = [{ start = 18800, end = 18999 }]`）；而**所有实例共用同一个 frpc token**
  （`/etc/mrrc-hub/frps.token.portal`），谁先到谁占。
- 后果：撤销过的实例可以长期占据端口，甚至可以抢占现役实例的入口 —— 属"不报错的故障"。
- 候选修法（按性价比排序）：
  1. **每实例独立 frpc user/token + `ports` 限额**（frp 原生支持），撤销时吊销该 user；
  2. 门户 `revoked` 时**通知该实例自停隧道**（需要有回连通道，可与 1 合并）；
  3. `allowPorts` 收窄为"注册表里的端口集合"（需要 frps 能读注册表或定期重载）。

### 5.2 退出应用不回收子进程（macOS，实测一次）

- 现象：在 MacBook 上用 AppleScript 退出 `MRRC-Modern.app` 后，**Launcher 退了，但
  `MRRC-Modern-Server`（PID 19194）与 `frpc`（PID 19195）成为孤儿（PPID=1）继续占着隧道端口**。
- 手动 `kill` 两个进程后隧道才释放。
- 与 v1.25.4 修的"每启动一次漏一个 frpc"同类，但出在**启动器→服务端**这一层的收尾。
- 待确认：菜单里的"退出"是否同样如此（本次只在 AppleScript quit 上复现）。

## 6. 当晚的修复记录（三台，含操作与可还原项）

| 实例 | 病因（类别） | 动作 | 结果 |
| --- | --- | --- | --- |
| **bg1sb**（本机 Mac mini） | 服务与隧道都没起；且**源码运行要找 `<repo>/fleet/frpc`** 而那里没有（`tunnel_started:false` **不报错**） | 起服务 + 放 frpc + 触发 refresh（enroll）+ 重启进程 | `/` → 302、`/login` → 200 |
| **ba4eg**（W103D 盒子 192.168.1.217） | B：证书 20:05 已装好，服务是 19:31 起的（未重载） | `systemctl restart mrrc-modern` | 302 / 200 |
| **bg7ifp**（其 Windows 机 MS-HNIHQJTDQNNQ） | A：18803 被 MacBook 上的 bg8aaa 占住 | 见下 | 40 秒后自动接管，302 / 200 |

**MacBook 上的动作（已告知操作者，可还原）**：

```bash
E="$HOME/Library/Application Support/MRRC-Modern/mrrc_modern.env"
cp "$E" "$E.bak-20261011-204707"        # 备份（原 mode 644）
# 移除 6 条 MRRC_CLOUD_*（CALLSIGN/LABEL/PORT/TOKEN/ENTRY/PORTAL）⇒ 不会再抢端口
# AppleScript quit 只退 Launcher，随后手动 kill 孤儿进程 19194 / 19195
# 还原：拷回 .bak 并重新打开应用（bg8aaa 已撤销，公有入口本就不可用）
```

## 7. 审计口径：两个坑与两处待补

1. **两个 `portal.json`** ✗：
   - `/etc/mrrc-hub/portal/portal.json` —— **10-02 就停笔的旧档**（其中根本没有 bg8aaa/bg7ifp）；
   - `/var/lib/mrrc-hub/portal/portal.json` —— **活档**（40 KB，随时在写）。
   审计一律读后者。建议把旧档改名或移走，避免下一次审计拿错。
2. **撤销类事件有 `actor`，自动授予类没有** ✗：10-01～10-05 的 `granted` 全部缺 actor，
   只有经门户 UI 授予的（BG1SB 10-05、BG7IFP 10-08、10-09 那批）记了 `cheenle`。
   想靠审计定责，建议 `granted` 一律写 actor。
3. **门户日志不记呼号** ✗（`portal: "POST /apply" 409 -`），且不记来源 IP（它看到的是 nginx 的
   127.0.0.1）⇒ "谁从哪做的"只有 audit 里的 `login_ok`/`login_failed` 能给。**这一类事件上次被我漏读，
   导致一度把来源误判为 SSH 来源**，在此记一笔。
4. **复核 `cheenle` 账号的登录面**（audit 汇总，10-05 → 10-11 共 9 个 IP，含 4 次失败登录）：

   | IP | 账号 | 次数 | 首次 | 末次 | 失败 |
   | --- | --- | --- | --- | --- | --- |
   | 183.241.215.1 | cheenle | 6 | 10-05 08:32 | 10-05 09:44 | 2 |
   | 183.241.215.1 | BG1SB | 2 | 10-05 09:34 | 10-05 09:35 | 2 |
   | 183.241.215.10 | cheenle | 1 | 10-05 14:59 | | |
   | 120.244.221.189 | cheenle | 1 | 10-06 07:41 | | ← 撤销 BG8AAA 那次 |
   | 120.244.220.165 | cheenle | 1 | 10-07 10:25 | | |
   | 223.104.41.24 | cheenle | 1 | 10-08 08:20 | | ← 授予 BG7IFP 那次 |
   | 223.104.202.87 | cheenle | 2 | 10-09 00:33 | 10-10 10:47 | |
   | 183.241.215.194 | cheenle | 1 | 10-10 20:36 | | |
   | 183.241.216.3 | cheenle | 6 | 10-11 07:43 | 10-11 19:33 | |

   均为移动/宽带出口；如有不认识的会话，应按"账号已外泄"处理（改密码 + 重签各实例 enroll secret）。

## 8. 方法论备忘（我犯过、值得记住）

- **端口分配史 ≠ 机器沿革**：端口是门户"授权给谁就指给谁"的资源，撤销后重新分配与前一呼号**毫无关系**。
  据端口把 BG9AAA→BG8AAA→BG7IFP 串成"同一台机器换呼号"是错的；反证早已在数据里
  （BG8AAA 申请 contact 为空 vs BG7IFP 为 `7261808@qq.com`）。
- **先看 frps 的代理名再谈证书**：只要 ② 里代理名 ≠ 路由名，后面所有证书分析都是在错误对象上做的。
- **audit 要按"事件类别"通读**：漏掉 `login_ok` 这一类，就会把"谁做的"归错。

## 9. 复现与验收清单

```bash
# 五台在线实例的入口（期望：前三台 302，后两台 502 且原因见 §4-C）
for h in bg1sb bg7ifp ba4eg bg7kxr bh7hcu; do
  printf '%-10s %s\n' "$h" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 https://$h.mrrc.vlsc.net/)"
done
```

**本次未解决、留给对应机主**：bg7kxr / bh7hcu 的实例**没有开 TLS**（未配 `MRRC_SSL_CERT/KEY`），
在 hub 的"逐实例校验"下必然 502；离线的 6 台待其盒子开机。
