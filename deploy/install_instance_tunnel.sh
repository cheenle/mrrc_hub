#!/usr/bin/env bash
# Install the instance side of the Cloud Hub tunnel as a persistent service (macOS).
#
#   MRRC_HUB_TOKEN=<frps token> ./install_instance_tunnel.sh <name> <port> [local-port]
#   MRRC_HUB_TOKEN=… ./install_instance_tunnel.sh test1 18800
#
# <name>/<port> must match a line in the hub's /etc/mrrc-hub/instances.tsv — the
# hub authority owns the port allocation, this side just claims it.
#
# What it does:
#   * writes a 0600 frpc config under ~/Library/Application Support/mrrc-fleet/
#     (token on disk, but never in a world-readable file or in argv)
#   * installs a LaunchAgent with KeepAlive, so the tunnel survives crashes,
#     reboots and network changes without anyone watching it
#   * refuses to start if a manually-run frpc is already holding the tunnel, since
#     two clients on one name would flap
#
# The instance's own MRRC server is NOT managed here: it stays theirs
# (com.user.mrrc.plist or whatever started it), and the tunnel simply 502s until
# it is listening on <local-port>.
set -euo pipefail

NAME="${1:?usage: install_instance_tunnel.sh <name> <port> [local-port]}"
PORT="${2:?missing hub-side port (see /etc/mrrc-hub/instances.tsv)}"
LOCAL_PORT="${3:-8888}"
HUB_HOST="${MRRC_HUB_HOST:-tunnel.mrrc.vlsc.net}"
HUB_CONTROL_PORT="${MRRC_HUB_CONTROL_PORT:-8989}"
TOKEN="${MRRC_HUB_TOKEN:?set MRRC_HUB_TOKEN (the frps token) — or read it on the hub: sudo cat /etc/frp/frps.token}"

CONF_DIR="$HOME/Library/Application Support/mrrc-fleet"
CONF="$CONF_DIR/frpc-$NAME.toml"
PLIST="$HOME/Library/LaunchAgents/com.mrrc.fleet-tunnel.$NAME.plist"
LABEL="com.mrrc.fleet-tunnel.$NAME"
FRPC="$(command -v frpc || echo "$HOME/bin/frpc")"

[[ -x "$FRPC" ]] || {
	echo "frpc not found — install it first (brew install frp, or a release tarball)" >&2
	exit 2
}

if pgrep -f "frpc -c .*mrrc" >/dev/null 2>&1 && [[ "${MRRC_FORCE:-0}" != "1" ]]; then
	echo "a manually started frpc is already running; stop it first (or set MRRC_FORCE=1)" >&2
	exit 2
fi

mkdir -p "$CONF_DIR" "$HOME/Library/LaunchAgents"
umask 077
cat >"$CONF" <<EOF
# Managed by mrrc_hub/deploy/install_instance_tunnel.sh (instance: ${NAME}).
# Put this machine's radio server on the hub as https://${NAME}.mrrc.vlsc.net:9988.
#
# The instance side only dials OUT (no public IP, no port forwarding, no UPnP) —
# hub SDD AD-H01. The hub claims ${PORT} on its loopback for this name; that port
# is never reachable from the internet.
serverAddr = "${HUB_HOST}"
serverPort = ${HUB_CONTROL_PORT}
auth.method = "token"
auth.token = "${TOKEN}"

# The tunnel itself is encrypted; frps refuses anything that is not.
transport.tls.enable = true

log.to = "${CONF_DIR}/frpc-${NAME}.log"
log.level = "info"
log.maxDays = 7

[[proxies]]
name = "${NAME}"
type = "tcp"
localIP = "127.0.0.1"
localPort = ${LOCAL_PORT}
remotePort = ${PORT}

# Why type=tcp: the hub's nginx speaks TLS to this end, so the instance's real
# certificate is verified by name across the whole path. frp's http proxy type
# would require a plaintext local backend, and taking that shortcut is how
# certificate verification gets disabled (hub SDD NFR-H021).
EOF
chmod 600 "$CONF"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${FRPC}</string>
        <string>-c</string>
        <string>${CONF}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key><false/>
        <key>Crashed</key><true/>
    </dict>
    <key>ThrottleInterval</key><integer>15</integer>
    <key>StandardOutPath</key><string>${CONF_DIR}/frpc-${NAME}.out.log</string>
    <key>StandardErrorPath</key><string>${CONF_DIR}/frpc-${NAME}.err.log</string>
    <!-- The home IPv6 prefix changes and the hub moves; a tunnel must not depend
         on a lease or a route surviving. -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF
chmod 644 "$PLIST"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
sleep 3
launchctl print "gui/$UID/$LABEL" 2>/dev/null | grep -E "^\s+(state|pid) " | sed 's/^/  /' || true
echo "==> ${NAME} → https://${NAME}.mrrc.vlsc.net:9988 (local 127.0.0.1:${LOCAL_PORT})"
echo
echo "check:"
echo "  tail -5 '${CONF_DIR}/frpc-${NAME}.log'          # want: login to server success / start proxy success"
echo "  curl -sk https://${NAME}.mrrc.vlsc.net:9988/api/health   # 401 once the radio server is up"
echo "  launchctl bootout gui/$UID/${LABEL}            # to remove it"
