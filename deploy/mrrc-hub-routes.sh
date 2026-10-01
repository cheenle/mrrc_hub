#!/bin/sh
# Regenerate the routes and the trust bundle, verify the result, and reload nginx only if the
# configuration is still valid. Kept as a script rather than an ExecStart one-liner so the gate is
# readable: the whole point is that a broken generation must never reach a reload.
set -eu

echo "regenerating hub routes"
/usr/local/sbin/gen_hub_routes.py

if nginx -t; then
	echo "nginx -t passed; reloading"
	systemctl reload nginx
else
	echo "nginx -t FAILED after regenerating - leaving the running configuration alone" >&2
	exit 1
fi
