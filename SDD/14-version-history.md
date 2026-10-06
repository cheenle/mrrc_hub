# 14. Version History

> 记录本 SDD 与其描述的系统的演进。每条必须说明：改了什么、为什么、影响哪些约束/决策。

## V0.30 — 2026-10-06 — 逐章对账（第二遍）：V0.29 只扫了一条轴

**触发**：V0.29 之后自查"SDD 是不是真的全面更新了"，答案是没有 —— V0.29 顺着**一条轴**清扫
（"实例侧 C1–C6 未合并 main / Stable 仍 v1.21.0"这类分支限定语），**没有逐章核对**。这一轮把
15 章（不含本节历史行，共 2679 行）按过期标记词过了一遍，再逐条核实。

**逐章结果**：

1. **§12.8.1 与 §12.8 自相矛盾（真陈旧）**：§12.8.1 结尾写"尚未上线：注册表条目、实例侧隧道、
   www 的产品段"，可**同一章的 §12.8** 记着 2026-10-04 的全量机上读数 —— 附加产品 `bg6lh-legacy`
   占 **18802**、在 map 里、入口 **302**，且 §12.8 自己的措辞是"不打断**正在服务的** legacy 入口"。
   已把 §12.8.1 的结论改为引用 §12.8 的读数，并显式说明**不对"该产品是否真在服务"下断言**（SDD 没记）。
2. **§7.x.1 照抄了同一句**（"尚未挂注册表"）—— 同步订正，并标明那是 2026-09-30 的原记。
3. **§10.8 措辞不严**：原文"尚未实现：实例清单服务"紧挨着它自己那句"租户管理 Portal 已实现并上线"。
   "清单**服务**"确实仍不存在（现状是静态注册表文件 + 路由生成），但逐实例**在线状态**自 V0.23 起
   已可由 portal 回环探测给出 —— 补一句把"可观测性"和"清单服务"分开。
4. **§12.8 的 `hub.vlsc.net` 证书待办：复核后仍开**。2026-10-06 实测握手，该名仍落到通配证书
   （`CN=*.mrrc.vlsc.net`，SAN 只有 `*.mrrc.vlsc.net` / `mrrc.vlsc.net`，到期 2026-12-29）。
   该句改为"待办（2026-10-06 实测复核，仍开）"。

**核实后判定"不是陈旧"，原样保留**：I-H6 / PTT 半开（NFR-H006、§15 §15.5 的 ❌ 表）、Operator 租约
（§10.8、§11、SDD/README）、设备 mTLS（§9）、配额与计费、§12 的 Operator 单次最长占用"需定值"；
以及 §9/§12 那句"新主机上的逐项现场读数尚未全部复测"—— 那是**自知的**限定语，没有证据表明已复测，
故不动（本轮只顺手复核了 DNS：`hub.vlsc.net` 解析到 `203.25.119.168` 与
`2403:2c81:2000:2189::a`，与 §12 记录一致）。

**方法说明**：按标记词（待实现 / 尚未 / 待决策…）grep 是**启发式** —— 不带这些字眼却已过时的断言
（例如把已经停了的事写成"已上线"）这一轮抓不到。真要穷尽，只能逐句对着系统读，那是比这两轮都大的活。

## V0.29 — 2026-10-06 — 对账轮：结清「实例侧未合并 main」这一整类叙述

**触发**：2026-10-06 `mrrc_modern` 的 `feat/hub` 并入 `main` 并发布 **v1.25.4**（本仓自己的
`feat/hub` 同日并入 `main`，打发布标记 tag `v1.0`）。于是本 SDD 里写于 2026-10-01～10-03 的
一整套限定语 ——「C1–C6 在 feat/hub 已实现但**未合并 main**」「Stable 渠道与产品站仍是
v1.21.0」—— 从当天起就是错的：它们描述的那条分叉已经不存在了。

**改了什么**（只订正"现状"叙述；历史条目一律不改，它们各自成立于当时）：

1. `SDD/README.md`：`SDD Version` V0.28 → **V0.29**，`Baseline Date` → 2026-10-06；Status 行里
   "实例侧…未合并 main、Stable v1.21.0 仍拼 `?token=`"改为"已随之发布，令牌按实例侧 **AD-024**
   走 Cookie / Bearer，`?token=` 仅兼容并告警"；`Instance baseline` 由 v1.21.0（`4f385dd`）
   改为 **v1.25.4**；能力表"实例侧 Hub 前置能力"同步。
2. §11.3 对账注 + "交付状态"：落点从"`origin/feat/hub`、**未合并 main**、Stable 仍 v1.21.0"
   改为"已随打包版发布（当前 v1.25.4）"；**保留**两条残留（Cookie 仍 `httponly=False`、无
   `Secure`，C3 仍 open）。原文引用的 v1.22.0/v1.23.0 是分支上的版本号，**从未发布**。
3. §12.8 实例侧运行一节：删掉"未合并进 main、无 tag、Stable 仍 v1.21.0"的限定。
4. §13 **I-H6**：删掉"未合并 main"；**"V1–V10 回归未跑"照旧保留** —— `mrrc_modern` 的
   SDD/15 仍写着该矩阵"须在 Hub 试点时在实例上复跑"，本条**没有**随合并关闭。
5. `README.md`：状态行原文写"架构评审完成；四项 MVP 前必修项待决策"，与实际（阶段 1 已在
   公网生产）不符；仓库关系里的产品基线 v1.21.0；以及工程约定里的 `sdd_context.py` 路径
   —— 原指向 `~/.pi/...`（上游未打补丁的副本），改为本仓携带本地补丁的
   `.agents/skills/sdd-guardian/harness/sdd_context.py`。
6. 站点三处叙述（`website/index.html`、`website/design.html`、`website/start.html`）与
   `website/README.md` 的"当前权威版本"。
7. `deploy/README.md`"装机后才暴露的三个缺陷"：第 3 项（PowerShell 把 openssl 的进度点当致命
   错误）**实际已修** —— `deploy/install_instance_tunnel.ps1` 现为 `$ErrorActionPreference =
   "Continue"` + 逐处显式查 `$LASTEXITCODE`，而原表仍标"✗ 未修"；标题里的"v1.23.1 待带"随之删除。

**为什么记一条版本行而不是改完就算**：这正是 V0.16 同型的问题（文档跑在现实前面），而 V0.16
的**订正本身**成了这次的原因之一 —— 它写下的分支限定，生命周期只有 5 天。分支型限定语应当
带"截至某时点"的写法，而不是当成长期事实。

**未解决（不受本轮影响）**：I-H6（隧道层 PTT 半开释放 + V1–V10 回归）、C3、`httponly=True`、
Operator 租约、设备 mTLS、安装包分发。

## V0.28 — 2026-10-05 — 后台管理台：一人一账号的登录，与隧道性能可观测面

**触发**：`/admin` 从上线起只有一个共享运维令牌（`X-Portal-Token`）——多运维无法归因
（“谁批的/谁撤的”只能写 token），而令牌从 `sudo cat` 里拷来拷去也不是人用的。同时 V0.24 的
可观测面在隧道层明确写着“frps 的每代理统计不可得”，于是「隧道带宽/延时」这条最常用的排障
事实只能 SSH 上去手工拼。

**已做**：

- **账号与会话**（新模块 `portal/htpasswd.py`、`portal/sessions.py`）：htpasswd `$apr1$`
  账号文件（`/etc/mrrc-hub/portal-users`，`0640 root:mrrcportal`，一人一账号）；纯 stdlib
  实现 apr1 校验（Python 3.13 已移除 `crypt` 模块），常数时间比较 + 用户不存在时假哈希；
  登录成功发 `mrrc_portal_session`（HttpOnly/SameSite=Lax，公网 Host 带 Secure、回环不带），
  空闲 8h/绝对 24h，状态变更要表单 CSRF；导航改为 GET `?view=`，新增登出。
- **防爆破**：固定阈值——用户名 5 次/5 分钟、来源 IP 10 次/5 分钟，各锁 5 分钟；成功登录清零。
  明确接受“按用户名锁可被恶意触发”的代价（规格决策 7）。
- **机器路径不动**：`X-Portal-Token` 只走请求头（表单字段移除）；审计新增 `actor` 字段与
  `login_ok/login_failed/login_locked` 事件（登录事件带来源 IP，仅管理台可见）。
- **隧道性能**（新模块 `portal/metrics.py`）：frps 开 `webServer`（只绑 127.0.0.1:7100，
  Basic 认证，凭据 0640 root:mrrcportal）；portal 后台线程每 30s 采代理流量差分算上下行带宽
  - 复用四态探测做 TLS 握手计时算延时，每实例内存环形历史 120 样本（≈1h）。新增「隧道」视图
  （延时当前/均值/峰值、带宽最近/均值、今日流量、连接数、采样新鲜度）；系统页③加面板状态/
  全代理合计/hub 网卡；总览页附摘要。
- **诚实降级**：面板不可用/凭据不可读/代理不存在/计数器重置/采样停滞，全部给可读原因，
  不用 0 冒充（延续 V0.24 的姿态）。

**边界**：

- **已部署（2026-10-05，hub `203.25.119.168`）**：账号文件 `/etc/mrrc-hub/portal-users` 已有
  首个账号；frps 面板已开（凭据 0640 root:mrrcportal）；portal unit 里过期的
  `MRRC_PORTAL_BASE=/mrrc_portal` 已移除。公网复验：4 个实例全部出带宽/延时/今日流量，
  审计出现 `login_ok`（`actor=cheenle`），租户页无回归。代码侧同时把登录/登出重定向改为
  **按请求路径推导**：unit 里那个变量曾让登录跳去租户页（nginx 把门户挂在根，
  `/mrrc_portal/*` 只是 301）、会话 Cookie 的 Path 也对不上。
- **部署中推翻的两个假设**：① frp 0.71 **不热重载** —— SIGHUP 让它**干净退出**，而 systemd
  把“干净退出”当成 reload 成功、不会自动拉起（实测 ~7 秒空窗后手工 start；已从
  `bootstrap-hub.sh` 与部署文档移除 `ExecReload` 写法）。② 0.71 面板**没有累计
  `trafficIn/Out`**，只有 `todayTrafficIn/Out` + `curConns`（采样器改按今日累计差分，跨日/
  重启由回绕检测兜底）。
- **会话在内存**：portal 重启即全部登出；不支持改密即时踢人（每次登录读账号文件，改密/删人
  对新登录生效）。
- **apr1 取舍**：MD5 系哈希抗 GPU 暴力弱于 bcrypt——账号少、密码强、有固定阈值锁定与
  nginx `limit_req` 兜底；该取舍记录在规格的决策记录里。
- **指标不落盘**：历史只存内存、重启即清；不做告警与图表。

**测试** 27 → **48 组**（新增 `test_htpasswd.py` 4、`test_portal_auth.py` 7、
`test_portal_metrics.py` 10；`test_portal.py` 27）。apr1 与 `openssl passwd -apr1` 交叉验证
（固定向量 + 随机 20 组）；登录/锁定/会话过期/登出/CSRF/令牌路径不回归；采样器差分/回绕/
缺失/降级（假时钟 + 假面板）；面板两种应答形态（0.71 的 `{proxies:[…]}` 与旧版裸列表）；
重定向跟随请求前缀（挂根/挂前缀）；隧道视图端到端拼接。规格：
`docs/superpowers/specs/2026-10-05-portal-admin-auth-tunnel-metrics-design.md`。

## V0.27 — 2026-10-04 — 注册表全量取证、主产品入口 `bg1sb` 补回；hub 日志被同名代理重试刷屏（根因在客户端）

