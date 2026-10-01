#!/usr/bin/env bash
# 为某实例签一张自签名证书（Cloud Hub 接入用）。
#
#   ./make_instance_cert.sh <呼号/标签> [输出目录]
#
# 为什么是自签名：租户没有自己的域名，证书跟着安装包走即可。约定是**证书签给实例自己的
# 入口名**（<标签>.mrrc.vlsc.net）—— hub 侧按这个名字校验（proxy_ssl_name），并把这张
# 公钥钉进信任包（/etc/mrrc-hub/trust-bundle.pem）。校验因此始终是开着的：
# 自签证书靠"钉住它"通过，而不是靠关掉 verification。
#
# 幂等：已有可用证书且 CN 匹配时不重签（除非 FORCE=1）。
set -euo pipefail

NAME="${1:?usage: make_instance_cert.sh <callsign/label> [outdir]}"
OUT="${2:-$(pwd)/certs}"
FQDN="${NAME,,}.mrrc.vlsc.net"
DAYS="${DAYS:-3650}"

mkdir -p "$OUT"
CRT="$OUT/fullchain.pem"      # 与 mrrc_modern 的默认路径一致（SSL_CERTFILE）
KEY="$OUT/$(echo "${NAME,,}").key"

if [[ "${FORCE:-0}" != "1" && -s "$CRT" && -s "$KEY" ]] \
   && openssl x509 -in "$CRT" -noout -subject 2>/dev/null | grep -q "CN *= *${FQDN}"; then
	echo "已有 ${FQDN} 的证书，复用（FORCE=1 可强制重签）: $CRT"
	openssl x509 -in "$CRT" -noout -subject -enddate | sed 's/^/  /'
	# 注意：**不在此退出** —— 复跑必须能重试下面的登记，
	# 否则"hub 可达后重跑"这个恢复路径形同虚设（实测踩过：日志里只有一次 200）。
fi

# -config 形式：LibreSSL 与 OpenSSL 3 都认；-addext 在 LibreSSL（macOS 自带）上不存在 ✗
CFG="$(mktemp -t mrrc-cert-cnf)"
cat > "$CFG" <<'CNF'
[req]
distinguished_name = dn
x509_extensions    = v3
prompt             = no
[dn]
CN = placeholder
[v3]
basicConstraints = critical,CA:FALSE
keyUsage         = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
CNF
openssl req -x509 -newkey rsa:2048 -nodes -days "$DAYS" \
	-keyout "$KEY" -out "$CRT" \
	-subj "/CN=${FQDN}" -config "$CFG" 2>/dev/null
rm -f "$CFG"

chmod 600 "$KEY"; chmod 644 "$CRT"
echo "已签发自签名证书（${DAYS} 天）:"
openssl x509 -in "$CRT" -noout -subject -ext subjectAltName -enddate | sed 's/^/  /'
echo "  cert: $CRT"
echo "  key:  $KEY"
echo "  实例侧设置:  MRRC_SSL_CERT=$CRT   MRRC_SSL_KEY=$KEY"
echo "  hub 侧登记:  把这个文件的内容交上去，hub 写进 /etc/mrrc-hub/instance-certs/${NAME,,}.pem"
echo "               （hub 侧只需公钥；私钥永远不离开实例）"
# ---- 登记：把**公钥**交给 hub（私钥永不外传）----
# 口令来自 Portal 的"分配入口"（运维页显示），一次性；没有口令时跳过并说明后果。
if [[ -n "${MRRC_ENROLL_SECRET:-}" ]]; then
	url="${MRRC_ENROLL_URL:-https://www.vlsc.net/mrrc_portal/enroll}"
	echo "登记到 hub: $url"
	if out="$(curl -fsS --retry 3 --connect-timeout 20 \
			-X POST --data-urlencode "callsign=$NAME" \
			--data-urlencode "secret=$MRRC_ENROLL_SECRET" \
			--data-urlencode "cert@$CRT" "$url" 2>&1)"; then
		echo "  登记成功 ✓ $(echo "$out" | tr -d '\n' | head -c 160)"
		echo "  hub 上还需 root 执行（Portal 有意不代劳）："
		echo "    sudo /usr/local/sbin/gen_hub_routes.py && sudo nginx -t && sudo systemctl reload nginx"
	else
		echo "  登记失败 ✗ ${out:0:200}" >&2
		echo "  证书已在本地；hub 可达后重跑本脚本即可（幂等）" >&2
	fi
else
	echo "未设 MRRC_ENROLL_SECRET ⇒ 跳过登记"
	echo "  （自签证书必须登记到 hub 才会被信任，否则入口会 502；口令在 Portal 的「分配入口」里）"
fi
