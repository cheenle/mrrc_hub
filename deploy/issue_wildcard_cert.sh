#!/usr/bin/env bash
# Issue and auto-renew the hub's trusted wildcard certificate — root, on the hub.
#
#   sudo ./issue_wildcard_cert.sh [--check]
#
# WHY ON THE HUB, AND WHY DNS-01
#   * The hub is in a mainland-China region: ports 80/443 are not usable without an
#     ICP filing, so HTTP-01 (fixed to port 80) and TLS-ALPN-01 (fixed to 443) are
#     both out. DNS-01 is the only route to any publicly trusted certificate here —
#     and the only route to a *wildcard*, which is what one certificate for 200
#     instances means (R-H13, AD-H02's port revision).
#   * DNS-01 needs no inbound port at all, so this host can issue and renew it
#     itself; no cross-host distribution is involved for the hub's own entry (the
#     renew hook reloads the local nginx). www.vlsc.net keeps its own certificate
#     for its own name and does not need this one while the entry is a redirect.
#   * certbot's normal renewal machinery then does the rest: the hook below runs on
#     every renewal, so nobody has to remember a 90-day cycle.
#
# WHAT YOU MUST PROVIDE
#   /root/.secrets/aliyun.ini — an Aliyun RAM user that can edit DNS and nothing
#   else (policy AliyunDNSFullAccess), with these two lines:
#
#       dns_aliyun_access_key = <AccessKeyId>
#       dns_aliyun_access_key_secret = <AccessKeySecret>
#
#   chmod 600 it. A RAM user is the point: a primary-account key would hand out
#   everything the account can do, and this file exists only so a cron job can
#   write one TXT record four times a year.
set -euo pipefail

CREDS="/root/.secrets/aliyun.ini"
CERT_NAME="mrrc-wildcard"
BASE_DOMAIN="mrrc.vlsc.net"
TLS_DIR="/etc/mrrc-hub/tls"
HOOK="/usr/local/sbin/mrrc-hub-cert-hook.sh"
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 2; }

if [[ ! -s "$CREDS" ]]; then
    cat >&2 <<EOF
missing $CREDS — the wildcard needs DNS-01, and DNS-01 needs DNS API credentials.

Create a RAM user (Aliyun console → 访问控制 → 用户) with a single policy,
AliyunDNSFullAccess, then:

    install -d -m 700 /root/.secrets
    printf 'dns_aliyun_access_key = %%s\\ndns_aliyun_access_key_secret = %%s\\n' \\
        '<AccessKeyId>' '<AccessKeySecret>' > $CREDS
    chmod 600 $CREDS
    $0

Manual alternative if you would rather not create a key: run
\`certbot certonly --manual --preferred-challenges dns -d '*.${BASE_DOMAIN}' -d ${BASE_DOMAIN}\`
on any host, add the printed TXT record in the Aliyun DNS console, and repeat every
90 days — manual mode cannot renew itself.
EOF
    exit 2
fi
perms=$(stat -c '%a' "$CREDS")
[[ "$perms" == "600" ]] || { echo "$CREDS must be 0600 (is $perms)" >&2; exit 2; }

echo "==> DNS plugin"
if ! python3 -c "import certbot_dns_aliyun" 2>/dev/null; then
    pip3 install --quiet --break-system-packages certbot-dns-aliyun || {
        echo "could not install certbot-dns-aliyun; if pip is blocked, use the" >&2
        echo "manual route in this script's error message instead." >&2
        exit 2
    }
fi

echo "==> renew hook: install the certificate where nginx already reads it"
cat >"$HOOK" <<EOF
#!/usr/bin/env bash
# Runs after every successful issuance/renewal (certbot --deploy-hook), so the
# hub's nginx always serves the current certificate without anyone copying files.
set -euo pipefail
SRC="/etc/letsencrypt/live/${CERT_NAME}"
install -m 644 "\$SRC/fullchain.pem" "${TLS_DIR}/fullchain.pem"
install -m 600 "\$SRC/privkey.pem"   "${TLS_DIR}/privkey.pem"
systemctl reload nginx
echo "mrrc-hub: certificate installed and nginx reloaded (\$(date -Is))"
EOF
chmod 755 "$HOOK"

if [[ $CHECK_ONLY -eq 1 ]]; then
    echo "==> check only: credentials present, plugin importable, hook written"
    exit 0
fi

echo "==> issuing *.${BASE_DOMAIN} (+ the apex) via DNS-01"
certbot certonly \
    --cert-name "$CERT_NAME" \
    --dns-aliyun \
    --dns-aliyun-credentials "$CREDS" \
    --deploy-hook "$HOOK" \
    --non-interactive --agree-tos --register-unsafely-without-email \
    --keep-until-expiring \
    -d "*.${BASE_DOMAIN}" -d "${BASE_DOMAIN}"

echo
echo "==> done. Verify from anywhere (no -k, no warning expected):"
echo "    curl -sI https://test1.${BASE_DOMAIN}:9988/login   # 200, real certificate"
echo "    openssl s_client -connect $(hostname -I | awk '{print $1}'):9988 -servername test1.${BASE_DOMAIN} </dev/null 2>/dev/null | openssl x509 -noout -issuer -ext subjectAltName"
echo
echo "renewal: certbot.timer runs twice daily and triggers the hook above."
systemctl list-timers certbot.timer --no-pager 2>/dev/null | head -2 || \
    echo " (no certbot.timer — add a cron entry: 0 3 * * * certbot renew -q)"
