# 呼号自助 Portal（UC-H10 的实现）

按 **规范化 → 查重 → 核验 → 分配** 四步，把"接入一个实例"从手工改注册表变成一条自助闭环。

```
POST /apply    规范化（BG1SB ≡ bg1sb）→ 查重（同呼号拒绝，不静默覆盖）→ 核验
               应答里交付 **申请令牌**（应用在设置里存下它，凭它轮询 /status）
POST /status   申请方凭申请令牌查自己那一条；批准后给出 label/端口/登记口令/frps 令牌
POST /verify   人工核验通过（维护者 / 执照材料）
POST /grant    分配标签与端口 → 写注册表 → 打印实例侧上线命令
POST /enroll   实例提交自签证书的公钥（凭一次性登记口令；校内证书名字必须等于入口名）
POST /revoke   撤销并移除注册表条目（冒用被举报后走这里）
```

**申请令牌只在 `/apply` 的应答里出现一次**，且只够读自己那一条：改不了任何状态、也读不到别人的申请。
客户端若拿不到它就无法轮询批准状态 —— 这正是 V0.18 修掉的那个缺陷（当时测试从 store 直读令牌，
绕过了唯一真实的取令牌路径）。

## 为什么必须核验（本设计的立足点）

**呼号是公开标识**：它写在执照上、在 QRZ 之类呼号库里、在每次通联记录里。而按 AD-H15
入口名就是呼号（`<呼号>.mrrc.vlsc.net`），于是：

1. **入口可被枚举** —— 实例存在性必然可枚举，这一点 I-H9 已结案**接受**（拒绝它就得放弃
   "呼号即身份"，改用不可猜的 token 子域）。既然防不了"被猜到"，防线就只能放在别处。
2. **冒用成本极低** —— 任何人都能输入 `BG1SB`。不核验，就等于把一位真实持照者的身份、
   连同他名下那台**能发射**的电台，交给任何会打字的人。
3. **一次授予是长期的** —— 撤销需要人工介入，错授的代价远大于拒授。

所以核验被放在**授予之前**，并且是代码层的硬前置（`store.grant` 只接受 `verified`；
`Portal.grant` 在做任何写操作之前先查状态）。这条不变式由测试守着
（`tests/test_portal.py::test_grant_requires_verification` 与端到端用例）。

> 附一条实测教训：早期实现是"先写注册表、后调 `store.grant`"，于是未核验的申请虽被拒绝，
> **注册表里却留下了一行**（等于开了一个孤儿入口）。测试抓到了它。这就是为什么"写注册表"
> 必须发生在核验之后 —— 写注册表就是开入口。

## 怎么跑

```bash
# 自检（不监听）：看配置、注册表现有端口、令牌是否就位
python3 -m portal.app --dry-run

# 启动（默认只绑 127.0.0.1：这是管理面，不要直接暴露公网）
python3 -m portal.app --port 8890
```

配置（环境变量或命令行同名参数）：

| 项 | 默认 | 说明 |
| ---- | ------ | ------ |
| `--store` | `/etc/mrrc-hub/portal.json` | 申请/授予记录 + 追加式审计（原子写） |
| `--registry` | `/etc/mrrc-hub/instances.tsv` | 与 hub 上 `gen_hub_routes.py` 用的同一份 |
| `--callsign-db` | `/etc/mrrc-hub/callsigns.txt` | 呼号库，一行一个（`#` 注释）。有它就自动核验，没有就全转人工 |
| `--clublog` | `/var/lib/mrrc-hub/portal/clublog_users.json` | **Club Log 全库**（27 万条），与站内留言版同源；由 hub 每天 04:30 从 www 拉取 |
| `--token-file` | `/etc/mrrc-hub/portal.token` | 运维动作令牌（建议 0600，`openssl rand -hex 32`） |
| `--users-file` | `/etc/mrrc-hub/portal-users` | 后台账号（htpasswd `$apr1$`，一行一个 `用户名:哈希`；建议 `0640 root:mrrcportal`） |
| `--cookie-secure` | `auto` | 会话 Cookie 的 Secure：`auto` = 回环 Host 不带、其余带；`on`/`off` 强制 |
| `--session-idle-hours` / `--session-max-hours` | `8` / `24` | 会话空闲/绝对超时 |
| `--frps-api-url` | `http://127.0.0.1:7100` | frps 面板（`webServer`，只绑回环） |
| `--frps-credentials` | `/etc/mrrc-hub/frps-web.credentials` | 面板凭据（`user:password`，0640） |
| `--metrics-interval` / `--metrics-history` | `30` / `120` | 采样间隔秒（0=关采集器）/ 每实例保留样本数（≈1h） |

