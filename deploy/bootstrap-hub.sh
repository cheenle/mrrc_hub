#!/usr/bin/env bash
# Bootstrap the MRRC Cloud Hub validation host (idempotent; safe to re-run).
#
#   sudo ./bootstrap-hub.sh <test-fqdn>        e.g. test1.mrrc.vlsc.net
#
# What this installs, and why in this order:
#   1. nginx + certbot                          — the user-facing edge
#   2. frps from the pinned release, SHA-256 verified against the official
#      checksums file                           — the tunnel server
#   3. /etc/frp/frps.toml + a 0600 token file   — token auth, loopback-only tcp proxy
#   4. systemd unit                             — survives reboot
#   5. an nginx vhost for the test subdomain:   — TLS (Let's Encrypt HTTP-01) in
#      front of the tunnel, with certificate verification ON upstream
#
# Deliberately NOT done here:
#   * frp's own vhost/subdomain mode — nginx keeps subdomain routing so the
#     upstream hop can stay verified (B2 shipped `proxy_ssl_verify off`; the hub
#     design forbids that pattern, NFR-H021).
#   * wildcard certificates — those need DNS-01, i.e. DNS provider API
#     credentials. A per-name HTTP-01 cert needs nothing beyond port 80.
#
# Preflight it cannot fix for you: the cloud security group must already allow
# 80/tcp, 443/tcp and 7000/tcp inbound (only 22 was open on 2026-09-30), and this
# script needs root (sudo was password-protected then — see deploy/README.md).
set -euo pipefail

SUBDOMAIN="${1:-}"
if [[ -z "$SUBDOMAIN" ]]; then
    echo "usage: sudo $0 <test-fqdn>   e.g. test1.mrrc.vlsc.net" >&2
    exit 2
fi
[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 2; }

FRP_VERSION="0.71.0"
FRP_SHA256_AMD64="84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716"
FRP_SHA256_ARM64="f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266"

# Ports are non-standard on purpose: a mainland-China ECS serving 80/443 needs an
# ICP filing, so the hub entry lives on 8899 (plain) / 9988 (TLS) and the tunnel
# control port on 8989. Consequence to keep in mind: users must type the port, and
# networks that only allow 80/443 outbound cannot reach the hub at all.
HTTP_PORT="8899"
HTTPS_PORT="9988"
FRP_TLS_PORT="8989"

# The instance presents a real Let's Encrypt certificate for this name; nginx
# verifies against it by name rather than skipping verification.
UPSTREAM_SSL_NAME="radio.vlsc.net"
# Loopback-only: the tunnel proxy port must never be reachable from the internet.
FRP_TCP_PORT="18888"

case "$(uname -m)" in
    x86_64)  FRP_ARCH="linux_amd64"; FRP_SHA256="$FRP_SHA256_AMD64" ;;
    aarch64) FRP_ARCH="linux_arm64"; FRP_SHA256="$FRP_SHA256_ARM64" ;;
    *) echo "unsupported arch $(uname -m)" >&2; exit 2 ;;
esac

log() { printf '\n==> %s\n' "$*"; }

log "preflight: ports $HTTP_PORT/$HTTPS_PORT/$FRP_TLS_PORT must be reachable (security group)"
for p in "$HTTP_PORT" "$HTTPS_PORT" "$FRP_TLS_PORT"; do
    if ss -tln "sport = :$p" 2>/dev/null | grep -q LISTEN; then
        echo "    :$p already listening (likely a re-run)"
    else
        echo "    :$p idle — will bind"
    fi
done
echo "    If the security group still blocks these, nothing below is reachable"
echo "    from the internet: open $HTTP_PORT/$HTTPS_PORT/$FRP_TLS_PORT first."
echo "    NOTE: Let's Encrypt cannot validate on non-standard ports (HTTP-01 is"
echo "    fixed to 80, TLS-ALPN-01 to 443). A trusted certificate therefore needs"
echo "    DNS-01 - see the TLS section below; otherwise this falls back to a"
echo "    self-signed certificate, which is fine for the smoke test and nothing else."

log "apt: nginx + certbot"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx ca-certificates curl

