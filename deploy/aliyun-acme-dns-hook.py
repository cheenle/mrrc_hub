#!/usr/bin/env python3
"""certbot manual DNS-01 hook for Aliyun DNS (std-lib only).

Called by certbot twice per challenge:

    aliyun-acme-dns-hook.py auth      # add  _acme-challenge.<domain> TXT
    aliyun-acme-dns-hook.py cleanup   # remove exactly that value again

certbot exports CERTBOT_DOMAIN / CERTBOT_VALIDATION for us. Why a hand-written
hook instead of certbot-dns-aliyun: that plugin is third-party and unmaintained,
and the hub's Python is new enough that a bridge plugin is a gamble. The RPC
signature is 20 lines of stdlib, and this box already needs to talk to Aliyun DNS
(the operator's own aliddns.py does the same for its A records).

Credentials: /root/.secrets/aliyun.ini, mode 0600, either

    access_key_id = ...
    access_key_secret = ...

or the certbot plugin's naming (dns_aliyun_access_key[..._secret]) so a file
written for either tool works.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ENDPOINT = "https://alidns.aliyuncs.com/"
CREDS = Path("/root/.secrets/aliyun.ini")
API_VERSION = "2015-01-09"


def credentials() -> tuple[str, str]:
    key = secret = ""
    for raw in CREDS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip().lower(), value.strip().strip('"')
        if name in ("access_key_id", "dns_aliyun_access_key"):
            key = value
        elif name in ("access_key_secret", "dns_aliyun_access_key_secret"):
            secret = value
    if not key or not secret:
        sys.exit(f"{CREDS} must define access_key_id / access_key_secret")
    return key, secret


def percent(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def call(action: str, key: str, secret: str, **params) -> dict:
    """Signed Aliyun RPC call (HMAC-SHA1 over the sorted parameters)."""
    common = {
        "Format": "JSON", "Version": API_VERSION,
        "AccessKeyId": key, "SignatureMethod": "HMAC-SHA1",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "SignatureVersion": "1.0", "SignatureNonce": str(uuid.uuid4()),
        "Action": action,
    }
    allp = {**common, **params}
    canonical = "&".join(f"{percent(k)}={percent(allp[k])}" for k in sorted(allp))
    string_to_sign = "POST&%2F&" + percent(canonical)
    digest = hmac.new((secret + "&").encode(), string_to_sign.encode(), hashlib.sha1).digest()
    allp["Signature"] = base64.b64encode(digest).decode()
    body = "&".join(f"{percent(k)}={percent(v)}" for k, v in allp.items()).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def rr_name(certbot_domain: str) -> tuple[str, str]:
    """('_acme-challenge.mrrc', 'vlsc.net') for mrrc.vlsc.net (or a name under it)."""
    parts = certbot_domain.split(".")
    for i in range(1, len(parts)):
        candidate = ".".join(parts[i:])
        if candidate.count(".") == 1:          # vlsc.net
            return "_acme-challenge." + ".".join(parts[:i]), candidate
    return "_acme-challenge", certbot_domain


def state_file(domain: str, value: str) -> Path:
    """Where auth parks the value so cleanup can find it again.

    certbot guarantees CERTBOT_DOMAIN for cleanup but *not* CERTBOT_VALIDATION - it
    passes the auth hook's stdout as CERTBOT_AUTH_OUTPUT instead. Relying on the
    variable worked for auth and broke cleanup (measured: the hook exited with its
    usage message and the challenge failed), so the value is persisted explicitly.
    """
    digest = hashlib.sha256(f"{domain}:{value}".encode()).hexdigest()[:16]
    return Path(f"/tmp/aliyun-acme-{digest}.state")


def wait_visible(fqdn: str, value: str, timeout: float = 90.0) -> bool:
    """Poll a public resolver until the TXT value is visible.

    The CA validates through its own resolvers, not through the zone's
    authoritative server, so a record that answers locally can still be invisible
    where it matters.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"https://dns.google/resolve?name={fqdn}&type=TXT", timeout=10) as r:
                txt = " ".join(a.get("data", "") for a in json.loads(r.read()).get("Answer", []))
            if value in txt:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def resolve_mode() -> str:
    """Which phase are we in?

    certbot runs the hook with **no arguments** - the phase is what it exports to the
    environment: auth gets CERTBOT_VALIDATION, cleanup gets CERTBOT_AUTH_OUTPUT (and
    may not set CERTBOT_VALIDATION at all). Assuming an argument made every call exit
    with the usage message, which is why the first two issuance attempts failed with
    "some challenges have failed" while a hand-run `hook auth` worked fine.
    An explicit argument is still honoured, for manual testing.
    """
    explicit = sys.argv[1] if len(sys.argv) > 1 else ""
    if explicit in ("auth", "cleanup"):
        return explicit
    if os.environ.get("CERTBOT_AUTH_OUTPUT") is not None:
        return "cleanup"
    if os.environ.get("CERTBOT_VALIDATION"):
        return "auth"
    return ""


def main() -> int:
    mode = resolve_mode()
    domain = os.environ.get("CERTBOT_DOMAIN", "")
    value = os.environ.get("CERTBOT_VALIDATION", "")
    if mode not in ("auth", "cleanup") or not domain:
        sys.exit("usage: aliyun-acme-dns-hook.py [auth|cleanup]   (certbot sets CERTBOT_*)")
    key, secret = credentials()
    rr, zone = rr_name(domain)

    if mode == "auth":
        if not value:
            sys.exit("auth needs CERTBOT_VALIDATION")
        res = call("AddDomainRecord", key, secret, DomainName=zone, RR=rr, Type="TXT", Value=value)
        if "RecordId" not in res:
            if res.get("Code") not in ("DomainRecordDuplicate", "DomainRecordExist"):
                sys.exit(f"AddDomainRecord failed: {res}")
            print("  record already present")
        else:
            print(f"  TXT {rr}.{zone} added (RecordId {res['RecordId']})")
        state_file(domain, value).write_text(value, encoding="utf-8")
        fqdn = f"{rr}.{zone}"
        if not wait_visible(fqdn, value):
            sys.exit(f"{fqdn} never became visible to a public resolver (TXT {value[:12]}…)")
        print(f"  {fqdn} visible publicly")
        return 0

    # cleanup: work from the state file; fall back to whatever certbot did provide.
    candidates = [value] if value else []
    for path in Path("/tmp").glob("aliyun-acme-*.state"):
        candidates.append(path.read_text(encoding="utf-8").strip())
    listed = call("DescribeDomainRecords", key, secret, DomainName=zone, RRKeyWord=rr, TypeKeyWord="TXT")
    removed = 0
    for rec in listed.get("DomainRecords", {}).get("Record", []):
        if rec.get("Value") in candidates:
            call("DeleteDomainRecord", key, secret, RecordId=rec["RecordId"])
            removed += 1
            print(f"  TXT {rr}.{zone} removed (RecordId {rec['RecordId']})")
    for path in Path("/tmp").glob("aliyun-acme-*.state"):
        path.unlink(missing_ok=True)
    if not removed:
        print("  nothing to clean up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
