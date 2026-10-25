#!/bin/bash
# certbot deploy hook：把续期出来的 *.mrrc.vlsc.net 装进 nginx 真正读的位置。
#
# 为什么需要它、而主线脚本自己也会 install：certbot.timer 每天会独立跑 `certbot renew`。
# 那条路一旦续期成功，除了这里的 hook 没有任何人会把新证书搬到 /etc/mrrc-hub/tls/ ——
# 于是"证书续了但 nginx 还在用旧的"。反过来，如果这个 hook **不存在**，certbot 会认为
# 家族配置里的 deploy-hook 是坏的，续期直接失败（2026-10-21 排查到的状态：脚本里写着
# `--deploy-hook /usr/local/sbin/mrrc-hub-cert-hook.sh`，而那个文件根本不存在）。
#
# 它同时负责把到期时间写给 portal（控制台显示用）。PORTAL 进程以 mrrcportal 身份运行，
# 所以这里不为了"显示"放宽 /etc/mrrc-hub/tls 的目录权限，而是把值写到 portal 自己的目录。
set -u

CERT_DIR=/etc/mrrc-hub/tls
LIVE_DIR=/etc/letsencrypt/live/mrrc-wildcard
CRT="$CERT_DIR/fullchain.pem"
KEY="$CERT_DIR/privkey.pem"

if [ ! -s "$LIVE_DIR/fullchain.pem" ] || [ ! -s "$LIVE_DIR/privkey.pem" ]; then
	echo "[ERROR] 续期结果不存在: $LIVE_DIR" >&2
	exit 2
fi

install -m 644 "$LIVE_DIR/fullchain.pem" "$CRT" || exit 2
install -m 600 "$LIVE_DIR/privkey.pem" "$KEY" || exit 2

# 先写 portal 的到期快照，再 reload：万一 reload 失败，控制台上仍然是新值
dest=/var/lib/mrrc-hub/portal/cert.txt
if install -d -o mrrcportal -g mrrcportal -m 750 "$(dirname "$dest")" 2>/dev/null; then
	openssl x509 -in "$CRT" -noout -enddate -subject >"$dest" 2>/dev/null
	chown mrrcportal:mrrcportal "$dest" 2>/dev/null || true
	chmod 0640 "$dest" 2>/dev/null || true
fi

# 证书换了要 reload；nginx -t 不过就保持旧配置（reload 不会生效）
if nginx -t >/dev/null 2>&1; then
	systemctl reload nginx && echo "[INFO] 新证书已安装到 $CRT，nginx 已 reload"
else
	echo "[ERROR] nginx -t 未通过，未 reload；证书文件已更新" >&2
	exit 1
fi
