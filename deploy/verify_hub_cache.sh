#!/usr/bin/env bash
# 边缘静态资源缓存的验收 —— 8 条断言，只读，不改任何配置。
#
#   ./verify_hub_cache.sh ba4eg --token <mrrc_auth cookie 值>
#   MRRC_HUB_TEST_TOKEN=<值> ./verify_hub_cache.sh ba4eg
#
# cookie 从实例登录后拿：浏览器 DevTools → Application → Cookies → mrrc_auth，
# 或 `curl -sk -c jar -X POST https://<标签>.mrrc.vlsc.net/api/auth/login \
#      -H 'Content-Type: application/json' -d '{"password":"…"}'`。
# 没有令牌就只跑第 1 条（未知实例 404），其余跳过。
#
# 为什么这些断言值得单独一个脚本：缓存的东西坏了不会报错 ——
# 被缓存的 307 会让已登录用户反复被打回登录页，而页面看起来只是"又要登录"。
set -uo pipefail

LABEL="${1:?usage: $0 <instance-label> [--token <cookie-value>]}"
TOKEN="${MRRC_HUB_TEST_TOKEN:-}"
if [[ "${2:-}" == "--token" ]]; then TOKEN="${3:-}"; fi

HOST="https://${LABEL}.mrrc.vlsc.net"
ASSET="/modules/opus_wasm.js" # 534 KB，实例侧最大的静态件
COOKIE=(-H "Cookie: mrrc_auth=${TOKEN}")
pass=0
fail=0

check() { # check <名字> <期望> <实际>
	if [[ "$2" == "$3" ]]; then
		printf 'PASS  %s\n' "$1"
		pass=$((pass + 1))
	else
		printf 'FAIL  %s\n        期望: %s\n        实际: %s\n' "$1" "$2" "$3"
		fail=$((fail + 1))
	fi
}

code() { curl -sk -o /dev/null -w '%{http_code}' "$@"; }

hdr() { # hdr <头名> <curl 参数…>
	local name="$1"
	shift
	curl -sk -D - -o /dev/null "$@" |
		tr -d '\r' |
		awk -F': ' -v k="$name" 'BEGIN{IGNORECASE=1} tolower($1)==tolower(k){print $2}' |
		tail -1
}

echo "== $HOST =="
check "未知实例 → 404" "404" "$(code https://nope.mrrc.vlsc.net/)"

if [[ -z "$TOKEN" ]]; then
	echo "SKIP  未提供 --token：跳过需要登录的 7 条"
	printf '\n%s passed, %s failed\n' "$pass" "$fail"
	[[ $fail -eq 0 ]]
	exit
fi

check "资源 200（隧道 + 实例）" "200" "$(code "${COOKIE[@]}" "$HOST$ASSET")"
check "资源带 1 小时缓存头" "public, max-age=3600" "$(hdr cache-control "${COOKIE[@]}" "$HOST$ASSET")"
ETAG="$(hdr etag "${COOKIE[@]}" "$HOST$ASSET")"
check "重复请求命中边缘缓存" "HIT" "$(hdr x-cache-status "${COOKIE[@]}" "$HOST$ASSET")"
check "条件请求由边缘答 304" "304" "$(code "${COOKIE[@]}" -H "If-None-Match: $ETAG" "$HOST$ASSET")"
check "硬刷新绕过边缘缓存" "BYPASS" "$(hdr x-cache-status "${COOKIE[@]}" -H 'Cache-Control: no-cache' "$HOST$ASSET")"
SIZE="$(curl -sk --compressed -o /dev/null -w '%{size_download}' "${COOKIE[@]}" "$HOST$ASSET")"
check "gzip 生效（< 300 KB，实测 ${SIZE} B）" "yes" "$([[ $SIZE -lt 307200 ]] && echo yes || echo no)"
check "HTML 不进缓存（无 X-Cache-Status）" "" "$(hdr x-cache-status "${COOKIE[@]}" "$HOST/")"

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
