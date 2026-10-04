#!/usr/bin/env python3
"""portal.htpasswd 的测试：$apr1$ 校验与账号文件解析（零依赖）。

运行：python3 tests/test_htpasswd.py   （也兼容 pytest）
"""
from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import htpasswd as ht  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


#: 固定向量：`openssl passwd -apr1 -salt 8aaVXyz9 'S3cret-pass!'`（2026-10-05 实测）
VECTOR = ("S3cret-pass!", "8aaVXyz9", "$apr1$8aaVXyz9$ibFv5KrTL/uJnYuHKvW6I0")


def test_fixed_vector():
    pw, salt, stored = VECTOR
    check(ht.apr1(pw, salt) == stored, "apr1 固定向量与 openssl 一致")
    check(ht.verify(pw, stored), "正确密码通过")
    check(not ht.verify("wrong", stored), "错误密码拒绝")
    check(not ht.verify(pw, "$2y$05$abcdefghijklmnopqrstuv"), "未知前缀（bcrypt）拒绝")
    check(not ht.verify(pw, "$apr1$8aaVXyz9$short"), "畸形哈希拒绝")
    check(not ht.verify(pw, ""), "空哈希拒绝")


def test_cross_check_openssl():
    if not shutil.which("openssl"):
        print("  提示: 无 openssl，跳过交叉验证"); return
    for _ in range(20):
        pw = secrets.token_urlsafe(12)
        salt = "".join(secrets.choice(ht.ITOA64) for _ in range(8))
        ref = subprocess.run(["openssl", "passwd", "-apr1", "-salt", salt, pw],
                             capture_output=True, text=True, check=True).stdout.strip()
        check(ht.apr1(pw, salt) == ref, f"随机交叉验证不一致（盐 {salt!r}）")
    for pw in ("", "a", "abcdefghijklmnopq", "密码-Ünïcode"):
        ref = subprocess.run(["openssl", "passwd", "-apr1", "-salt", "sAlT1234", pw],
                             capture_output=True, text=True, check=True).stdout.strip()
        check(ht.apr1(pw, "sAlT1234") == ref, f"边界密码交叉验证不一致（{pw!r}）")


def test_parse_users():
    users = ht.parse_users("# 注释\n\nalice:$apr1$aaaaaaaa$0123456789012345678901\n"
                           "bob:$apr1$bbbbbbbb$0123456789012345678901\n"
                           "alice:$apr1$cccccccc$0123456789012345678901\n"
                           "malformed-line\n")
    check(users == {"alice": "$apr1$cccccccc$0123456789012345678901",
                    "bob": "$apr1$bbbbbbbb$0123456789012345678901"},
          "解析：跳过注释/畸形行，重复用户名取最后一条")


def test_users_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "portal-users"
        path.write_text("alice:" + ht.apr1("pw-1", "saltward") + "\n", encoding="utf-8")
        users = ht.UsersFile(path)
        ok, reason = users.verify("alice", "pw-1")
        check(ok and reason == "", "读盘校验：正确密码")
        ok, reason = users.verify("alice", "nope")
        check(not ok and reason == "", "读盘校验：错误密码（不泄露原因）")
        ok, reason = users.verify("nobody", "pw-1")
        check(not ok and reason == "unknown user", "不存在的用户有内部原因（对外文案一致）")
        ok, reason = users.verify("alice", "x")
        path.unlink()
        ok, reason = users.verify("alice", "pw-1")
        check(not ok and reason.startswith("unreadable"), "文件不可读 ⇒ 可读原因，不炸")
        users2 = ht.UsersFile(Path(td) / "absent")
        ok, reason = users2.verify("alice", "pw-1")
        check(not ok and reason.startswith("unreadable"), "文件不存在也走同一条降级")
        parsed, err = users2.read()
        check(parsed is None and err.startswith("unreadable"), "read() 与 verify 共用降级路径")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ htpasswd 测试通过（{len(tests)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