**触发①**：§12.8 长期写着“注册表行数未取证、两处记录冲突”，而这次排查发现**主产品的裸呼号入口
`https://bg1sb.mrrc.vlsc.net/` 根本不工作**：返回 404 `unknown instance`。**取到的根因**：`bg1sb` 不在注册表里
（备份文件证明它原为 `bg1sb 18802 radio.vlsc.net`，18802 后来归了附加产品 `bg6lh-legacy`），
于是 map 的 `default 0` 直接 404 —— 而那是**与“未登记实例”同一个 404**，现场因此先被读成网络故障。
**已做**：按“不夺回 18802、不打断在服务的 legacy 入口”补回 `bg1sb 18804 radio.vlsc.net`（空闲端口），
30 s 的 timer 自动重生成 map + reload，无需手工介入；实测 `/login` **200**、`/api/health` **401**（v4/v6 都测），
`nope.mrrc.vlsc.net` 仍 **404**、`bg6lh-legacy` 仍 **302**。§12.8 的注册表一节改为 2026-10-04 全量机上读数（5 行）。

**触发②**：`/var/log/frps.log` 一天 8499 行 `already exists`（`ba4eg` 7143 / `bg9aaa` 994 / `bg6lh-legacy` 362）。
**根因不在 hub**：`client login info` 行指出刷屏的 5 个 run id 全来自**同一台 Windows 机器**（hostname `MRRC`），
上机看到 **6 个 `frpc.exe`**（命令行逐字相同、5 个的父进程已退出）—— 客户端回收旧 frpc 的代码依赖
**Win11 已移除的 `wmic`**，异常又被静默吞掉，于是每次启动漏一个。**已做**：hub 侧**不改配置**，
只把三步取证写进 §12.8「排障增补」；现场手工清掉 5 个孤儿（6→1），刷屏即刻停止（最后一条 22:21:02），
`ba4eg` 入口仍 302。修法在客户端 → `mrrc_modern/SDD/14` **V2.69**。
**边界**：`bg9aaa` 那台（win11 VM）复测时已无 frpc 进程、报错也在 09:08 自停；`bg6lh-legacy` 的 362 行经验是本机
重连窗口的重叠（新旧连接争注册），属正常抖动。

**附带取证（取代旧结论）**：新 hub 的 **IPv6 可达且 AAAA 已发布**（本机→hub 82 ms / 0% 丢包，
v4 对照 293 ms / 6.7%；同一请求 v6 0.37 s vs v4 1.40 s）⇒ §12.8 中“hub 的 IPv6 入站仍不可达”与旧机的
`accept_ra` 待办随搬迁作废；`tunnel.mrrc.vlsc.net` 的 AAAA 发布后 frpc 重连自己走了 v6。

## V0.26 — 2026-10-03 — 路由自动化在现网上其实一直是坏的（装配缺失），补齐并取证

**触发**：一台新实例（`bg6lh`，端口 18806）走完了全流程 —— 申请 → 批准 → 客户端登记证书 → `instance-certs/bg6lh.pem` 落盘 → frps 已在 `127.0.0.1:18806` 监听 —— **而入口返回 404**。

**取到的根因**：nginx 的 label→端口表由 `gen_hub_routes.py` 生成，它由 root 的 `mrrc-hub-routes.timer` 每 30 s 驱动；而现网 hub 上**只装了 `mrrc-hub-routes.service`**，包装脚本与 timer 都缺 ⇒ 该 unit 指向的 `/usr/local/sbin/mrrc-hub-routes.sh` 不存在 ⇒ 每次执行 `status=203/EXEC` ⇒ **自 2026-10-02 01:07 起路由从未重生成过**。`deploy/README.md` 里"`bootstrap-hub.sh` 会一并安装 ✓（不会再漏 ✓）"这句因此被实测推翻。

**已做**：按 `bootstrap-hub.sh` 第 285–290 行的原意补齐两件 —— 包装脚本（`install -m 755`，sha256 与仓库逐字节一致）+ timer（`install -m 644` + `enable --now`），跑一次后 map 里出现 `bg6lh 18806`、`nginx -t` 通过并 reload；实测入口由 404 变 302，且 `bg1sb` / `bg9aaa` 未受影响。之后 timer 每 ~35 s 触发、常态输出 `nothing changed; not reloading`，**从此新实例的路由与信任包在 30 s 内自动就位**（信任包同样在哈希比较范围内，所以只登记证书、不动注册表也会触发 reload）。

**同时修正的文案**：`portal/app.py` 的 `grant()` 对 `mrrc_modern` 客户端的 `next_step` 原写作"点「刷新状态」即自动完成" —— 自客户侧 v1.25.0 起应用会自己轮询并完成接入，该文案改为"无需操作；也可点刷新立即完成"。设计记录里的"path 单元"说明也已核对：`.path` 是**故意不装**的（`PathChanged` 会因 atime 更新自激，实测 2 分钟 232 次），只有 timer 该装。

**未处置**：另一台阿里云 ECS `8.160.161.80` 上跑着一套**分叉**的 frps+portal+nginx（注册表标签带 `-mrrc-modern` 后缀，自 2026-09-30 19:22 起无实例接入，DNS 不指向它）。`deploy/README.md` 已把它标注为历史目标，其退役与否待定。

## V0.25 — 2026-10-03 — 管理台与自助页的窄屏可用性：宽表堆叠成卡片，状态色收进 CSS

**触发**：V0.24 把实例页扩到 6 列之后，手机上已经没法看了 —— 证书主体
（`CN=bg9aaa.mrrc.vlsc.net`）、签发者（`C=US, O=Let's Encrypt, CN=YE1`）、HTTP 状态行
这类长串会把 6 列挤成一团或撑破容器。而运维**恰恰是在现场用手机**看这个页面的。
根因不是"列太多"，是整份 CSS 只有一条媒体查询、且只管 `.p-apply` 表单：表格、导航、
长字符串全都没有窄屏处理，`_page()` 有 viewport meta 但没有任何配套的响应式规则。

**已做**：

- **宽表在 ≤720px 堆叠成卡片**（`table.stack`）：每行变成一张卡，每格用 `::before` 显示
  小标题，标题取自该格的 `data-label`。表头不删除而是**视觉隐藏**（`clip:rect(0 0 0 0)`），
  读屏仍能拿到列名。两列的「项/值」表（总览、主机、隧道层、呼号库）本来就窄，标为
  `table.kv` 保持表格形态，只加 `overflow-x:auto` 兜底。
- **新增 `trow()` 助手**：一行由 `(窄屏标签, HTML)` 组成，标签与单元格**写在同一处**。
  这是刻意的结构选择 —— 若标签写在 CSS 里按列序号配（`td:nth-child(3)::before{content:"隧道"}`），
  以后插一列就会整体错位，而且错得静默。六个视图的行构造器全部改用它。
- **状态色从内联 `style='color:#34d399'` 收进 CSS 类**（`.pill.ok/.warn/.bad/.mute`），
  Python 侧只保留 `TUNNEL_PILL` 这个状态→类名的映射（`TUNNEL_COLOR` 删除）。
  散落各视图的内联颜色既无法统一主题，也让"哪些状态是同一严重级"看不出来。
- **导航改成 `<nav class=nav>` 弹性条**：可换行、按钮 `min-height:44px`（触摸目标下限），
  当前页用 **`aria-current=page`** 标记而不是内联 `font-weight:700`（语义 + 可被 CSS 控制）。
  表格内的动作按钮单独给 36px，不与主导航抢视觉重量。
- **长串不许撑破布局**：`td,th{overflow-wrap:anywhere;word-break:break-word}`，
  `td code` 允许换行（`white-space:normal`）；`body` 加 `-webkit-text-size-adjust:100%`
  防止 iOS 横竖屏切换时自动放大字号打乱布局。
- **公开自助页的「已授予」表同样处理** —— 那是租户在**自己手机上**看的表，
  不是运维内部页面，优先级不低于管理台。

**守卫**（`tests/test_portal.py`，套件 26 → **27 组**）：新增 `test_pages_are_mobile_suitable`，
用 stdlib `HTMLParser` **真解析**渲染结果（正则糊不住嵌套表格），对 7 个页面逐页断言：
有 viewport meta；**`stack` 表里每个 `td` 都带 `data-label`**（`colspan` 占位行除外）；
没有内联 `style='color:'`；导航恰有一项 `aria-current=page`；**每个视图至少有 N 张表挂着
`class=stack`**（这条是补的盲区：宽表若丢了 `class=stack`，它的 td 就退出 `data-label`
检查范围，守卫会静默放行）；CSS 里必须能找到窄屏断点、`::before` 小标题、`attr(data-label)`、
表头视觉隐藏、`min-height:44px`、`overflow-wrap:anywhere` 与徽章类；并断言 `TUNNEL_COLOR`
这个内联颜色字典已不存在。还有一条防空跑断言：实际检查到的 stack 单元格必须 > 20 个，
否则"页面没渲染出内容"会被当成"没有问题"。

**六处变异严格隔离验证**（改一处 → 跑 → 还原 → 断言干净），每处只打中该打的那条：
实例页某列丢掉 `data-label`；CSS 窄屏断点消失；`_page()` 丢掉 viewport meta；
状态色退回内联 `style`；实例页宽表丢掉 `class=stack`；CSS 丢掉 `min-height:44px`。

**边界**：

- 未做真机/浏览器实测。判据是**结构与 CSS 规则**层面的（DOM 里有 `data-label`、
  CSS 里有对应规则、无内联色），不是"在 iPhone Safari 上截图确认好看"。
  卡片式堆叠是成熟模式，但字号/间距的最终观感仍需一次真机过目。
- 打印样式、深色/浅色主题切换、以及 `prefers-reduced-motion` 均未涉及（页面本就无动画）。
- 只改了 portal 自己的 `_PORTAL_CSS`；`www.vlsc.net/js/global-nav.js` 那个全站导航条
  不在本仓，它在窄屏上的表现未验证。

## V0.24 — 2026-10-03 — 后台管理台的可观测面：从 hub 主机一路看到实例里那个应用

**触发**：V0.23 把「在线」的判据修对了，但管理台仍然只回答一个是/否。排 bg7zhs 时需要的事实散在
四个地方（`ss`、`systemctl`、`openssl s_client`、nginx 错误日志），而且其中一部分**只有 root 能看到**。
运维每次都要重新拼一遍，拼错一处就得出「三实例全离线」那种结论（本轮真的错过一次：先 SSH 到了
`deploy/README.md` 写的那台旧机）。所以把能采的事实一次性摆到页面上，并**如实标出采不到的部分**。

**先量边界，再设计**：portal 以非特权用户 `mrrcportal` 运行（`NoNewPrivileges=true`、不能 sudo），
所以「能看到什么」由那个用户的实际权限决定，不是由想看什么决定。2026-10-03 在 hub 上逐项实测：

| 可达 | 不可达 |
| --- | --- |
| `/etc/mrrc-hub/instances.tsv`、`callsigns.txt`、**`instance-certs/*.pem`** | `/var/log/nginx/*.log` ⇒ 拿不到每实例的 nginx 错误计数 |
| `/proc/{loadavg,meminfo,uptime}`、`shutil.disk_usage` | `/etc/frp/frps.toml` |
| `systemctl is-active/is-enabled/show`、`ss -tn` / `-ltn`（不带 `-p`）、`openssl` | frps 的每代理统计（未配 `logFile`、未开 `webServer` 面板） |

**已做**：

