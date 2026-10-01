#!/usr/bin/env bash
# MRRC Cloud Hub 文档站 — 发布到 www.vlsc.net/mrrc_hub/
#
# 幂等：可重复执行；先备份、再校验、最后 reload。
# 本脚本**不会**被自动执行 —— 上线由人决定（规格 §1.2 非目标）。
#
# 学到的教训（源自 mrrc_modern/website/deploy.sh，逐条保留）：
#   * 备份保留按**名字**排序而不是 mtime（mtime 会继承源目录时间戳，
#     曾导致刚做的备份被当成最旧的删掉）
#   * scp 之前先清掉服务器上的旧包，避免解包 glob 匹配到截断的包
#   * 解包只覆盖不删除，所以要显式 prune 掉不该出现在 DocumentRoot 的东西
#   * nginx 配置改完必须先 nginx -t 再 reload
set -euo pipefail

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_HOST="www.vlsc.net"
REMOTE_USER="cheenle"
REMOTE_WEBROOT="/var/www/vlsc.net/mrrc_hub"
SITE_URL="https://www.vlsc.net/mrrc_hub"
STAMP="$(date +%Y%m%d_%H%M%S)"

# --yes / -y ：跳过确认提示。没有它、且 stdin 不是终端时（比如被代理或 CI 调用），
# 以前会静静退在 `read` 上 —— 因为 `set -e` 会在 read 遇 EOF 返回非零时终结脚本，
# 结果就是“两道闸门都绿了、然后退出码 1、什么也没发生”。这个坑实测踩过。
ASSUME_YES=0
case "${1:-}" in
-y | --yes) ASSUME_YES=1 ;;
-h | --help)
	echo "用法: bash deploy.sh [--yes]"
	echo "  --yes   跳过确认提示（非交互调用时必须带）"
	exit 0
	;;
"") ;;
*)
	echo "未知参数: $1（只接受 --yes）" >&2
	exit 2
	;;
esac

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

cd "$LOCAL_DIR"

echo "=========================================="
echo " MRRC Cloud Hub 文档站 发布"
echo "=========================================="
echo "本地: $LOCAL_DIR"
echo "远端: $REMOTE_USER@$REMOTE_HOST:$REMOTE_WEBROOT"
echo "URL : $SITE_URL/"
echo ""

echo "检查必需文件..."
REQUIRED_FILES=(
	index.html start.html use.html trouble.html design.html
	css/octen.css css/hub.css js/hub.js README.md
)
for f in "${REQUIRED_FILES[@]}"; do
	if [[ ! -f "$f" ]]; then
		echo -e "${RED}缺文件: $f${NC}"
		exit 1
	fi
	echo -e "${GREEN}✓${NC} $f"
done

