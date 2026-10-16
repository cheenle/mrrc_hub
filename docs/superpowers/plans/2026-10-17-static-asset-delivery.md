# 静态资源分发（gzip + 两层缓存）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** `ba4eg.mrrc.vlsc.net`（及其余实例）的重复访问不再重传大静态件，且部署后新版仍能立即看到。

**架构：** hub 边缘 nginx 加 gzip 与资源级 `proxy_cache`（1 小时、只缓存 200、按实例分键），实例侧（`mrrc_modern`）补 `Cache-Control` 与条件请求 304 —— 两层同一套值，边缘对公网路径生效，实例对局域网/退化路径生效。

**技术栈：** nginx 1.28（`proxy_cache` / `gzip` / `map`）、FastAPI + Starlette 1.3（`FileResponse`）、`unittest`。

**规格：** `docs/superpowers/specs/2026-10-17-static-asset-delivery-design.md`（本计划的验收口径全部来自 §5）

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `mrrc_hub/deploy/nginx/mrrc-hub-upstream.conf` | 创建 | hub → 实例这一跳的**唯一**上游定义（`proxy_pass` + 逐实例 TLS 校验 + 转发头） |
| `mrrc_hub/deploy/nginx/mrrc-hub-cache.conf` | 创建 | 缓存区与两个 `map`（状态码、客户端 `no-cache`） |
| `mrrc_hub/deploy/nginx/mrrc-instances.vhost` | 创建 | 通配 vhost 模板（从现网导出 + 三处改动），由脚本安装 |
| `mrrc_hub/deploy/deploy_hub_routes.sh` | 修改 | 安装上面三份配置、建缓存目录、`nginx -t` 失败自动回滚；顺带收口 X1 漂移（`proxy_ssl_name`、vhost 文件名、自签注释） |
| `mrrc_hub/deploy/verify_hub_cache.sh` | 创建 | 边缘缓存验收：7 条断言逐条打印 PASS/FAIL |
| `mrrc_hub/tests/test_hub_vhost_template.py` | 创建 | 结构性守卫：模板必须逐实例校验、不得出现 `proxy_ssl_verify off`、资源 location 必须 `include` 上游片段 |
| `mrrc_hub/deploy/README.md`、`SDD/{12,14,README}.md` | 修改 | 文档同步（X1 → 已对齐；新增「缓存与压缩」） |
| `mrrc_modern/server.py` | 修改 | `_cache_control_for()` / 条件请求 304 / 有扩展名的缺失文件 404 |
| `mrrc_modern/tests/test_static_cache_headers.py` | 创建 | 上面三件事的单测（含鉴权顺序不回归） |
| `mrrc_modern/{CHANGELOG.md,AGENTS.md,tests/README.md,SDD/14-version-history.md}` | 修改 | 文档同步 |

---

## 任务 1：hub 的三份 nginx 配置（可评审、可守卫）

**文件：**

- 创建：`mrrc_hub/deploy/nginx/mrrc-hub-upstream.conf`
- 创建：`mrrc_hub/deploy/nginx/mrrc-hub-cache.conf`
- 创建：`mrrc_hub/deploy/nginx/mrrc-instances.vhost`

- [ ] **步骤 1：写上游片段**

`deploy/nginx/mrrc-hub-upstream.conf` —— 两个 `location` 共用同一份，杜绝「一处漏抄 = TLS 校验被关掉」：

```nginx
# Managed by mrrc_hub/deploy/deploy_hub_routes.sh — edits are overwritten.
#
# hub → 实例这一跳的唯一定义：两个 location（`/` 与静态资源）都 include 它。
# 之所以收成一份，是因为 deploy/README.md 的 X1 漂移正是「同一件事写两处、
# 漏改一处」：静态资源 location 若漏抄 proxy_ssl_verify on，
# 就等于把 NFR-H021 悄悄关掉，而且 nginx -t 与页面都看不出来。
#
# 不含 proxy_buffering：WebSocket 与单向流不缓冲，静态资源要缓冲（各自设置）。

# Unknown name → 404, never a guess at some other instance's tunnel.
if ($mrrc_port = 0) {
    return 404 "unknown instance\n";
}

proxy_pass https://127.0.0.1:$mrrc_port;

# End-to-end TLS: frps forwards raw TCP, so this verification covers the
# instance's own certificate, not frp's.
proxy_ssl_verify on;
proxy_ssl_verify_depth 2;
proxy_ssl_name $mrrc_tls_name;   # 按实例：自签租户的证书签给它自己的入口名
proxy_ssl_server_name on;
proxy_ssl_trusted_certificate /etc/mrrc-hub/trust-bundle.pem;   # 系统 CA + 各实例证书
proxy_ssl_session_reuse on;

proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;

# MRRC runs five long-lived WebSocket endpoints.
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400;
```

