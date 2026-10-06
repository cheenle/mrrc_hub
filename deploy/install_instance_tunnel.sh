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

case "$(uname -s)" in
	Darwin) CONF_DIR="$HOME/Library/Application Support/mrrc-fleet" ;;
	*)      CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mrrc-fleet" ;;
esac
CONF="$CONF_DIR/frpc-$NAME.toml"
PLIST="$HOME/Library/LaunchAgents/com.mrrc.fleet-tunnel.$NAME.plist"
LABEL="com.mrrc.fleet-tunnel.$NAME"
FRPC="$(command -v frpc || echo "$HOME/bin/frpc")"

# frpc 从哪来（按优先级）：
#   1. 安装包自带的副本（与脚本同级，或 .frpc/ 子目录）—— 离线也能装 ✓
#   2. 系统 PATH 里已有的（brew 或发行版包）
#   3. 从 frp 官方 release 下载 **并校验 SHA-256**；校验和不一致即拒绝使用
# 版本与 hub 上的 frps 对齐（pin 死）：客户端比服务端新可能握手失败。
FRP_VERSION="${MRRC_FRP_VERSION:-0.71.0}"
FRP_CACHE="${MRRC_FRP_DIR:-$HOME/.local/share/mrrc-fleet}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

frpc_platform() {
	case "$(uname -s)" in
		Darwin) echo darwin ;;
		Linux) echo linux ;;
		*) echo "" ;;
	esac
}

frpc_arch() {
	case "$(uname -m)" in
		arm64|aarch64) echo arm64 ;;
		x86_64|amd64) echo amd64 ;;
		*) echo "" ;;
	esac
}

ensure_frpc() {                     # 结果写进全局 FRPC
	local candidate os arch base url sums want got tmp
	for candidate in "$SCRIPT_DIR/frpc" "$SCRIPT_DIR/.frpc/frpc"; do
		if [[ -x "$candidate" ]]; then FRPC="$candidate"; echo "使用安装包自带的 frpc: $FRPC" >&2; return 0; fi
	done
	if candidate="$(command -v frpc 2>/dev/null)" && [[ -x "$candidate" ]]; then
		FRPC="$candidate"; echo "使用系统中已有的 frpc: $FRPC" >&2; return 0
	fi
	os="$(frpc_platform)"; arch="$(frpc_arch)"
	if [[ -z "$os" || -z "$arch" ]]; then
		echo "没有自带 frpc，且 $(uname -s)/$(uname -m) 无官方构建可下载。" >&2
		echo "请把 frpc 放到脚本同级目录（或用 MRRC_FRP_DIR 指定）后重跑。" >&2
		return 1
	fi
	base="frp_${FRP_VERSION}_${os}_${arch}"
	url="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${base}.tar.gz"
	sums="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_checksums.txt"
	mkdir -p "$FRP_CACHE"
	tmp="$(mktemp -d)"
	echo "下载 frpc ${FRP_VERSION} (${os}/${arch}) 并校验 SHA-256…" >&2
	curl -fsSL --retry 3 -o "$tmp/$base.tar.gz" "$url" || { echo "下载失败: $url" >&2; rm -rf "$tmp"; return 1; }
	curl -fsSL --retry 3 -o "$tmp/sums.txt" "$sums" || { echo "校验和文件下载失败: $sums" >&2; rm -rf "$tmp"; return 1; }
	want="$(awk -v f="$base.tar.gz" '$2 == f {print $1}' "$tmp/sums.txt")"
	if [[ -z "$want" ]]; then echo "校验和文件里没有 $base.tar.gz —— 拒绝安装" >&2; rm -rf "$tmp"; return 1; fi
	if command -v sha256sum >/dev/null 2>&1; then
		got="$(sha256sum "$tmp/$base.tar.gz" | awk '{print $1}')"
	else
		got="$(shasum -a 256 "$tmp/$base.tar.gz" | awk '{print $1}')"
	fi
	if [[ "$got" != "$want" ]]; then
		echo "SHA-256 不匹配，拒绝安装（期望 ${want}，实得 ${got}）" >&2; rm -rf "$tmp"; return 1
	fi
	echo "校验通过 ✓" >&2
	tar -xzf "$tmp/$base.tar.gz" -C "$tmp" || { rm -rf "$tmp"; return 1; }
	install -m 755 "$tmp/$base/frpc" "$FRP_CACHE/frpc" || { rm -rf "$tmp"; return 1; }
	rm -rf "$tmp"
	FRPC="$FRP_CACHE/frpc"
	echo "已安装: ${FRPC}（$("$FRPC" --version 2>/dev/null || echo 'version unknown')）" >&2
}

