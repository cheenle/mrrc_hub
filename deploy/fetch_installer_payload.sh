#!/usr/bin/env bash
# 取安装包要内置的外部二进制（frpc / openssl），**逐个校验 SHA-256**。
#
#   ./fetch_installer_payload.sh --out payload [--platforms darwin-arm64,linux-amd64,windows-amd64]
#   ./fetch_installer_payload.sh --record-openssl <url> <name>     # 记一条 openssl 条目（含哈希）
#
# 设计要点：
#   * frpc：从 frp 官方 release 取，并用官方 checksums.txt 校验 —— 哈希来源可信且可复现。
#   * openssl：官方项目**不发布** Windows 二进制，任何第三方构建都必须先由人确认来源与哈希。
#     所以本脚本**不硬编码**openssl 的 URL/哈希，而是从 lock 文件读；lock 里没有该平台的
#     条目就跳过（并在总结里列出缺失项）—— 宁可不打包，也不把来路不明的二进制塞进安装包。
#   * 任何一步哈希不符 ⇒ 删除该文件并报错退出。
set -euo pipefail

OUT=""; PLATFORMS="darwin-arm64,darwin-amd64,linux-arm64,linux-amd64,windows-amd64"
FRP_VERSION="${MRRC_FRP_VERSION:-0.71.0}"
LOCK=""; RECORD=""; NAME_OVERRIDE=""
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
	case "$1" in
		--out) OUT="$2"; shift 2 ;;
		--platforms) PLATFORMS="$2"; shift 2 ;;
		--frp-version) FRP_VERSION="$2"; shift 2 ;;
		--lock) LOCK="$2"; shift 2 ;;
		--record-openssl) RECORD="$2"; NAME_OVERRIDE="$3"; shift 3 ;;
		*) echo "unknown arg: $1" >&2; exit 64 ;;
	esac
done
[[ -n "$OUT" ]] || { echo "usage: $0 --out <dir> [--platforms …] [--lock file] [--record-openssl <url> <name>]" >&2; exit 64; }
LOCK="${LOCK:-$SELF_DIR/payload.lock}"

sha256_of() {
	if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
	else shasum -a 256 "$1" | awk '{print $1}'; fi
}

record_openssl() {
	# 人工确认来源后，把 URL 与实测哈希写进 lock —— 以后每次都按它校验。
	local url="$1" name="$2" tmp hash
	tmp="$(mktemp)"; trap 'rm -f "$tmp"' RETURN
	curl -fsSL --retry 3 -o "$tmp" "$url" || { echo "下载失败: $url" >&2; return 1; }
	hash="$(sha256_of "$tmp")"
	printf '%s\t%s\t%s\n' "$name" "$url" "$hash" >> "$LOCK"
	echo "已记录: $name  sha256=$hash" >&2
	echo "（请人工确认这个来源可信，再把该行提交入库：${LOCK}）" >&2
}

if [[ -n "$RECORD" ]]; then record_openssl "$RECORD" "$NAME_OVERRIDE"; exit 0; fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$OUT"

# ---- frpc：官方 release + 官方 checksums ----
sums="$tmp/frp_checksums.txt"
url_sums="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_sha256_checksums.txt"
if curl -fsSL --retry 3 -o "$sums" "$url_sums"; then
	IFS=',' read -ra PLIST <<< "$PLATFORMS"
	for plat in "${PLIST[@]}"; do
		os="${plat%-*}"; arch="${plat#*-}"; [[ "$os" == windows ]] && ext=zip || ext=tar.gz
		base="frp_${FRP_VERSION}_${os}_${arch}.${ext}"
		want="$(awk -v f="$base" '$2 == f {print $1}' "$sums")"
		if [[ -z "$want" ]]; then echo "  ✗ $base: 官方校验和文件里没有它 —— 跳过" >&2; continue; fi
		if ! curl -fsSL --retry 3 -o "$tmp/$base" "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${base}"; then
			echo "  ✗ $base: 下载失败（网络？）" >&2; continue
		fi
		got="$(sha256_of "$tmp/$base")"
		if [[ "$got" != "$want" ]]; then
			rm -f "$tmp/$base"; echo "  ✗ $base: SHA-256 不匹配，已删除（期望 $want 实得 ${got}）" >&2; exit 1
		fi
		mkdir -p "$OUT/$plat"
		case "$ext" in
			zip) unzip -qo "$tmp/$base" -d "$tmp/x-$plat" ;;
			*)   tar -xzf "$tmp/$base" -C "$tmp" && mv "$tmp/${base%.tar.gz}" "$tmp/x-$plat" ;;
		esac
		bin="$(find "$tmp/x-$plat" -type f \( -name frpc -o -name frpc.exe \) | head -1)"
		[[ -n "$bin" ]] || { echo "  ✗ $base: 包里没有 frpc" >&2; exit 1; }
		install -m 755 "$bin" "$OUT/$plat/$(basename "$bin")"
		echo "  ✓ $plat: $(basename "$bin")（校验通过）" >&2
	done