- **实例页从 4 列扩到 6 列**，一次探测采齐三层事实（不再多开连接：证书是在同一次 TLS 握手里用
  `getpeercert(binary_form=True)` 顺带取走的）：隧道状态（V0.23 的四态）、**实例里那个应用**
  （HTTP 状态行、`Server` 头、`sw.js` 的 `CACHE = 'mrrc-vNN'` 构建代号）、**上游证书**
  （主体 / 自签还是 CA 签 / 到期日与剩余天数 / **名字是否与注册表期望相符**）。
  实测渲染：`bg9aaa | 在线 | HTTP/1.1 401 Unauthorized / server: uvicorn / 构建代号 mrrc-v99 |
  CN=bg9aaa.mrrc.vlsc.net / 自签 / 名字相符`；`bg7zhs | 隧道在、后端无应答 | — | —（握手没成）`。
- **补上 V0.23 记下的那条边界**：「实例在服务、但证书签给了错的名字」以前显示为 `serving`，
  而 nginx 对上游开着证书校验 ⇒ 同样 502。现在 `Registry.entries_full()` 交出第三列 `tls_name`
  （老式实例写自己的域名如 `radio.vlsc.net`，新式自签租户不写则派生 `<label>.mrrc.vlsc.net`），
  探测据此比对 CN/SAN，不符就在页面上标红「名字不符 ⇒ nginx 必 502」。`entries()` 仍是两列，
  既有调用点与测试不受影响。
- **新增「系统」视图**，按层排：① hub 主机（负载 / CPU / 内存含可用百分比 / 磁盘 / 已运行 / Python）
  ② hub 服务（`WATCHED_UNITS` 六个单元的状态、开机自启、起于、重启次数）③ 隧道层
  （8989 是否在听、frpc 控制连接数与对端 IP、**注册了但没在听** / **在听但注册表里没有**两个差集）
  ④ hub 侧已登记的实例证书清单（文件名 / 主体 / 到期 / 剩余天数）。
- **「未安装」是一种结论而不是错误**：`is-enabled` = `not-found` 时明确这么报。这直接暴露了一个真实缺口 ——
  **`mrrc-hub-routes.timer` 根本没装在 hub 上**（`list-unit-files` 里只有 `mrrc-hub-routes.service`(static)
  与 `mrrc-portal.service`），而 V0.22 写着「V0.17 起 30 s timer 自动重生成路由」⇒ 新增/撤销实例后
  nginx 路由**不会**自动出现，入口一直 404 直到有人手工跑 `gen_hub_routes.py && reload nginx`
  （正是 portal 页面自己提示的那条命令）。仓里 `mrrc-hub-routes.{timer,path}` 两个单元文件都在，只是没装。
- **采集器一律降级而不抛异常**：读不到就给可读文案（`读不到：[Errno 2] …`、`systemctl 不可用`、
  `（证书目录不存在或不可读：…）`）。管理台是排障入口，它自己 500 了就什么都看不到。
  其中「证书目录读不到」必须与「没有实例登记过」分开报 —— `Path.glob()` 对不存在的目录
  **不抛异常、只返回空**，`try/except` 拦不住，会把权限故障显示成业务事实。
- `_days_left()` 用 `calendar.timegm` 解析 openssl 的 GMT 时间（既有的 `_cert_days` 用 `mktime`，
  会带进最多 ±14 小时的本地时区偏差 —— 那是既有行为，本轮不动，只在新代码里做对）。
- `Registry._parse_port()` 收紧：非十进制、`0`、`>65535` 一律当无效行跳过。注册表是 root 用编辑器
  手改的文件，`999999` 以前会被照单收下，然后在探测与 nginx 那边才炸。同时把「注册表不可读」
  改成明确的 `RuntimeError` 而**不是**返回 `[]`：`Portal.grant()` 用它查重并挑空闲端口，
  读不到就当「注册表是空的」会把新实例分配到别人正在用的端口上，直接切断一个活实例 —— 宁可炸，不要猜。
- 删掉重构后剩下的死代码 `_probe_http_status`（与新的 `_probe_http` 近乎重复），并把「任何状态码都算
  在服务」的论证搬到活的那一个上，不连理由一起丢。

**测试** 16 → **26 组**。桩后端按路径分流（`/api/health` 回 401 + `Server: uvicorn`，`/sw.js` 回带
`CACHE = 'mrrc-v99'` 的正文），于是第 5 层可测；`systemctl`/`ss` 用替身 `_run` 喂固定输出，
不依赖宿主是不是 systemd。**八处变异严格隔离验证**（改一处→跑→还原→断言干净），每处只打中该打的那条：
证书目录读不到时静默返回空、frpc 对端不归一化、监听端口不做范围过滤、单元缺失不再报「未安装」、
不再比对证书名、不再取构建代号、注册表不交出第三列、端口越界不拦。
另补一条**端到端渲染**测试：既有的 `test_admin_ui_flow` 是用空注册表渲染实例页的，
新加的那几列从来没被真正拼过 —— helper 各自返回对的值，不等于页面把它们拼对了。

**边界**：

- **未部署**：改动只在仓库里，hub 上跑的仍是 V0.23 之前的判据与四列实例页。
- **构建代号不是 semver**：实例没有任何未鉴权的版本端点（`/api/*` 全部要令牌；`/login`、`/manifest.json`、
  `/version.txt` 实测都不含版本号），所以只能取 `sw.js` 里那个每次改静态资产都会 bump 的缓存代号，
  用来判断各实例**是否同代**。要拿到确切版本，得让应用自己上报（它轮询 `/status` 时带上
  `support_bundle.detect_version()`），那是一次应用侧改动，不在本服务能单独完成的范围内。
- **实例内部状态看不到**：电台是否连着、有没有在录音、会话数——全在令牌之后。这是设计使然
  （hub 不持有租户凭据），不是遗漏。
- nginx 每实例错误计数与 frps 每代理统计仍不可得（见上表）。要给它们，得改日志权限或给 frps 开面板，
  两者都是 hub 侧的运维决定。
- `mrrc-hub-routes.timer` 缺失这件事**只是被暴露出来，本轮没有装**（装单元需要 root，属于部署动作）。

## V0.23 — 2026-10-03 — 「在线」必须意味着真的在服务：隧道判据从 TCP 可连改为拿到 HTTP 应答

**触发**：bg7zhs 排障。门户总览与实例页判定「隧道在线」的依据是 *hub 回环上该端口能不能 TCP 连上*，
而 **frps 是在 hub 本机接受连接的** —— 只要 frpc 注册过代理，这个连接就永远成功，与隧道另一端有没有
程序在服务**完全无关**。bg7zhs 正是这个状态：frpc 控制连接活着（来自 `39.144.70.1`，与 bg1sb/bg9aaa 的
`120.244.220.52` 不同网段）、frps 在听 `127.0.0.1:18805`、hub 上 `bg7zhs.pem` 已于当天 10:37 签发，
总览于是显示「在线」；而从 hub 直连 18805，**明文与 TLS 都拿不到一个字节**，每个访客得到 nginx 的 502
（`error.log`: `peer closed connection in SSL handshake while SSL handshaking to upstream`,
`upstream: "https://127.0.0.1:18805"`）。对照组 bg9aaa(18803)/bg1sb(18802) 同样的探测分别得到
TLS 200 + `CN=bg9aaa.mrrc.vlsc.net`（自签）与 TLS 200 + `CN=radio.vlsc.net`（Let's Encrypt）。
**后果是排障方向被指错**：运维照着「在线」两个字会一路查 nginx 与证书，而真因在租户机器上。

**已做**：

- `_tunnel_state()` 取代布尔判据：完成 TLS 握手并要一次 `/api/health`，**任何 HTTP 状态码都算在服务**
  （包括 401/404）—— 与 `mrrc_modern/launcher_net.answers()` 同一个判据；那边正是因为把 401 当失败，
  才让启动器在服务器明明活着的时候去开了另一个协议（v1.24.6「装完黑屏」）。
- **四种结论而不是两种，因为修法完全不同**：`serving`；`plain-http`（应用起来了但没加载证书，而 nginx
  以 https 反代并校验上游 ⇒ 访客必 502，即 v1.24.5 黑屏的同一形状）；`hollow`（隧道在、后端空：frpc 在跑
  但它转发的本地端口上没有程序 —— 应用没起 / `localPort` 与 `MRRC_WEB_PORT` 不一致 / 绑到了别的地址）；
  `down`（端口没人听 ⇒ frpc 根本没注册代理）。bg7zhs = `hollow`，bh1eih = `down`（无证书、18804 未监听）。
- **不校验证书**：实例证书是自签的（`CN=<label>.mrrc.vlsc.net`），而 bg1sb 那类老实例用自己的
  `radio.vlsc.net`（注册表第三列 `tls_name`，且 `Registry.entries()` 只返回 `(label, port)`、第三列被丢掉）。
  证书名对不对是**另一个**故障模式（nginx 会记校验失败），这里只回答「有没有在服务」。
- `_tunnel_states()` **并发**探测：最坏情况是每个实例都黑洞（要等到超时），4 个实例串行就是 4×2×timeout，
  总览页不该为此卡住。实测 3 个黑洞端口：并发 1.6 s、串行 4.82 s。
- 页面文案跟着判据改：总览不再只给一个数字，而是「注册表实例 N 个，其中**真正在服务** M 个」，并把每个
  不在服务的实例连**原因**一起列出；实例页状态格用琥珀色区分两类「连得上但用不了」（`plain-http`/`hollow`）
  与红色的真离线，`title` 悬停给探测详情；脚注从「「在线」= hub 回环上该端口可连接 ⇒ frpc 隧道已建立」
  改为实测判据，并写明 `hollow` 时该去租户机查哪三件事（应用在不在跑、frpc 的 `localPort` 是否等于
  `MRRC_WEB_PORT`、`MRRC_WEB_HOST` 是否被改成局域网 IP —— 那就只听那个地址，frpc 拨 127.0.0.1 必然失败）。
- 测试 16 → **19 组**：用 openssl 造夹具证书（沿用本仓既有的 `-config` 形式，macOS 自带 LibreSSL 没有
  `-addext`），起四种假后端（`tls`/`plain`/`hollow`/`blackhole`）。**`hollow` 那条是回归守卫**：
  旧判据在它面前返回 True。**五处变异逐条验证**，每处只打中该打的那条断言：改回旧的 TCP-only 判据 ⇒
  「hollow 不得再被当成在线」红；批量改回串行 ⇒ 「并发探测（实测 4.82s）」红；明文 HTTP 也算在线 ⇒
  两条 `plain-http` 断言红；`down` 报成 `hollow`、`hollow` 报成 `down` 两个方向各红一组。
- 顺带修掉 `tests/test_portal.py` 里两处对 `store.get()` 结果直接取属性的既有告警，改用本文件自己的
  `stored()` 助手（其 docstring 即「用清晰的失败代替对 None 取属性」）。
- 顺带订正本卷自身的漂移：`SDD/README` 的 `SDD Version` 停在 **V0.21**，而 V0.22 已经入档
  （V0.22 条目自称把 README 从 V0.20 改到 V0.21，漏了它自己）。本仓没有文档一致性门禁
  （`tests/` 只有 `test_portal.py`，不像 `mrrc_modern` 有 `release_check.py` + 版本一致性测试），
  所以这类漂移只能靠人；本次一并改到 V0.23。

**边界**：

- **未部署**：改动只在仓库里，hub 上跑的 `mrrc-portal` 仍是旧判据（需重启服务才生效）。
- **证书名不匹配仍不可见**：`plain-http` 与 `hollow` 已可区分，但「实例在服务、只是证书签给了错的名字」
  会显示为 `serving`，而 nginx 那一跳同样 502。要覆盖它得在探测里比对证书 CN/SAN 与注册表的
  `tls_name`（并让 `Registry.entries()` 交出第三列）。