ensure_frpc || exit 2

if pgrep -f "frpc -c .*mrrc" >/dev/null 2>&1 && [[ "${MRRC_FORCE:-0}" != "1" ]]; then
	echo "a manually started frpc is already running; stop it first (or set MRRC_FORCE=1)" >&2
	exit 2
fi

mkdir -p "$CONF_DIR" "$HOME/Library/LaunchAgents"
umask 077
cat >"$CONF" <<EOF
# Managed by mrrc_hub/deploy/install_instance_tunnel.sh (instance: ${NAME}).
# Put this machine's radio server on the hub as https://${NAME}.mrrc.vlsc.net.
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

case "$(uname -s)" in
Darwin)
	launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
	launchctl bootstrap "gui/$UID" "$PLIST"
	sleep 3
	launchctl print "gui/$UID/$LABEL" 2>/dev/null | grep -E "^\s+(state|pid) " | sed 's/^/  /' || true
	;;
Linux)
	# systemd --user：不需要 root，且用 linger 让它活过登录会话 ——
	# 隧道是常驻服务，租户注销后停掉就等于实例离线。
	UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
	UNIT="$UNIT_DIR/mrrc-fleet-tunnel-${NAME}.service"
	mkdir -p "$UNIT_DIR"
	cat > "$UNIT" <<EOF
[Unit]
Description=MRRC Cloud Hub tunnel (${NAME})
After=network-online.target

[Service]
ExecStart=${FRPC} -c ${CONF}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
	chmod 600 "$UNIT"
	systemctl --user daemon-reload
	systemctl --user enable --now "mrrc-fleet-tunnel-${NAME}.service"
	if ! loginctl enable-linger "$USER" 2>/dev/null; then
		echo "  ⚠ 无法设置 linger：注销后隧道会停。需要 root 执行： sudo loginctl enable-linger $USER" >&2
	fi
	sleep 3
	systemctl --user --no-pager --lines=0 status "mrrc-fleet-tunnel-${NAME}.service" 2>/dev/null | head -3 | sed 's/^/  /' || true
	;;
*)
	echo "unsupported platform: $(uname -s) — start it by hand: $FRPC -c $CONF" >&2
	;;
esac
# ---- 应用侧环境：隧道通了不等于应用能接住；这两件事过去是分开的（见 SDD V0.15 遗留）----
# 同一组变量在 Windows 安装器里已经写了；这里补上 macOS/Linux 的两种惯例位置。
"$(dirname "${BASH_SOURCE[0]}")/wire_instance_env.sh" "${LOCAL_PORT}"

echo "==> ${NAME} → https://${NAME}.mrrc.vlsc.net (local 127.0.0.1:${LOCAL_PORT})"
echo
echo "check:"
echo "  tail -5 '${CONF_DIR}/frpc-${NAME}.log'          # want: login to server success / start proxy success"
echo "  curl -sk https://${NAME}.mrrc.vlsc.net/api/health   # 401 once the radio server is up"
case "$(uname -s)" in
	Darwin) echo "  launchctl bootout gui/$UID/${LABEL}            # to remove it" ;;
	Linux)  echo "  systemctl --user disable --now mrrc-fleet-tunnel-${NAME}.service   # to remove it"
	        echo "  journalctl --user -u mrrc-fleet-tunnel-${NAME}.service -n 20       # its log" ;;
esac