运维动作（`verify` / `reject` / `grant` / `revoke`）两条路径：浏览器用**会话 + 表单 CSRF 字段**，
脚本/curl 用 `X-Portal-Token` 请求头（只认请求头，不再收表单里的令牌字段）。

## 后台管理台：登录、会话与锁定

- **加账号**（标准命令，不自研 CLI）：

  ```bash
  printf '%s:%s\n' <用户名> "$(openssl passwd -apr1)" | sudo tee -a /etc/mrrc-hub/portal-users
  sudo chown root:mrrcportal /etc/mrrc-hub/portal-users && sudo chmod 640 /etc/mrrc-hub/portal-users
  ```

  （`htpasswd -m /etc/mrrc-hub/portal-users <用户名>` 等价，需 apache2-utils。）
- **只认 `$apr1$`**：bcrypt/SHA1 等前缀一律拒绝登录（fail closed），并在审计里记一条
  `login_failed`。密码用 apache MD5-crypt 纯 stdlib 重算（Python 3.13 已移除 `crypt` 模块），
  常数时间比较；用户不存在时也跑一次假哈希，响应时间不泄露用户是否存在。
- **会话**：登录成功发 `mrrc_portal_session`（HttpOnly / SameSite=Lax；公网 Host 带 Secure）。
  空闲 8h / 绝对 24h；登出与进程重启都会失效（会话只在内存，不落盘）。
- **CSRF**：管理台的导航是 GET `?view=`，**所有状态变更表单**带每会话随机的 `csrf` 字段。
- **防爆破**：用户名 5 次/5 分钟、来源 IP 10 次/5 分钟，各锁 5 分钟（429 + `Retry-After`）。
  来源 IP 仅在回环对端时信任 `X-Forwarded-For`/`X-Real-IP`；**nginx 没透传时会退化成
  127.0.0.1 全局桶** —— 部署检查单里要核对这一条。
- **审计归因**：动作与登录事件都记 `actor`（用户名 / `token`）；登录事件带来源 IP。
- **令牌仍可用**：账号文件丢了/不可读时管理台登不进去，但 `X-Portal-Token` 的机器路径不受影响。

## 隧道性能（「隧道」视图）

- 数据源：frps 面板（`webServer` 只绑 127.0.0.1:7100，Basic 认证）的 `trafficIn/Out`
  与 `todayTrafficIn/Out`、`curConns`；portal 后台线程每 30s 采一次。
- **带宽** = 累计字节的两轮差分；**延时** = 复用隧道四态探测的完整 TLS 握手计时（只在
  握手成功时给出，连不上的等待时间不算延时）。
- 历史只存内存（默认 120 样本 ≈ 1 小时，重启即清）；面板不可用/凭据不可读/代理不存在/
  计数器回绕/采样停滞都会在页面上**如实标注原因**，不用 0 冒充。
- `--metrics-interval 0` 关闭采集器（视图会说明未启用）；`--dry-run` 会打印账号文件、面板
  地址与采样间隔。

## 授予之后还有一步（故意不自动做）

`grant` 会写好注册表并打印实例侧命令，但**不会**重生成 nginx 路由 —— 那需要 root，
属于部署动作：

```bash
sudo /usr/local/sbin/gen_hub_routes.py && sudo systemctl reload nginx
sudo bash deploy/install_instance_tunnel.sh <标签> <端口>     # 在实例那台机器上
```

## 有意为之的边界

- **只绑 127.0.0.1**：要对外提供自助注册，请经 hub 的 nginx 暴露，并在那一层加限流
  （隧道路径下登录限流退化为全局桶的教训见 SDD §12.8）。
- **申请端点不要求登录**（自助的性质），因此它天然只能放在受控入口之后。
- 呼号正则**有意从宽**：真实世界的呼号形态远多于正则所能覆盖，边界情形靠人工核验兜底 ——
  这也是核验环节存在的意义。
- 实例存在性**可枚举是有意接受的性质**（I-H9），不是缺陷；Portal 的价值不在于藏，
  而在于"核验过才给"。
