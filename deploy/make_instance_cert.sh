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
	echo "已有 ${FQDN} 的证书，跳过（FORCE=1 可强制重签）: $CRT"
	openssl x509 -in "$CRT" -noout -subject -enddate | sed 's/^/  /'
	exit 0
fi

openssl req -x509 -newkey rsa:2048 -nodes -days "$DAYS" \
	-keyout "$KEY" -out "$CRT" \
	-subj "/CN=${FQDN}" \
	-addext "subjectAltName=DNS:${FQDN}" \
	-addext "basicConstraints=critical,CA:FALSE" \
	-addext "keyUsage=critical,digitalSignature,keyEncipherment" \
	-addext "extendedKeyUsage=serverAuth" 2>/dev/null

chmod 600 "$KEY"; chmod 644 "$CRT"
echo "已签发自签名证书（${DAYS} 天）:"
openssl x509 -in "$CRT" -noout -subject -ext subjectAltName -enddate | sed 's/^/  /'
echo "  cert: $CRT"
echo "  key:  $KEY"
echo "  实例侧设置:  MRRC_SSL_CERT=$CRT   MRRC_SSL_KEY=$KEY"
echo "  hub 侧登记:  把这个文件的内容交上去，hub 写进 /etc/mrrc-hub/instance-certs/${NAME,,}.pem"
echo "               （hub 侧只需公钥；私钥永远不离开实例）"