- **frps 侧零可观测性依旧**：`/etc/frp/frps.toml` 没配 `logFile`、没开面板（`webServer`），journald 里
  只有 systemd 的启停行、**没有任何 frps 应用日志**。本次排障因此只能靠 nginx 错误日志 + 从 hub 直接探测
  反推，拿不到「工作连接为什么失败」的服务端证据。建议至少把 frps 日志接到 journald 并开 info 级。
- **另有一台同角色机器**：`8.160.161.80`（阿里云，hostname `iZ0jlaouy9vk8n98wfp3a6Z`）跑着同样的
  frps/mrrc-portal/nginx 与**已分叉的注册表**（`bg9aaa-mrrc-modern`/`bh1eih-mrrc-modern`，带后缀，
  与真 hub 的 `bg9aaa`/`bh1eih`/`bg7zhs` 不一致），自 2026-09-30 19:22 起**从未有客户端连上**；
  而 `deploy/README.md` 仍把 SSH 地址写成它 —— 本轮排障一开始就被带错，据此得出过「三实例全离线」的
  错误结论。与 V0.22 边界里记的 `deploy/frpc-instance.toml.example` 的 `serverAddr` 仍是 `8.160.161.80`
  属同一批残留，建议一并处置（下线，或在文档里标明是旧机/备机）。

## V0.22 — 2026-10-02 — 两张架构图按 V0.21 重绘；「两条路」残留在 SDD 与 deploy/README 里一次清掉

**触发**：V0.21 当天把门户/入口/站点合并到一台机器，代码与 SDD 正文跟上了，但 `docs/` 里两张图
（逻辑 `architecture-2026-10-01-as-built.*`、物理 `physical-architecture-2026-10-01.*`）和若干段落仍画/写着
「两条路、三台主机、`:9988`/`:8899`」—— 读者照着旧图排障，会走到已经删除的路径上。

**已做**：

- 新图 `docs/architecture-2026-10-02-as-built.{svg,png,html}` 与
  `docs/physical-architecture-2026-10-02.{svg,png}`：一台机器、443 唯一入口、8989 唯一独立端口；
  物理图由三块改两块（主机③ 并入主机②），两图各加「V0.21 删掉的（存史）」与「合并的代价：单点变大了」；
  HTML 附录逐条记录对 10-01 版的订正，并单列**未取证因而不画**的事实
  （新机规格/SSH 账号/安全组明细、新机 IPv6 可达性、通配 A 现值、注册表行数、47.80.243.9 的后续处置）。
  旧四件留作快照，页头标注已停止维护。
- SDD 与 deploy/README 的一致性修订：`SDD/README` 版本号 V0.20→V0.21、AD/NFR 编号上限、ICP 备案不再列剩余项；
  `SDD/09` §9.9 删自相矛盾句（「Portal 未落地」）与「三台主机、两个入口」；`SDD/12` §12.8 标题日期改 2026-10-02、
  **AD-H21 悬空引用改指 `08` 卷首未编号的 V0.21 一节（不新造 AD-H21）**、排障表坏行修复、
  §12.9 三条 V0.20 残留（门户主机 47.80.243.9、跨机 `mrrc-portal-sync.timer`、三条跨机耦合）与
  「grant 后仍需 root 手工重生成路由」的旧说法（V0.17 起 30 s timer 自动，Portal 无 reload 权限是有意分工）；
  `SDD/04`/`05`/`10` 三处坏表格行与已删退化路径的活口语气；deploy/README 漂移表 X1 按现码重写
  （现存漂移：`deploy_hub_routes.sh` 仍写死 `proxy_ssl_name radio.vlsc.net`、生成 vhost 头部注释仍写 self-signed），
  X2/X3 随边缘删除标存史。
- 记录冲突入档而不编数据：注册表「机上读数 1 行」与「V0.21 两条已迁移」并存，两处都标未取证；
  118–168 ms 往返标为旧 hub 读数、迁港后未复测。

**边界**：本轮只动文档与图。代码侧的同源滞后**未动**（另案，见下）：
`deploy/bootstrap-hub.sh` 整体是 pre-V0.21 夹具且引用从未定义的 `$SELF_DIR`（`set -u` 下必失败）；
`deploy/deploy_www_edge.sh` 服务于已删除的边缘路径；`deploy/gen_hub_routes.py` 对 map 与信任包是
直接覆盖写（NFR-H031 要求原子替换，只有「`nginx -t` 过了才 reload」那半句被 timer 兑现）；
`deploy/mrrc-hub-cert.sh` 的 `write_cert_info()` 定义在 `exit` 之后、永不被调用；
`portal/app.py` 管理台文案仍打印手工 root 命令、docstring 只列四个端点（实为 9 POST + 2 GET）；
`deploy/frpc-instance.toml.example` 的 `serverAddr` 仍是 8.160.161.80。

## V0.21 — 2026-10-02 — 一台机器：门户/入口/站点合并，只留 8989

- 整站迁到香港 VPS `hub.vlsc.net`（203.25.119.168），它与 `www.vlsc.net`、门户是同一台机器。
- 门户挂在根：`https://portal.mrrc.vlsc.net/`（旧 `/mrrc_portal` 301）。
- 实例入口回到 **443** 且不再带端口；`:9988` / `:8899` 两个监听取消，**只留隧道控制 8989**。
- 标签 = 裸呼号（`bg9aaa`，不再 `bg9aaa-mrrc-modern`）；已有两条记录已迁移，端口不变。
- 边缘路径（`www` 反代）整体删除，应用只认一个门户地址；旧地址在 v1.24.4 里自动改道。
- 实测更正：`:8899` 从未对公网开放 —— 这才是"申请成功但状态刷不出来"的根因，见
  `08-architecture-decisions.md` 卷首的 **V0.21** 一节（该节未编号；本仓没有 AD-H21）。

## V0.20 — 2026-10-02 — Portal 迁到 47.80.243.9（用户面 8899 / 边缘面 9988），并给它装上自维护

**触发**：操作员要求把 `portal.mrrc.vlsc.net` 迁到新主机 47.80.243.9（并即将切换解析）；老 hub 的 v6 不可达（见 V0.19），把门户与 hub 的角色拆开。

**已做**（全部在 47.80.243.9，Ubuntu 26.04 / nginx 1.28.3）：新建 `mrrcportal` 服务账号与目录；代码按 hub 仓 HEAD 部署（含 V0.18 的令牌交付与 `/claim`）；**数据整体搬迁**并双侧 `sha256` 校验一致：`portal.json`、`instances.tsv`、`portal.token`、`callsigns.txt`、`frps.token.portal`、`instance-certs/`、`clublog_users.json`（36 MB，273,047 条）、`cert.txt`；通配证书 + 私钥随迁（`/etc/mrrc-hub/tls/`）；两套 vhost（8899 用户面带 `/apply` 限流、9988 边缘面）、`hub_safe` 日志格式、限流 zone、`proxy_params_mrrc_portal` 全部照搬；systemd 单元与 hub 同构。

**验证**：本机 8899/9988 均 200；协议级 `apply`（32 字符令牌）→ `status`（applied）→ `claim` 错口令 403 → 错令牌 403 → `reject` 清理 200；**外部**：9988 从本机与从边缘都通（0.12–0.40 s），**8899 仍被安全组拦（待开）**；边缘 `/mrrc_portal/` 上游已切到 `47.80.243.9:9988`，边缘路径 6/6 200（0.37–0.59 s），且**新主机访问日志**里正是边缘 IP 的那 6 条（`193.111.30.163 … 200 rt=0.003`）—— 请求真的落到了新主机，不是缓存或旧路径。

**自维护**（否则证书续期/每日呼号库会让门户悄悄坏掉）：hub 新增受限导出 `/usr/local/sbin/mrrc-hub-export-for-portal.sh`（root 的 `authorized_keys` 用 `command=` 绑定，只吐一个 tar，拿不到 shell）；新主机每日 08:30 由 `mrrc-portal-sync.timer` 拉回证书/私钥/呼号库（沿用 hub 的**规模门 ≥10 万条**，换库后重启 portal —— 因为 `ClubLogVerifier._index` 是进程内缓存；只有证书变了才 `reload nginx`）。真跑一次：273,047 条 ✓、证书未变 ✓、portal active ✓，双侧哈希一致 ✓。

**仍留在老 hub 的耦合（必须记住，别以为迁完就无关了）**：
① **注册表**：`grant` 改的是**新主机**的 `instances.tsv`，hub 的入口不会自己多一行 —— 运维仍需把这行同步到 hub 并跑 `gen_hub_routes.py`（V0.17 的 timer 只负责重生成，不负责搬文件）；
② **instance-certs**：`/enroll` 落的实例证书现在落在新主机，而 hub 的 nginx 逐实例校验需要它们 + hub 的 `trust-bundle.pem` ⇒ 迁移或登记后要把证书同步到 hub 并重建信任包；
③ **边缘信任文件**：新主机用的仍是 hub 签发的通配证书 ⇒ 证书续期后除了新主机（本 timer 已覆盖），还要更新边缘的 `/etc/nginx/mrrc-hub-trust.pem`（这是 hub 文档里咬过两次的 502 坑）；
④ 切换前**老 hub 的 `mrrc-portal` 仍在跑**：两套 store 会分叉 ⇒ 切解析那一刻要重拷 `portal.json`/`instances.tsv`，然后停掉老服务。

**未做/边界**：8899 安全组待放行；DNS 切换由操作员进行，切换后的三步（重拷状态、停老服务、更新 §12.8 主机表）在本文末列出。

## V0.19 — 2026-10-02 — 边缘间歇故障的真凶：nginx 选中了 hub 不可达的 IPv6

**触发**：给 `www.vlsc.net` 与 `*.mrrc.vlsc.net` 都加上 AAAA 后，准备把服务器到服务器的跳数改走 IPv6。

**测量（先量后改）**：边缘→hub v6 **0/4 全超时**、v4 4/4 通（0.4–0.8 s）；hub→www v6 0/2；hub 自身 v6 出站（含 google）全失败；而**边缘自身的 v6 是好的**（google 0.1 s 200）⇒ 坏点在 hub 的 v6 入站/出站，不在边缘。

**顺带定位了 V0.17 记录的那条「边缘间歇无响应」**：边缘那两处指向 hub 的 `proxy_pass` 写的是裸主机名（无 `resolver` ⇒ 启动时解析一次），而本机 `getaddrinfo` 按 RFC6724 把 AAAA 排在前面 ⇒ nginx 选中 hub 的 IPv6，而该地址不可达 ⇒ 请求挂到客户端放弃（499）。这正是「6 次里 3 次 20 s 无响应」的形态，当时只定到「`www → hub:9988` 这一跳」并猜成云厂商限流。**修法**：两处 `proxy_pass` 钉为 `8.160.161.80:9988` + reload；复测 `/mrrc_portal/` **8/8 200**、实例入口 4/4 302。

**仍未解决（需要控制台动作）**：① 阿里云安全组的 IPv6 规则 / VPC IPv6 公网带宽 —— hub 的 v6 地址与默认路由都在、网关 REACHABLE、本机 ufw/ip6tables 全开，但出站 v6 无响应，边缘也到不了它；② hub 上 `net.ipv6.conf.eth0.accept_ra=0`：RA 派生的地址与默认路由（`expires 8981sec`）不会续期，即使放行也会在约 2.5 h 后消失，应设 `accept_ra=2` 并写进 netplan。**v6 验通前不要把边缘改回主机名**（见 deploy/README 漂移表 X3）。

