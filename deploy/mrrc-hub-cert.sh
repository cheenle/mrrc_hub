#!/bin/bash
# MRRC Hub 通配证书：获取 / 续期 / 到期检查
# 覆盖 *.mrrc.vlsc.net（所有实例的入口），按呼号命名的子域共用这一张
#
# 两种状态都可用，凭证到位后自动切换：
#   A) 有 /root/.secrets/aliyun.ini  → DNS-01 签发**真证书**（Let's Encrypt），自动续期
#   B) 没有                              → 维持一张自签通配证书，仅做到期监控
# 通配只能 DNS-01：HTTP-01 固定走 80、TLS-ALPN-01 固定走 443，而境内 80/443 不可用（R-H13）。
#
# 退出码: 0=正常 1=即将到期(<=14天) 2=已过期/缺失
set -u

CERT_DIR=/etc/mrrc-hub/tls
CRT="$CERT_DIR/fullchain.pem"
KEY="$CERT_DIR/privkey.pem"
CREDS=/root/.secrets/aliyun.ini
CERT_NAME=mrrc-wildcard
BASE=mrrc.vlsc.net
DAYS_WARNING=14
DAYS_RENEW=30          # 低于此天数就动手续期/重签

mkdir -p "$CERT_DIR" 2>/dev/null || true

days_left() {
    [ -s "$1" ] || { echo -1; return; }
    local end
    end=$(openssl x509 -in "$1" -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -n "$end" ] || { echo -1; return; }
    echo $(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
}

reload_if_changed

# 供 Portal 后台显示证书到期：写到 Portal 能读的位置。
# 不为了「显示」而放宽 /etc/mrrc-hub/tls 的目录权限 —— 权限收紧是对的，改这边的写入方。
write_cert_info() {
    local dest=/var/lib/mrrc-hub/portal/cert.txt
    [ -s /etc/mrrc-hub/tls/fullchain.pem ] || return 0
    install -d -o mrrcportal -g mrrcportal -m 750 "$(dirname "$dest")" 2>/dev/null \
        || install -d -m 750 "$(dirname "$dest")"
    openssl x509 -in /etc/mrrc-hub/tls/fullchain.pem -noout -enddate -subject 2>/dev/null > "$dest"
    chown mrrcportal:mrrcportal "$dest" 2>/dev/null || true
    chmod 0640 "$dest" 2>/dev/null || true
}
write_cert_info
() {
    nginx -t >/dev/null 2>&1 && systemctl reload nginx && echo "[INFO] nginx 已 reload（证书已更新）"
}

# ── A) 真证书路径 ─────────────────────────────────────────────────────
if [ -s "$CREDS" ]; then
    # Manual + our own DNS hook rather than certbot-dns-aliyun: that plugin is
    # third-party and unmaintained, and this box's Python is newer than it. With
    # both hooks present the manual plugin renews unattended like any other.
    HOOK=/usr/local/sbin/aliyun-acme-dns-hook.py
    if [ ! -s "/etc/letsencrypt/live/$CERT_NAME/fullchain.pem" ]; then
        echo "[INFO] 首次 DNS-01 签发 *.${BASE}（凭证已就位）"
        certbot certonly --cert-name "$CERT_NAME" \
            --manual --preferred-challenges dns \
            --manual-auth-hook "$HOOK" --manual-cleanup-hook "$HOOK" \
            --deploy-hook /usr/local/sbin/mrrc-hub-cert-hook.sh \
            --non-interactive --agree-tos --register-unsafely-without-email \
            -d "*.${BASE}" -d "${BASE}" && reload_if_changed
    else
        left=$(days_left "/etc/letsencrypt/live/$CERT_NAME/fullchain.pem")
        if [ "$left" -lt "$DAYS_RENEW" ]; then
            echo "[INFO] 真证书剩 $left 天，执行续期"
            certbot renew --cert-name "$CERT_NAME" --quiet && reload_if_changed
        fi
        install -m 644 "/etc/letsencrypt/live/$CERT_NAME/fullchain.pem" "$CRT"
        install -m 600 "/etc/letsencrypt/live/$CERT_NAME/privkey.pem" "$KEY"
    fi
# ── B) 自签兜底路径 ───────────────────────────────────────────────────
else
    left=$(days_left "$CRT")
    # Regenerate unless it is the canonical shape: a leftover certificate with extra
    # names (an earlier bootstrap wrote test1.mrrc.vlsc.net into the SAN) would live
    # for years and quietly keep stale names in a certificate named *.mrrc.vlsc.net.
    SAN_NOW=$(openssl x509 -in "$CRT" -noout -ext subjectAltName 2>/dev/null | tail -1 | tr -d ' ')
    WANT="DNS:*.${BASE},DNS:${BASE}"
    if [ "$left" -lt "$DAYS_RENEW" ] || [ "$SAN_NOW" != "$WANT" ]; then
        echo "[INFO] 自签通配证书缺失/剩余 $left 天/SAN 不是规范形式，重新生成（凭证未就位，等 AccessKey）"
        openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
            -keyout "$KEY" -out "$CRT" -subj "/CN=*.${BASE}" \
            -addext "subjectAltName=DNS:*.${BASE},DNS:${BASE}" 2>/dev/null
        chmod 600 "$KEY"; chmod 644 "$CRT"
        echo "[NOTICE] 自签证书不能让浏览器免警告；/root/.secrets/aliyun.ini 一到位即自动换真证书"
        reload_if_changed
    fi
fi

# ── 到期检查（与你 mac 上那份 check_ssl_expiry.sh 同风格）──────────────
if [ ! -s "$CRT" ]; then
    echo "[ERROR] 证书文件不存在: $CRT"
    exit 2
fi
ISSUER=$(openssl x509 -in "$CRT" -noout -issuer 2>/dev/null | sed 's/issuer=//')
SAN=$(openssl x509 -in "$CRT" -noout -ext subjectAltName 2>/dev/null | tail -1 | tr -d ' ')
DAYS=$(days_left "$CRT")
echo "[INFO] $CRT 签发者=$ISSUER SAN=$SAN"

if [ "$DAYS" -le 0 ]; then
    echo "[ERROR] 证书已过期（剩余 $DAYS 天）: $CRT"
    exit 2
elif [ "$DAYS" -le "$DAYS_WARNING" ]; then
    echo "[WARNING] 证书将在 $DAYS 天后到期，请尽快处理！"
    exit 1
else
    echo "[OK] 证书正常，还有 $DAYS 天到期"
    exit 0
fi
