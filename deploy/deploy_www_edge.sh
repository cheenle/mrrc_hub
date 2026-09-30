#!/usr/bin/env bash
# Publish the Cloud Hub entry on the overseas host (www.vlsc.net) — the detour
# around a mainland-China region's 80/443 reality.
#
#   sudo ./deploy_www_edge.sh <instance-fqdn> [hub-upstream-host:port] [mode]
#   sudo ./deploy_www_edge.sh test1.mrrc.vlsc.net tunnel.mrrc.vlsc.net:9988 redirect
#
# MODE
#   redirect (default) — https://www.vlsc.net/mrrc_modern/<name>/… 302s to the
#     instance's own URL. No DNS change needed, and the first hop is a real
#     certificate on 443, so the address users are handed is trusted and
#     memorable. It does NOT remove the certificate warning: after the jump the
#     browser is on the hub's non-standard port with its (for now) self-signed
#     certificate, and the session cookie belongs to that origin — the user logs
#     in there. Treat it as a trusted bookmark, not as a fix.
#   proxy — www terminates TLS for the instance name itself and reverse-proxies
#     the whole session (HTTP + five WebSockets) into the tunnel: standard port
#     AND real certificate, at one extra overseas round trip (measured 0.13s →
#     0.69s on /login). Needs an explicit DNS A record for the name pointing here
#     — an explicit record overrides the *.mrrc.vlsc.net wildcard, which is why
#     it is not the default.
#
# WHY THIS LAYER EXISTS AT ALL
#   80/443 are not usable on the mainland hub without an ICP filing, and plain
#   HTTP to an unfiled domain is intercepted in transit (measured: the client got
#   Aliyun's block page while the origin's own log recorded 301). This host is
#   outside that regime and already terminates real certificates on 443.
#
# The hop into the hub stays TLS-verified in proxy mode: the hub presents a
# self-signed certificate, so its certificate is installed here as a trust anchor
# rather than switching verification off — the `proxy_ssl_verify off` pattern this
# project already regrets (hub SDD NFR-H021).
set -euo pipefail

SUBDOMAIN="${1:?usage: deploy_www_edge.sh <instance-fqdn> [hub-upstream] [redirect|proxy]}"
UPSTREAM="${2:-tunnel.mrrc.vlsc.net:9988}"
MODE="${3:-redirect}"
case "$MODE" in
redirect | proxy) ;;
*)
	echo "mode must be redirect or proxy" >&2
	exit 2
	;;
esac

ENTRY_PATH="/mrrc_modern/${SUBDOMAIN%%.*}"
HUB_CA="/etc/nginx/mrrc-hub-ca.pem"
TLS_DIR="/etc/mrrc-edge/tls"
SITE="/etc/nginx/sites-available/vlsc.net"
MARKER_START="    # ── MRRC Cloud Hub edge (${SUBDOMAIN}) ──"

[[ $EUID -eq 0 ]] || {
	echo "must run as root (sudo)" >&2
	exit 2
}
command -v nginx >/dev/null || {
	echo "nginx not installed here" >&2
	exit 2
}
[[ -s "$HUB_CA" ]] || {
	echo "missing $HUB_CA — copy the hub certificate there first" >&2
	exit 2
}

if [[ "$MODE" == "proxy" ]]; then
	install -d -m 0750 "$TLS_DIR"
	if [[ -d "/etc/letsencrypt/live/${SUBDOMAIN}" ]]; then
		CERT_CRT="/etc/letsencrypt/live/${SUBDOMAIN}/fullchain.pem"
		CERT_KEY="/etc/letsencrypt/live/${SUBDOMAIN}/privkey.pem"
		echo "==> certificate: Let's Encrypt for ${SUBDOMAIN}"
	else
		CERT_CRT="$TLS_DIR/fullchain.pem"
		CERT_KEY="$TLS_DIR/privkey.pem"
		echo "==> certificate: none for ${SUBDOMAIN} yet (self-signed placeholder)"
		echo "    once ${SUBDOMAIN} resolves here: certbot certonly --webroot -w /var/www/html -d ${SUBDOMAIN}"
		if [[ ! -s "$CERT_CRT" ]]; then
			openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
				-keyout "$CERT_KEY" -out "$CERT_CRT" -subj "/CN=${SUBDOMAIN}" \
				-addext "subjectAltName=DNS:${SUBDOMAIN}" 2>/dev/null
			chmod 600 "$CERT_KEY"
		fi
	fi
fi

