#!/usr/bin/env bash
# Install the hub's wildcard routing (one vhost for every instance) — root, on the hub.
#
#   sudo ./deploy_hub_routes.sh
#
# Installs ONE wildcard vhost for all instances, plus its two companions:
#
#   deploy/nginx/mrrc-instances.vhost       → /etc/nginx/sites-available/mrrc-instances
#   deploy/nginx/mrrc-hub-upstream.conf     → /etc/nginx/snippets/   (hub → 实例那一跳的唯一定义)
#   deploy/nginx/mrrc-hub-cache.conf        → /etc/nginx/conf.d/     (静态资源缓存区与两个 map)
#   deploy/nginx/mrrc-hub-log.conf          → /etc/nginx/conf.d/     (hub_safe 日志格式，含 $host)
#
#   <name>.mrrc.vlsc.net  →  https://127.0.0.1:<port>  (that instance's tunnel)
#
# The only per-instance fact left is the loopback port its tunnel claims, kept in
# /etc/mrrc-hub/instances.tsv. Adding instance #2..#200 is a line in that file plus
# a re-run — not an nginx edit per instance, which is what B2 did and what made
# each new frontend asset a centre-side change.
#
# The hop into the tunnel is TLS-verified end to end, per instance, by the name in
# `$mrrc_tls_name` against `/etc/mrrc-hub/trust-bundle.pem` (system CAs + each
# instance's pinned certificate). 校验永远开着（NFR-H021）：这个片段存在的理由
# 就是两个 location 不会有一处漏掉它 —— 而漏掉一处正是 X1 漂移的形态。
#
# The configuration itself lives in `deploy/nginx/` as real nginx files, NOT in
# heredocs here: the previous heredoc form is how the deployed file drifted away
# from the repo without anybody noticing.
set -euo pipefail

REGISTRY="/etc/mrrc-hub/instances.tsv"
GENERATOR="/usr/local/sbin/gen_hub_routes.py"
VHOST="/etc/nginx/sites-available/mrrc-instances" # 现网名；旧脚本写的 mrrc-hub 早已不是 sites-enabled 指向的那个
SNIPPET="/etc/nginx/snippets/mrrc-hub-upstream.conf"
CACHE_CONF="/etc/nginx/conf.d/mrrc-hub-cache.conf"
LOG_CONF="/etc/nginx/conf.d/mrrc-hub-log.conf"
CACHE_DIR="/var/lib/nginx/cache-mrrc"
HERE="$(cd "$(dirname "$0")" && pwd)"

[[ $EUID -eq 0 ]] || {
	echo "must run as root (sudo)" >&2
	exit 2
}
mkdir -p /etc/mrrc-hub

if [[ ! -s "$REGISTRY" ]]; then
	cat >"$REGISTRY" <<EOF
# MRRC Cloud Hub instance registry — one line per instance.
#
#   <subdomain-label>   <loopback port for its tunnel>
#
# The port must sit inside frps' allowPorts range (see /etc/frp/frps.toml); the
# instance's frpc claims the same number as its remotePort. Names must be single
# DNS labels: test1 means https://test1.mrrc.vlsc.net.
#
# After editing: sudo gen_hub_routes.py && sudo nginx -t && sudo systemctl reload nginx
test1		18800
EOF
	echo "==> seeded $REGISTRY"
fi

install -m 0755 "$HERE/gen_hub_routes.py" "$GENERATOR"
python3 "$GENERATOR"

install -D -m 0644 "$HERE/nginx/mrrc-hub-upstream.conf" "$SNIPPET"
install -D -m 0644 "$HERE/nginx/mrrc-hub-cache.conf" "$CACHE_CONF"
# 日志格式也进仓库、由这里安装。它原先只存在于现网机器的 conf.d 里（"hub_safe 记 URI
# 不记 Host" 那句文档就是那么来的）—— 又一处「现网有、仓库没有」的漂移。
install -D -m 0644 "$HERE/nginx/mrrc-hub-log.conf" "$LOG_CONF"

# nginx 的 worker 是 www-data，缓存目录必须它可写（cache conf 里 use_temp_path=off，
# 临时文件也落这里）。
mkdir -p "$CACHE_DIR"
chown www-data:www-data "$CACHE_DIR"
chmod 0700 "$CACHE_DIR"

BACKUP="$VHOST.bak.$(date +%Y%m%d%H%M%S)"
cp -a "$VHOST" "$BACKUP" 2>/dev/null || true
install -D -m 0644 "$HERE/nginx/mrrc-instances.vhost" "$VHOST"

# 配置坏了就退回上一版并再校验一次 —— 这台机器挂着全部实例，
# 不能把它留在 nginx -t 失败的状态里。
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
echo "  ./verify_hub_cache.sh <标签> --token <mrrc_auth 值>   # 边缘缓存 8 条断言"
echo "  curl -sk  https://<实例>.mrrc.vlsc.net/api/health    # 401 (tunnel + instance)"
echo "  curl -sk  https://nope.mrrc.vlsc.net/                # 404 (unknown instance)"