echo ""
echo "发布前闸门..."
if grep -rnE '[?&](token|code|ticket)=' ./*.html; then
	echo -e "${RED}以上命中违反 SDD 约束 hub-token-not-in-url —— 拒绝发布${NC}"
	exit 1
fi
echo -e "${GREEN}✓${NC} 金规则 clean"

if ! diff -q css/octen.css ../../mrrc_modern/website/css/octen.css >/dev/null; then
	echo -e "${RED}css/octen.css 与上游不再一致 —— 这是「永不 fork」约定被破坏的信号${NC}"
	echo "  修法：cp ../../mrrc_modern/website/css/octen.css css/octen.css"
	exit 1
fi
echo -e "${GREEN}✓${NC} upstream 样式表逐字节一致"

echo ""
if [[ "$ASSUME_YES" == "1" ]]; then
	echo "--yes：跳过确认，直接发布"
else
	# `|| true` 是必需的：read 遇 EOF 返回非零，而 set -e 会把整个脚本干掉。
	# 我们要的是“干净的取消”，不是“崩溃在提示行上”。
	read -rp "继续发布？(y/N): " confirm || confirm=""
	if [[ ! "$confirm" =~ ^[yY] ]]; then
		echo "已取消（没有改动远端）。要跳过此提示：bash deploy.sh --yes"
		exit 0
	fi
fi

PACKAGE="/tmp/mrrc_hub_website_${STAMP}.tar.gz"
tar -czf "$PACKAGE" \
	--exclude='deploy.sh' --exclude='.DS_Store' --exclude='.__*' \
	--exclude='__pycache__' -C "$LOCAL_DIR" .
echo -e "${GREEN}✓${NC} 打包 $PACKAGE"

ssh "$REMOTE_USER@$REMOTE_HOST" <<EOF
set -e

# 1) 备份（保留最新 3 份，按名字排序 —— 见文件头教训）
if [ -d "$REMOTE_WEBROOT" ] && [ -n "\$(ls -A $REMOTE_WEBROOT 2>/dev/null)" ]; then
	sudo mkdir -p /var/tmp
	BK="/var/tmp/mrrc_hub_backup_${STAMP}"
	sudo rsync -a "$REMOTE_WEBROOT/" "\$BK"/
	sudo touch "\$BK"
	ls -1d /var/tmp/mrrc_hub_backup_* 2>/dev/null | sort -r | tail -n +4 \
		| xargs -r -d '\n' sudo rm -rf || true
	echo "已备份: \$BK"
fi

# 2) 清掉旧包，保证解包 glob 只匹配到一个文件
sudo rm -f /var/tmp/mrrc_hub_website_*.tar.gz

# 3) nginx: 幂等确保 /mrrc_hub/ location 存在
NGINX_SITE=/etc/nginx/sites-available/vlsc.net
if [ -f "\$NGINX_SITE" ]; then
	sudo python3 - "\$NGINX_SITE" <<'PYEOF'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
if "location ^~ /mrrc_hub/" in text:
    print("nginx: /mrrc_hub/ location 已存在")
else:
    block = """    # ── MRRC Cloud Hub 文档站 (/mrrc_hub/) ──
    location ^~ /mrrc_hub/ {
        try_files \$uri \$uri/ =404;
        autoindex off;
    }
    location = /mrrc_hub {
        return 301 /mrrc_hub/;
    }
"""
    marker = "    # ── MRRC Cloud Hub edge ("
    if marker in text:
        text = text.replace(marker, block + "\n" + marker, 1)
    else:
        text = text.rstrip() + "\n\n" + block
    open(path, "w", encoding="utf-8").write(text)
    print("nginx: 已添加 /mrrc_hub/ location")
PYEOF
	sudo nginx -t && sudo systemctl reload nginx && echo "nginx reloaded"
else
	echo -e "${YELLOW}警告: \$NGINX_SITE 不存在，跳过 nginx 配置${NC}"
fi

sudo mkdir -p "$REMOTE_WEBROOT"
EOF

scp "$PACKAGE" "$REMOTE_USER@$REMOTE_HOST:/var/tmp/"

ssh "$REMOTE_USER@$REMOTE_HOST" <<EOF
set -e
TARBALL=\$(ls -1t /var/tmp/mrrc_hub_website_*.tar.gz | head -1)
sudo mkdir -p "$REMOTE_WEBROOT"
sudo tar -xzf "\$TARBALL" -C "$REMOTE_WEBROOT" --overwrite

# 解包只覆盖不删除：把不属于站点内容的东西从 DocumentRoot 里清掉
sudo rm -f "$REMOTE_WEBROOT/deploy.sh" 2>/dev/null || true

sudo chown -R www-data:www-data "$REMOTE_WEBROOT"
sudo chmod -R 755 "$REMOTE_WEBROOT"
sudo find "$REMOTE_WEBROOT" -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' \) \
	-exec chmod 644 {} \;
rm -f "\$TARBALL"

echo ""
echo "发布完成。逐页实测："
echo "  /          → \$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/")"
for p in index start use trouble design; do
	echo "  /\$p.html → \$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL/\$p.html")"
done
EOF

rm -f "$PACKAGE"
echo ""
echo -e "${GREEN}完成${NC} → $SITE_URL/"
