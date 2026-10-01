# MRRC Cloud Hub 文档站

面向**电台主**的接入与使用文档，外加**单独一页**给工程/平台读者的设计与实现。
纯静态、零构建、无 npm、无打包。

发布目标：`https://www.vlsc.net/mrrc_hub/`

---

## 1. 文件职责

| 文件 | 职责 |
| --- | --- |
| `index.html` | 概览：四条主张、30 秒数据路径、能力现状表、该从哪开始 |
| `start.html` | 接入四步：前提自检 → 注册 → 装隧道 → 验证 → 重启之后 |
| `use.html` | 使用与分享：三个入口怎么选、两把口令两个角色、怎么分享、已知退化 |
| `trouble.html` | 排障：症状对照表、两条诊断命令、四跳分诊、日志位置 |
| `design.html` | **工程侧唯一一页**：六层职责与边界、关键决策、安全不变量、现状与目标态 |
| `css/octen.css` | **上游设计系统，原样复制，永不 fork** |
| `css/hub.css` | 本站新增组件。上游之外的一切样式都在这里 —— 保证差异是一眼可见的单一文件 |
| `js/hub.js` | 渐进增强：移动菜单、目录高亮、代码复制。无框架 |
| global-nav.js（热链） | 每页末尾从 `https://www.vlsc.net/js/global-nav.js?v=8` 加载：全局顶 nav、回到顶部、滚动进度条、GA4（带 vlsc.net 域守卫）。与 www 各子站同源，**不复制进本仓** |
| `deploy.sh` | 幂等发布脚本。**只写不执行**，上线由人决定 |
| `../.pi-lens.json` | 把 `css/octen.css` 排除出自动格式化 —— 见下方「必须钉住的两个文件」 |
| `../biome.json` | 把本站的缩进风格钉成 2 空格（与上游 `octen.css` 一致），并双保险地禁用对 `octen.css` 的格式化 |

### 关于 `octen.css`

`css/octen.css` 是从 `mrrc_modern/website/css/octen.css` **逐字节复制**的
（2026-10-01 核对：与线上 `https://www.vlsc.net/mrrc_modern/css/octen.css` 的
SHA-256 完全一致）。**不要在这里改它。**

> 注意：门户站自己的 `/css/octen.css` 是**另一份**拷贝，与子站版本有差异
> （`.features-grid` 的列定义、`.vlsc-gn` 的移动端段落）。
> 复拷时认准 `mrrc_modern/website/css/octen.css`，不要从门户站取。

### 必须钉住的两个文件

自动格式化（biome，默认配置是 **tab** 缩进）会重排它碰到的每一个文件。
这对本站的 HTML/CSS/JS 无害（纯空白变化），但**会破坏 `octen.css` 的逐字节一致性** ——
而那正是「永不 fork」这条约定赖以成立的东西。2026-10-01 实际发生过一次：
复制后哈希原本一致，被格式化器重排成 tab 后产生 991 行插入 / 382 行删除的伪差异。

所以仓库根目录放了两个文件把它钉住：

- `.pi-lens.json` —— `ignore` 掉 `website/css/octen.css`（直接不让它进格式化流水线）
- `biome.json` —— 缩进风格设为 space/2（跟上游一致），并再禁用一次对该文件的格式化

**看到 `octen.css` 出现大 diff 时，先跟第 5 节 ③ 对比哈希**，不要直接 commit。

---

## 2. 事实源映射

**站点不发明事实。** 每一页的每个 URL、端口、行为，都必须能指回一个权威出处。

