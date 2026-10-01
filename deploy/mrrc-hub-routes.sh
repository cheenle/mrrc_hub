#!/bin/sh
# Regenerate the hub's routes and trust bundle, and reload nginx only when something actually
# changed and the new configuration passes nginx -t.
#
# Run from a timer rather than a path unit on purpose: systemd's PathChanged also fires on atime
# updates, so a unit that reads the certificate directory triggers itself - measured at 232 starts
# in two minutes. A 30-second timer costs a glob and a diff and cannot do that.
set -eu

MAP=/etc/nginx/conf.d/mrrc-hub-map.conf
BUNDLE=/etc/mrrc-hub/trust-bundle.pem

before=$(cat "$MAP" "$BUNDLE" 2>/dev/null | sha256sum | cut -d' ' -f1)
/usr/local/sbin/gen_hub_routes.py
after=$(cat "$MAP" "$BUNDLE" 2>/dev/null | sha256sum | cut -d' ' -f1)

if [ "$before" = "$after" ]; then
	echo "nothing changed; not reloading"
	exit 0
fi

if nginx -t; then
	echo "configuration changed and nginx -t passed; reloading"
	systemctl reload nginx
else
	echo "nginx -t FAILED after regenerating - leaving the running configuration alone" >&2
	exit 1
fi