BLOCK_FILE="$(mktemp)"
trap 'rm -f "$BLOCK_FILE"' EXIT

if [[ "$MODE" == "redirect" ]]; then
	cat >"$BLOCK_FILE" <<EOF
${MARKER_START}
    # Managed by mrrc_hub/deploy/deploy_www_edge.sh (mode: redirect).
    #
    # ^~ is load-bearing: this site has regex locations (the .js static-asset
    # rule) that outrank a plain prefix match and would serve local 404s for the
    # frontend assets — the same lesson B2 recorded.
    #
    # The redirect comes from an \`if\` capture, not from
    # \`rewrite ... break\` + \`return\`: \`break\` ends the rewrite phase, so the
    # \`return\` never executes and the request falls through to the static root
    # (measured — it 404'd, with the error log pointing at /var/www/vlsc.net/login).
    location = ${ENTRY_PATH} {
        return 302 https://${SUBDOMAIN}:9988/;
    }
    location ^~ ${ENTRY_PATH}/ {
        if (\$request_uri ~ ^${ENTRY_PATH}(?<rest>/.*)\$) {
            return 302 https://${SUBDOMAIN}:9988\$rest;
        }
    }
    # ── end MRRC Cloud Hub edge ──
EOF
	INSERT_MODE="into-443-block"
else
	cat >"$BLOCK_FILE" <<EOF
${MARKER_START}
    # Managed by mrrc_hub/deploy/deploy_www_edge.sh (mode: proxy).
    # Terminates TLS here (real certificate, port 443) and proxies the whole
    # session into the hub's tunnel, so the user never meets the mainland port or
    # its self-signed certificate.
    server {
        listen 80;
        listen [::]:80;
        server_name ${SUBDOMAIN};

        # Only here so certbot can validate the name once DNS points at this host
        # (HTTP-01 is unavailable on the mainland hub). Everything else goes TLS.
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

        # The hub's certificate is self-signed; pin it as a trust anchor instead
        # of switching verification off.
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
	INSERT_MODE="append"
fi

# ── idempotent placement ────────────────────────────────────────────────
cp -a "$SITE" "$SITE.bak.$(date +%Y%m%d%H%M%S)"
SITE="$SITE" BLOCK_FILE="$BLOCK_FILE" MARKER_START="$MARKER_START" \
	INSERT_MODE="$INSERT_MODE" python3 - <<'PY'
import os, re, sys

site = os.environ["SITE"]
block = open(os.environ["BLOCK_FILE"], encoding="utf-8").read()
marker = os.environ["MARKER_START"]
mode = os.environ["INSERT_MODE"]

text = open(site, encoding="utf-8").read()

# Drop any previous copy, wherever it ended up — an earlier version inserted into
# the port-80 block because that was the first block whose server_name matched.
if marker in text:
    text, n = re.subn(re.escape(marker) + r".*?# ── end MRRC Cloud Hub edge ──\n",
                      "", text, flags=re.DOTALL)
    print(f"==> removed {n} existing block(s)")

if mode == "append":
    text = text.rstrip("\n") + "\n" + block
    print("==> appended (top-level server block)")
else:
    # A bare `location` is only valid inside a `server` block, and it must be the
    # block that actually serves the name on 443 — users arrive there, not on 80.
    placed = False
    for m in re.finditer(r"(?m)^[ \t]*server[ \t]*\{", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.start():i + 1]
        if "server_name" in body and "www.vlsc.net" in body and "listen 443" in body:
            text = text[:i] + block + text[i:]
            placed = True
            print("==> inserted into the www.vlsc.net 443 server block")
            break
    if not placed:
        print("==> no 443 server block for www.vlsc.net found; nothing changed",
              file=sys.stderr)
        sys.exit(1)

open(site, "w", encoding="utf-8").write(text)
PY

nginx -t
systemctl reload nginx
echo "==> nginx reloaded (mode: $MODE)"
echo
if [[ "$MODE" == "redirect" ]]; then
	echo "verify:"
	echo "  curl -sI https://www.vlsc.net${ENTRY_PATH}/login   # 302 → https://${SUBDOMAIN}:9988/login"
	echo "  curl -skL -o /dev/null -w '%{http_code}\\n' https://www.vlsc.net${ENTRY_PATH}/login   # 200"
else
	echo "verify:"
	echo "  curl -sI  https://${SUBDOMAIN}/login        # 200 through hub + tunnel"
	echo "  curl -s   https://${SUBDOMAIN}/api/health   # 401 until a session exists"
fi