| 站点内容 | 事实源 |
| --- | --- |
| 入口 URL、端口、TLS 入口数量 | 现网 nginx 实际配置；`SDD/12 §12.8` |
| 边缘入口的路径前缀、大小写规范 | 现网 www 的 `vlsc.net` vhost |
| 证书签发方式与有效期 | 现网证书文件 + `SDD/05 NFR-H030` |
| 实例侧行为（口令、角色、数据通道、PTT） | `mrrc_modern` 源码 + `mrrc_modern/SDD/` |
| 注册流程与核验理由 | `SDD/06 UC-H10`、`SDD/03 SC-H10` |
| 安全不变量 | `SDD/08`（AD-H06/07/11）、`SDD/15` |
| 排障条目 | `SDD/12 §12.7 §12.8`、`deploy/README.md` |
| 运营事实（主机、注册表、运维命令） | `SDD/12 §12.8` |
| Portal 自助入口与核验流程 | `SDD/12 §12.9`、`portal/README.md`；现网 `https://portal.mrrc.vlsc.net:8899/` |

Portal 自助页（`portal/app.py` 内置的三个页面）与本站同设计令牌（黑底 / 青 accent /
同款表格与按钮观感），样式**内联**、不外链 CSS —— Portal 保持零第三方依赖，
www 不可用时注册页仍完整可用。

无法取证的内容一律写"待核实"，**不猜**。

---

## 3. 怎么改

### 改文案

直接改对应 HTML。改完跑第 5 节的复验清单。

### 上游设计系统改了

```bash
cd mrrc_hub/website
cp ../../mrrc_modern/website/css/octen.css css/octen.css
# 复核 hub.css 里有没有被上游覆盖的类（上游偶尔会改 .features-grid / .vlsc-gn 这类）
```

### 现网变了

先**复核**（读实际配置 / 实测），再改页面，最后更新第 2 节这张表。
顺序反过来就会生产出一份"看起来对"的文档。

### 三条硬约定

1. **关键内容不要用 `.vlsc-reveal`。** 那个类在 `octen.css` 里默认 `opacity: 0`，
   必须靠 JS 加 `.in` 才可见 —— JS 一旦加载失败，正文会整段隐形。
   入场动画请用纯 CSS 的 `.animate`。
2. **HTML 里不得出现查询串形式的令牌字段。** 本仓的 SDD 约束
   （`hub-token-not-in-url`）会把 `?token=` / `?code=` / `?ticket=` 判为**阻断级违规**。
   讲"凭据不进 URL"这个决策时，写"查询参数形式的启动码"或只写字段名，
   **不要为了举例写出字面串**。也不要用 `exclude_scope` 削弱规则来给自己开后门。
3. **`<body data-site>` 必须等于热链脚本 `PATHS` 里的键**（本站是 `mrrc_hub`）。
   顶栏的高亮项就是拿它去比对的：写成别的值不会报错，只会**静默不高亮**。
   键名随 `www.vlsc.net/js/global-nav.js` 走 —— 改本站这个值前先去那份 canonical 里确认。

---

## 4. 发布

```bash
cd mrrc_hub/website
bash deploy.sh          # 会先跑金规则闸门，再问一次确认
```

脚本会：备份现网（按名字排序保留最新 3 份）→ 幂等确保 nginx 有 `/mrrc_hub/`
的 location → 上传 → 修权限 → 逐页实测状态码。

发布后仍需**人工确认**：

```bash
for p in "" index start use trouble design; do
  curl -s -o /dev/null -w "/$p.html → %{http_code}\n" "https://www.vlsc.net/mrrc_hub/$p.html"
done
```

---

## 5. 复验清单（每次发布前跑）