else
	echo "  ✗ 无法取得 frp 官方校验和文件（${url_sums}）—— frpc 一概不放入" >&2
fi

# ---- openssl：只从 lock 取，无条目则跳过 ----
if [[ -s "$LOCK" ]]; then
	while IFS=$'\t' read -r name url hash; do
		[[ -n "$name" && "$name" != \#* ]] || continue
		plat="${name%%/*}"; file="${name##*/}"
		[[ ",$PLATFORMS," == *",$plat,"* ]] || continue
		if ! curl -fsSL --retry 3 -o "$tmp/$file" "$url"; then echo "  ✗ $plat/$file: 下载失败" >&2; continue; fi
		got="$(sha256_of "$tmp/$file")"
		if [[ "$got" != "$hash" ]]; then
			rm -f "$tmp/$file"; echo "  ✗ $plat/$file: SHA-256 与 lock 不符，已删除（期望 $hash 实得 ${got}）" >&2; exit 1
		fi
		mkdir -p "$OUT/$plat"
		case "$file" in
			*.zip) unzip -qo "$tmp/$file" -d "$OUT/$plat" ;;
			*) install -m 755 "$tmp/$file" "$OUT/$plat/$file" ;;
		esac
		echo "  ✓ $plat/${file}（按 lock 校验通过）" >&2
	done < "$LOCK"
else
	echo "  · openssl: lock 文件不存在或无条目（${LOCK}）—— 需要 Windows 上的证书生成时，" >&2
	echo "    先用 --record-openssl <url> <平台>/<文件名> 记一条并人工确认来源" >&2
fi

# ---- 实例侧脚本：与二进制同源、同级，且必须是"这次构建的代码" ----
# 只放二进制是不够的：安装器脚本版本落后，租户就会装出一个登记不上、或应用侧环境没接线的
# 实例 —— 与发布二进制是同一类错误。脚本直接取自本目录（mrrc_hub/deploy，权威副本），
# 每个平台放它要用的那份：Windows 用 .ps1，macOS/Linux 用 .sh 一族（后者会调用
# wire_instance_env.sh，所以这两个必须同目录，否则安装器找不到它）。
IFS=',' read -ra PLIST <<< "$PLATFORMS"
for plat in "${PLIST[@]}"; do
	mkdir -p "$OUT/$plat"
	case "$plat" in
		windows-*)
			for s in install_instance_tunnel.ps1; do
				install -m 644 "$SELF_DIR/$s" "$OUT/$plat/$s"
				echo "  ✓ $plat/${s}（$(sha256_of "$OUT/$plat/$s" | cut -c1-12)…）" >&2
			done
			;;
		*)
			for s in install_instance_tunnel.sh wire_instance_env.sh make_instance_cert.sh; do
				install -m 755 "$SELF_DIR/$s" "$OUT/$plat/$s"
				echo "  ✓ $plat/${s}（$(sha256_of "$OUT/$plat/$s" | cut -c1-12)…）" >&2
			done
			;;
	esac
done

echo "取件完成: $OUT"
find "$OUT" -type f -maxdepth 2 | sort | sed 's/^/  /'