**边界**：本次只动 www 上的一处配置（已备份 `vlsc.net.bak-20261001_204315`）并 reload；hub 与 VPC 侧没有任何改动。

## V0.18 — 2026-10-02 — 申请令牌其实从没交到申请方手里（应用因此永远等不到批准）

**触发**：客户端（mrrc_modern `feat/hub` 的「接入云端」）修掉自己的两个缺陷后做真机联调，仍在最后一步
失败：`POST /apply` 回 200，但应答里没有 `request_token`，应用报 "portal did not return a request token"
—— 拿不到令牌就无法轮询 `/status`，批准与否都到不了应用。

**根因**：V0.16 引入申请令牌时只加了 `/status`（凭令牌读自己那一条），`/apply` 的应答从未把令牌交出去；
而当时的测试从 `store.get(...).request_token` **直读 store** 取令牌，把唯一真实的取令牌路径 —— HTTP 应答
—— 绕过去了。同一类盲区（测试用了只有测试能用的入口）当晚在客户端也刚咬过一次（`import cloud_hub`）。

**改动**：`Portal.apply()` 的应答增加 `request_token`（只随这一次应答交给申请方本人；读不了别人的申请、
也改不了任何状态）。测试改为**从 `/apply` 的 HTTP 应答取令牌**再走完 `/status` 全流程（错令牌 403、
拿别人呼号 403、`applied` 不泄露接入字段、`granted` 才给 label/端口/口令/入口），并把 `store.get()` 的
Optional 访问统一换成显式断言 `stored()` —— None 不该变成 AttributeError。

**同一批排障里顺手修掉的旧账**（都在 `portal/app.py`）：`_admin` 两个视图各定义了一个同名 `probe()`
（bool 版与 HTML 版，同一函数作用域互相遮蔽）→ 合为 `_tunnel_online()` + 实例页的 `tunnel_cell()`；
`log_message` 的参数名改回基类的 `format`；`_body()` 把 `Content-Length` 与 JSON 解析失败包成
`ValueError`（调用方本来就把它们变成 400「请求体无法解析」，现在连原因也写清楚）。

**验证**：`python3 tests/test_portal.py` 15 组通过（改前先在「`/apply` 不交令牌」上红）；追加探针确认
坏 JSON body → 400、正常表单 → 200。部署到 hub（备份 `app.py.bak-20261001_202921` + 覆盖 +
`systemctl restart mrrc-portal`，服务 active）。**公网实测**（`portal.mrrc.vlsc.net:8899`，即应用默认入口）：
`POST /apply` `bg1prb` → 应答含 32 字符令牌；`POST /status` 用它 → `200 applied`，label/port/secret/entry
全空；错令牌 → `403 申请令牌无效`。两条探针记录（`BG1PRB`、`BG1SMK`）已按惯例拒绝清理并留审计。

**未解决**：批准之后仍需运维动作才能开入口（`/grant` + 路由重生成 —— 后者已由 V0.17 的 timer 自动完成），
这是刻意的分工；应用侧「申请 → 等待 → 自动接好」的全链路，待 mrrc_modern v1.24.1 发布后在真实租户机上
复测（本轮验证到协议层：令牌交付与状态查询）。

## V0.17 — 2026-10-02 — 批准之后不再需要任何人敲命令；接入搬进应用（hub 侧接线）

V0.16 把登记链跑通，但最后一步仍是"运维在 hub 上执行一条 root 命令"。本版把它取消，并补上应用
自助接入所需的两个 hub 侧接口。

1. **路由与信任包自动重生成**（`deploy/systemd/mrrc-hub-routes.{timer,service}` +
   `mrrc-hub-routes.sh`，root）。30 秒一次：先哈希 map 与信任包 → 跑 `gen_hub_routes.py` →
   再哈希 → **只有真的变了**才 `nginx -t` + `systemctl reload nginx`（`nginx -t` 不过就保持运行中
   的配置不动并报错退出）。实测：加一个实例 ⇒ `map: written (4 instance(s))` + reload ✓；
   撤掉 ⇒ 又变回 3 ✓；只加注释 ⇒ "nothing changed; not reloading" ✓（注释不影响生成物 ✓）。
   仍守着 AD 的分工：**接收公网输入的 Portal 服务不获得 reload nginx 的权限**，这是独立的 root 单元。
2. **`POST /status`**：申请方（应用）凭申请令牌查询自己那条申请；批准后返回 label/端口/一次性口令，
   以及**隧道登录用的 frps 令牌**（租户拿不到运维密钥 —— 令牌来自服务账号可读的副本，
   服务读不到 root 的那份文件）。未批准时接入字段一律为空 ✓。POST 而非 GET：令牌不进 URL/日志。
3. **客户端侧修复的 hub 侧对应**：登记入口默认改为 **443 边缘** —— 实测国内家宽到 hub IP 的 **TLS
   在所有端口同时失败**（portal:8899 / portal:8989 / tunnel:8899 / 生产入口 9988 全部 curl rc=35），
   而海外 443 边缘正常 ⇒ 这正是 R-H13 预留的退路。

**两条本版记下的排障教训**：

① **path 单元会自激**：systemd 的 `PathChanged` **也包含属性变化（atime）**，而服务本来就要读
   证书目录 ⇒ 它不断触发自己，实测 **2 分钟 232 次**、每次都 reload nginx。改成 timer + 内容哈希
   比较后彻底消失。教训：拿"文件有没有变"当触发条件时，必须区分"我读了它"与"它变了"。
② **`systemctl reload nginx` 不改变 master pid**（只换 worker）—— 我用 master pid 当"是否 reload 过"
   的判据，是错的；该看服务日志。

**本版未解决**：实例侧的 Windows 启动器仍只在**它自己的配置里**看到证书（v1.24.0 起接入脚本会把
证书写进那个文件，所以正常路径已成立）；rpi 镜像重建已完成（v1.24.0，662,225,336 bytes，
SHA-256 `9a81ca4c…`）。现场保留一个测试入口 `bg9zzz` 作为可用参照。

## V0.16 — 2026-10-01 — 代码对账轮：物理架构图 + 三处"文档跑在代码前面"的订正

本轮不新增设计，只做一件事：**把 SDD 的每一句"已实现/已打包"拿回代码库对账**，
并把对账结果写回。动机是评审发现三处文档陈述领先于 `mrrc_modern` 实际代码。

1. **新增物理架构图**（`docs/physical-architecture-2026-10-01.svg` / `.png`）：三台主机
   （实例 / hub ECS / 海外 www）+ 外部依赖（DNS、Let's Encrypt、Club Log、浏览器），
   落到进程、文件、端口、cron 一级；与逻辑架构图（`docs/architecture-2026-10-01-as-built.svg`）
   互为补集。§9.9 与 §12.8 各加一条指向。
2. **订正 §12.8 的"打包版 v1.22.0"**：v1.22.0/v1.23.0 存在于 `mrrc_modern` **feat/hub 分支**的
   CHANGELOG（含 C1–C6），但**未合并 main、无 tag**，Stable 渠道仍 v1.21.0。原句缺分支限定，
   改为带限定的叙述，并留下运营待确认项：现网实例跑在哪个 ref。
3. **订正 §10.8 的"Portal 尚未实现"**：Portal 已于 2026-10-01 上线公网入口
   （`portal.mrrc.vlsc.net:8899`，§12.9），移出未实现清单。
4. **§11.3 增加对账注**：C1–C6 逐条标注落地位置 —— feat/hub 已实现、main 未合并；
   README Quick Facts 的"令牌不进 URL 已实现"拆成 hub 侧 / 实例侧（feat/hub）/ Stable 渠道三档。
5. **网站同步**：`website/` 概览与设计页的"会话凭据不进 URL＝已实现"改为同三档叙述。
6. **集成发现**：hub ↔ mrrc_modern 的实质集成工作集中在 `mrrc_modern` 的 feat/hub 分支
   （ahead main 25 commits）—— 建议尽快合并并打 tag，否则"Stable 渠道不含 Hub 前置能力"
   会持续制造文档与现实的落差；另建议加跨仓契约门禁（grep `?token=` 即 fail）。

**未解决（留给代码，不留给文档）**：feat/hub 合并 + V1–V10 回归（I-H6 关闭条件）、
Cookie `httponly/Secure` 收紧（C3）、现网实例 ref 确认。

## V0.16 — 2026-10-02 — 开通链在真实租户机上跑通；那个 409 结案（两层原因都在我们这边）

> **编号说明（2026-10-06 注）**：本仓有**两行都编号 V0.16** —— 上一行是 2026-10-01 的代码对账轮，
> 本行是 2026-10-02 的开通链实测。两者写在不同分支上，合并时撞了号。**不改号**：V0.17–V0.29
> 已有十余行被其它章节按号引用（"见 V0.23"「V0.21 起」…），重新编号的破坏面远大于收益。
> 序号重复只影响阅读顺序，不影响任何一条内容。

V0.15 记的是登记端点与安装器的机制。本版记的是**第一次在真实 Windows VM 上装包、按租户的方式接入**，
以及它逼出来的东西。

1. **闭环证据（从租户机一路到入口）**：VM 上脚本签出 `CN=bg9zzz.mrrc.vlsc.net` ✓ →
   `POST /enroll` 返回 **200** ✓ → hub 落盘 `instance-certs/bg9zzz.pem`（1207 B，属主 `mrrcportal`）✓ →
   `gen_hub_routes.py` + `nginx -t` 通过 + reload ✓ → **公网访问该入口返回 502**（= hub 已认这张证书、
   只等实例连上来）✓✓。剩下的最后一格是实例侧隧道常驻（任务已能注册，但其执行仍失败）。
2. **V0.15 遗留的"未解释 409"结案，而且是两层原因叠在一起**：
   - 第一层是**运维动作**：`/etc/mrrc-hub/instance-certs` 被手工建成 `root:mrrcportal 750` ⇒ 服务账号
     **没有写权限** ⇒ 写临时文件失败。仓库自己的 `mrrc-hub-cert.sh:104` 本来写的是
     `-o mrrcportal -g mrrcportal` ✓ —— **是手敲那一次建错了**。已按服务账号修正。
   - 第二层是**部署**：`import re` 那个修复早已提交（`bede9e8`），但**没有重新部署到 hub** ⇒
     hub 上跑的还是旧代码 ⇒ 证书解析为空 ⇒ 报"名字不符"。
   - 顺带记一个误导：`PermissionError` 被处理器映射成 **409**（应 500），让人以为是"你自己提交的东西不对"。
3. **判据教训（本版最该记住的一条）**：单元测试、构建门禁、产物哈希**全绿**，包却**接不进任何入口** ——
   六个真缺陷（见 `deploy/README.md`）全部只在"装完真跑"时现形。以及一条更细的：我的"自足性证明"
   证的是"带 `-config` 能签"，而脚本没传 `-config` ⇒ **判据比结论窄一点，就差出一次事故**。

**本版未解决**：实例侧隧道任务注册成功但执行失败（`lastResult=1`）；`fleet/` 不在热修覆盖面内
⇒ 安装器类修复只能重打包（待出 v1.23.1）。

## V0.15 — 2026-10-02 — 开通链闭环：证书登记、免预装取件、三平台常驻

V0.13 把"一机一证"入档，V0.14 把 AD 与实况的矛盾摆明，但**从"实例拿到证书"到"hub 信任它"之间
还缺一段**：签发脚本在 hub 侧、信任包生成器也在 hub 侧，而没有任何一条路径把两者连起来。本版补上
这段，并把它两侧的前提（取件、常驻）一起做完。

