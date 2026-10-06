"""htpasswd 账号文件与 $apr1$ 校验（纯标准库）。

为什么自己实现 apr1：Portal 零第三方依赖，而 Python 3.13 起标准库移除了 crypt
模块 ⇒ 校验 htpasswd 里任何 crypt 哈希都没有现成函数。选 $apr1$ 是因为
`openssl passwd -apr1`（hub 必有）与 `htpasswd -m`（apache2-utils，可选）都能生成，
算法短且可用 openssl 做交叉验证。

已知取舍：MD5 系哈希抗 GPU 暴力弱于 bcrypt —— 管理台账号少、密码强、有固定阈值
锁定与 nginx limit_req 兜底；该取舍记录在 specs/2026-10-05-portal-admin-auth-tunnel-metrics-design.md
的决策记录里。校验用常数时间比较；用户不存在时也跑一次假哈希，响应时间不泄露用户是否存在。
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_MAGIC = b"$apr1$"

#: 用户不存在时的替身：格式合法、值无意义。见模块说明的时序说明。
_DUMMY = "$apr1$00000000$0000000000000000000000"


def apr1(password: str, salt: str) -> str:
    """Apache MD5-crypt（`$apr1$`）——与 `openssl passwd -apr1` 逐字节一致。"""
    pw = password.encode("utf-8")
    sb = salt.encode("ascii")[:8]
    ctx = hashlib.md5(pw + _MAGIC + sb)
    ctx1 = hashlib.md5(pw + sb + pw).digest()
    pl = len(pw)
    while pl > 0:
        ctx.update(ctx1[: min(pl, 16)])
        pl -= 16
    i = len(pw)
    while i:
        ctx.update(b"\x00" if (i & 1) else pw[:1])
        i >>= 1
    final = ctx.digest()
    for i in range(1000):
        c = hashlib.md5()
        c.update(pw if (i & 1) else final)
        if i % 3:
            c.update(sb)
        if i % 7:
            c.update(pw)
        c.update(final if (i & 1) else pw)
        final = c.digest()
    out = []
    for a, b, c in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)):
        v = (final[a] << 16) | (final[b] << 8) | final[c]
        for _ in range(4):
            out.append(ITOA64[v & 0x3F])
            v >>= 6
    v = final[11]
    for _ in range(2):
        out.append(ITOA64[v & 0x3F])
        v >>= 6
    return "$apr1$" + sb.decode("ascii") + "$" + "".join(out)


def verify(password: str, stored: str) -> bool:
    """只有 `$apr1$` 且格式完整才校验；其他前缀一律 False（fail closed）。"""
    if not stored.startswith("$apr1$"):
        return False
    parts = stored.split("$")
    if len(parts) != 4 or not parts[2] or len(parts[3]) != 22:
        return False
    try:
        computed = apr1(password, parts[2])
    except (UnicodeEncodeError, ValueError):
        return False
    return hmac.compare_digest(computed, stored)


def parse_users(text: str) -> dict:
    """`用户名:哈希` 一行一个；空行与 `#` 注释跳过；重复取最后一条；畸形行跳过。"""
    users: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        user, sep, digest = line.partition(":")
        if not sep or not user.strip() or not digest.strip():
            continue
        users[user.strip()] = digest.strip()
    return users


class UsersFile:
    """每次登录读盘（改密码/删人无需重启）；失败给可读原因而不是异常。"""

    def __init__(self, path):
        self.path = Path(path)

    def read(self) -> tuple[dict | None, str]:
        """→ (用户名→哈希, 错误原因)。错误原因以 `unreadable` 开头，供 dry-run 与登录共用。"""
        try:
            return parse_users(self.path.read_text(encoding="utf-8")), ""
        except OSError as exc:
            return None, f"unreadable: {exc}"

    def verify(self, username: str, password: str) -> tuple[bool, str]:
        """→ (是否通过, 内部原因)。原因只进审计/排障，不直接展示给用户。"""
        users, error = self.read()
        if users is None:
            return False, error
        stored = users.get(username)
        if stored is None:
            verify(password, _DUMMY)          # 时序等价：不存在的用户也付出一次校验成本
            return False, "unknown user"
        if not stored.startswith("$apr1$"):
            return False, "unsupported hash"
        return verify(password, stored), ""