- [ ] **步骤 2：写缓存配置**

`deploy/nginx/mrrc-hub-cache.conf` —— 缓存区落在 `/var/lib/nginx/`（Debian/Ubuntu 的 nginx 可写惯例目录，`/var/lib/nginx/proxy` 已由 www-data 持有）：

```nginx
# Managed by mrrc_hub/deploy/deploy_hub_routes.sh — edits are overwritten.
#
# 只有 <名>.mrrc.vlsc.net 这一组 vhost 用它；门户（portal）与站点不共享该缓存区。

proxy_cache_path /var/lib/nginx/cache-mrrc levels=1:2 keys_zone=mrrc_assets:32m
                 max_size=1g inactive=7d use_temp_path=off;

# 只有 200/304 才带缓存头。307（未登录）与 404 若带上 max-age，
# 浏览器会把「要登录」或「没有这个文件」记下来 —— 这是本设计最危险的一处：
# 一个被缓存的 307 会让已登录用户在一小时内反复被打回登录页。
map $status $mrrc_asset_cc {
    default "";
    200     "public, max-age=3600";
    304     "public, max-age=3600";
}

# 客户端明确要求别用缓存（硬刷新 / DevTools「停用缓存」）→ 绕过边缘缓存回源。
# 只认 no-cache / no-store：普通重新加载发的 max-age=0 仍走缓存，
# 否则每次 F5 都会把整套静态件重新拉过隧道。
map $http_cache_control $mrrc_client_nocache {
    default        0;
    "~*no-cache"   1;
    "~*no-store"   1;
}
```

- [ ] **步骤 3：写 vhost 模板**

`deploy/nginx/mrrc-instances.vhost` —— 内容 = 现网 `/etc/nginx/sites-available/mrrc-instances`（2026-10-17 导出）+ 三处改动（① 头部注释不再说自签 ② `location /` 改 `include` 上游片段 ③ 新增 gzip 与资源 location）：

```nginx
# Managed by mrrc_hub/deploy/deploy_hub_routes.sh — edits are overwritten.
#
# ONE vhost for every instance. The alternative (a server block per instance) is
# what B2 did and what made adding an instance a centre-side nginx edit; here the
# per-instance fact is only the loopback port in the generated map.
#
# TLS 是 hub 的通配证书，现网由 DNS-01 签发的真 Let's Encrypt 证书（每日续期）；
# `deploy/mrrc-hub-cert.sh` 是唯一入口。
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name ~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net$;

    ssl_certificate     /etc/mrrc-hub/tls/fullchain.pem;
    ssl_certificate_key /etc/mrrc-hub/tls/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Query strings are never logged here (AD-H07 / NFR-H014).
    access_log /var/log/nginx/mrrc-hub.access.log hub_safe;

    # nginx 默认只压 text/html，而实例自己不发 Content-Encoding ⇒ 不加这几行，
    # opus_wasm.js（534 KB）、ft710_ui.js（94 KB）等都是原样过隧道。
    gzip on;
    gzip_vary on;
    gzip_min_length 256;
    gzip_proxied any;
    gzip_types text/css application/javascript text/plain application/json image/svg+xml;

    location / {
        include snippets/mrrc-hub-upstream.conf;

        # 这里刻意不加 Cache-Control：该路径会返回带 no-store 的敏感响应
        # （首启口令窗口等），覆盖它比不优化更糟。HTML 的 no-cache 由实例侧发。
        proxy_buffering off;
    }

    # 静态资源：唯一的缓存路径。正则 location 优先于 location /。
    # 判定按 URI 扩展名（Content-Type 要等响应回来才知道，而 proxy_cache
    # 是否启用是 location 级的）。
    location ~* \.(?:js|mjs|css|map|png|jpe?g|gif|svg|ico|webp|avif|woff2?|ttf|otf|wasm|wav|mp3|m4a)$ {
        include snippets/mrrc-hub-upstream.conf;

        proxy_buffering on;

        proxy_cache mrrc_assets;
        proxy_cache_key "$mrrc_instance$uri$is_args$args";   # 实例 + URI + query，跨实例不串味
        proxy_cache_valid 200 1h;              # 只列 200：302/307/401 永不落盘
        proxy_cache_revalidate on;             # 过期后用 If-Modified-Since 回源复验
        proxy_cache_lock on;                   # 冷缓存并发只放一个回源
        proxy_cache_lock_timeout 5s;
        proxy_cache_background_update on;      # 过期条目先在后台更新
        proxy_cache_use_stale updating error timeout http_500 http_502 http_503 http_504;
        proxy_cache_bypass $mrrc_client_nocache;   # 硬刷新 → 回源

        proxy_hide_header Cache-Control;       # 只发一份，避免与实例侧重复
        add_header Cache-Control $mrrc_asset_cc always;
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

- [ ] **步骤 4：写结构性守卫测试**

创建 `mrrc_hub/tests/test_hub_vhost_template.py`：

```python
"""通配 vhost 模板的守卫（2026-10-17）。

`deploy/nginx/` 下的三份配置是现网的唯一真相源：脚本只做安装，不再用 heredoc
在 shell 里拼 nginx 配置（X1 漂移就是那么来的 —— 模板藏在转义过的 heredoc 里，
现网改了没人发现）。这些断言挡住两类回归：
  ① 逐实例 TLS 校验被压平或关掉（NFR-H021 / hub-tls-verify-off）；
  ② 新增的 location 漏抄上游片段（那等于把校验悄悄关掉，且 nginx -t 看不出来）。
"""
import re
import unittest
from pathlib import Path