1. **登记端点 `POST /enroll`**（§10 现网端点由四增至五）。实例交上来的是**公钥**，私钥不出本机。
   三道闸依次是：一次性登记口令（`grant` 时生成、运维页可见）→ 必须是 PEM → **证书 CN/SAN 必须
   等于该实例自己的入口名**。第三条是这条链的关键 —— 只有它能把"知道口令"与"能登记任意名字"
   分开。被拒时不留文件。端点**不**重生成路由，而是把 root 命令交回运维：解析公网输入的服务
   不获得 reload nginx 的权限（沿用既有分工）。
2. **两平台安装器各自登记**（`make_instance_cert.sh` / `install_instance_tunnel.ps1`），幂等 ——
   证书已存在时**仍然登记**。这条是我第一版写错的：登记块落在签名路径里，复用分支提前 `exit 0`，
   于是脚本注释里承诺的"hub 可达后重跑即可"**是假的**（服务日志里三次运行只有一次请求）。
3. **免预装取件**（`fetch_installer_payload.sh`）：无第三方依赖、**必校 SHA-256**、不符即拒绝而非
   降级（NFR-H032）。Windows 安装包改为**携带 frpc 与 openssl**，不满足就不出包。
4. **三平台常驻 + 三平台 env 接线**：macOS launchd / Linux systemd（注销后存活）/ Windows 服务均已
   落地；应用侧环境变量三平台已通 —— Windows 用用户级变量，macOS 用 LaunchAgent（`launchctl setenv`）
   - 登录片段，Linux 用 `environment.d` + 登录片段。**两处都写是必要的**：从访达启动的应用不读 shell
   配置，SSH 登录不读 `environment.d`。接线做成独立脚本 `wire_instance_env.sh`（可沙箱测试、幂等、
   只写有值的变量——写空路径会让应用去找一个没人放文件的地方）。
5. **文档漂移修正**：`deploy/README.md` 仍在指 `issue_wildcard_cert.sh`，该脚本已改名
   `mrrc-hub-cert.sh`；四个新脚本未收录。本版一并修正。

**三条自我批评，都关于"验证"**：

① **静默的 `except` 会把代码缺陷伪装成对用户的合理拒绝**。`cert_names` 漏写 `import re`，外层
   `except Exception: pass` 把 `NameError` 吞成空集，端点于是把一张**完全正确**的证书报成
   "名字不符" —— 排障两轮都在看那段本来没问题的 openssl 输出。已改为把原因写进日志。
② **判据不能取脚本自己的说法**。我用"输出里有『登记成功』"判定登记成功，而脚本在**根本没发出
   请求**时也这么打印。改成**数服务端自己记录的请求行**之后，"复跑不重试"当场现形。
③ **自造脚手架比被测对象更容易出错**。一次在测试进程里改写了处理类，把被测服务打坏并据此得出
   "服务有 bug"的错误结论（产品未被改动、其测试全绿，据此撤回）；一次把已在测试呼号库中
   自动核验的呼号又手动核验一遍，被状态机正确拒绝 —— **代码是对的，脚本是错的**。
   固定做法：**判据取产品自己的输出，不取自造脚手架。**

**遗留**：`POST /enroll` 曾出现一次三连 **409**，同代码同设置复跑即 200，**原因未查明**。
观测点：409 响应体带异常文本，现场遇到先看它。

## V0.14 — 2026-10-01 — 设计记录补全：AD 与实况的正面矛盾入档

V0.13 补齐了 §12（运维层），但设计记录的**其他章节**对新组件仍是零覆盖。
本次按章逐一排查（对 `portal` / `install_instance_tunnel` / `trust-bundle` / `mrrc_tls_name`
四个关键词做全章扫描），补上四处：

1. **`08` AD-H11 增补 as-built 指认 —— 这一条是本次最重要的**。AD-H11 写着“禁用全 fleet 共用
   静态 token”，而现网隧道**用的正是共享 token**。这是 AD 与实况的正面矛盾（不是遗漏），
   按治理规则必须在同一处修订而不能默默分叉。已如实分两层记录：
   hub → 实例的 **TLS 身份已是一机一证**（自签 + 钉住）；**隧道认证仍为共享 token**，
   属对 AD 字面的**有意偏离**，退出条件 = 内置 Fleet Agent 上线。
2. **`05` NFR 补三条**：NFR-H031 实例证书生命周期（私钥不出实例、信任包**原子替换 + nginx -t
   过了才 reload**、不得回退到关校验）；NFR-H032 无预装可安装且**必校 SHA-256**、
   不符即拒绝而非降级；NFR-H033 文档事实必须可追溯，不得凭设计意图措辞。
   同时把 NFR-H021 的两跳信任源分开写清（www 边缘=系统 CA；hub→实例=信任包）。
3. **`11` §11.1 增 as-built 指认**：逐行给出“在跑的极简子集 vs 目标态”，并列明真正未实现的八个
   组件。加一句防误读：**子集不是目标态的实例化**。
4. **`10` §10.1 增 as-built 指认**：目标态 REST 表与实跑四端点路径不同，**不要拿上表的路径去调现网**。

**一条自我批评**：V0.11 与 V0.13 两次写错“一机一证”，根因都是把两个不同层次的东西
（谁能接入隧道 vs 这台实例是不是它声称的那台）混成一句笼统的“阶段 2”。已在 AD-H11 的
指认里写明这个教训。

## V0.13 — 2026-10-01 — 实例开通链与一机一证入档；能力表按现网校正

本次是**文档追代码**：代码侧已落了一整条实例开通链，但 `SDD/12` 与 `deploy/README.md`
对它零记载。补入两节（均在 §12.8）：

1. **「实例证书链」（一机一证）**：`make_instance_cert.sh` 签自签证书（签给实例**自己的**
   入口名）、公钥钉进 `/etc/mrrc-hub/trust-bundle.pem`、nginx 按 `$mrrc_tls_name` 逐实例校验。
   自签靠“钉住它”通过，而不是靠关掉 verification。注册表因此多了第三列（`<标签> <端口> <上游 TLS 名>`）。
   **状态写明为“机制就位、尚未施用”** —— 现网 `bg1sb` 仍在用 `radio.vlsc.net` 那张旧证书。
2. **「实例开通链」（安装器）**：`install_instance_tunnel.{sh,ps1}` 自取 frpc 并校验 SHA-256、
   与 frps 版本 pin 死、三平台常驻；`fetch_installer_payload.sh` 构建内嵌载荷
   （openssl 的 URL/哈希**不硬编码**，缺条目就跳过）。边界写明：仍是仓内脚本，无公开发布的安装包。

**能力表校正**（`SDD/README.md`）：呼号注册改为**已上线公网**；新增实例证书链、实例安装器、
实例侧 Hub 前置能力三行；PTT 半开释放拆为“实例侧已实现（opt-in）/ 隧道层待做”。
顺带修掉 V0.11 遗留的一个排版缺陷：一条说明块把能力表从中间截断了。

**文档站同步**（`website/` 五页）：

- `start.html` 「装隧道」整步重写 —— 不再要求 `brew install frp`（安装器自取并校验 SHA-256）、
  补上 Windows 的 PowerShell 版与它额外做的证书/环境变量、常驻方式按三平台分列；
  「重启之后」改为区分打包版与源码运行。
- `index.html` / `design.html` 现状表：PTT 拆为两行；新增实例证书链与安装器两行；
  「一机一证」保留为阶段 2 但改名为**隧道自身的**设备证书，并请读者不要把它
  与 TLS 身份混为一谈。`design.html` 的 L3 层与失效表现改为“按实例名校验”。
- `trouble.html` 新增“自助申请没动静”“注册页 429”两条，并把 502 那条补上信任包细节。

**漂移升级（X1）**：`deploy_hub_routes.sh` 的危险从“一重”变成“三重” —— 除了把 8899 退回明文，
它还会抹掉逐实例校验与信任包（它写死 `radio.vlsc.net` + 系统 CA）。
已在 `deploy/README.md` 把 X1 重写为高危并加醒目告警。

**同时纠正一条已被本次工作推翻的旧陈述**：`deploy/README.md` 原先写“frp 用单个共享 token，
不是一机一证” —— 隧道自身的认证确实仍是共享 token，但 **hub → 实例这一跳的 TLS 身份已是一机一证**。
两者层次不同（谁能接入隧道 vs 这台实例是不是它声称的那台），原文把两件事说成了一件事。

## V0.12 — 2026-10-01 — 文档站接入全站导航；门户侧登记本产品

**行为变更**：`website/` 的 5 个页面底部热链 `https://www.vlsc.net/js/global-nav.js`
（与 www 各子站同一份，**不复制进本仓**），页面随其它子站获得全站顶栏、回到顶部、
滚动进度条与 GA4（带 vlsc.net 域守卫）。同源热链让导航只有一份 canonical 拷贝：
www 的脚本一改，本站下次加载即生效，不存在第二份会漂移的副本。

**契约（写进 `website/README.md` 硬约定第 3 条）**：`<body data-site>` 必须等于
canonical 脚本 `PATHS` 里的键 —— 本站是 `mrrc_hub`。顶栏高亮拿它比对，值写错不报错、
只静默不高亮。

**跨仓**：门户站 `www.vlsc.net` 侧新增本产品入口（顶部全站导航条 + 门户选择表、
项目卡、生态段）。门户是呈现层，本仓是接入层事实的 owner ——
两边的**事实**仍以本 SDD 为准，门户不复制本仓架构细节。

## V0.11 — 2026-10-01 — 面向用户的文档站建立；文档与现网对齐；脚本-现网漂移入档

**新增**：`website/` —— 面向用户的文档站（5 页：概览 / 接入四步 / 使用与分享 / 排障 /
设计与层层实现）。视觉与 `www.vlsc.net` 同源（`octen.css` 逐字节复制 + `hub.css` 隔离新增）；
零构建；`website/README.md` 载有事实源映射与可自举的发布前复验清单。

**修正（文档 vs 现网，均于 2026-10-01 现场取证）**：

1. `SDD/README.md` 能力表把“实例出站隧道”“通配子域接入”“透明 HTTP/WS 代理”“令牌不进 URL”
   记为**待实现**，而它们已在真实公网跑通 —— 与本仓 §12.8 及 `deploy/README.md` 的实测记录
   直接矛盾。已按实况改写，并给表加了一条“与 §12.8 冲突时以 §12.8 为准”的防回退说明。
2. §12.8 与 §7.x.1 只写 `:8899`。**现网 8899 已是 TLS 入口**（原明文 301 口因 R-H13 升级），
   而主入口 9988 反而没写。已改为“9988 为主、8899 同 vhost 的第二个 TLS 入口”，
   并补上路径入口的**大写呼号**规范。
3. `deploy/README.md` 顶部“状态：未部署”与同文件后半的“已验证”自相矛盾；
   退化路 URL 写的是 `test1.mrrc.vlsc.net`（子域代理），而现网是
   `www.vlsc.net/mrrc_modern/<呼号大写>/`（**路径**代理）。均已按实况改写，历史段落标注保留。

**新发现（入档，未修）**：

1. **海外边缘路径间歇性失败**：2026-10-01 实测 6 次中 3 次 20 s 无响应（交替出现）。
   已排除本地 DNS/TCP/TLS、www 静态服务、www 上另一条代理腿、hub 侧 SNI/Host 组合；
   失败定位于 `www → hub:9988` 这一跳。入 `§12.8` 排障增补与站点 `use/design/trouble` 三页。
