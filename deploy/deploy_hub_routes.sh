#!/usr/bin/env bash
# Install the hub's wildcard routing (one vhost for every instance) — root, on the hub.
#
#   sudo ./deploy_hub_routes.sh
#
# Replaces the per-instance vhost with a single wildcard server block:
#
#   <name>.mrrc.vlsc.net  →  https://127.0.0.1:<port>  (that instance's tunnel)
#
# The only per-instance fact left is the loopback port its tunnel claims, kept in
# /etc/mrrc-hub/instances.tsv. Adding instance #2..#200 is a line in that file plus
# a re-run — not an nginx edit per instance, which is what B2 did and what made
# each new frontend asset a centre-side change.
#
# The hop into the tunnel is TLS-verified end to end: frps forwards raw TCP, so the
# TLS session is between this nginx and the instance itself, verified by name
# against the system CA store (the instance holds a real Let's Encrypt
# certificate). No `proxy_ssl_verify off` — see hub SDD NFR-H021.
set -euo pipefail

REGISTRY="/etc/mrrc-hub/instances.tsv"
GENERATOR="/usr/local/sbin/gen_hub_routes.py"
VHOST="/etc/nginx/sites-available/mrrc-hub"
UPSTREAM_SSL_NAME="${MRRC_UPSTREAM_SSL_NAME:-radio.vlsc.net}"

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

install -m 0755 "$(dirname "$0")/gen_hub_routes.py" "$GENERATOR"
python3 "$GENERATOR"

cat >"$VHOST" <<EOF
# Managed by mrrc_hub/deploy/deploy_hub_routes.sh — edits are overwritten.
#
# ONE vhost for every instance. The alternative (a server block per instance) is
# what B2 did and what made adding an instance a centre-side nginx edit; here the
# per-instance fact is only the loopback port in the generated map.
#
# TLS is the hub's wildcard certificate (currently self-signed: a trusted one
# needs DNS-01, i.e. DNS provider credentials — see deploy/README.md).
server {
    listen 8899;
    listen [::]:8899;
    server_name ~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net\$;

    # Plain HTTP is not a usable path in the mainland region anyway (R-H13), so
    # this port only points at the TLS one.
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    listen [::] ssl;
    http2 on;
    server_name ~^(?<mrrc_instance>[a-z0-9-]+)\.mrrc\.vlsc\.net\$;

    ssl_certificate     /etc/mrrc-hub/tls/fullchain.pem;
    ssl_certificate_key /etc/mrrc-hub/tls/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Query strings are never logged here (AD-H07 / NFR-H014).
    access_log /var/log/nginx/mrrc-hub.access.log hub_safe;

    location / {
        # Unknown name → 404, never a guess at some other instance's tunnel.
        if (\$mrrc_port = 0) {
            return 404 "unknown instance\\n";
        }

        proxy_pass https://127.0.0.1:\$mrrc_port;

        # End-to-end TLS: frps forwards raw TCP, so this verification covers the
        # instance's own certificate, not frp's.
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;
        proxy_ssl_name ${UPSTREAM_SSL_NAME};
        proxy_ssl_server_name on;
        # The trust bundle, not the system CAs alone: an instance presents its own self-signed
        # certificate, which is pinned here (the generator merges those on top of the system
        # set). Verifying against the system store only rejects every instance with error 18
        # and turns the entry into a 502 that looks like a dead tunnel.
        proxy_ssl_trusted_certificate /etc/mrrc-hub/trust-bundle.pem;
        proxy_ssl_session_reuse on;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # MRRC runs five long-lived WebSocket endpoints.
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_buffering off;
    }
}
EOF

cp -a "$VHOST" "$VHOST.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
nginx -t
systemctl reload nginx
echo "==> wildcard routing live"
echo
echo "verify:"
echo "  curl -sk  https://test1.mrrc.vlsc.net/api/health   # 401 (tunnel + instance)"
echo "  curl -sk  https://nope.mrrc.vlsc.net/             # 404 (unknown instance)"