log "frps $FRP_VERSION (SHA-256 verified against the official checksums file)"
TARBALL="frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${TARBALL}"
if [[ ! -x /usr/local/bin/frps ]] || [[ ! -f /etc/frp/.version ]] \
        || [[ "$(cat /etc/frp/.version 2>/dev/null)" != "$FRP_VERSION" ]]; then
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    curl -fsSL -o "$TMP/$TARBALL" "$URL"
    echo "${FRP_SHA256}  ${TARBALL}" >"$TMP/sha.txt"
    ( cd "$TMP" && sha256sum -c sha.txt )
    tar -xzf "$TMP/$TARBALL" -C "$TMP"
    install -m 0755 "$TMP/frp_${FRP_VERSION}_${FRP_ARCH}/frps" /usr/local/bin/frps
    install -m 0755 "$TMP/frp_${FRP_VERSION}_${FRP_ARCH}/frpc" /usr/local/bin/frpc
    install -d -m 0755 /etc/frp
    printf '%s' "$FRP_VERSION" >/etc/frp/.version
else
    echo "    already at $FRP_VERSION"
fi

log "token (generated once, 0600, never printed into logs)"
install -d -m 0750 /etc/frp
if [[ ! -s /etc/frp/frps.token ]]; then
    openssl rand -hex 32 >/etc/frp/frps.token   # openssl ships with the base image
fi
chmod 600 /etc/frp/frps.token

log "frps.toml"
cat >/etc/frp/frps.toml <<EOF
# Managed by mrrc_hub/deploy/bootstrap-hub.sh — edits are overwritten on re-run.
bindAddr = "0.0.0.0"
bindPort = ${FRP_TLS_PORT}

# frp binds each proxied remote port on bindAddr by default, i.e. on the public
# interface. That is not what "loopback-only tunnel port" means in the design, so
# say it explicitly - found by testing (the tcp proxy port was reachable on
# 0.0.0.0 until this line existed).
proxyBindAddr = "127.0.0.1"

auth.method = "token"
auth.token = "$(cat /etc/frp/frps.token)"

# The instance dials out to :${FRP_TLS_PORT}; anything short of TLS is rejected
# rather than silently downgraded.
transport.tls.force = true

# Remote ports a client may claim — keeps a mistyped config from publishing an
# arbitrary service, and nothing here is world-reachable anyway (nginx owns 443).
allowPorts = [{ start = 18800, end = 18999 }]

log.to = "/var/log/frps.log"
log.level = "info"
EOF
chmod 600 /etc/frp/frps.toml

log "systemd unit"
cat >/etc/systemd/system/frps.service <<'EOF'
[Unit]
Description=frp server (MRRC Cloud Hub tunnel)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.toml
Restart=on-failure
RestartSec=3
LimitNOFILE=65536
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now frps
systemctl is-active --quiet frps && echo "    frps active on :${FRP_TLS_PORT} + tcp :${FRP_TCP_PORT}"

log "TLS material for ${SUBDOMAIN}"
install -d -m 0750 /etc/mrrc-hub/tls
install -d -m 0750 /etc/letsencrypt
CERT_CRT="/etc/mrrc-hub/tls/fullchain.pem"
CERT_KEY="/etc/mrrc-hub/tls/privkey.pem"
if [[ -s "/etc/letsencrypt/live/${SUBDOMAIN}/fullchain.pem" ]]; then
    echo "    using the Let's Encrypt certificate for ${SUBDOMAIN}"
    CERT_CRT="/etc/letsencrypt/live/${SUBDOMAIN}/fullchain.pem"
    CERT_KEY="/etc/letsencrypt/live/${SUBDOMAIN}/privkey.pem"
elif [[ -s /etc/mrrc-hub/aliyun.ini ]]; then
    # DNS-01 is the only route to a publicly trusted certificate when 80/443 are
    # closed - and the only route to a *wildcard*, which is what 200 instances
    # will need. Credentials: an Aliyun RAM user limited to AliyunDNSFullAccess.
    echo "    issuing via DNS-01 (Aliyun credentials found)"
    apt-get install -y -qq python3-pip >/dev/null 2>&1 || true
    pip3 install --quiet --break-system-packages certbot-dns-aliyun 2>/dev/null || true
    certbot certonly --non-interactive --agree-tos \
        --register-unsafely-without-email \
        --dns-aliyun --dns-aliyun-credentials /etc/mrrc-hub/aliyun.ini \
        -d "$SUBDOMAIN" --keep-until-expiring
    CERT_CRT="/etc/letsencrypt/live/${SUBDOMAIN}/fullchain.pem"
    CERT_KEY="/etc/letsencrypt/live/${SUBDOMAIN}/privkey.pem"