2. **脚本与现网漂移 X1/X2**：`deploy_hub_routes.sh` 重跑会把 8899 退回明文；
   `deploy_www_edge.sh` 缺现网在用的 `path proxy` 模式。已在 `deploy/README.md` 置顶警示块，
   **本次只记录不改脚本**。

**一条工具链教训**：自动格式化（biome 默认 tab 缩进）把逐字节复制的 `octen.css` 重排成 tab，
产生 991 插入 / 382 删除的侨差异，直接破坏了“上游样式表永不 fork”这条约定。
已加 `.pi-lens.json`（排除该文件）与 `biome.json`（钉 space/2）两个配置防再犯，
并把“两份哈希必须相同”加为发布脚本的第二道闸门。

## V0.10 — 2026-09-30 — UC-H10 落地为可运行的自助 Portal

1. **实现**：`portal/` 五模块 —— 规范化（大小写不敏感，`BG1SB ≡ bg1sb`）、查重（同呼号拒绝，
   不静默覆盖）、核验（可插拔：呼号库自动比对 / 人工）、分配（标签规则 + 空闲端口 + 注册表追加）、
   审计（每次状态流转留痕）、撤销（移除注册表条目）。
2. **安全前置写进代码**：`store.grant` 只接受 `verified`；`Portal.grant` 在**任何写操作之前**
   先查状态。测试 `tests/test_portal.py` 8 组，含"未核验不得授予"与端到端流程。
3. **实现过程中测试抓到一个真 bug**：早期版本先写注册表、后调 `store.grant`，
   于是未核验的申请虽被拒绝，注册表里却留了**孤儿入口**。教训入档：写注册表就是开入口，
   必须发生在核验之后。
4. **呼号是公开标识、入口可枚举 ⇒ 防线只能在核验之后**：这条论证同时写进
   `portal/callsign.py` 顶部与 `portal/README.md`，作为设计的第一性理由，而不是附注。

## V0.9 — 2026-09-30 — 第二产品具备接入条件 + 实况互指

1. **`mrrc`（站点侧产品）完成接入所需的全部代码改造**：路径前缀能力（默认空 = 行为不变，含
   Cookie path 限定）、会话遥测（`/api/session_metrics` + 周期一行日志）、PTT 三层防线核实
   （发现活性闸门**早已存在**，此前评估误记为缺失，已更正）。
2. **互指关系**：本文档 §12.8.1 记录第二产品现状；该产品侧的改造记录在其仓内
   `docs/current/design/hub-parity-plan.md`。
3. **一处方法论教训入档**：对该产品的 PTT 能力曾误判为"缺失"，原因是只读了 TX 路径的一部分。
   结论前读完那条路径 —— 这条比结论本身更值得记。
4. 上线仍待定：需要能独立运行该产品的站点（电台/音频/串口独占），且需 www 增加产品段。

## V0.8 — 2026-09-30 — 呼号核验落地为流程 + I-H9 结案 + 真证书上线

**触发**：限流暂缓，其余办好。

1. **UC-H10 呼号注册与核验**：提交 → 规范化（大小写不敏感）→ 查重 → **核验**（呼号库/执照审核）→
   绑定 → 注册表分配标签与端口 → 实例侧上线。异常分支写明四种，其中「呼号已被绑定」走申诉/转移、
   **绝不静默覆盖**，冒用核实则撤销绑定并停用入口。
2. **SC-H10**：呼号即身份，注册实例与用户都须提供经核验的真实呼号。
3. **I-H9 结案**：接受实例存在性可枚举。理由：这是 AD-H15 的另一面，要拒绝枚举就得放弃「呼号即身份」。
   SC-H5 从「不能**发现**或访问」收窄为「不能**访问**且不泄露实例内容」，防御重心明确放到
   「**授予访问之前**核验呼号」（UC-H10）。代价入档，不当事缺陷。
4. **真证书上线（同日的部署工作）**：hub 持有 Let's Encrypt 的 `*.mrrc.vlsc.net` 通配证书（DNS-01，
   自建 hook 直接调阿里云 DNS API，不依赖年久失修的第三方 certbot 插件）；两条入口浏览器零警告
   （实测不带 `-k` 通过校验）。www 边缘的上游校验由「钉自签证书」改为**系统 CA**，消除了
   「每次续期要跨机同步信任锚」这个咬过两次的耦合。

**未做**：限流（明确暂缓）；Portal 注册 UI 与呼号库对接（阶段 2）；呼号核验在用户维度的代码实现。

## V0.7 — 2026-09-30 — 租户命名定为呼号（AD-H15）

**触发**：确认多租户按呼号注册 —— `BG1SB` 的远程入口就是 `https://BG1SB.mrrc.vlsc.net:8899/`。

**改动**

1. **AD-H15 呼号即租户身份**：入口用 `<呼号>.mrrc.vlsc.net`（子域）与
   `www.vlsc.net/mrrc_modern/<呼号>/`（海外前缀入口）；**注册实例与注册用户都必须提供真实呼号**，
   呼号即账号标识符、大小写不敏感、同一呼号只能绑定一个 Owner；**注册时须核验呼号**（执照/呼号库/人工审核），
   否则"身份"这层是空的（谁都能抢注 `BG1SB`）。
2. **实现（命名部分）**：注册表按小写标签存储、生成器接受任意大小写输入
   （`BG1SB` → `bg1sb`）；hub 的 vhost 用 `server_name ~*` 匹配，大小写都能路由（实测两种 Host 均 401）；
   URL **路径**大小写敏感，故规范形式用呼号原样大写，小写走 301（`/mrrc_modern/bg1sb/` → 301 → `/mrrc_modern/BG1SB/`）。
3. **NFR-H028/H029**：呼号必须真实、核验手段与撤销机制。
4. **I-H9 开放问题**：呼号公开可猜 ⇒ **实例存在性可枚举**（登记名 401/502 vs 未登记名 404，可探测）。
   我的建议是接受（呼号本就公开），并把 SC-H5 的"不能**发现**"改成"不能**访问**，且不泄露内容"——
   但**验收标准是你的**，所以只记为待决策，没有擅自改。
5. **收尾清理**：`test01` 与 `test1` 两个演示实例已从注册表与实例侧服务中撤除，注册表现状 = `bg1sb → 18802`
   （一个实例、一个名字，避免"多实例已跑通"的误判）。

**未做**：Portal 侧的注册/核验/Owner 绑定（阶段 2）；呼号即身份在**用户**维度的落地（当前只落在实例命名上）。

## V0.6 — 2026-09-30 — 通配证书的签发改由 hub 自理（等凭证）

**触发**：要 `*.mrrc.vlsc.net`，并让我参考现有 crontab 的续订程序。

**勘察结论（重要）**：现有续订就是**标准 certbot + HTTP-01**（www 的 `/etc/cron.d/certbot` +
`certbot.timer`，renewal 里 `authenticator = nginx/webroot`），**无法产出通配证书** ——
LE 的通配只走 DNS-01；也没有 acme.sh、没有 DNS 凭证文件、w3/w6/l6 均不可达（无可复用装置）。
结合 R-H13（境内 80/443 不可用），**DNS-01 是唯一路径**。

**决策**：签发与续订放在 **hub 自己**（起初的 `deploy/issue_wildcard_cert.sh`，V0.8 起由 `deploy/mrrc-hub-cert.sh` 取代），而不是 www。理由：
www→hub 无免密 SSH（跨机分发要先建信任），而 **DNS-01 不需要任何入站端口**，所以 hub 能自签自续；
证书正好就是 hub 自己的 nginx 在用的，deploy hook 把它装到 `/etc/mrrc-hub/tls/` 并 reload
（**nginx 配置零改动**，因为该路径本就是它读的）。www 当前只是跳转，继续用它自己的 `www.vlsc.net` 证书。

**未完成，阻塞在一个 RAM AccessKey**：需一个只挂 `AliyunDNSFullAccess` 的 RAM 用户凭证写入
`/root/.secrets/aliyun.ini`（0600）。退路是 `certbot --manual` 手工加 TXT（每 90 天一次，不自动续订）。

## V0.5 — 2026-09-30 — 阶段 1 正式化（通配路由 + 注册表 + 常驻隧道）

**触发**："证书后边再搞，其他都正式搞"。

**改动**

1. **hub 侧从"每实例一条 vhost"改为"一条通配 vhost + 注册表"**（`deploy/deploy_hub_routes.sh`
   - `deploy/gen_hub_routes.py`）：`/etc/mrrc-hub/instances.tsv` 是唯一的每实例事实（名字 → 回环端口），
   生成器产出 nginx `map` 并校验端口落在 frps `allowPorts` 内；vhost 用
   `~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net$`，**未知名字回 404**，不回退到别的实例
   （NFR-H022）。加实例 = 注册表一行 + 重跑 + reload。
   这直接消掉了 B2 的痛点：每加一个实例/一个前端资源就要改中心 nginx。
2. **实例侧从手工 `nohup frpc` 改为 launchd 常驻服务**（`deploy/install_instance_tunnel.sh`）：
   0600 配置文件放 `~/Library/Application Support/mrrc-fleet/`，LaunchAgent 带 `KeepAlive`
   （崩溃/重启/换网自恢复），并拒绝在已有手工 frpc 运行时启动（两个客户端抢同一名字会抖动）。
   实例自己的电台服务不归隧道管 —— 隧道常连，实例没起来就是 502。
3. **进 hub 的那一跳保持证书校验**且现在是"端到端"的：frps 转发裸 TCP，所以 nginx 的
   `proxy_ssl_verify on` + `proxy_ssl_name radio.vlsc.net` 校验的是**实例自己的真证书**。

**实测**：服务日志握手成功；经通配 vhost `test1.mrrc.vlsc.net:9988` → `/api/health` 401、
`/login` 200；`nope.mrrc.vlsc.net:9988` → 404。

**本阶段已知限制**：frp 共享单 token（frp 的模型），非一机一证 —— 与 AD-H11/AD-H13 把 frp 定位为
MVP 验证通道、设备证书留给自研 Agent 一致。

## V0.4 — 2026-09-30 — 海外边缘作为退化入口（443 + 真证书）

**触发**：明确"443 在境内不用想、80/443 肯定不行，迂回一下"。因此不追求让 hub 拿到 80/443，
而是把**用户可见的边缘放到境外**已有 443 与真证书的主机上。

**做法**：`deploy/deploy_www_edge.sh`（幂等、marker 分块替换、改前备份、`nginx -t` 后才 reload）
在 <www.vlsc.net> 上为一个实例名建 443 vhost，把**整条会话（HTTP + 5 个 WS）反代**进
`tunnel.mrrc.vlsc.net:9988`。**不是 302 跳转** —— 跳转只换地址，浏览器仍会落在非标端口 + 不信任证书上。

**进 hub 那一跳同样开着校验**：hub 是自签证书，所以把它的证书作为**信任锚**装到 www
（`proxy_ssl_trusted_certificate` + `proxy_ssl_verify on`），而不是关掉校验 —— 这正是 B2 的教训（NFR-H021）。

**实测（经 www 全程）**：`/login` 200、`/api/health` 401、`/listen` 302；**五个 WS 端点全部
`101 Switching Protocols`**（Cookie 鉴权，无凭据对照 403）。**延迟代价量化**：`/login` 直连 hub 0.13 s
→ 经 www **0.69 s**（多一跳海外往返）。

