#!/usr/bin/env bash
# Publish the Cloud Hub edge on the overseas host (www.vlsc.net) — the detour
# around a mainland-China region's 80/443 reality.
#
#   sudo ./deploy_www_edge.sh <user-facing-fqdn> [hub-upstream-host:port]
#   sudo ./deploy_www_edge.sh test1.mrrc.vlsc.net tunnel.mrrc.vlsc.net:9988
#
# WHY THIS LAYER EXISTS
#   The hub itself sits in cn-wulanchabu, where 80/443 are not usable without an
#   ICP filing (and plain HTTP to an unfiled domain is intercepted in transit —
#   measured: the client got Aliyun's block page while the origin logged 301).
#   So the hub exposes the tunnel on a non-standard TLS port with no publicly
#   trusted certificate. Both problems are solved by putting the *user-facing*
#   edge on a host outside the mainland that already has 443 and a real
#   certificate: this script terminates TLS there and proxies the whole session
#   — HTTP and the five WebSockets — into the tunnel.
#
#   A 302 redirect would not do the same job: it only renames the address, and
#   the browser would still land on a non-standard port with a certificate it
#   does not trust.
#
# The hop into the hub is TLS-verified too. The hub presents a self-signed
# certificate, so its certificate is installed here as a trust anchor rather
# than disabling verification (the `proxy_ssl_verify off` pattern this project
# already regrets; see hub SDD NFR-H021).
set -euo pipefail

SUBDOMAIN="${1:?usage: deploy_www_edge.sh <user-facing-fqdn> [hub-upstream]}"
UPSTREAM="${2:-tunnel.mrrc.vlsc.net:9988}"
HUB_CA="/etc/nginx/mrrc-hub-ca.pem"
TLS_DIR="/etc/mrrc-edge/tls"
SITE="/etc/nginx/sites-available/vlsc.net"
MARKER_START="    # ── MRRC Cloud Hub edge (${SUBDOMAIN}) ──"

[[ $EUID -eq 0 ]] || { echo "must run as root (sudo)" >&2; exit 2; }
command -v nginx >/dev/null || { echo "nginx not installed here" >&2; exit 2; }
[[ -s "$HUB_CA" ]] || { echo "missing $HUB_CA — copy the hub certificate there first" >&2; exit 2; }

# ── certificate for the user-facing name ─────────────────────────────────
# Let's Encrypt when the name points at this host (HTTP-01 works here, unlike in
# the mainland region), otherwise a self-signed placeholder so the configuration
# is valid and the path is testable before DNS is ready.
install -d -m 0750 "$TLS_DIR"
if [[ -d "/etc/letsencrypt/live/${SUBDOMAIN}" ]]; then
    CERT_CRT="/etc/letsencrypt/live/${SUBDOMAIN}/fullchain.pem"
    CERT_KEY="/etc/letsencrypt/live/${SUBDOMAIN}/privkey.pem"
    echo "==> certificate: Let's Encrypt for ${SUBDOMAIN}"
else
    CERT_CRT="$TLS_DIR/fullchain.pem"
    CERT_KEY="$TLS_DIR/privkey.pem"
    echo "==> certificate: none for ${SUBDOMAIN} yet"
    echo "    (fetch it with: certbot certonly --webroot -w /var/www/html -d ${SUBDOMAIN}"
    echo "     once ${SUBDOMAIN} resolves to this host, then re-run this script)"
    if [[ ! -s "$CERT_CRT" ]]; then
        openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
            -keyout "$CERT_KEY" -out "$CERT_CRT" -subj "/CN=${SUBDOMAIN}" \
            -addext "subjectAltName=DNS:${SUBDOMAIN}" 2>/dev/null
        chmod 600 "$CERT_KEY"
    fi
fi

# ── configuration block (idempotent, marker-delimited) ───────────────────
BLOCK="$(cat <<EOF
${MARKER_START}
    # Managed by mrrc_hub/deploy/deploy_www_edge.sh — edits are overwritten.
    # Terminates TLS here (real certificate, port 443) and proxies the whole
    # session into the hub's tunnel, so the user never meets the mainland port
    # or its self-signed certificate.
    server {
        listen 80;
        listen [::]:80;
        server_name ${SUBDOMAIN};

        # Only here so certbot can validate the name once DNS points at this
        # host (HTTP-01 is unavailable on the mainland hub). Everything else
        # goes to TLS.
        location /.well-known/acme-challenge/ { root /var/www/html; }
        location / { return 301 https://\$host\$request_uri; }
    }
    server {
        listen 443 ssl;
        listen [::]:443 ssl;
        server_name ${SUBDOMAIN};

        ssl_certificate     ${CERT_CRT};
        ssl_certificate_key ${CERT_KEY};
        ssl_protocols TLSv1.2 TLSv1.3;

        # The hub's certificate is self-signed; trust it by pinning its
        # certificate instead of switching verification off.
        proxy_ssl_trusted_certificate ${HUB_CA};
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;

        location / {
            proxy_pass https://${UPSTREAM};
            proxy_ssl_server_name on;
            proxy_ssl_name ${UPSTREAM%%:*};
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;

            proxy_http_version 1.1;
            proxy_set_header Upgrade \$http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_read_timeout 86400;
            proxy_buffering off;
        }
    }
    # ── end MRRC Cloud Hub edge ──
EOF
)"

cp -a "$SITE" "$SITE.bak.$(date +%Y%m%d%H%M%S)"
if grep -qF "$MARKER_START" "$SITE"; then
    python3 - "$SITE" "$MARKER_START" <<'PY'
import re, sys
path, marker = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
pattern = re.compile(re.escape(marker) + r".*?# ── end MRRC Cloud Hub edge ──\n", re.DOTALL)
print(f"==> replacing {len(pattern.findall(text))} existing block(s)")
text = pattern.sub("", text)
open(path, "w", encoding="utf-8").write(text)
PY
fi
printf '%s\n' "$BLOCK" >>"$SITE"
echo "==> block written to $SITE"

nginx -t
systemctl reload nginx
echo "==> nginx reloaded"
echo
echo "verify (from anywhere that can reach this host):"
echo "  curl -sI  https://${SUBDOMAIN}/login        # 200 through hub + tunnel"
echo "  curl -s   https://${SUBDOMAIN}/api/health   # 401 until a session exists"
echo "  curl -s   https://${SUBDOMAIN}/api/session_metrics   # 401, then counts after login"
