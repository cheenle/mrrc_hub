#!/bin/bash
# MRRC Hub 通配证书：获取 / 续期 / 到期检查
# 覆盖 *.mrrc.vlsc.net（所有实例的入口），按呼号命名的子域共用这一张
#
# 两种状态都可用，凭证到位后自动切换：
#   A) 有阿里云凭证 → DNS-01 签发**真证书**（Let's Encrypt），自动续期
#   B) 没有          → 维持一张自签通配证书，仅做到期监控
# 通配只能 DNS-01：HTTP-01 固定走 80、TLS-ALPN-01 固定走 443，而境内 80/443 不可用（R-H13）。
#
# 退出码: 0=正常 1=即将到期(<=21天) 2=已过期/缺失/需要人处理
#
# 2026-10-21 的现场与修补（这条链当时断在四处，全部在这里收口）：
#   ① 没有任何 timer/cron 调本脚本 —— 由 deploy/systemd/mrrc-hub-cert.timer 补上；
#   ② certbot 的世系 `mrrc-wildcard` 被删过（/etc/letsencrypt/live 里没有它），
#      于是 `certbot renew` 根本没东西可续，而脚本只会走"首次签发"分支；
#   ③ `--deploy-hook` 指向 /usr/local/sbin/mrrc-hub-cert-hook.sh，那个文件**不存在**
#      （certbot 见到缺失的 hook 会让续期失败）—— 现在它与本脚本一起入库并安装；
#   ④ 凭证路径两处文档打架（/root/.secrets/aliyun.ini 与 /etc/mrrc-hub/aliyun.ini），
#      现在两个都认，缺失时日志直说"缺哪个"。
set -u

CERT_DIR=/etc/mrrc-hub/tls
CRT="$CERT_DIR/fullchain.pem"
KEY="$CERT_DIR/privkey.pem"
CERT_NAME=mrrc-wildcard
LIVE_DIR="/etc/letsencrypt/live/$CERT_NAME"
BASE=mrrc.vlsc.net
DAYS_WARNING=21        # 告警线：留出"人去找 AccessKey"的时间
DAYS_RENEW=30          # 低于此天数就动手续期/重签
HOOK_DNS=/usr/local/sbin/aliyun-acme-dns-hook.py
HOOK_DEPLOY=/usr/local/sbin/mrrc-hub-cert-hook.sh
# 文档里出现过两个路径，两个都认（先 /root/.secrets，与 DNS hook 的默认一致）
CREDS=""
for candidate in /root/.secrets/aliyun.ini /etc/mrrc-hub/aliyun.ini; do
    [ -s "$candidate" ] && { CREDS="$candidate"; break; }
done

mkdir -p "$CERT_DIR" 2>/dev/null || true