**结论与定位**：这是**退化路径**，不是主路。对"用户在国内、实例也在国内"的场景，境外边缘是绕路，
音频与 PTT 的往返多 0.4–0.6 s（已补进 NFR-H005 的适用范围）。主路应当是 hub 上的 DNS-01 **通配真证书**
（低延迟 + 免警告），届时退化路只服务只放行 80/443 的网络。

**待你一条 DNS 记录**：`test1.mrrc.vlsc.net A 193.111.30.163`（显式记录覆盖通配）。加完即可用
www 上可用的 HTTP-01 签真证书、重跑脚本换掉自签。加之前用 `--resolve` 已可全程验证。

## V0.3 — 2026-09-30 — 阶段 1 通路在真实公网跑通

**触发**：安全组放行 8899/9988/8989，要求"用 mrrc.vlsc.net"。

**结果**：真实公网路径（家宽 → hub nginx:9988 → frps:8989 → frpc → 实例）实测通过：
`/login` 200、`/api/health` 401、`/listen` 302，往返 **118–168 ms**；上游对实例**真 LE 证书**的校验通过；
送达浏览器的前端资源中 `?token=` **0 次**。命名定为 `test1.mrrc.vlsc.net`（实例入口）与
`tunnel.mrrc.vlsc.net`（隧道控制），均走已存在的 `*.mrrc.vlsc.net` 通配记录。

**这次抓到并修掉的三件事**

1. **frp 默认把代理端口绑在 `0.0.0.0`** —— 设计写"只绑回环"，frp 的默认不是；隧道端口一度在公网面监听。
   已在 `frps.toml` 显式加 `proxyBindAddr = "127.0.0.1"`（脚本 + hub 运行配置同步）。
2. **未备案域名在大陆地域的明文 HTTP 会被拦/替换**（新增 **R-H13**）：对 8899 发的请求，
   客户端拿到阿里云未备案拦截页（`Server: Beaver` 403），而源站日志显示同一请求回了 301 ——
   响应途中被改写。TLS 口不受影响。⇒ **入口必须 HTTPS**；8899 明文口在备案前不能承载任何依赖；
   ACME HTTP-01 在此环境不可靠，真证书只能走 DNS-01。
3. **边缘日志脱敏落地**：验证 WS 透明性时我用 `?token=` 发了两次请求，64 位真令牌当场进入 access log ——
   正是 AD-H07 预言的失效模式（前端已不发，但已安装的原生 App 仍会触发）。hub vhost 改用
   `hub_safe` 日志格式：只记路径、不记 query，实测带 `token=` 的请求 **0 命中**。

**方法学教训（写下来）**：`websockets` 客户端的 `additional_headers` 送 Cookie **静默不生效**，
我一度据此怀疑 AD-024 有回归；降到**裸 TCP 握手**才定界清楚（cookie/`?token=`/无凭据 = 101/101/403，
直连与经隧道完全一致）。**用一层客户端库做安全结论之前先降到裸协议。**

**仍未做**：通配真证书（需 DNS-01 凭证，见 deploy/README.md）；ICP 备案（决定能否回到 443）；
Portal / 设备证书 / 租约（阶段 2）。

## V0.2 — 2026-09-30 — 入口改用非标端口 + 验证环境落地

**触发**：确定 Hub 主机（阿里云 ECS `8.160.161.80`）与入口端口，要求"可以直接部署测试"。

**勘察得到的事实**（全部实测，不是假设）

- 主机**裸机**：无 nginx / frp / docker / caddy / certbot / node，只有 sshd；2C/3.6G/40G。
- **非 22 端口从公网不可达**：在 18080 起临时监听，本机 200、公网 000 —— 安全组只放行 22
  （也可能是 ufw，读它需要 root）。
- `cheenle` 可 SSH 登录，但 **sudo 需要密码** ⇒ 装包与绑定低端口都做不了。
- **`*.mrrc.vlsc.net` 已是通配 A 记录指向该机**（`a1/a2.mrrc.vlsc.net` 实测解析成功）
  ⇒ SDD 自己的命名 `portal./tunnel./<id>.` **今天就能用，不需要动 DNS**。
- `hub.vlsc.net` **不存在**（在 `vlsc.net` 区，不在通配内）。
- 实例侧证书是**真的 Let's Encrypt**（`CN=radio.vlsc.net`，2026-12-10 到期）。
- `vlsc.net` 的 DNS 托管在**阿里云万网**（`dns25/dns26.hichina.com`）。

**改动**

1. **AD-H02 port 修订**：入口不用 80/443，改用 **8899（明文跳转）/ 9988（TLS）/ 8989（隧道控制）**
   —— 国内 ECS 在 80/443 上需要 ICP 备案。代价写进决策本身，不当免费选择：
   入口 URL 带端口；**只放行 80/443 出站的用户网络连不上**（新增 **R-H12**）；
   **自动签发受信证书只剩 DNS-01 一条路**（HTTP-01 固定 80、TLS-ALPN-01 固定 443）——
   真证书/通配证书以 DNS API 凭证为前提。
2. **建立 NFR-H001**（此前被 `SDD/README.md` 与 `SDD/09` §9.5 引用但从未存在，是一处悬空引用；
   `sdd NFR-H001` 已可解析）。它把两件常被混为一谈的事分开：**实例**只需出站 8989，
   **用户浏览器**需能出站访问 9988。§5 章节号随之 5.1→5.2…5.5→5.6（无外部引用受影响）。
3. **`deploy/` 落地**：`bootstrap-hub.sh`（幂等、root 侧：nginx + certbot；frps 0.71.0
   **带 SHA-256 校验**（对官方 checksums 文件）；代理端口**只绑 127.0.0.1**；token 0600；
   systemd；nginx 在 9988 终结 TLS 并以 **`proxy_ssl_verify on` + `proxy_ssl_name radio.vlsc.net`**
   回源）、`frpc-instance.toml.example`、`README.md`（勘察事实 / 解除阻塞清单 / 拓扑 / V-a…V-g 验证表）。
4. **`proxy_ssl_verify off` 的前提消失了**：B2 之所以关校验是因为实例曾是自签证书，而实例现在是真
   LE 证书 ⇒ hub 侧可以开着校验回源。verify 表中把"故意改错 `proxy_ssl_name` 看它失败"列为
   V-d，因为一行没人见过它失败的校验配置，正是 `proxy_ssl_verify off` 当初能在生产里活下来的原因。

**跨仓影响**：无（本仓文档 + 部署件）。实例侧 frpc 配置属验证夹具，不改 `mrrc_modern`。

**未做/边界**：**未在本机之外安装任何东西、未开任何端口**。部署仍阻塞在三件控制台动作上：
安全组放行 8899/9988/8989、给 `cheenle` 免密 sudo、（可选）为 `hub.vlsc.net` 加 A 记录。
证书在 DNS 凭证到位前是自签的，并在脚本与 README 里被明确标为 smoke test 夹具。

## V0.1 — 2026-09-30 — SDD 建立（架构评审稿冻结）

**触发**：源设计文档 `MRRC_modern_远程接入统一设计文档_v2.0_20260930.md`（架构评审稿）提交评审。

**本版本完成的动作**

1. **建立本 SDD 作为唯一设计基线**，覆盖 15 章（TeamSD 对齐），并把源文档的全部结论吸收进来
   （源文档不再单独维护）。
2. **代码取证评审**：逐条把源文档结论与 `mrrc_modern`（`4f385dd`，v1.21.0）代码核对，
   产出 [`docs/2026-09-30-fleet-hub-design-review.md`](../docs/2026-09-30-fleet-hub-design-review.md)。
3. **新增"现状基线"**（第 1 章 §1.2）：确认已有 4 套远程接入机制（B1 SSH 隧道 / **B2 IPv6 直连 + nginx，
   生产运行** / B3 路径前缀代理 / B4 支持上报通道）。源文档未把它们列为基线，导致 MVP 起点被误判为"从零开始"。
4. **修正 4 项 P0 级事实偏差**，并落为决策：
   - `AD-H06` + 第 15 章：PTT 半开连接不释放（既有 dead-man switch 只在真正断线时触发，
     `MRRC_PTT_MAX_TX_SECONDS` 默认关闭）→ 定义隧道层 TX 期间心跳契约与实例侧活性闸门
   - `AD-H07`：会话令牌在 URL query 中且实例跑 uvicorn 默认访问日志 → 透明代理模式下必然泄露；
    该问题项目已知（`support_bundle.py` 的脱敏正则）但只在导出诊断包时处理 → 前端改造并入 MVP
   - `AD-H09`：通配子域下 Access 与实例**共享同一 origin**，双会话 Cookie 命名/生命周期未定义；
     实例 Cookie 无 `Secure`、30 天有效
   - `AD-H08`：Listener 实际语义是"受限操作"（可调频/换模式，`LISTEN_ALLOWED_SET_FIELDS`），
     非源文档所称"永远只读"；且调谐是写操作，其并发仲裁在源文档中缺失
5. **用实测替换估算**（第 9 章 §9.3、`NFR-H007/H008`、`AD-H14`）：RX Opus 默认 64 kbps
   （非 48–64 区间）；频谱 1701 B/帧 × 30 fps ≈ **408 kbps**（非 100–300），占单会话 **~86%** ——
   带宽优化杠杆在频谱而非音频；Listener 侧已有 1/3 帧率机制。
6. **明确复用边界**（`AD-H13`、第 11 章 §11.5）：OTA 复用 `upgrade_core.py`；
   诊断复用 `deploy_support_receiver.sh`；脱敏照搬 `support_bundle.py`。
7. **建立发布门禁**（第 3 章 §3.5）：G1 PTT 半开释放 / G2 令牌不进 URL / G3 Listener 语义 /
   G4 双会话 Cookie —— 四项未决不开工。

**本版本引入的跨仓影响**

- `mrrc_modern` 需落地 C1–C6（第 11 章 §11.3），其中 **C1（远程会话活性闸门）与 C2（token 不进 URL）
  是 MVP 前置**；需在该仓 SDD（`08-architecture-decisions.md`、`15-ptt-safety-architecture.md`）
  登记为新层/新决策，并同步测试计数。
- `mrrc`（旧架构）的 B1 SSH 隧道脚本定位为历史，不参与 Hub 演进。

**本版本未解决（留在第 13 章）**

- `I-H1` Listener 并发实测（**可立即开始采集**，是 AD-H12 的触发依据）
- `I-H2` 活跃率与会话时长（决定出口带宽与数据面规格）
- `I-H6` PTT 半开释放的实例侧实现与 V1–V10 回归
- `I-H7` B2/B3 的长期定位（是否投入自动化）
- `I-H8` 私有部署/自建 Hub 的开源许可边界

**版本号说明**：`V0.1` 表示"设计基线已冻结、实现未开始"。首个可上线版本到达时升 `V1.0`
并在此登记实际规格、压测结果与 SLO 实测值。

---

## 变更登记规约

| 若改变了… | 必须同时更新 |
| --- | --- |
| 隧道/协议行为 | 第 10 章服务契约 + 第 9 章链路描述 |
| PTT 释放路径或时限 | 第 [15](15-ptt-safety-hub-mode.md) 章 + `NFR-H006/H019` + `SC-H4` |
| 带宽/码率/帧率 | `NFR-H007/H008` + 第 9 章容量模型 + `AD-H14` |
| 角色语义 | `AD-H08` + 第 6 章 UC + 第 7 章权威矩阵 |
| 凭证/会话/Cookie | `AD-H07`/`AD-H09`/`AD-H11` + `NFR-H012/H013/H014/H020` |
| 架构方法 | 第 8 章（新增或修订 AD） |
| 任何行为变更 | **本条版本历史新增一条** + `SDD/README.md` 版本号 |