NGINX = Path(__file__).resolve().parent.parent / "deploy" / "nginx"
VHOST = (NGINX / "mrrc-instances.vhost").read_text(encoding="utf-8")
UPSTREAM = (NGINX / "mrrc-hub-upstream.conf").read_text(encoding="utf-8")
CACHE = (NGINX / "mrrc-hub-cache.conf").read_text(encoding="utf-8")


def _locations() -> dict:
    """location 头 -> 该块正文（花括号配平，模板只有一层嵌套）。"""
    out = {}
    for match in re.finditer(r"^\s*(location [^\n{]+)\{", VHOST, re.M):
        depth, i = 0, match.end() - 1          # 指向 '{'
        while i < len(VHOST):
            if VHOST[i] == "{":
                depth += 1
            elif VHOST[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out[match.group(1).strip()] = VHOST[match.end() - 1:i + 1]
    return out


class VhostTemplateTests(unittest.TestCase):
    def test_every_cached_location_verifies_the_instance_certificate(self):
        for name, body in _locations().items():
            self.assertIn("include snippets/mrrc-hub-upstream.conf;", body,
                          f"{name} 没有 include 上游片段 —— 逐实例 TLS 校验会在这里缺失")

    def test_verification_is_never_disabled(self):
        for text, label in ((VHOST, "vhost"), (UPSTREAM, "upstream")):
            self.assertNotIn("proxy_ssl_verify off", text, f"{label} 关掉了证书校验（NFR-H021）")
        self.assertIn("proxy_ssl_name $mrrc_tls_name;", UPSTREAM,
                      "上游校验名必须是逐实例的 $mrrc_tls_name（X1 漂移）")

    def test_only_200_is_cached(self):
        self.assertRegex(CACHE, r"proxy_cache_valid 200 1h;")
        self.assertIn('map $status $mrrc_asset_cc', CACHE)
        self.assertNotIn('301 "\n', CACHE)

    def test_asset_location_does_not_cache_unversioned_query_forever(self):
        body = [b for n, b in _locations().items() if n.startswith("location ~*")][0]
        self.assertIn("proxy_cache_bypass $mrrc_client_nocache;", body)
        self.assertNotIn("immutable", body)

    def test_gzip_covers_javascript_and_css(self):
        self.assertRegex(VHOST, r"gzip_types[^;]*application/javascript[^;]*;")
        self.assertRegex(VHOST, r"gzip_types[^;]*text/css[^;]*;")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 5：跑守卫测试（此刻应通过 —— 配置已写好）**

运行：`cd mrrc_hub && python3 -m unittest tests.test_hub_vhost_template -v`
预期：`OK`（5 项）

- [ ] **步骤 6：Commit**

```bash
cd mrrc_hub
git add deploy/nginx tests/test_hub_vhost_template.py
git commit -m "hub(nginx): 通配 vhost 的三份配置入库（逐实例 TLS 校验收成一处 + 资源级缓存与 gzip）"
```

---

## 任务 2：部署脚本改为「安装 + 失败自动回滚」

**文件：**

- 修改：`mrrc_hub/deploy/deploy_hub_routes.sh`

- [ ] **步骤 1：替换变量段**

把脚本头部（`REGISTRY` … `UPSTREAM_SSL_NAME`）改为：

```bash
REGISTRY="/etc/mrrc-hub/instances.tsv"
GENERATOR="/usr/local/sbin/gen_hub_routes.py"
VHOST="/etc/nginx/sites-available/mrrc-instances"   # 现网名；旧脚本写的 mrrc-hub 早就不是 sites-enabled 指向的那个
SNIPPET="/etc/nginx/snippets/mrrc-hub-upstream.conf"
CACHE_CONF="/etc/nginx/conf.d/mrrc-hub-cache.conf"
CACHE_DIR="/var/lib/nginx/cache-mrrc"
HERE="$(cd "$(dirname "$0")" && pwd)"
```

（删除 `UPSTREAM_SSL_NAME="${MRRC_UPSTREAM_SSL_NAME:-radio.vlsc.net}"`：逐实例校验名来自 `$mrrc_tls_name`，写死一个全局名字正是 X1 的症状。）

- [ ] **步骤 2：把 heredoc 换成安装 + 回滚**

删掉整段 `cat >"$VHOST" <<EOF … EOF`，替换为：

```bash
install -m 0644 "$HERE/nginx/mrrc-hub-upstream.conf" "$SNIPPET"
install -m 0644 "$HERE/nginx/mrrc-hub-cache.conf" "$CACHE_CONF"

# nginx 的 worker 是 www-data，缓存目录必须它可写（缓存配置里 use_temp_path=off，
# 临时文件也落这里）。
mkdir -p "$CACHE_DIR"
chown www-data:www-data "$CACHE_DIR"
chmod 0700 "$CACHE_DIR"

BACKUP="$VHOST.bak.$(date +%Y%m%d%H%M%S)"
cp -a "$VHOST" "$BACKUP" 2>/dev/null || true
install -m 0644 "$HERE/nginx/mrrc-instances.vhost" "$VHOST"

# 配置坏了就退回上一版并再次校验 —— 不能把一台挂着全部实例的 hub 留在 nginx -t 失败的状态。
if ! nginx -t; then
 echo "==> nginx -t failed — restoring $VHOST from $BACKUP" >&2
 cp -a "$BACKUP" "$VHOST" 2>/dev/null || rm -f "$VHOST"
 nginx -t
 exit 1
fi

systemctl reload nginx
echo "==> wildcard routing live (cache + gzip)"
echo
echo "verify:"
echo "  ./verify_hub_cache.sh ba4eg              # 边缘缓存 7 条断言"
echo "  curl -skI https://nope.mrrc.vlsc.net/    # 404 (unknown instance)"
```

- [ ] **步骤 3：语法与幂等自检（不改现网）**

运行：`bash -n mrrc_hub/deploy/deploy_hub_routes.sh && echo OK`
预期：`OK`

运行：`grep -c "EOF" mrrc_hub/deploy/deploy_hub_routes.sh`
预期：`0`（heredoc 已删干净；剩下的 `EOF` 只可能出现在别的文件里）

- [ ] **步骤 4：Commit**

```bash
cd mrrc_hub
git add deploy/deploy_hub_routes.sh
git commit -m "hub(deploy): vhost/片段/缓存配置改为安装式；nginx -t 失败自动回滚；X1 漂移收口"
```

---

## 任务 3：落到现网并验收

**文件：**

- 创建：`mrrc_hub/deploy/verify_hub_cache.sh`

- [ ] **步骤 1：写验收脚本**

```bash
#!/usr/bin/env bash
# 边缘静态资源缓存的验收（7 条）。用真实例跑，只读，不改任何配置。
#
#   ./verify_hub_cache.sh ba4eg [--token <mrrc_auth cookie 值>]
#
# 不带 --token 时用 MRRC_HUB_TEST_TOKEN 环境变量；两者都没有就跳过需要登录的断言。
set -uo pipefail

LABEL="${1:?usage: $0 <instance-label> [--token <cookie-value>]}"
TOKEN="${MRRC_HUB_TEST_TOKEN:-}"
[[ "${2:-}" == "--token" ]] && TOKEN="${3:-}"
HOST="https://${LABEL}.mrrc.vlsc.net"
ASSET="/modules/opus_wasm.js"     # 534 KB，最大的那个
COOKIE=(-H "Cookie: mrrc_auth=${TOKEN}")
pass=0; fail=0
check() { # check <名字> <期望> <实际>
 if [[ "$2" == "$3" ]]; then printf 'PASS  %s\n' "$1"; pass=$((pass+1));
 else printf 'FAIL  %s\n        期望 %s\n        实际 %s\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}
code() { curl -sk -o /dev/null -w '%{http_code}' "$@"; }
hdr()  { curl -sk -D - -o /dev/null "$@" | tr -d '\r' | awk -F': ' -v k="$1" 'BEGIN{IGNORECASE=1} tolower($1)==tolower(k){print $2}' | tail -1; }

echo "== $HOST =="
check "未知实例 → 404" "404" "$(code https://nope.mrrc.vlsc.net/)"

if [[ -z "$TOKEN" ]]; then
 echo "SKIP  未提供 --token：跳过需要登录的 5 条"
 exit 0
fi

check "资源 200" "200" "$(code "${COOKIE[@]}" "$HOST$ASSET")"
check "资源带 1 小时缓存头" "public, max-age=3600" "$(hdr cache-control "${COOKIE[@]}" "$HOST$ASSET")"
ETAG="$(hdr etag "${COOKIE[@]}" "$HOST$ASSET")"
check "重复请求命中边缘缓存" "HIT" "$(hdr x-cache-status "${COOKIE[@]}" "$HOST$ASSET")"
check "条件请求边缘答 304" "304" "$(code "${COOKIE[@]}" -H "If-None-Match: $ETAG" "$HOST$ASSET")"
check "硬刷新绕过缓存" "BYPASS" "$(hdr x-cache-status "${COOKIE[@]}" -H 'Cache-Control: no-cache' "$HOST$ASSET")"
SIZE="$(curl -sk --compressed -o /dev/null -w '%{size_download}' "${COOKIE[@]}" "$HOST$ASSET")"
check "gzip 生效（< 300 KB）" "yes" "$([[ $SIZE -lt 307200 ]] && echo yes || echo no)"
check "HTML 不进缓存" "" "$(hdr x-cache-status "${COOKIE[@]}" "$HOST/")"
printf '\n%s passed, %s failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
```

- [ ] **步骤 2：备份 + 应用（在生产 hub 上）**

```bash
# 本机：把 deploy/ 同步到 hub（配置与脚本一起过去，避免"改了现网没进仓"）
rsync -a --exclude='*.pyc' mrrc_hub/deploy/ cheenle@www.vlsc.net:~/deploy-new/
ssh -4 cheenle@www.vlsc.net '
  sudo cp -a /etc/nginx/sites-available/mrrc-instances ~/mrrc-instances.bak.$(date +%Y%m%d%H%M%S)
  cd ~/deploy-new && sudo ./deploy_hub_routes.sh
'
```

预期输出：`==> wildcard routing live (cache + gzip)`，且 `nginx -t` 通过。

- [ ] **步骤 3：跑验收**

```bash
./verify_hub_cache.sh ba4eg --token <登录 https://ba4eg.mrrc.vlsc.net/ 后 Cookie 里的 mrrc_auth 值>
```

预期：`8 passed, 0 failed`。

- [ ] **步骤 4：抽查其余实例不受影响**

```bash
for i in bg7zhs bg1sb bh2xjd; do ./verify_hub_cache.sh "$i" --token …; done
curl -sk https://bg7zhs.mrrc.vlsc.net/api/health -H "Cookie: mrrc_auth=…"   # 该实例的既有行为不变
```

- [ ] **步骤 5：回滚演练（记录命令即可，不在生产上执行）**

```bash
sudo cp -a ~/mrrc-instances.bak.<时间戳> /etc/nginx/sites-available/mrrc-instances
sudo rm -f /etc/nginx/conf.d/mrrc-hub-cache.conf /etc/nginx/snippets/mrrc-hub-upstream.conf
sudo rm -rf /var/lib/nginx/cache-mrrc
sudo nginx -t && sudo systemctl reload nginx
```

---

## 任务 4：hub 文档同步

**文件：**

- 修改：`mrrc_hub/deploy/README.md`（X1 行改为「已对齐」+ 新增「缓存与压缩」一节）
- 修改：`mrrc_hub/SDD/12-operational-model.md`、`SDD/14-version-history.md`、`SDD/README.md`

- [ ] **步骤 1：README 的 X1 行**

把 X1 行改为：已对齐（`proxy_ssl_name $mrrc_tls_name` 现由 `deploy/nginx/mrrc-hub-upstream.conf` 提供，vhost 与资源 location 都 include 它；脚本不再把模板藏在 heredoc 里），并删除「在写回之前不要重跑」的警告。

- [ ] **步骤 2：README 新增一节（放在「脚本与现网漂移」之后）**

```markdown
## 静态资源：gzip + 边缘缓存（2026-10-17）

实例侧（`mrrc_modern`）只发 `ETag`/`Last-Modified`，不发 `Cache-Control`，也不实现条件
请求 —— 实测带 `If-None-Match` 仍返回 200 + 完整 534 KB。于是"每次加载都慢"由三件事叠成：
不压缩、不缓存、重新校验必然全量重传。

边缘因此做三件事（配置在 `deploy/nginx/`，脚本安装）：

| 项 | 值 | 位置 |
| --- | --- | --- |
| gzip | `text/css` `application/javascript` `application/json` `image/svg+xml` | vhost server 级 |
| 资源缓存 | `proxy_cache` 1 小时，**只缓存 200**，按 `实例+URI+query` 分键 | vhost 的资源 location |
| 响应头 | 200/304 才发 `Cache-Control: public, max-age=3600` | `deploy/nginx/mrrc-hub-cache.conf` 的 `map $status` |

三条容易踩的：

1. **307/404 不能被缓存**。未登录取静态件会拿到 307 跳登录页；这个响应一旦带上
   `max-age`，已登录用户也会在一小时内反复被打回登录页。所以 `proxy_cache_valid`
   只列 200，且 `Cache-Control` 由 `map $status` 只在 200/304 上发。
2. **硬刷新要能穿透**。`Cache-Control: no-cache` 的请求由
   `proxy_cache_bypass $mrrc_client_nocache` 直接回源；但普通重新加载（`max-age=0`）
   仍走缓存 —— 否则每次 F5 都把整套静态件重新拉过隧道。
3. **两个 location 必须用同一份上游定义**（`snippets/mrrc-hub-upstream.conf`）。
   漏抄一处 `proxy_ssl_verify on` 就是 NFR-H021 被悄悄关掉，而 `nginx -t` 与页面都正常。
   `tests/test_hub_vhost_template.py` 钉住这一点。

验收：`./verify_hub_cache.sh <标签> --token <mrrc_auth 值>`（8 条断言）。
回滚：恢复 vhost 备份 + 删掉 `conf.d/mrrc-hub-cache.conf`、`snippets/mrrc-hub-upstream.conf`
与 `/var/lib/nginx/cache-mrrc`，再 `nginx -t && systemctl reload nginx`。
```

- [ ] **步骤 3：SDD 条目**

`SDD/12-operational-model.md` 增小节「边缘缓存与压缩」（三条取舍：只缓存 200、按扩展名、
未登录可拿静态件）；`SDD/14-version-history.md` 增条目并指向本计划与规格；
`SDD/README.md` 版本号 +0.01。

- [ ] **步骤 4：Commit**

```bash
cd mrrc_hub && git add deploy/README.md SDD/ && git commit -m "docs(hub): 边缘缓存与压缩入档；X1 漂移收口后删除禁跑警告"
```

---

## 任务 5：实例侧三件事（TDD）

**文件：**

- 测试：`mrrc_modern/tests/test_static_cache_headers.py`
- 修改：`mrrc_modern/server.py:4846-4885`（`serve_static`）与 `server.py:4827-4845` 附近的辅助区

- [ ] **步骤 1：写失败的测试**

```python
"""静态资源的两层缓存契约（2026-10-17，规格 §3.3）。

实例侧要发三件事：分类的 Cache-Control、条件请求 304、有扩展名的缺失文件 404。
边缘（hub nginx）会对公网路径再包一层同样的值；这里钉的是"实例自己也对"，
于是局域网直连、B2/B3 退化路径、别的反代拿到同样的语义。

为什么值得测：实例此前只发 ETag/Last-Modified、不实现条件 GET —— 实测带
`If-None-Match` 仍返回 200 与完整 534 KB，于是每次重新加载都等于重新穿一遍隧道。
"""
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

import server


def _request(path: str, **headers: str) -> Request:
    raw = [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": raw, "scheme": "http",
        "server": ("testserver", 80), "client": ("127.0.0.1", 12345), "root_path": "",
    }
    return Request(scope)


def _serve(path: str, **headers: str):
    """绕过鉴权直接取文件响应（鉴权顺序由 login 那个测试单独钉）。"""
    with patch.object(server, "_verify_auth", return_value=True):
        return asyncio.run(server.serve_static(path, _request("/" + path, **headers)))


class CacheControlTests(unittest.TestCase):
    def test_documents_revalidate_every_time(self):
        for path in ("", "index.html", "settings.html", "manifest.json", "sw.js"):
            self.assertEqual(_serve(path).headers["cache-control"], "no-cache", path)

    def test_assets_are_cached_for_an_hour(self):
        for path in ("ft710.css", "ft710_main.js", "modules/opus_wasm.js", "audio/cq.wav"):
            self.assertEqual(_serve(path).headers["cache-control"],
                             "public, max-age=3600", path)

    def test_helper_covers_types_without_a_file_on_disk(self):
        for name in ("x.woff2", "x.svg", "x.wasm", "x.mp3"):
            self.assertEqual(server._cache_control_for(Path(name)), "public, max-age=3600")
        for name in ("x.html", "x.json"):
            self.assertEqual(server._cache_control_for(Path(name)), "no-cache")


class ConditionalRequestTests(unittest.TestCase):
    def test_matching_etag_answers_304_without_a_body(self):
        first = _serve("ft710.css")
        again = _serve("ft710.css", if_none_match=first.headers["etag"])
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.body, b"")
        self.assertEqual(again.headers["etag"], first.headers["etag"])
        self.assertEqual(again.headers["cache-control"], "public, max-age=3600")

    def test_stale_etag_still_gets_the_file(self):
        response = _serve("ft710.css", if_none_match='"deadbeef"')
        self.assertEqual(response.status_code, 200)

    def test_if_modified_since_at_or_after_mtime_answers_304(self):
        first = _serve("ft710.css")
        again = _serve("ft710.css", if_modified_since=first.headers["last-modified"])
        self.assertEqual(again.status_code, 304)

    def test_unparseable_if_modified_since_is_ignored(self):
        self.assertEqual(_serve("ft710.css", if_modified_since="not-a-date").status_code, 200)


class MissingAssetTests(unittest.TestCase):
    def test_a_missing_file_with_an_extension_is_404_not_index(self):
        """favicon.png 不存在：旧行为回落 40 KB 的 index.html，浏览器当图片收下。"""
        for path in ("favicon.png", "favicon.ico", "nope.js"):
            response = _serve(path)
            self.assertEqual(response.status_code, 404, path)

    def test_extension_less_paths_still_fall_back_to_index(self):
        response = _serve("some/spa/route")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "text/html")

    def test_static_assets_still_need_auth(self):
        """缓存头不得改变鉴权顺序：没带令牌取资源仍然是 307 跳登录。"""
        response = asyncio.run(server.serve_static("ft710.css", _request("/ft710.css")))
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/login")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行，确认失败**

运行：`cd mrrc_modern && ./venv/bin/python -m unittest tests.test_static_cache_headers -v`
预期：FAIL —— `AttributeError: module 'server' has no attribute '_cache_control_for'`（以及若干 `KeyError: 'cache-control'`）

- [ ] **步骤 3：实现**

在 `server.py` 的 `_resolve_static_path` 之后、`serve_static` 之前插入：

```python
def _cache_control_for(path: Path) -> str:
    """静态件的缓存语义（两层同一套值：hub 边缘也发这两个常量）。

    文档（HTML/JSON）与 sw.js 每次都重新校验 —— 部署后新版必须立刻可见；
    其余静态件 1 小时：``?v=`` 是**手工** bump 的，漏 bump 时这就是用户最长踩到
    旧代码的窗口。刻意不写 ``immutable``：那会把漏 bump 的代价放成一年。
    """
    if path.suffix.lower() in (".html", ".htm", ".json") or path.name == "sw.js":
        return "no-cache"
    return "public, max-age=3600"


def _not_modified(request: Request, headers) -> bool:
    """条件请求命中（RFC 7232：If-None-Match 存在时不再看 If-Modified-Since）。"""
    etag = headers.get("etag")
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        if not etag:
            return False
        candidates = {token.strip() for token in if_none_match.split(",")}
        return etag in candidates or f"W/{etag}" in candidates
    if_modified_since = request.headers.get("if-modified-since")
    last_modified = headers.get("last-modified")
    if if_modified_since and last_modified:
        try:
            return parsedate_to_datetime(if_modified_since) >= parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            return False     # 报文里的日期坏掉时当作"没带条件"，宁可多发一次文件
    return False
```

`import` 区补 `from email.utils import parsedate_to_datetime`（与既有 `import` 排序一致）。

把 `serve_static` 的文件分支替换为：

```python
    if not file_path.is_file():
        # 有扩展名 = 在要一个静态文件（/favicon.png、/nope.js）：没有就是 404。
        # 旧行为会回落 index.html —— 浏览器把 40 KB 的 HTML 当图片或脚本收下，
        # 每次加载白拉一遍。无扩展名的 SPA 路由（/settings、/ft8…）仍按原样回落。
        if Path(path).suffix:
            return HTMLResponse("<h1>404 Not Found</h1>", status_code=404)
        file_path = STATIC_DIR / "index.html"
        if not file_path.exists():
            return HTMLResponse("<h1>MRRC Modern</h1><p>Static files not found.</p>", status_code=404)

    ext = file_path.suffix.lower()
    content_types = {
        ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".wav": "audio/wav", ".mp3": "audio/mpeg",
    }
    response = FileResponse(
        file_path,
        media_type=content_types.get(ext, "application/octet-stream"),
        # 显式传入 stat：Starlette 1.3 的 FileResponse 只在 __call__ 里 stat 并补
        # ETag/Last-Modified，而条件请求要在**发出去之前**就能比对。
        stat_result=file_path.stat(),
    )
    response.headers["Cache-Control"] = _cache_control_for(file_path)
    if _not_modified(request, response.headers):
        headers = {name: response.headers[name] for name in ("etag", "last-modified", "cache-control")
                   if name in response.headers}
        return Response(status_code=304, headers=headers)
    return response
```

- [ ] **步骤 4：运行，确认通过**

运行：`cd mrrc_modern && ./venv/bin/python -m unittest tests.test_static_cache_headers -v`
预期：`OK`（13 项）

- [ ] **步骤 5：跑既有静态相关测试，确认无回归**

运行：`./venv/bin/python -m unittest tests.test_server_security tests.test_static_cache_busting tests.test_server_box_pages -v`
预期：`OK`

- [ ] **步骤 6：Commit**

```bash
cd mrrc_modern
git add server.py tests/test_static_cache_headers.py
git commit -m "perf(static): 静态件发 Cache-Control + 条件请求答 304；有扩展名的缺失文件 404

实例此前只发 ETag/Last-Modified、不实现条件 GET —— 带 If-None-Match 仍返回
200 与完整 534 KB，每次重新加载都等于重新穿一遍隧道。文档类 no-cache、
其余静态件 1 小时（?v= 是手工 bump 的，1 小时是漏 bump 的最长窗口）。"
```

---

## 任务 6：实例侧文档同步与全套件

**文件：**

- 修改：`mrrc_modern/CHANGELOG.md`（当前未发布的 v1.28.1 段）
- 修改：`mrrc_modern/SDD/14-version-history.md`、`AGENTS.md`、`tests/README.md`
- 修改：`mrrc_modern/docs/`（如需，指向本计划的 hub 侧记录）

- [ ] **步骤 1：CHANGELOG 条目**（追加到 v1.28.1 段末尾）

要点写清：三条改动、为什么 1 小时、为什么不用 `immutable`、为什么 404 规则只认扩展名、
测试数 `N → N+13`。

- [ ] **步骤 2：全套件**

运行：`cd mrrc_modern && ./venv/bin/python -m unittest discover -s tests 2>&1 | tail -3`
预期：与改动前同红灯数（本改动前先记录基线），无新增 FAIL。

- [ ] **步骤 3：SDD 守卫与文档计数**

运行：`python3 .agents/skills/sdd-guardian/harness/sdd_context.py check --staged`
运行：`python3 dev_tools/release_check.py`（离线规则应仍全过）
预期：clean / 无漂移

- [ ] **步骤 4：Commit**

```bash
cd mrrc_modern
git add CHANGELOG.md SDD/ AGENTS.md tests/README.md docs/
git commit -m "docs(static): 缓存契约入 CHANGELOG/SDD/tests 计数"
```

---

## 完成判据

- [ ] `mrrc_hub/deploy/verify_hub_cache.sh ba4eg --token …` → 8 条全 PASS
- [ ] 同一浏览器重复加载 `https://ba4eg.mrrc.vlsc.net/`：DevTools 里 `opus_wasm.js` 第二次起为 `(memory cache)`/304，传输 0 B
- [ ] 首屏静态件传输量从 816 KB 降到 ≤ 274 KB（gzip 后）
- [ ] 硬刷新（Cmd/Ctrl+Shift+R）后 `X-Cache-Status: BYPASS`，拿到实例当前文件
- [ ] `mrrc_modern` 全套件无新增红灯；`tests/test_static_cache_headers.py` 13 项全绿
- [ ] `mrrc_hub` 与 `mrrc_modern` 的文档同步提交完成