days_left() {
    [ -s "$1" ] || { echo -1; return; }
    local end
    end=$(openssl x509 -in "$1" -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -n "$end" ] || { echo -1; return; }
    echo $(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
}

is_real_cert() {
    # 只看签发者：Let's Encrypt 签出来的才是真证书，自签的 CN 与 subject 相同。
    [ -s "$1" ] || return 1
    openssl x509 -in "$1" -noout -issuer 2>/dev/null | grep -qi "let's encrypt"
}

# 供 Portal 后台显示证书到期：写到 Portal 能读的位置。
# 不为了「显示」去放宽 /etc/mrrc-hub/tls 的目录权限 —— 收紧是对的，改这里的写入方。
# （原实现把这段放在 `exit 0` 之后，是永远执行不到的死代码：控制台上的到期时间
#   因此停在那一次手工写入的值上，2026-10-21 排查时才发现。）
write_cert_info() {
    local dest=/var/lib/mrrc-hub/portal/cert.txt
    [ -s "$CRT" ] || return 0
    install -d -o mrrcportal -g mrrcportal -m 750 "$(dirname "$dest")" 2>/dev/null \
        || install -d -m 750 "$(dirname "$dest")"
    openssl x509 -in "$CRT" -noout -enddate -subject 2>/dev/null > "$dest"
    chown mrrcportal:mrrcportal "$dest" 2>/dev/null || true
    chmod 0640 "$dest" 2>/dev/null || true
}

# ── A) 真证书路径 ─────────────────────────────────────────────────────
if [ -n "$CREDS" ]; then
    if [ ! -s "$HOOK_DNS" ] || [ ! -s "$HOOK_DEPLOY" ]; then
        echo "[ERROR] 凭证在（$CREDS）但 hook 缺：DNS=$HOOK_DNS deploy=$HOOK_DEPLOY" >&2
        echo "        两个 hook 都在 mrrc_hub/deploy/ 下，装到 /usr/local/sbin/ 再跑。" >&2
        exit 2
    fi
    if [ ! -s "$LIVE_DIR/fullchain.pem" ]; then
        echo "[INFO] 首次 DNS-01 签发 *.${BASE}（凭证已就位）"
        if certbot certonly --cert-name "$CERT_NAME" \
            --manual --preferred-challenges dns \
            --manual-auth-hook "$HOOK_DNS" --manual-cleanup-hook "$HOOK_DNS" \
            --deploy-hook "$HOOK_DEPLOY" \
            --non-interactive --agree-tos --register-unsafely-without-email \
            -d "*.${BASE}" -d "${BASE}"; then
            # certbot 的 deploy-hook 会安装并 reload；这里是兜底（hook 未触发时）
            [ -s "$LIVE_DIR/fullchain.pem" ] && "$HOOK_DEPLOY"
        fi
    else
        left=$(days_left "$LIVE_DIR/fullchain.pem")
        if [ "$left" -lt "$DAYS_RENEW" ]; then
            echo "[INFO] 真证书剩 $left 天，执行续期"
            certbot renew --cert-name "$CERT_NAME" --quiet && "$HOOK_DEPLOY"
        fi
        install -m 644 "$LIVE_DIR/fullchain.pem" "$CRT"
        install -m 600 "$LIVE_DIR/privkey.pem" "$KEY"
    fi
# ── B) 自签兜底路径 ───────────────────────────────────────────────────
else
    left=$(days_left "$CRT")
    SAN_NOW=$(openssl x509 -in "$CRT" -noout -ext subjectAltName 2>/dev/null | tail -1 | tr -d ' ')
    WANT="DNS:*.${BASE},DNS:${BASE}"
    if is_real_cert "$CRT"; then
        # 关键守卫：真证书**绝不被自签覆盖**。原实现在"剩余 < 30 天"时会用自签
        # 顶掉 Let's Encrypt 那张 —— 那会在到期前就搞坏所有实例入口，而且不可逆
        # （私钥一并被换掉）。没有凭证时只能喊人，不能动手。
        echo "[CRITICAL] $CRT 是 Let's Encrypt 真证书，但**找不到阿里云凭证**（$left 天后到期）" >&2
        echo "           凭证路径任选其一：/root/.secrets/aliyun.ini 或 /etc/mrrc-hub/aliyun.ini（0600）。" >&2
        echo "           没有凭证就无法续期；★ 本脚本不会用自签覆盖真证书。" >&2
        [ "$left" -le "$DAYS_WARNING" ] && exit 1
        write_cert_info
        echo "[OK] 真证书仍有效，还有 $left 天到期 —— 但续期路径是断的（缺凭证）"
        exit 0
    fi
    # Regenerate unless it is the canonical shape: a leftover certificate with extra
    # names (an earlier bootstrap wrote test1.mrrc.vlsc.net into the SAN) would live
    # for years and quietly keep stale names in a certificate named *.mrrc.vlsc.net.
    if [ "$left" -lt "$DAYS_RENEW" ] || [ "$SAN_NOW" != "$WANT" ]; then
        echo "[INFO] 自签通配证书缺失/剩余 $left 天/SAN 不是规范形式，重新生成（凭证未就位，等 AccessKey）"
        openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
            -keyout "$KEY" -out "$CRT" -subj "/CN=*.${BASE}" \
            -addext "subjectAltName=DNS:*.${BASE},DNS:${BASE}" 2>/dev/null
        chmod 600 "$KEY"; chmod 644 "$CRT"
        echo "[NOTICE] 自签证书不能让浏览器免警告；凭证一到位即自动换真证书"
        nginx -t >/dev/null 2>&1 && systemctl reload nginx && echo "[INFO] nginx 已 reload"
    fi
fi

# ── 到期检查 ──────────────────────────────────────────────────────────
if [ ! -s "$CRT" ]; then
    echo "[ERROR] 证书文件不存在: $CRT"
    exit 2
fi
ISSUER=$(openssl x509 -in "$CRT" -noout -issuer 2>/dev/null | sed 's/issuer=//')
SAN=$(openssl x509 -in "$CRT" -noout -ext subjectAltName 2>/dev/null | tail -1 | tr -d ' ')
DAYS=$(days_left "$CRT")
write_cert_info
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
