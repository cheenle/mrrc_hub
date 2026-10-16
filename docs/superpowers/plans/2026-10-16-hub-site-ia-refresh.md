# MRRC Cloud Hub 文档站 六页双轨重排 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把 `mrrc_hub/website/` 从"五页文档站"重排为"六页双轨站"（首页 / 接入 / 使用 / 维护 / 排障 / 设计），补齐 10 月新事实（门户改版、远程协助、换机判据、盒子路径），发布到 `https://www.vlsc.net/mrrc_hub/`。

**架构：** 纯静态 HTML/CSS/JS，零构建。沿用上游设计系统 `octen.css`（逐字节冻结）与本站 `hub.css`；新增「维护」页与两轨交叉导航；新拓扑图从 `mrrc_modern/website/images/` 复制并加来源注记。

**技术栈：** HTML5 + CSS + 原生 JS + Bash 闸门（`website/README.md` §5）；发布 `website/deploy.sh`。

**规格：** `docs/superpowers/specs/2026-10-16-hub-site-ia-refresh-design.md`（commit `56abda5`）

**工作方式：** 本仓是多会话共用 `main` 的仓库，`deploy.sh` 就在本工作树执行，**不另开 worktree**；改为小步提交 + `git add` 只列本次文件，避免夹带其他会话的未提交改动（现存于 `SDD/`、`.agents/`、`deploy/`）。

---

## 文件结构

**创建**

- `website/maintain.html` — 维护与生命周期页
- `website/images/station-topology.svg` + `.png` — 自 mrrc_modern 复制（SVG 加来源注记）
- `docs/2026-10-16-site-recheck.md` — 现网只读复核记录

**修改**

- `website/index.html` / `start.html` / `use.html` / `trouble.html` / `design.html`
- `website/css/hub.css` — 仅在确需时新增 `hub-tracks` / `hub-crossnav`
- `website/README.md` — 文件清单 + 事实源映射 + 基线日期
- `SDD/14-version-history.md` — 一条版本记录

---

### 任务 0：现网只读复核与记录

**文件：** 创建 `docs/2026-10-16-site-recheck.md`

- [ ] **步骤 1：入口、证书、注册表、自动化、门户、信任包**

```bash
ssh cheenle@hub.vlsc.net 'sudo nginx -T 2>/dev/null | grep -nE "server_name|listen |mrrc-instances|portal" | head -40'
ssh cheenle@hub.vlsc.net 'sudo ls /etc/mrrc-hub/tls/ && sudo openssl x509 -in /etc/mrrc-hub/tls/fullchain.pem -noout -subject -dates -ext subjectAltName 2>/dev/null | head -8'
ssh cheenle@hub.vlsc.net 'sudo cat /etc/mrrc-hub/instances.tsv'
ssh cheenle@hub.vlsc.net 'systemctl list-timers "mrrc-hub-*" --no-pager; systemctl is-active mrrc-portal; frps --version 2>/dev/null || /usr/bin/frps --version'
ssh cheenle@hub.vlsc.net 'sudo grep -c "BEGIN CERTIFICATE" /etc/mrrc-hub/trust-bundle.pem'
```

证书文件名以现场 `ls` 为准；全部命令只读（`cat`/`grep`/`openssl x509`/`systemctl`）。

- [ ] **步骤 2：延迟实测（本机 → 入口；v6 / v4 各 5 次）**

```bash
for i in 1 2 3 4 5; do curl -6 -s -o /dev/null -w 'v6 %{time_connect} %{time_total}\n' https://www.vlsc.net/mrrc_hub/; done
for i in 1 2 3 4 5; do curl -4 -s -o /dev/null -w 'v4 %{time_connect} %{time_total}\n' https://www.vlsc.net/mrrc_hub/; done
```

取中位；若 v6/v4 差异不能稳定复现，在记录里写明并让首页统计改成不带数字的表述。

- [ ] **步骤 3：实例侧已发布版本**

```bash
rg -n "^## \[" /Users/cheenle/HAM/hub/mrrc_modern/CHANGELOG.md | head -3
```

