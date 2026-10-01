#!/usr/bin/env bash
# 把实例侧应用的运行环境写到**正确的地方**（macOS / Linux 各按惯例），与 Windows 安装器写的是同一组变量。
#
#   MRRC_SSL_CERT=… MRRC_SSL_KEY=… ./wire_instance_env.sh <local-port> [证书目录]
#
# 为什么不能只写进 shell 配置：macOS 上从访达/Dock 启动的图形应用**不读** ~/.zprofile，
# Linux 图形会话也不读；反过来，SSH 登录不读 systemd 的 environment.d。所以两处都要写：
#   1. ~/.config/mrrc/env.sh        —— 自己 source 得到，也是下面两处的内容来源（0600）
#   2. macOS: LaunchAgent 跑 launchctl setenv  —— 图形应用（登录时生效）
#      Linux: ~/.config/environment.d/mrrc.conf —— systemd 用户会话（图形登录时生效）
#   3. 登录 shell 里 source 第 1 项 —— SSH/终端里启动应用的情形
# 幂等：用标记块替换，绝不重复追加、也不动块外的任何一行。
set -euo pipefail

LOCAL_PORT="${1:?usage: wire_instance_env.sh <local-port> [cert-dir]}"
OS="${MRRC_WIRE_OS:-$(uname -s)}"          # MRRC_WIRE_OS 是测试用的替代口（默认按 uname）
BEGIN="# >>> mrrc hub env >>>"
END="# <<< mrrc hub env <<<"

ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/mrrc"
ENV_SH="$ENV_DIR/env.sh"
mkdir -p "$ENV_DIR"

# 只写"确实给了值"的变量：没给就说明用户在用默认路径，写个假值反而更糟。
{
	echo "$BEGIN"
	echo "# 由 wire_instance_env.sh 生成（$(date +%Y-%m-%d)）；手动改这里也会被下次运行覆盖。"
	[[ -n "${MRRC_SSL_CERT:-}" ]] && printf 'export MRRC_SSL_CERT=%q\n' "$MRRC_SSL_CERT"
	[[ -n "${MRRC_SSL_KEY:-}" ]] && printf 'export MRRC_SSL_KEY=%q\n' "$MRRC_SSL_KEY"
	printf 'export MRRC_WEB_PORT=%q\n' "$LOCAL_PORT"
	# 隧道把长连接转发进来，心跳太慢会让对端以为会话死了；与 Windows 安装器取同一值。
	printf 'export MRRC_REMOTE_SESSION_TX_HEARTBEAT_S=5\n'
	echo "$END"
} > "$ENV_SH.new"
chmod 600 "$ENV_SH.new"
mv "$ENV_SH.new" "$ENV_SH"
echo "  应用环境: ${ENV_SH}（0600）"

# 登录 shell：标记块替换，块外的行原样保留。
PROFILE="${MRRC_WIRE_PROFILE:-$HOME/.profile}"
if ! grep -qF "$BEGIN" "$PROFILE" 2>/dev/null; then
	printf '\n%s\n[ -f "%s" ] && . "%s"\n%s\n' "$BEGIN" "$ENV_SH" "$ENV_SH" "$END" >> "$PROFILE"
	echo "  登录 shell: $PROFILE 已 source"
else
	echo "  登录 shell: $PROFILE 已有来源行（未重复追加）"
fi

case "$OS" in
Darwin)
	PLIST="$HOME/Library/LaunchAgents/com.mrrc.fleet-env.plist"
	mkdir -p "$(dirname "$PLIST")"
	{
		echo '<?xml version="1.0" encoding="UTF-8"?>'
		echo '<plist version="1.0"><dict>'
		echo '  <key>Label</key><string>com.mrrc.fleet-env</string>'
		echo '  <key>ProgramArguments</key><array>'
		echo '    <string>/bin/sh</string><string>-c</string>'
		printf '    <string>%s</string>\n' "launchctl setenv MRRC_WEB_PORT $LOCAL_PORT; launchctl setenv MRRC_REMOTE_SESSION_TX_HEARTBEAT_S 5${MRRC_SSL_CERT:+; launchctl setenv MRRC_SSL_CERT $MRRC_SSL_CERT}${MRRC_SSL_KEY:+; launchctl setenv MRRC_SSL_KEY $MRRC_SSL_KEY}"
		echo '  </array>'
		echo '  <key>RunAtLoad</key><true/>'
		echo '</dict></plist>'
	} > "$PLIST"
	chmod 644 "$PLIST"
	echo "  图形应用: ${PLIST}（登录时生效；本次会话可先跑 launchctl setenv 立即生效）"
	;;
Linux)
	ED_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d"
	mkdir -p "$ED_DIR"
	{
		echo "# 由 wire_instance_env.sh 生成；systemd 用户会话读取（图形登录生效）"
		[[ -n "${MRRC_SSL_CERT:-}" ]] && echo "MRRC_SSL_CERT=$MRRC_SSL_CERT"
		[[ -n "${MRRC_SSL_KEY:-}" ]] && echo "MRRC_SSL_KEY=$MRRC_SSL_KEY"
		echo "MRRC_WEB_PORT=$LOCAL_PORT"
		echo "MRRC_REMOTE_SESSION_TX_HEARTBEAT_S=5"
	} > "$ED_DIR/mrrc.conf"
	chmod 644 "$ED_DIR/mrrc.conf"
	echo "  图形应用: $ED_DIR/mrrc.conf（systemd 用户会话）"
	;;
*)
	echo "  图形应用: 未支持的平台 $OS —— 手动 export 即可（值见 $ENV_SH）" >&2
	;;
esac

echo
echo "  现在也能立即用（当前终端）："
echo "    . \"$ENV_SH\""