else
    echo "    !! no DNS-01 credentials (/etc/mrrc-hub/aliyun.ini): generating a"
    echo "    !! SELF-SIGNED certificate. Browsers will warn; this is a smoke test"
    echo "    !! fixture, not a deployment. Steps to a real certificate:"
    echo "    !!   1. create an Aliyun RAM user with AliyunDNSFullAccess"
    echo "    !!   2. write /etc/mrrc-hub/aliyun.ini (chmod 600):"
    echo "    !!        dns_aliyun_access_key = <id>"
    echo "    !!        dns_aliyun_access_key_secret = <secret>"
    echo "    !!   3. re-run this script - it then issues a real wildcard"
    if [[ ! -s "$CERT_CRT" ]]; then
        openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
            -keyout "$CERT_KEY" -out "$CERT_CRT" \
            -subj "/CN=${SUBDOMAIN}" \
            -addext "subjectAltName=DNS:${SUBDOMAIN},DNS:*.mrrc.vlsc.net,DNS:*.vlsc.net" 2>/dev/null
        chmod 600 "$CERT_KEY"
    fi
fi

log "nginx: TLS vhost fronting the tunnel (upstream VERIFIED, not skipped)"
cat >/etc/nginx/sites-available/mrrc-hub <<EOF
# Managed by mrrc_hub/deploy/bootstrap-hub.sh — edits are overwritten on re-run.
#
# Region of record: the instance is reached through the tunnel below, and that
# hop is TLS-verified by name. B2 (the current production path) carries
# \`proxy_ssl_verify off\` because the instance used a self-signed cert; this host
# verifies instead, so a wrong or expired instance certificate fails loudly.
server {
    listen ${HTTP_PORT};
    listen [::]:${HTTP_PORT};
    server_name ${SUBDOMAIN};

    location / { return 301 https://\$host:${HTTPS_PORT}\$request_uri; }
}

server {
    listen ${HTTPS_PORT} ssl;
    listen [::]:${HTTPS_PORT} ssl;
    http2 on;
    server_name ${SUBDOMAIN};

    ssl_certificate     ${CERT_CRT};
    ssl_certificate_key ${CERT_KEY};
    ssl_protocols TLSv1.2 TLSv1.3;

    # MRRC's own session cookie is host-only and JS-readable; do not add a
    # Domain= here or instances would share cookies (hub AD-H09).
    location / {
        proxy_pass https://127.0.0.1:${FRP_TCP_PORT};
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;
        proxy_ssl_name ${UPSTREAM_SSL_NAME};
        proxy_ssl_server_name on;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_ssl_session_reuse on;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSockets: MRRC runs five endpoints over a long-lived upgrade.
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_buffering off;
    }
}
EOF
ln -sf /etc/nginx/sites-available/mrrc-hub /etc/nginx/sites-enabled/mrrc-hub
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

log "done"
cat <<EOF

Instance side — put this in ~/mrrc-frpc.toml and run \`frpc -c ~/mrrc-frpc.toml\`:

    serverAddr = "$(curl -fsS -m 5 https://api.ipify.org || echo 8.160.161.80)"
    serverPort = ${FRP_TLS_PORT}
    auth.method = "token"
    auth.token = "$(cat /etc/frp/frps.token)"
    transport.tls.enable = true

    [[proxies]]
    name = "mrrc-${SUBDOMAIN%%.*}"
    type = "tcp"
    localIP = "127.0.0.1"
    localPort = 8888          # MRRC_modern, HTTPS with its real certificate
    remotePort = ${FRP_TCP_PORT}

Then verify from a machine that is NOT this host:

    curl -sI  https://${SUBDOMAIN}:${HTTPS_PORT}/login        # expect 200
    curl -s   https://${SUBDOMAIN}:${HTTPS_PORT}/api/health   # expect 401 until a session exists
    # add -k if the certificate is the self-signed smoke-test fixture

Proof that upstream verification is real (do it once, keep the habit):
temporarily set \`proxy_ssl_name example.com;\`, reload, and confirm the request
now FAILS. A verification setting nobody has seen fail is not a verification
setting — that is how \`proxy_ssl_verify off\` survived in B2.
EOF

# ---- 路由自动重生成（root）----
# 证书或注册表一变就重生成通配路由与信任包，nginx -t 过了才 reload。
# 放在 root 的 path 单元里，而不是让接收证书的 Portal 服务去 reload nginx（它没有那个权限，
# 也不应该有）。装了它以后，批准一个实例就不再需要任何人手工敲命令。
install -m 755 "$SELF_DIR/mrrc-hub-routes.sh" /usr/local/sbin/mrrc-hub-routes.sh
install -m 644 "$SELF_DIR/systemd/mrrc-hub-routes.service" /etc/systemd/system/mrrc-hub-routes.service
install -m 644 "$SELF_DIR/systemd/mrrc-hub-routes.path" /etc/systemd/system/mrrc-hub-routes.path
systemctl daemon-reload
systemctl enable --now mrrc-hub-routes.path
echo "routes auto-regeneration: enabled"