- [ ] **步骤 4：写记录并提交**

`docs/2026-10-16-site-recheck.md` 格式：每项 = 命令 / 读数 / 将落在哪一页。提交：

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub
git add docs/2026-10-16-site-recheck.md
git commit -m "docs(site): 2026-10-16 现网只读复核读数"
```

---

### 任务 1：拓扑图入库与 README 文件清单

**文件：** 创建 `website/images/station-topology.svg` + `.png`；修改 `website/README.md`

- [ ] **步骤 1：复制并加来源注记**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
cp ../../mrrc_modern/website/images/station-topology.svg images/
cp ../../mrrc_modern/website/images/station-topology.png images/
```

在 SVG 第一行 `<?xml...` 之前插入一行注释（保持 `<?xml` 为文件首行是 XML 规范要求，注释插在其后）：

```xml
<!-- 来源：mrrc_modern/website/images/station-topology.svg @ defacb6 (2026-10-16)；本站为副本，改动请先改上游 -->
```

- [ ] **步骤 2：校验 XML 与尺寸**

```bash
python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse('images/station-topology.svg'); print('XML OK')"
```

- [ ] **步骤 3：README §1 文件清单 + §2 事实源映射各加一行，事实基线日期改为 2026-10-16**

- [ ] **步骤 4：Commit**

```bash
git add website/images/station-topology.svg website/images/station-topology.png website/README.md
git commit -m "site: 电台站接线拓扑图入库（自 mrrc_modern 复制并加来源注记）"
```

---

### 任务 2：index.html 重写（首页）

**文件：** 修改 `website/index.html`

- [ ] **步骤 1：按规格 §2 的六段重排**：Hero（统计带换复核值）→ 系统地图（拓扑图）→ 四条主张 → 双轨入口卡 → 能力现状表（加 10 月新行）→ 按意图的"从哪开始"。
- [ ] **步骤 2：导航加入「维护」（六项），页脚加两轨交叉导航带**
- [ ] **步骤 3：自检**

```bash
grep -c 'hub-tracks\|station-topology' index.html    # 期望 ≥2
grep -n '9988\|8899' index.html                       # 只允许历史注记处出现
```

- [ ] **步骤 4：Commit**（`site: 首页重排为系统地图 + 双轨入口`）

---

### 任务 3：start.html 重写（接入）

**文件：** 修改 `website/start.html`

- [ ] **步骤 1：按规格 §2 的六段重排**，重点是"选路径（盒子 / 电脑）"与"注册（门户核验）"两段。
- [ ] **步骤 2：外链盒子指南**：`https://www.vlsc.net/mrrc_modern/zh/w103d.html`（现网 200，写作时复测一次）。
- [ ] **步骤 3：自检**：`grep -n 'mrrc_modern/zh/w103d' start.html`；导航六项一致。
- [ ] **步骤 4：Commit**（`site: 接入页补齐选路径与门户注册现状`）

---

### 任务 4：maintain.html 新建（维护与生命周期）

**文件：** 创建 `website/maintain.html`

- [ ] **步骤 1：复制任一现有页做骨架**（nav / footer / 样式引用逐字保持一致），再写六节：换机·迁移 / 证书与续期 / 撤销·退出 / 远程协助 / 版本升级 / 何时找维护者。
- [ ] **步骤 2：事实核对**（写前复核，全部可在仓内读）：
  - 远程协助：`mrrc_modern/help_session.py` 头部注释 + `static/support.html` 的按钮与文案；
  - 换机判据：`mrrc_hub/portal/trust.py` 与 2026-10-16 提交 `93b1b22` 的信息；
  - 撤销/退出：`mrrc_hub/docs/2026-10-11-instance-lifecycle-and-port-squatting.md`。
- [ ] **步骤 3：自检**：链接 `zh/w103d.html`、`trouble.html`、`start.html` 均为有效相对/绝对 URL；导航六项一致。
- [ ] **步骤 4：Commit**（`site: 新增「维护」页（换机/撤销/远程协助/升级）`）

---