```bash
cd mrrc_hub/website

# ① 金规则：不得出现查询串形式的令牌字段
grep -rnE '[?&](token|code|ticket)=' ./*.html \
  && { echo "违反 SDD 约束 hub-token-not-in-url —— 拒绝发布"; exit 1; } \
  || echo "✓ 金规则 clean"

# ② 断链 + 标签平衡 + id 唯一 + 跨页锚点
python3 - <<'PY'
import re, os
from html.parser import HTMLParser

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
SKIP_SCHEME = ('http://','https://','mailto:','tel:','data:','javascript:')

class Doc(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.ids, self.err = [], [], []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if 'id' in d: self.ids.append(d['id'])
        if tag not in VOID: self.stack.append((tag, self.getpos()[0]))
    def handle_endtag(self, tag):
        if tag in VOID: return
        if self.stack and self.stack[-1][0] == tag: self.stack.pop()
        else: self.err.append(f'</{tag}>（第 {self.getpos()[0]} 行）不匹配')

bad = []
pages = sorted(f for f in os.listdir('.') if f.endswith('.html'))
parsed = {}
for f in pages:
    src = open(f, encoding='utf-8').read()
    d = Doc(); d.feed(src); parsed[f] = d
    if d.err or d.stack:
        bad.append(f'{f}: 标签不平衡 {d.err or [t for t, _ in d.stack]}')
    dup = sorted({i for i in d.ids if d.ids.count(i) > 1})
    if dup: bad.append(f'{f}: 重复 id {dup}')

for f in pages:
    src = open(f, encoding='utf-8').read()
    for href in re.findall(r'href="([^"]+)"', src):
        if href.startswith(SKIP_SCHEME): continue
        path, _, frag = href.partition('#')
        if not path:                                    # 同页锚点
            if frag and frag not in parsed[f].ids:
                bad.append(f'{f}: 同页锚点 #{frag} 无目标')
            continue
        path = path.split('?', 1)[0]                    # 去掉 ?v= 缓存串
        if not path: continue
        if not os.path.exists(path):
            bad.append(f'{f}: 断链 → {href}'); continue
        if frag and path in parsed and frag not in parsed[path].ids:
            bad.append(f'{f}: 跨页锚点 {path}#{frag} 无目标')

print('✓ 断链 / 标签平衡 / 锚点 全部通过（%d 页）' % len(pages) if not bad
      else '✗ 发现问题:\n  ' + '\n  '.join(bad))
raise SystemExit(0 if not bad else 1)
PY

# ③ 上游样式表未被意外改动（两行哈希必须相同）
shasum -a 256 css/octen.css ../../mrrc_modern/website/css/octen.css

# ④ 现网入口仍符合站点描述（页面里写的就是这些期望值）
curl -s -o /dev/null -w "主路 /login    → %{http_code}（期望 200）\n" https://bg1sb.mrrc.vlsc.net:9988/login
curl -s -o /dev/null -w "主路 /api/health → %{http_code}（期望 401）\n" https://bg1sb.mrrc.vlsc.net:9988/api/health
curl -s -o /dev/null -w "备用口 :8899     → %{http_code}（期望 200）\n" https://bg1sb.mrrc.vlsc.net:8899/login

# ⑤ 仓库 SDD 约束
python3 ../.agents/skills/sdd-guardian/harness/sdd_context.py check --staged
```

> 用 `curl -s -o /dev/null -w`，**不要用 `curl -sI`** —— 后者发 HEAD，
> 而登录页只接受 GET，会返回 405 让你误判。

---

## 6. 已知的现网问题（写进站点了，别忘了它还开着）

| 问题 | 状态 | 站内位置 |
| --- | --- | --- |
| 海外边缘入口 `www → hub:9988` 这一跳间歇性失败（2026-10-01 实测 6 次中 3 次 20 s 无响应） | **未修复**，已定位到 www 到 Hub 那一跳；已排除本地链路、www 静态服务、www 上另一条代理腿、Hub 侧 SNI/Host 组合 | `use.html#entries`、`design.html#status`、`trouble.html#symptoms` |
| 登录限流在隧道路径下退化为全局桶 | 已决定暂缓 | `use.html#gaps` |
| `deploy/*.sh` 与现网漂移（重跑会让现网退化） | 已记录未修 | `deploy/README.md` 的「⚠️ 脚本与现网漂移」 |

修好之后，上面三处站内描述要**一并**更新。