### 任务 5：use.html 更新

- [ ] **步骤 1：入口表按复核读数复核；两角色/分享/手机段轻改；已知退化表更新 10 月口径。**
- [ ] **步骤 2：Commit**（`site: 使用页按 10 月现状复核`）

---

### 任务 6：trouble.html 更新

- [ ] **步骤 1：症状表补四类新症状（502/404/超时分辨、换机后、隧道残留、TCP 未断掉线），分诊段对应补判据。**
- [ ] **步骤 2：Commit**（`site: 排障页补 10 月新判据`）

---

### 任务 7：design.html 更新

- [ ] **步骤 1：六节骨架内更新：V0.21 单机、路由 timer、实例证书链、远程协助通道、门户端点、令牌不进 URL 现状；事实基线改 2026-10-16。**
- [ ] **步骤 2：Commit**（`site: 设计页同步 10 月机制事实`）

---

### 任务 8：中文文案规整与全站闸门

- [ ] **步骤 1：过 chinese-prose 的两个脚本**

```bash
python3 ~/.pi/agent/skills/chinese-prose/scripts/fix_cjk_spacing.py website/*.html
python3 ~/.pi/agent/skills/chinese-prose/scripts/fix_cjk_quotes.py website/*.html
```

（路径以技能实际位置为准；脚本只动可渲染空白与成对直引号，跑完 `git diff --stat` 复核。）

- [ ] **步骤 2：README §5 ①–④ 全跑**（金规则、断链/标签/锚点、octen 哈希、现网入口）
- [ ] **步骤 3：三档宽度目视**（375 / 768 / 1440）确认双轨卡与拓扑图不破版

```bash
cd website && python3 -m http.server 8099
```

- [ ] **步骤 4：Commit**（`site: 中文标点/引号规整 + 全站闸门`）

---

### 任务 9：用户过目（硬门槛）

- [ ] **步骤 1：把改动摘要 + 本地预览方式发给用户**，等明确同意后才执行任务 10。

---

### 任务 10：发布与线上验证

- [ ] **步骤 1：发布**

```bash
cd /Users/cheenle/HAM/hub/mrrc_hub/website
bash deploy.sh --yes
```

- [ ] **步骤 2：线上逐页与关键文案**

```bash
for p in "" index start use maintain trouble design; do
  curl -s -o /dev/null -w "/$p → %{http_code}\n" "https://www.vlsc.net/mrrc_hub/$p.html"
done
curl -s https://www.vlsc.net/mrrc_hub/maintain.html | grep -c "远程协助"
curl -s -o /dev/null -w "topology %{http_code}\n" https://www.vlsc.net/mrrc_hub/images/station-topology.svg
```

- [ ] **步骤 3：确认线上无 `:9988`/`:8899` 作为可用入口的表述（只允许历史注记）**

---

### 任务 11：提交与文档同步

- [ ] **步骤 1：`website/` 全部变更提交**（`git status --short website/` 先核对不夹带）
- [ ] **步骤 2：`SDD/14-version-history.md` 加一条**（本次站点重排 + 事实基线日期）
- [ ] **步骤 3：如需，按复核结果回改 `SDD/12 §12.8`**（只改与现场不符处，并注明复核日期）
- [ ] **步骤 4：最终 `git log --oneline -8` 与人读一遍 `git status`**

---

## 自检记录

**1. 规格覆盖度**：规格 §1（六页）→ 任务 2–7；§2（每页结构）→ 任务 2–7 各步骤 1；§3（约定/图/中文）→ 任务 1、8；§4（取证）→ 任务 0；§5（验证/发布/提交）→ 任务 8–11；§6（非目标）→ 任务 0 的只读约束与任务 11 的提交范围。

**2. 占位符扫描**：无 TODO/待定；每步都给了命令或明确段落清单。

**3. 一致性**：页面文件名与导航六项在任务 2–7 中一致（`index/start/use/maintain/trouble/design`）；图片路径在任务 1、2、10 中一致（`images/station-topology.svg`）；`zh/w103d.html` 外链在任务 3、4 中一致。
