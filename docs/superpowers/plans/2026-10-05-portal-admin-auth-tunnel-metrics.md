# Portal 后台管理：用户名/密码认证 + 隧道性能指标 — 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 给 `mrrc_hub/portal` 的 `/admin` 运维台加上一人一账号的用户名/密码登录（htpasswd `$apr1$` + 服务端会话 + CSRF），并新增「隧道」视图显示每实例的延时、上下行带宽、今日流量与连接数（数据来自 frps 回环面板 + 30s 后台采样）。

**架构：** 三个新模块各守一个边界：`htpasswd.py`（凭据校验）、`sessions.py`（会话与登录防护）、`metrics.py`（面板客户端 + 采样器 + 内存环形历史）。`app.py` 只在 HTTP 层接线与渲染；`store.py` 只加审计的 `actor` 字段。机器路径（`X-Portal-Token` 请求头）保留，浏览器路径改为会话+CSRF。

**技术栈：** Python 3 标准库（零第三方依赖）；`hashlib`/`hmac`/`secrets`/`threading`/`http.cookies`/`urllib`；测试为裸函数 + `FAILS` 列表（兼容 pytest），沿用 `tests/test_portal.py` 的写法。

**规格：** `docs/superpowers/specs/2026-10-05-portal-admin-auth-tunnel-metrics-design.md`（已批准，commit `c3a0f58`）

---

## 文件结构（先锁定边界，再拆任务）

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `portal/htpasswd.py` | `$apr1$` 重算与校验、htpasswd 文本解析、`UsersFile`（每次读盘、失败原因可读） | 新建 |
| `portal/sessions.py` | `SessionStore`（内存会话、空闲/绝对超时、CSRF）与 `LoginGuard`（固定阈值锁定），时钟可注入 | 新建 |
| `portal/metrics.py` | `FrpsPanel`（回环面板 Basic 取数）与 `Sampler`（30s 后台线程、差分速率、探测计时、环形历史、诚实降级） | 新建 |
| `portal/store.py` | 审计 `actor` 字段 + `record_login()` | 修改 |
| `portal/app.py` | 登录/登出路由、Cookie/CSRF、`_admin` 会话化、双路径动作鉴权、隧道视图渲染、main() 参数 | 修改 |
| `tests/test_htpasswd.py` | 固定向量 + openssl 交叉验证 + 文件解析/降级 | 新建 |
| `tests/test_portal_auth.py` | 会话/锁定单元 + 登录全链路 + CSRF/登出/审计 + 既有测试适配 | 新建 |
| `tests/test_portal_metrics.py` | 采样器单元（假面板/假时钟/假探测）+ 隧道视图端到端渲染 | 新建 |
| `tests/test_portal.py` | 管理台相关测试改为会话登录；导航改 GET 后更新断言 | 修改 |
| `deploy/bootstrap-hub.sh` | frps 面板段 + 凭据生成 + `ExecReload` + 账号文件占位 | 修改 |
| `deploy/README.md`、`portal/README.md`、`SDD/10,11,12,14,README` | 文档同步 | 修改 |

---

### 任务 1：`$apr1$` 校验与账号文件

**文件：**

- 创建：`portal/htpasswd.py`
- 测试：`tests/test_htpasswd.py`

- [ ] **步骤 1：编写失败的测试**

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_htpasswd.py`
预期：`ModuleNotFoundError: No module named 'portal.htpasswd'`

- [ ] **步骤 3：实现 `portal/htpasswd.py`**

```python
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

    def verify(self, username: str, password: str) -> tuple[bool, str]:
        """→ (是否通过, 内部原因)。原因只进审计/排障，不直接展示给用户。"""
        try:
            users = parse_users(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            return False, f"unreadable: {exc}"
        stored = users.get(username)
        if stored is None:
            verify(password, _DUMMY)          # 时序等价：不存在的用户也付出一次校验成本
            return False, "unknown user"
        if not stored.startswith("$apr1$"):
            return False, "unsupported hash"
        return verify(password, stored), ""
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_htpasswd.py`
预期：`✅ htpasswd 测试通过（4 组）`（无 openssl 时 3 组 + 提示）

- [ ] **步骤 5：Commit**

```bash
git add portal/htpasswd.py tests/test_htpasswd.py
git commit -m "portal: verify htpasswd \$apr1\$ logins without the removed crypt module"
```

---

### 任务 2：会话与登录防护（`portal/sessions.py`）

**文件：**

- 创建：`portal/sessions.py`
- 测试：`tests/test_portal_auth.py`（本任务先写其中的会话/锁定单元部分）

- [ ] **步骤 1：编写失败的测试**（`tests/test_portal_auth.py` 的首段）

```python
#!/usr/bin/env python3
"""Portal 后台认证：会话/锁定单元 + 登录全链路 + CSRF/登出/审计。

运行：python3 tests/test_portal_auth.py   （也兼容 pytest）
"""
from __future__ import annotations

import http.cookiejar
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import htpasswd as ht            # noqa: E402
from portal import registry as reg           # noqa: E402
from portal import sessions as sess          # noqa: E402
from portal.app import Portal, make_handler  # noqa: E402
from portal.store import Store               # noqa: E402
from portal.verify import CallsignListVerifier  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_session_lifecycle():
    clock = FakeClock()
    store = sess.SessionStore(idle_seconds=100, absolute_seconds=200, clock=clock)
    sid = store.create("alice")
    s = store.get(sid)
    check(s is not None and s.user == "alice" and s.csrf, "会话创建后可取，且带 CSRF")
    check(len(sid) >= 32, "会话 ID 足够长（token_urlsafe(32)）")
    clock.advance(99)
    check(store.get(sid) is not None, "空闲未到期仍有效")
    clock.advance(2)
    check(store.get(sid) is None, "空闲超时失效")
    sid2 = store.create("bob")
    clock.advance(199)
    check(store.get(sid2) is not None, "绝对期限前有效（每次访问会刷新 last_seen）")
    clock.advance(2)
    check(store.get(sid2) is None, "绝对超时即使一直在用也失效")
    sid3 = store.create("carol")
    store.destroy(sid3)
    check(store.get(sid3) is None, "登出销毁")


def test_login_guard():
    clock = FakeClock()
    guard = sess.LoginGuard(user_limit=3, user_window=100, ip_limit=5, ip_window=100,
                            lock_seconds=50, clock=clock)
    for _ in range(2):
        guard.fail("alice", "10.0.0.1")
    check(guard.locked("alice", "10.0.0.1") == 0, "未到阈值不锁")
    guard.fail("alice", "10.0.0.1")
    check(guard.locked("alice", "10.0.0.1") > 0, "到阈值即锁")
    check(guard.locked("alice", "10.0.0.2") > 0, "用户名维度跨 IP 生效")
    clock.advance(51)
    check(guard.locked("alice", "10.0.0.1") == 0, "锁定到期自解")
    for _ in range(4):
        guard.fail("bob", "10.9.9.9")
    check(guard.locked("bob", "10.9.9.9") > 0, "IP 维度阈值独立生效（5 次）")
    check(guard.locked("carol", "10.9.9.9") > 0, "同一 IP 的其他用户也被 IP 锁拦")
    guard.success("alice", "10.0.0.1")
    check(guard.locked("alice", "10.0.0.1") == 0, "成功登录清空失败记录")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_auth.py`
预期：`ModuleNotFoundError: No module named 'portal.sessions'`

- [ ] **步骤 3：实现 `portal/sessions.py`**

```python
"""后台会话与登录防护（内存态，零第三方依赖）。

边界：会话只在 portal 进程内有效 —— 重启即全部登出（规格里明确接受），
因此不落盘、不引入签名密钥。时钟可注入，锁定与超时都能用假时钟测试。
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Session:
    user: str
    csrf: str
    created: float
    last_seen: float


class SessionStore:
    def __init__(self, idle_seconds: float = 8 * 3600, absolute_seconds: float = 24 * 3600,
                 clock=time.time):
        self.idle_seconds = float(idle_seconds)
        self.absolute_seconds = float(absolute_seconds)
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user: str) -> str:
        sid = secrets.token_urlsafe(32)                       # 登录成功即换发新 ID（防会话固定）
        now = self._clock()
        with self._lock:
            self._sessions[sid] = Session(user=user, csrf=secrets.token_urlsafe(24),
                                          created=now, last_seen=now)
        return sid

    def get(self, sid: str) -> Session | None:
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            s = self._sessions.get(sid)
            if s is None:
                return None
            if now - s.last_seen > self.idle_seconds or now - s.created > self.absolute_seconds:
                del self._sessions[sid]
                return None
            s.last_seen = now
            return s

    def destroy(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def count(self) -> int:
        with self._lock:
            self._prune_locked(self._clock())
            return len(self._sessions)

    def _prune_locked(self, now: float) -> None:
        for sid, s in list(self._sessions.items()):
            if now - s.last_seen > self.idle_seconds or now - s.created > self.absolute_seconds:
                del self._sessions[sid]


class LoginGuard:
    """固定阈值硬锁定（规格决策 7）：用户名 5 次/5 分钟、IP 10 次/5 分钟，各锁 5 分钟。

    接受"按用户名锁可被恶意触发"的代价；成功登录清空该用户名与该 IP 的计数。
    """

    def __init__(self, user_limit: int = 5, user_window: float = 300.0,
                 ip_limit: int = 10, ip_window: float = 300.0,
                 lock_seconds: float = 300.0, clock=time.time):
        self.user_limit, self.user_window = user_limit, user_window
        self.ip_limit, self.ip_window = ip_limit, ip_window
        self.lock_seconds = lock_seconds
        self._clock = clock
        self._user_fails: dict[str, deque] = {}
        self._ip_fails: dict[str, deque] = {}
        self._user_locked: dict[str, float] = {}
        self._ip_locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked(self, user: str, ip: str) -> int:
        """剩余锁定秒数（向上取整）；0 = 未锁。"""
        now = self._clock()
        with self._lock:
            remaining = 0.0
            for key, table in ((user, self._user_locked), (ip, self._ip_locked)):
                until = table.get(key, 0.0)
                if until > now:
                    remaining = max(remaining, until - now)
                elif until:
                    table.pop(key, None)
            return int(remaining + 0.999) if remaining > 0 else 0

    def fail(self, user: str, ip: str) -> None:
        now = self._clock()
        with self._lock:
            if len(self._record(self._user_fails, user, now, self.user_window)) >= self.user_limit:
                self._user_locked[user] = now + self.lock_seconds
            if len(self._record(self._ip_fails, ip, now, self.ip_window)) >= self.ip_limit:
                self._ip_locked[ip] = now + self.lock_seconds

    def success(self, user: str, ip: str) -> None:
        with self._lock:
            self._user_fails.pop(user, None)
            self._ip_fails.pop(ip, None)

    @staticmethod
    def _record(table: dict, key: str, now: float, window: float) -> deque:
        q = table.setdefault(key, deque())
        q.append(now)
        while q and now - q[0] > window:
            q.popleft()
        return q
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_auth.py`
预期：`✅ ... 2 组`（本任务阶段只有两个 test_ 函数；未实现的部分在任务 4 补齐）

- [ ] **步骤 5：Commit**

```bash
git add portal/sessions.py tests/test_portal_auth.py
git commit -m "portal: in-memory admin sessions and fixed-threshold login guard"
```

---

### 任务 3：审计 `actor` 与登录事件

**文件：**

- 修改：`portal/store.py`
- 修改：`portal/app.py`（`Portal.grant/revoke` 透传 actor，见任务 4；本任务只改 store 与调用点签名）
- 测试：`tests/test_portal_auth.py`（追加断言）

- [ ] **步骤 1：编写失败的测试**（追加到 `tests/test_portal_auth.py`）

```python
def test_audit_actor_and_login_events():
    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td) / "portal.json")
        store.apply("BG1SB")
        store.mark_verified("BG1SB", "材料", actor="alice")
        store.grant("BG1SB", "bg1sb", 18802, actor="alice")
        store.record_login("login_ok", "alice", "203.0.113.7")
        events = store.audit()
        by_event = {e["event"]: e for e in events}
        check(by_event["verified"].get("actor") == "alice", "核验记下操作者")
        check(by_event["granted"].get("actor") == "alice", "授予记下操作者")
        login = by_event["login_ok"]
        check(login.get("actor") == "alice" and login["callsign"] == "", "登录事件 actor=用户名、无呼号")
        check("203.0.113.7" in login["detail"], "登录事件带来源 IP")
        check(all("actor" in e for e in events), "所有条目都有 actor 字段（旧文件缺省为空）")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_auth.py`
预期：FAIL（`mark_verified() got an unexpected keyword argument 'actor'` 或 `record_login` 不存在）

- [ ] **步骤 3：实现 store.py 改动**

```python
# _audit：追加 actor
def _audit(self, data: dict, callsign: str, event: str, detail: str = "", actor: str = "") -> None:
    data["audit"].append({"at": time.time(), "callsign": callsign, "event": event,
                          "detail": detail, "actor": actor})

# 登录事件：没有呼号，actor = 尝试的用户名；长度封顶防垃圾写入
def record_login(self, event: str, user: str, ip: str) -> None:
    """login_ok / login_failed / login_locked。调用方保证 event 来自白名单。"""
    data = self._load()
    self._audit(data, "", event, f"user={user[:40]} ip={ip[:45]}", actor=user[:40])
    self._save(data)

# 各入口加 actor 关键字参数并透传：
def mark_verified(self, callsign: str, evidence: str, actor: str = "") -> Application:
    return self._transition(callsign, VERIFIED, evidence, {APPLIED}, actor=actor)

def reject(self, callsign: str, reason: str, actor: str = "") -> Application:
    return self._transition(callsign, REJECTED, reason, {APPLIED, VERIFIED}, actor=actor)

def revoke(self, callsign: str, reason: str, actor: str = "") -> Application:
    return self._transition(callsign, REVOKED, reason, {GRANTED}, actor=actor)

def _transition(self, callsign, new_status, detail, allowed, actor: str = "") -> Application:
    ...  # 体内 self._audit(data, callsign, new_status, detail, actor=actor)

def grant(self, callsign: str, label: str, port: int, actor: str = "") -> Application:
    ...  # 体内 self._audit(data, callsign, "granted", f"{label} → {port}", actor=actor)
```

- [ ] **步骤 4：同步 `Portal.grant/revoke` 透传 actor**

```python
def grant(self, raw_callsign: str, actor: str = "") -> dict:
    ...
    granted = self.store.grant(normalized, label, port, actor=actor)

def revoke(self, raw_callsign: str, reason: str, actor: str = "") -> dict:
    ...
    self.store.revoke(normalized, reason, actor=actor)
```

- [ ] **步骤 5：运行测试验证通过**

运行：`python3 tests/test_portal_auth.py && python3 tests/test_portal.py`
预期：新测试通过；既有测试不回归（`actor` 有默认值）

- [ ] **步骤 6：Commit**

```bash
git add portal/store.py portal/app.py tests/test_portal_auth.py
git commit -m "portal: attribute audit entries to an actor and record login events"
```

---

### 任务 4：HTTP 接入（登录/登出/会话/CSRF/双路径鉴权）

**文件：**

- 修改：`portal/app.py`（`make_handler`、`_send`、新增认证路由、`_admin` 会话化）
- 修改：`tests/test_portal.py`（管理台既有测试改为会话登录）
- 测试：`tests/test_portal_auth.py`（补全全链路测试）

- [ ] **步骤 1：编写失败的测试**（追加到 `tests/test_portal_auth.py`）

```python
USERS_TEXT = "ops:" + ht.apr1("str0ng-pass", "saltward") + "\n"


def _auth_env(tmp: Path, base=""):
    """起一个带账号文件的 Portal：返回 (base_url, portal, 可关闭的 httpd)。"""
    (tmp / "callsigns.txt").write_text("BG1SB\n", encoding="utf-8")
    users_path = tmp / "portal-users"
    users_path.write_text(USERS_TEXT, encoding="utf-8")
    portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                    CallsignListVerifier(tmp / "callsigns.txt"))
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        portal, token="tok", base=base, users=ht.UsersFile(users_path),
        sessions=sess.SessionStore(), guard=sess.LoginGuard()))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", portal, httpd


def _opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def _get(opener, url):
    try:
        with opener.open(url, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def _post(opener, url, fields):
    data = urllib.parse.urlencode(fields).encode()
    try:
        with opener.open(url, data=data, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def test_login_flow_and_csrf():
    with tempfile.TemporaryDirectory() as td:
        base, portal, httpd = _auth_env(Path(td))
        try:
            op, jar = _opener()
            st, page, _ = _get(op, base + "/admin")
            check(st == 200 and "用户名" in page and "密码" in page, "未登录看到登录页")
            st, page, _ = _post(op, base + "/admin/login", {"user": "ops", "password": "wrong"})
            check(st == 401 and "不正确" in page, "错密码 401 且文案不区分用户是否存在")
            st, page, _ = _post(op, base + "/admin/login", {"user": "ghost", "password": "wrong"})
            check(st == 401 and "不正确" in page, "不存在的用户同文案")
            st, page, hdr = _post(op, base + "/admin/login", {"user": "ops", "password": "str0ng-pass"})
            check(st == 200 and "后台管理" in page, "正确密码登录后跟到管理台")
            cookie = next(c for c in jar if c.name == "mrrc_portal_session")
            check(cookie.has_nonstandard_attr("HttpOnly") or cookie.get_nonstandard_attr("HttpOnly") is not None,
                  "Cookie 是 HttpOnly")
            check(cookie.get_nonstandard_attr("SameSite") == "Lax", "Cookie 是 SameSite=Lax")
            check(cookie.secure, "公网 Host（127.0.0.1 例外）策略下带 Secure")
            st, page, _ = _get(op, base + "/admin?view=system")
            check(st == 200 and "后台管理" in page and "hub 主机" in page, "会话可切换视图")
            # 有会话、无 CSRF 的动作 → 403
            portal.store.apply("bg1sb")
            portal.store.mark_verified("BG1SB", "x")
            st, body, _ = _post(op, base + "/verify", {"callsign": "BG1SB", "evidence": "人工"})
            check(st == 403, "会话但没有 CSRF 的动作被拒")
            csrf = _csrf_from(page)
            st, page2, _ = _post(op, base + "/verify",
                                 {"callsign": "BG1SB", "evidence": "人工核验", "csrf": csrf})
            check(st == 200 and "已核验" in page2, "会话+CSRF 动作成功并回到管理台")
            check(portal.store.get("BG1SB").status == "verified", "状态真的变了")
            check(portal.store.audit()[-1]["actor"] == "ops", "动作审计记下操作者")
            # 登出：无 CSRF → 403；带 CSRF → 会话销毁
            st, _, _ = _post(op, base + "/admin/logout", {})
            check(st == 403, "登出也要 CSRF")
            st, page3, hdr = _post(op, base + "/admin/logout", {"csrf": csrf})
            check(st == 200 and "用户名" in page3, "登出后回到登录页")
            st, page4, _ = _get(op, base + "/admin")
            check(st == 200 and "用户名" in page4, "旧 Cookie 已失效（需要重新登录）")
        finally:
            httpd.shutdown()


def test_token_header_still_works_and_lockout():
    with tempfile.TemporaryDirectory() as td:
        base, portal, httpd = _auth_env(Path(td))
        try:
            op, _ = _opener()
            portal.store.apply("bg1sb")
            portal.store.mark_verified("BG1SB", "x")
            req = urllib.request.Request(base + "/grant",
                                         data=urllib.parse.urlencode({"callsign": "BG1SB"}).encode(),
                                         headers={"X-Portal-Token": "tok"})
            with urllib.request.urlopen(req, timeout=10) as r:
                check(r.status == 200, "令牌请求头路径不回归")
            check(portal.store.audit()[-1]["actor"] == "token", "令牌动作 actor=token")
            # 固定阈值：5 次失败后 429
            for _ in range(5):
                _post(op, base + "/admin/login", {"user": "ops", "password": "nope"})
            st, page, hdr = _post(op, base + "/admin/login", {"user": "ops", "password": "str0ng-pass"})
            check(st == 429, "5 次失败后即使密码正确也被锁")
            check("Retry-After" in hdr, "锁定响应带 Retry-After")
        finally:
            httpd.shutdown()
```

其中 `_csrf_from(page)` 是测试内小工具：

```python
import re


def _csrf_from(page: str) -> str:
    m = re.search(r"name=csrf value='([^']+)'", page) or re.search(r'name=csrf value="([^"]+)"', page)
    if not m:
        raise AssertionError("管理台表单里找不到 csrf 隐藏字段")
    return m.group(1)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_auth.py`
预期：FAIL（登录页没有用户名表单；`make_handler` 不认 `users=` 参数）

- [ ] **步骤 3：实现 `portal/app.py` 接入**

要点（按文件内位置）：

1. 顶部 import 增加：

```python
from http.cookies import SimpleCookie

from portal import htpasswd as hp            # noqa: E402
from portal.sessions import LoginGuard, SessionStore  # noqa: E402

COOKIE_NAME = "mrrc_portal_session"
```

1. `_send` 增加响应头参数：

```python
def _send(self, code: int, payload: dict | str, ctype="application/json; charset=utf-8", headers=None):
    ...
    for k, v in (headers or {}).items():
        self.send_header(k, v)
    self.end_headers()
```

1. `_operator_ok` 收紧为**只认请求头**：

```python
def _operator_ok(self, body: dict | None = None) -> bool:
    """令牌只走请求头：浏览器路径已由会话+CSRF 取代（表单字段不再接受）。"""
    if not token:
        return False
    supplied = (self.headers.get("X-Portal-Token") or "").strip()
    return hmac.compare_digest(supplied, token)
```

1. `make_handler` 签名与闭包新增（旧调用点全部有默认值，不受影响）：

```python
def make_handler(portal: Portal, token: str, base: str = "", *,
                 users: hp.UsersFile | None = None,
                 sessions: SessionStore | None = None,
                 guard: LoginGuard | None = None,
                 sampler=None,
                 cookie_secure: str = "auto"):
    sessions = sessions or SessionStore()
    guard = guard or LoginGuard()
```

1. Handler 新增认证辅助方法：

```python
def _query(self) -> dict:
    from urllib.parse import parse_qs, urlsplit
    return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

def _session(self):
    """→ (sid, Session) 或 (None, None)。"""
    jar = SimpleCookie()
    jar.load(self.headers.get("Cookie") or "")
    morsel = jar.get(COOKIE_NAME)
    if not morsel:
        return None, None
    s = sessions.get(morsel.value)
    return (morsel.value, s) if s else (None, None)

def _cookie_secure(self) -> bool:
    if cookie_secure == "on":
        return True
    if cookie_secure == "off":
        return False
    host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
    return host not in ("127.0.0.1", "localhost", "::1")

def _cookie_header(self, sid: str, max_age: int) -> str:
    parts = [f"{COOKIE_NAME}={sid}", f"Path={base or '/'}", "HttpOnly", "SameSite=Lax",
             f"Max-Age={max_age}"]
    if self._cookie_secure():
        parts.append("Secure")
    return "; ".join(parts)

def _client_ip(self) -> str:
    peer = self.client_address[0] if self.client_address else ""
    if peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        xff = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
        return xff or (self.headers.get("X-Real-IP") or "").strip() or peer
    return peer

def _csrf_ok(self, body: dict, s) -> bool:
    return bool(s) and hmac.compare_digest(str(body.get("csrf") or ""), s.csrf)

def _action_actor(self, body: dict) -> tuple[bool, str]:
    """机器路径（令牌头）或浏览器路径（会话+CSRF）——返回 (通过, actor)。"""
    if self._operator_ok(body):
        return True, "token"
    _, s = self._session()
    if s and self._csrf_ok(body, s):
        return True, s.user
    return False, ""
```

1. 登录页渲染（新增方法）：

```python
def _login_page(self, error: str = "", status: int = 200, retry_after: int = 0):
    note = ("<p><small>账号文件：<code>/etc/mrrc-hub/portal-users</code>（htpasswd，"
            "$apr1$；用 <code>openssl passwd -apr1</code> 生成）。脚本/curl 仍可用 "
            "<code>X-Portal-Token</code> 请求头调用运维动作。</small></p>")
    if retry_after:
        note = (f"<p class=msg>失败次数过多，请 {retry_after} 秒后再试。</p>" + note)
    elif error:
        note = f"<p class=msg>{html.escape(error)}</p>" + note
    body = ("<h1>运维审批</h1>"
            "<form method=post action=admin/login>"
            "<input name=user placeholder=用户名 autocomplete=username autofocus required>"
            "<input type=password name=password placeholder=密码 autocomplete=current-password required>"
            "<button>登录</button></form>" + note)
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return self._send(status, _page("MRRC Portal — 运维登录", body, noindex=True),
                      ctype="text/html; charset=utf-8", headers=headers)
```

1. `do_GET` 中 `/admin` 改为：

```python
if self._route() == "/admin":
    if self._query().get("view") == "admin":       # 兼容旧写法 `/admin?view=admin` 不存在，忽略
        pass
    _, s = self._session()
    if s is None:
        return self._login_page()
    view = self._query().get("view") or "overview"
    return self._send(200, self._admin(view), ctype="text/html; charset=utf-8")
```

1. `do_POST` 增加登录/登出（放在其它路由之前）：

```python
if route == "/admin/login":
    user = str(body.get("user") or "").strip()
    password = str(body.get("password") or "")
    ip = self._client_ip()
    remaining = guard.locked(user, ip)
    if remaining:
        portal.store.record_login("login_locked", user, ip)
        return self._login_page("", status=429, retry_after=remaining)
    ok, reason = (users.verify(user, password) if users
                  else (False, "unreadable: 账号文件未配置"))
    if reason.startswith("unreadable"):
        return self._login_page("账号文件不可读（部署问题，不是密码问题）。", status=503)
    if not ok:
        guard.fail(user, ip)
        portal.store.record_login("login_failed", user, ip)
        return self._login_page("用户名或密码不正确。", status=401)
    guard.success(user, ip)
    sid = sessions.create(user)
    portal.store.record_login("login_ok", user, ip)
    return self._send(303, "", ctype="text/plain; charset=utf-8",
                      headers={"Location": (base or "") + "/admin",
                               "Set-Cookie": self._cookie_header(sid, int(sessions.absolute_seconds))})

if route == "/admin/logout":
    sid, s = self._session()
    if not s or not self._csrf_ok(body, s):
        return self._send(403, {"error": "登出需要会话与 CSRF 令牌"})
    sessions.destroy(sid)
    return self._send(303, "", ctype="text/plain; charset=utf-8",
                      headers={"Location": (base or "") + "/admin",
                               "Set-Cookie": self._cookie_header("", 0)})
```

1. 四个动作的鉴权与 actor（替换原 `if not self._operator_ok(body):`）：

```python
ok, actor = self._action_actor(body)
if not ok:
    return self._send(403, {"error": "运维动作需要会话+CSRF 令牌，或 X-Portal-Token 请求头"})
```

并把动作分派改为带 actor：

```python
result = portal.store.mark_verified(who, body.get("evidence", "人工核验通过"), actor=actor)
result = portal.store.reject(who, body.get("reason", ""), actor=actor)
return self._send(200, portal.grant(who, actor=actor))
result = portal.revoke(who, body.get("reason", ""), actor=actor)
```

 1. `_admin(view, msg="")` 会话化：

```python
def _admin(self, view: str, msg: str = "") -> str:
    """后台管理台：全部服务端渲染；浏览器路径靠会话 Cookie + 表单里的 CSRF 字段。"""
    _, session = self._session()
    csrf_attr = html.escape(session.csrf if session else "")
    def nav(label, target):
        cur = " aria-current=page" if target == view else ""
        return (f"<a class=navlink href='?view={target}'{cur}>{html.escape(label)}</a>")
    def act(route, callsign, label, extra=""):
        return (f"<form method=post action={route} style='display:inline'>"
                f"<input type=hidden name=callsign value='{html.escape(callsign)}'>"
                f"<input type=hidden name=csrf value='{csrf_attr}'>"
                f"<input type=hidden name=view value='{html.escape(view)}'>{extra}"
                f"<button>{html.escape(label)}</button></form>")
    ...
```

页面头部加"当前用户 + 登出"：

```python
who = html.escape(session.user) if session else ""
logout = (f"<form method=post action=admin/logout style='display:inline'>"
          f"<input type=hidden name=csrf value='{csrf_attr}'>"
          f"<button>登出（{who}）</button></form>") if session else ""
...
return _page("MRRC Portal — 后台管理",
             "<h1>呼号自助 — 后台管理</h1>"
             + (f'<p class=msg>{html.escape(msg)}</p>' if msg else '')
             + f"<nav class=nav>{nav('总览','overview')}{nav('申请','applications')}{nav('实例','instances')}{nav('隧道','tunnel')}{nav('系统','system')}{nav('审计','audit')}{nav('呼号库','clublog')}</nav>"
             + f"<div class=who>{logout}</div>"
             + body, noindex=True)
```

> `tunnel` 视图在任务 7 实现；本任务先给一个占位分支 `body = "<h2>隧道</h2><p class=msg>采集器未启用。</p>"`，任务 7 替换为真实渲染。

 1. `_PORTAL_CSS` 增加导航链接与 who 的样式（替换 `.nav form`/`.nav button` 的导航用途；按钮样式仍供动作表单）：

```css
.nav a{display:inline-flex;align-items:center;min-height:44px;padding:.5rem 1rem;font-size:.9rem;
color:var(--tx2);text-decoration:none;border:1px solid var(--bd);border-radius:8px}
.nav a[aria-current=page]{background:var(--tx);border-color:var(--tx);color:#000}
.who{display:flex;justify-content:flex-end;margin:-.4rem 0 .8rem}
```

 1. `main()` 增加参数与接线（本步先加 `--users-file` / `--cookie-secure` / 会话时限，采样器在任务 8）：

```python
ap.add_argument("--users-file", default=os.environ.get("MRRC_PORTAL_USERS",
                                                       "/etc/mrrc-hub/portal-users"))
ap.add_argument("--cookie-secure", choices=("auto", "on", "off"), default="auto")
ap.add_argument("--session-idle-hours", type=float, default=8)
ap.add_argument("--session-max-hours", type=float, default=24)
...
users = hp.UsersFile(args.users_file) if args.users_file else None
httpd = ThreadingHTTPServer((args.host, args.port), make_handler(
    portal, token, base, users=users,
    sessions=SessionStore(args.session_idle_hours * 3600, args.session_max_hours * 3600),
    guard=LoginGuard(), cookie_secure=args.cookie_secure))
```

dry-run 增加一行：`print(f"账号文件={args.users_file}（{'可读' if ... else '不可读'}）")`。

- [ ] **步骤 4：更新 `tests/test_portal.py` 的管理台测试**

1. `test_admin_ui_flow_and_no_csrf_surface` → 改名为 `test_admin_ui_flow_with_sessions_and_csrf`，改为：
   - 起服务时传 `users=ht.UsersFile(...)`（临时账号 `ops`/`pw`，用 `ht.apr1` 生成）；
   - 未登录 GET `/admin` → 200 登录页；无 CSRF 的 `/verify` → 403；
   - 登录（cookie jar）→ GET `/admin?view=...` 逐视图渲染；
   - 动作表单里有 `name=csrf`；带 CSRF 的 `/verify` → 200「已核验」；
   - 令牌请求头动作仍 200（单独一段）。
2. 测试文件顶部加 `import http.cookiejar, re` 与 `from portal import htpasswd as ht`。
3. `test_admin_views_render_the_probe_facts_end_to_end`：`view(name)` 改为先登录再 `GET /admin?view=name`。
4. `test_mobile_*`（第 930 行附近）：`post(view)` 改为登录后的 GET；`pages` 字典加 `"tunnel"`；`need` 字典加 `"tunnel": 1`；aria-current 断言集合加 `"tunnel"`。
5. 审计视图断言：表头新增"操作者"，原有渲染断言相应更新。

- [ ] **步骤 5：运行全部测试验证通过**

运行：`python3 tests/test_portal_auth.py && python3 tests/test_portal.py && python3 tests/test_htpasswd.py`
预期：三份全绿；`test_portal.py` 组数仍为 26+（新增的会话测试在 auth 文件里）

- [ ] **步骤 6：Commit**

```bash
git add portal/app.py tests/test_portal.py tests/test_portal_auth.py
git commit -m "portal: log the admin console in with per-operator accounts and CSRF"

```

---

### 任务 5：隧道指标采集（`portal/metrics.py`）

**文件：**

- 创建：`portal/metrics.py`
- 测试：`tests/test_portal_metrics.py`

- [ ] **步骤 1：编写失败的测试**

```python
#!/usr/bin/env python3
"""portal.metrics 的测试：面板取数、差分速率、探测计时、环形历史与诚实降级。

运行：python3 tests/test_portal_metrics.py   （也兼容 pytest）
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import metrics as mt  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakePanel:
    """可编排的面板替身：每次 fetch 弹出一个预设结果。"""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0] if self.results else (None, "panel down")


def proxy(name, tin, tout, conns=0, today_in=0, today_out=0):
    return {"name": name, "trafficIn": tin, "trafficOut": tout, "curConns": conns,
            "todayTrafficIn": today_in, "todayTrafficOut": today_out}


def test_rates_and_history():
    clock = FakeClock()
    panel = FakePanel([
        ([proxy("a", 1000, 2000, 2, 500, 800)], ""),
        ([proxy("a", 1500, 2600, 3, 900, 1500)], ""),
    ])
    probes = {"a": ("serving", "握手成功", 12.5)}
    s = mt.Sampler(lambda: [("a", 18802)], lambda port, label: probes[label],
                   panel, interval=30.0, history=5, clock=clock, nic_path="/nonexistent")
    s.tick()
    snap = s.snapshot()["labels"]["a"]
    check(snap["last"].in_bps is None, "首轮没有差分 ⇒ 速率不可算（不是 0）")
    check(snap["last"].cur_conns == 2 and snap["last"].today_in == 500, "首轮拿累计值")
    clock.now += 30
    s.tick()
    snap = s.snapshot()["labels"]["a"]
    check(abs(snap["last"].out_bps - (600 * 8 / 30)) < 1e-6, "下行速率 = Δbytes×8/Δt")
    check(abs(snap["last"].in_bps - (500 * 8 / 30)) < 1e-6, "上行速率 = Δbytes×8/Δt")
    check(snap["latency_mean"] == 12.5 and snap["latency_peak"] == 12.5, "延时统计")
    for _ in range(8):
        clock.now += 30
        s.tick()
    check(len(s.samples_for("a")) == 5, "环形历史不超过 maxlen")


def test_counter_reset_and_missing_proxy():
    clock = FakeClock()
    panel = FakePanel([
        ([proxy("a", 5000, 5000)], ""),
        ([proxy("a", 10, 20)], ""),
        ([], ""),
    ])
    s = mt.Sampler(lambda: [("a", 18802), ("b", 18803)],
                   lambda port, label: ("down", "连接被拒", None),
                   panel, interval=30.0, history=10, clock=clock, nic_path="/nonexistent")
    s.tick(); clock.now += 30; s.tick()
    last = s.snapshot()["labels"]["a"]["last"]
    check(last.in_bps is None and "计数器" in last.note, "计数器回绕 ⇒ 速率标空并说明")
    clock.now += 30; s.tick()
    snap = s.snapshot()
    check("frps 里没有这个代理" in snap["labels"]["a"]["last"].note, "代理消失有明确原因")
    check(snap["labels"]["b"]["last"].note.startswith("frps 里没有这个代理"), "缺失代理不冒充 0")
    check(snap["labels"]["b"]["last"].latency_ms is None, "探测失败不编造延时")


def test_panel_and_probe_failures():
    clock = FakeClock()
    panel = FakePanel([(None, "面板不可用：connection refused")])
    s = mt.Sampler(lambda: [("a", 18802)],
                   lambda port, label: ("hollow", "隧道在、后端无应答", None),
                   panel, interval=30.0, history=10, clock=clock, nic_path="/nonexistent")
    s.tick()
    snap = s.snapshot()
    check("面板不可用" in snap["panel_error"], "面板错误原样呈现")
    check(snap["labels"]["a"]["last"].tunnel_state == "hollow", "探测结论保留")
    check(snap["nic"]["note"] == "本平台不适用", "/proc/net/dev 缺失 ⇒ 明确标注")


def test_frps_panel_credentials_parsing():
    with tempfile.TemporaryDirectory() as td:
        cred = Path(td) / "frps-web.credentials"
        cred.write_text("portal:secret42\n", encoding="utf-8")
        panel = mt.FrpsPanel("http://127.0.0.1:7100", cred)
        check(panel._credentials() == ("portal", "secret42"), "凭据文件 user:password 解析")
        cred.unlink()
        check(panel._credentials() is None, "凭据缺失返回 None（不炸）")
        _, reason = panel.fetch()
        check(reason.startswith("凭据不可读"), "fetch 对凭据缺失给可读原因")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ metrics 测试通过（{len(tests)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_metrics.py`
预期：`ModuleNotFoundError: No module named 'portal.metrics'`

- [ ] **步骤 3：实现 `portal/metrics.py`**

```python
"""frps 面板统计的采集与内存历史（纯标准库）。

数据源：hub 上 frps 的 webServer 面板（只绑 127.0.0.1，Basic 认证），
`GET /api/proxy/tcp` 一次取回全部代理的 trafficIn/Out、todayTrafficIn/Out、curConns。
frps 给的是**累计值** ⇒ 带宽是两次采样的差分；历史只存内存（重启即清），
默认 30s × 120 ≈ 1 小时。

诚实降级：拿不到就给可读原因，绝不用 0 冒充（与 app.py 探测器的姿态一致）。
字段名按 frp 0.71 的 dashboard API；拿不到或类型不符时标空并说明 —— 部署时用
`curl` 对照真响应（部署检查单里列了这一步）。
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Sample:
    at: float
    latency_ms: float | None = None
    tunnel_state: str | None = None
    tunnel_detail: str = ""
    in_bps: float | None = None
    out_bps: float | None = None
    cur_conns: int | None = None
    today_in: int | None = None
    today_out: int | None = None
    note: str = ""


class FrpsPanel:
    def __init__(self, url: str = "http://127.0.0.1:7100",
                 credentials_path="/etc/mrrc-hub/frps-web.credentials",
                 timeout: float = 3.0, opener=urllib.request.urlopen):
        self.url = url.rstrip("/")
        self.credentials_path = Path(credentials_path)
        self.timeout = timeout
        self._opener = opener

    def _credentials(self):
        try:
            text = self.credentials_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        user, sep, password = text.partition(":")
        return (user, password) if sep and user else None

    def fetch(self) -> tuple[list | None, str]:
        creds = self._credentials()
        if creds is None:
            return None, f"凭据不可读：{self.credentials_path}"
        token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
        req = urllib.request.Request(self.url + "/api/proxy/tcp",
                                     headers={"Authorization": f"Basic {token}"})
        try:
            with self._opener(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return None, "面板凭据错误"
            return None, f"面板不可用：HTTP {exc.code}"
        except Exception as exc:                       # noqa: BLE001 — 采集器不许把服务带崩
            return None, f"面板不可用：{exc}"
        if not isinstance(data, list):
            return None, "面板应答不是代理列表（字段名可能随版本变化）"
        return data, ""


class Sampler:
    """后台采样线程：面板取数（差分算速率）+ 隧道探测计时（复用 app 的探测函数）。"""

    def __init__(self, entries, probe, panel: FrpsPanel, *, interval: float = 30.0,
                 history: int = 120, clock=time.time, nic_path: str = "/proc/net/dev"):
        self._entries = entries              # () -> [(label, port)]
        self._probe = probe                  # (port, label) -> (state, detail, latency_ms|None)
        self._panel = panel
        self.interval = float(interval)
        self._history = int(history)
        self._clock = clock
        self._nic_path = Path(nic_path)
        self._samples: dict[str, deque] = {}
        self._prev: dict[str, tuple] = {}    # label -> (at, trafficIn, trafficOut)
        self._panel_error = ""
        self._panel_at: float | None = None
        self._nic_prev: tuple | None = None
        self._nic_rates: dict | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 采集 ----
    def tick(self) -> None:
        now = self._clock()
        entries = list(self._entries())
        proxies, panel_error = self._panel.fetch()
        by_name = {str(p.get("name")): p for p in (proxies or []) if isinstance(p, dict)}
        fresh: dict[str, Sample] = {}
        for label, port in entries:
            sample = Sample(at=now)
            state, detail, latency = self._probe(port, label)
            sample.tunnel_state, sample.tunnel_detail = state, detail
            sample.latency_ms = latency
            p = by_name.get(label)
            if p is None:
                sample.note = "frps 里没有这个代理（租户隧道未连）"
            else:
                tin, tout = p.get("trafficIn"), p.get("trafficOut")
                if isinstance(tin, int) and isinstance(tout, int):
                    prev = self._prev.get(label)
                    if prev is None:
                        sample.note = "首轮采样（速率自下一轮起可算）"
                    else:
                        prev_at, p_in, p_out = prev
                        dt = now - prev_at
                        if dt > 0 and tin >= p_in and tout >= p_out:
                            sample.in_bps = (tin - p_in) * 8 / dt
                            sample.out_bps = (tout - p_out) * 8 / dt
                        else:
                            sample.note = "计数器回绕/重置，本轮速率不可算"
                    self._prev[label] = (now, tin, tout)
                else:
                    sample.note = "面板未给出该字段（版本差异）"
                if isinstance(p.get("curConns"), int):
                    sample.cur_conns = p["curConns"]
                if isinstance(p.get("todayTrafficIn"), int):
                    sample.today_in = p["todayTrafficIn"]
                if isinstance(p.get("todayTrafficOut"), int):
                    sample.today_out = p["todayTrafficOut"]
            fresh[label] = sample
        nic = self._nic_tick(now)
        with self._lock:
            self._panel_error = panel_error
            if proxies is not None:
                self._panel_at = now
            if nic is not None:
                self._nic_rates = nic
            for label, sample in fresh.items():
                self._samples.setdefault(label, deque(maxlen=self._history)).append(sample)

    def _nic_tick(self, now: float) -> dict | None:
        try:
            total = [0, 0]
            for line in self._nic_path.read_text().splitlines()[2:]:
                name, _, rest = line.partition(":")
                if name.strip() == "lo":
                    continue
                fields = rest.split()
                total[0] += int(fields[0])
                total[1] += int(fields[8])
        except (OSError, IndexError, ValueError):
            return {"note": "本平台不适用"}
        rates = None
        if self._nic_prev is not None:
            prev_at, prx, ptx = self._nic_prev
            dt = now - prev_at
            if dt > 0 and total[0] >= prx and total[1] >= ptx:
                rates = {"rx_bps": (total[0] - prx) * 8 / dt,
                         "tx_bps": (total[1] - ptx) * 8 / dt}
        self._nic_prev = (now, total[0], total[1])
        return rates or {"note": "首轮采样（速率自下一轮起可算）"}

    # ---- 读取 ----
    def samples_for(self, label: str) -> list:
        with self._lock:
            return list(self._samples.get(label, ()))

    def snapshot(self) -> dict:
        now = self._clock()
        with self._lock:
            labels = {}
            for label, q in self._samples.items():
                last = q[-1]
                lats = [s.latency_ms for s in q if s.latency_ms is not None]
                ins = [s.in_bps for s in q if s.in_bps is not None]
                outs = [s.out_bps for s in q if s.out_bps is not None]
                labels[label] = {
                    "last": last,
                    "stale_s": max(0.0, now - last.at),
                    "latency_mean": (sum(lats) / len(lats)) if lats else None,
                    "latency_peak": max(lats) if lats else None,
                    "in_mean": (sum(ins) / len(ins)) if ins else None,
                    "out_mean": (sum(outs) / len(outs)) if outs else None,
                }
            return {"labels": labels, "panel_error": self._panel_error,
                    "panel_age": (now - self._panel_at) if self._panel_at else None,
                    "nic": self._nic_rates, "interval": self.interval}

    # ---- 线程 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        def loop():
            self.tick()
            while not self._stop.wait(self.interval):
                self.tick()
        self._thread = threading.Thread(target=loop, name="portal-metrics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_metrics.py`
预期：`✅ metrics 测试通过（4 组）`

- [ ] **步骤 5：Commit**

```bash
git add portal/metrics.py tests/test_portal_metrics.py
git commit -m "portal: sample frps panel traffic and tunnel latency into an in-memory history"
```

---

### 任务 6：「隧道」视图与系统/总览渲染

**文件：**

- 修改：`portal/app.py`（格式化助手 + `view == "tunnel"` 分支 + 系统页③ + 总览摘要）
- 测试：`tests/test_portal_metrics.py`（追加端到端渲染测试）

- [ ] **步骤 1：编写失败的测试**（追加到 `tests/test_portal_metrics.py`）

```python
def test_tunnel_view_renders_end_to_end():
    """假采样器 → 登录后的管理台真的把延时/带宽拼对了吗（延续 V0.24 的拼接教训）。"""
    import http.cookiejar
    import threading
    import urllib.parse
    import urllib.request
    from http.server import ThreadingHTTPServer

    from portal import htpasswd as ht
    from portal import registry as reg
    from portal import sessions as sess
    from portal.app import Portal, make_handler
    from portal.store import Store
    from portal.verify import CallsignListVerifier

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "callsigns.txt").write_text("NOBODY\n", encoding="utf-8")
        (tmp / "instances.tsv").write_text("bg1sb\t18802\n", encoding="utf-8")
        (tmp / "portal-users").write_text(
            "ops:" + ht.apr1("str0ng-pass", "saltward") + "\n", encoding="utf-8")
        portal = Portal(Store(tmp / "portal.json"), reg.Registry(tmp / "instances.tsv"),
                        CallsignListVerifier(tmp / "callsigns.txt"))
        clock = FakeClock()
        panel = FakePanel([([proxy("bg1sb", 0, 0, 4, 2_000_000, 7_000_000)], "")])
        s = mt.Sampler(lambda: [("bg1sb", 18802)],
                       lambda port, label: ("serving", "握手成功", 23.4),
                       panel, interval=30.0, history=10, clock=clock, nic_path="/nonexistent")
        s.tick()
        clock.now += 30
        s.tick()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            portal, token="tok", users=ht.UsersFile(tmp / "portal-users"),
            sessions=sess.SessionStore(), guard=sess.LoginGuard(), sampler=s))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            opener.open(base + "/admin/login",
                        data=urllib.parse.urlencode({"user": "ops", "password": "str0ng-pass"}).encode(),
                        timeout=10)
            with opener.open(base + "/admin?view=tunnel", timeout=10) as r:
                page = r.read().decode()
            for needle, why in (("隧道", "视图标题"),
                                ("bg1sb", "实例标签"),
                                ("23.4", "延时数值"),
                                ("在线", "隧道四态文案"),
                                ("4", "当前连接数"),
                                ("首轮采样", "采集器状态说明")):
                check(needle in page, f"隧道视图渲染出{why}")
        finally:
            httpd.shutdown()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_metrics.py`
预期：FAIL（隧道视图还是任务 4 的占位文案；`make_handler` 还不认 `sampler=`）

- [ ] **步骤 3：实现渲染**

1. 格式化助手（`portal/app.py` 模块级，便于单测与复用）：

```python
def _fmt_bps(value) -> str:
    if value is None:
        return "—"
    if value < 1000:
        return f"{value:.0f} bps"
    if value < 1_000_000:
        return f"{value / 1000:.1f} kbps"
    return f"{value / 1_000_000:.2f} Mbps"


def _fmt_bytes(value) -> str:
    if value is None:
        return "—"
    if value < 1024:
        return f"{value} B"
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KiB"
    if value < 1024 ** 3:
        return f"{value / 1024 ** 2:.1f} MiB"
    return f"{value / 1024 ** 3:.2f} GiB"


def _ago(seconds) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{int(seconds)}s 前"
    if seconds < 5400:
        return f"{int(seconds / 60)}m 前"
    return f"{seconds / 3600:.1f}h 前"
```

1. `_admin` 中 `view == "tunnel"` 分支：

```python
elif view == "tunnel":
    def perf_cell(snap):
        last = snap["last"]
        lat = "—"
        if last.latency_ms is not None:
            lat = (f"{last.latency_ms:.0f} ms"
                   f"<br><small>均值 {snap['latency_mean']:.0f} · 峰值 {snap['latency_peak']:.0f}</small>")
        elif last.tunnel_state:
            lat = f"<small>{html.escape(TUNNEL_TEXT.get(last.tunnel_state, last.tunnel_state))}</small>"
        bw = (f"↓ {_fmt_bps(last.out_bps)} / ↑ {_fmt_bps(last.in_bps)}"
              f"<br><small>均值 ↓ {_fmt_bps(snap['out_mean'])} / ↑ {_fmt_bps(snap['in_mean'])}</small>")
        traffic = (f"↓ {_fmt_bytes(last.today_out)}<br>↑ {_fmt_bytes(last.today_in)}")
        conns = "—" if last.cur_conns is None else str(last.cur_conns)
        fresh = _ago(snap["stale_s"])
        note = f"<br><small>{html.escape(last.note)}</small>" if last.note else ""
        return lat, bw, traffic, conns, f"{fresh}{note}", last.tunnel_state
    if sampler is None:
        body = ("<h2>隧道</h2><p class=msg>采集器未启用（--metrics-interval 0 或 dry-run）。"
                "延时与带宽需要后台采样线程。</p>")
    else:
        snap = sampler.snapshot()
        entries_now = registry.entries()
        rows = []
        for label, port in sorted(entries_now):
            item = snap["labels"].get(label)
            if item is None:
                rows.append(trow(("标签", f"<code>{html.escape(label)}</code>"),
                                 ("隧道", "<small>首轮采样中…</small>"),
                                 ("延时", "—"), ("带宽", "—"), ("今日流量", "—"),
                                 ("连接数", "—"), ("采样", "—")))
                continue
            lat, bw, traffic, conns, fresh, state = perf_cell(item)
            pill = (f"<span class='pill {TUNNEL_PILL[state]}'>"
                    f"{html.escape(TUNNEL_TEXT[state])}</span>") if state in TUNNEL_PILL else "—"
            rows.append(trow(("标签", f"<code>{html.escape(label)}</code>"),
                             ("隧道", pill), ("延时", lat), ("带宽", bw),
                             ("今日流量", traffic), ("连接数", conns), ("采样", fresh)))
        body = ("<h2>隧道</h2><table class=stack><tr><th>标签</th><th>隧道</th><th>延时</th>"
                "<th>带宽（↓下行/↑上行）</th><th>今日流量</th><th>连接数</th><th>采样</th></tr>"
                + ("".join(rows) or "<tr><td colspan=7>（注册表为空）</td></tr>") + "</table>"
                + (f"<p><small>⚠️ {html.escape(snap['panel_error'])}</small></p>"
                   if snap["panel_error"] else "")
                + "<p><small>带宽来自 frps 面板的累计字节差分，30 s 一轮；历史只存内存、重启即清。"
                "拿不到一律如实标注，不用 0 冒充。</small></p>")
```

1. 系统页③追加面板聚合（在现有隧道层表格后）：

```python
if sampler is not None:
    snap = sampler.snapshot()
    panel_line = ("可用" if not snap["panel_error"]
                  else f"<b>{html.escape(snap['panel_error'])}</b>")
    agg_in = agg_out = 0.0
    have = False
    for item in snap["labels"].values():
        if item["last"].in_bps is not None:
            agg_in += item["last"].in_bps; agg_out += item["last"].out_bps; have = True
    nic = snap["nic"] or {}
    nic_line = (f"↓ {_fmt_bps(nic.get('rx_bps'))} / ↑ {_fmt_bps(nic.get('tx_bps'))}"
                if "rx_bps" in nic else html.escape(nic.get("note", "—")))
    rows_extra = (
        f"<tr><td>frps 面板</td><td>{panel_line}"
        f"{'（' + _ago(snap['panel_age']) + '）' if snap['panel_age'] is not None else ''}</td></tr>"
        f"<tr><td>全代理合计速率</td><td>{'↓ ' + _fmt_bps(agg_out) + ' / ↑ ' + _fmt_bps(agg_in) if have else '（本轮不可算）'}</td></tr>"
        f"<tr><td>hub 网卡</td><td>{nic_line}</td></tr>")
```

1. 总览页摘要：在注册表实例行追加：

```python
tunnel_summary = ""
if sampler is not None:
    snap = sampler.snapshot()
    lats = [i["last"].latency_ms for i in snap["labels"].values() if i["last"].latency_ms is not None]
    outs = [i["last"].out_bps for i in snap["labels"].values() if i["last"].out_bps is not None]
    tunnel_summary = (f"（延时均值 {sum(lats) / len(lats):.0f} ms；"
                      f"出带宽 {_fmt_bps(sum(outs))}）" if lats and outs else
                      f"（{html.escape(snap['panel_error'])}）" if snap["panel_error"] else "")
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_metrics.py && python3 tests/test_portal.py`
预期：全绿；移动端测试对 `tunnel` 视图的 stack/aria-current 断言通过

- [ ] **步骤 5：Commit**

```bash
git add portal/app.py tests/test_portal_metrics.py
git commit -m "portal: render per-instance tunnel latency and bandwidth from the sampler"
```

---

### 任务 7：main() 采样器接线与参数

**文件：**

- 修改：`portal/app.py`（`main()`）
- 测试：`tests/test_portal_metrics.py`（追加接线单测）

- [ ] **步骤 1：编写失败的测试**（追加）

```python
def test_probe_timed_wraps_state_and_ms():
    """app._probe_timed：成功给毫秒；异常也不炸。"""
    from portal import app as app_mod
    state, detail, ms = app_mod._probe_timed(1, "unused", timeout=0.05)
    check(state in ("down", "hollow", "plain-http", "serving"), "异常/拒绝连接也有四态结论")
    check(ms is None or ms >= 0, "延时要么是数值要么是 None")


def test_main_dry_run_offers_flags(capsys=None):
    from portal import app as app_mod
    import io, contextlib
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "callsigns.txt").write_text("", encoding="utf-8")
        ret = None
        with contextlib.redirect_stdout(buf):
            ret = app_mod.main(["--dry-run", "--users-file", str(tmp / "none"),
                                "--store", str(tmp / "portal.json"),
                                "--registry", str(tmp / "instances.tsv"),
                                "--callsign-db", str(tmp / "callsigns.txt")])
        out = buf.getvalue()
    check(ret == 0 and "--users-file" not in out, "dry-run 正常退出")
    check("账号文件" in out, "dry-run 报告账号文件状态")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 tests/test_portal_metrics.py`
预期：FAIL（`_probe_timed` 不存在；dry-run 没打账号文件）

- [ ] **步骤 3：实现**

1. 在 `_tunnel_state` 附近加计时包装：

```python
def _probe_timed(port, label: str = "", timeout: float = 2.5) -> tuple:
    """采样器用的探测：复用四态判据，顺带把端到端耗时量出来。

    延时只在握手真正完成（serving）时给值 —— 连不上的等待时间不是网络延时，
    把它当延时展示是编数据（诚实降级原则）。
    """
    start = time.monotonic()
    try:
        state, detail = _tunnel_state(port, label, timeout)
    except Exception as exc:                          # noqa: BLE001 — 采集器不许把服务带崩
        return TUNNEL_DOWN, f"探测异常：{exc}", None
    elapsed = (time.monotonic() - start) * 1000.0
    return state, detail, (elapsed if state == TUNNEL_SERVING else None)
```

1. `main()` 增加参数：

```python
ap.add_argument("--frps-api-url", default=os.environ.get("MRRC_PORTAL_FRPS_API",
                                                         "http://127.0.0.1:7100"))
ap.add_argument("--frps-credentials",
                default=os.environ.get("MRRC_PORTAL_FRPS_CREDENTIALS",
                                       "/etc/mrrc-hub/frps-web.credentials"))
ap.add_argument("--metrics-interval", type=float, default=30.0,
                help="采样间隔秒；0 = 关闭采集器")
ap.add_argument("--metrics-history", type=int, default=120)
```

1. 启动接线（`httpd = ...` 之前）：

```python
sampler = None
if not args.dry_run and args.metrics_interval > 0:
    from portal import metrics as metrics_mod
    sampler = metrics_mod.Sampler(
        entries=lambda: portal.registry.entries(),
        probe=lambda port, label: _probe_timed(port, label),
        panel=metrics_mod.FrpsPanel(args.frps_api_url, args.frps_credentials),
        interval=args.metrics_interval, history=args.metrics_history)
    sampler.start()
```

1. dry-run 输出补两行：

```python
users_line = "未配置"
if users:
    _u, _err = users.read() if hasattr(users, "read") else (None, "")
    users_line = "可读" if not _err else _err
    # 说明：UsersFile.read() 返回 (users, error)。若实现里没有 read()，
    # 就用 verify 的 unreadable 分支探测；实现时二者取其一，保持 dry-run 只做只读探测。
print(f"账号文件={args.users_file}（{users_line}）")
print(f"frps 面板={args.frps_api_url} 凭据={args.frps_credentials}"
      f"{'（采集器关闭）' if args.metrics_interval <= 0 else ''}")
```

> 实现提示：`UsersFile` 在任务 1 里只有 `verify()`；dry-run 用
> `ok, reason = users.verify("", "")` 探测读盘是否可用（不可读时 reason 以
> `unreadable` 开头），避免为一个诊断输出新增 API。

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 tests/test_portal_metrics.py && python3 tests/test_portal_auth.py && python3 tests/test_portal.py`
预期：全绿

- [ ] **步骤 5：Commit**

```bash
git add portal/app.py tests/test_portal_metrics.py
git commit -m "portal: wire the metrics sampler and admin auth flags into main()"
```

---

### 任务 8：部署脚本与文档同步

**文件：**

- 修改：`deploy/bootstrap-hub.sh`、`deploy/README.md`、`portal/README.md`
- 修改：`SDD/10-service-model.md`、`SDD/11-component-model.md`、`SDD/12-operational-model.md`、`SDD/14-version-history.md`、`SDD/README.md`

- [ ] **步骤 1：`deploy/bootstrap-hub.sh`**

1. frps.toml heredoc 增加面板段（`$(cat ...)` 由 root 读同一批文件）：

```bash
# —— 面板：只绑回环，供 portal 读每代理统计（trafficIn/Out、curConns）。
# 不给外网开面：nginx 不代理它，凭据文件 0640 root:mrrcportal。
if [[ ! -s /etc/mrrc-hub/frps-web.credentials ]]; then
    install -d -m 755 /etc/mrrc-hub
    printf 'portal:%s\n' "$(openssl rand -hex 24)" >/etc/mrrc-hub/frps-web.credentials
    chmod 640 /etc/mrrc-hub/frps-web.credentials
    if id -u mrrcportal >/dev/null 2>&1; then
        chown root:mrrcportal /etc/mrrc-hub/frps-web.credentials
    else
        echo "⚠️ 用户 mrrcportal 不存在：面板凭据先留 root:root，portal 会如实报「凭据不可读」" >&2
    fi
fi
FRPS_WEB_USER="$(cut -d: -f1 /etc/mrrc-hub/frps-web.credentials)"
FRPS_WEB_PASS="$(cut -d: -f2- /etc/mrrc-hub/frps-web.credentials)"
```

并在 heredoc 里加：

```toml
webServer.addr = "127.0.0.1"
webServer.port = 7100
webServer.user = "${FRPS_WEB_USER}"
webServer.password = "${FRPS_WEB_PASS}"
```

1. frps.service 单元增加：

```ini
ExecReload=/bin/kill -HUP $MAINPID
```

1. 账号文件占位（**不覆盖**已有）：

```bash
if [[ ! -e /etc/mrrc-hub/portal-users ]]; then
    install -m 640 /dev/null /etc/mrrc-hub/portal-users
    if id -u mrrcportal >/dev/null 2>&1; then
        chown root:mrrcportal /etc/mrrc-hub/portal-users
    fi
    echo "==> 已建空账号文件 /etc/mrrc-hub/portal-users；加账号："
    echo "    printf '%s:%s\\n' <用户名> \"\$(openssl passwd -apr1)\" | sudo tee -a /etc/mrrc-hub/portal-users"
fi
```

- [ ] **步骤 2：`deploy/README.md` 增补**

新小节"后台管理台账号与 frps 面板"：账号文件格式与生成命令、`$apr1$` 取舍、frps 面板端口/凭据/`systemctl reload frps`、nginx 必须透传 `X-Forwarded-For`/`X-Real-IP`（否则 IP 锁定退化为全局桶）、`curl` 核对面板真响应（部署检查单第 1/2 条来自规格 §2.2）。

- [ ] **步骤 3：`portal/README.md` 更新**

路由表（含 `/admin/login`、`/admin/logout`）、会话/Cookie/CSRF/锁定参数、`X-Portal-Token` 仅请求头、新「隧道」视图与数据源、新增 CLI 参数表。

- [ ] **步骤 4：SDD 同步**

| 文件 | 条目 |
| --- | --- |
| `SDD/10-service-model.md` | 运维动作传令方式：会话+CSRF 或令牌请求头（删"浏览器用表单同名字段"） |
| `SDD/11-component-model.md` | Portal 组件描述加 `htpasswd.py`/`sessions.py`/`metrics.py` 三模块 |
| `SDD/12-operational-model.md` | §12.9：账号文件、Cookie 策略、锁定、frps 面板、采样器与部署检查单；§12.8 若提到"frps 每代理统计不可得"就地更正为"已开回环面板" |
| `SDD/14-version-history.md` | 新版本条目：动机（多运维归因 + 隧道性能可观测）、实现边界（内存历史、apr1 取舍、用户名可被恶意锁定）、测试数、部署步骤 |
| `SDD/README.md` | 版本号 bump（V0.24 → V0.25），能力表补"后台管理台账号体系 + 隧道性能指标" |

- [ ] **步骤 5：约束检查与全量测试**

```bash
cd mrrc_hub
python3 .agents/skills/sdd-guardian/harness/sdd_context.py check portal/app.py portal/htpasswd.py portal/sessions.py portal/metrics.py portal/store.py tests/test_portal.py tests/test_portal_auth.py tests/test_portal_metrics.py deploy/bootstrap-hub.sh
python3 tests/test_htpasswd.py && python3 tests/test_portal_auth.py && python3 tests/test_portal_metrics.py && python3 tests/test_portal.py
```

预期：`clean`；四份测试全绿

- [ ] **步骤 6：Commit**

```bash
git add deploy/bootstrap-hub.sh deploy/README.md portal/README.md SDD/10-service-model.md SDD/11-component-model.md SDD/12-operational-model.md SDD/14-version-history.md SDD/README.md
git commit -m "docs+deploy: portal accounts, frps panel, and the tunnel metrics collection"
```

---

### 任务 9：端到端验收（本地能做的部分）

**文件：** 无（只跑检查）

- [ ] **步骤 1：本机起服走一遍真登录**

```bash
python3 -m portal.app --store /tmp/portal-e2e/portal.json --registry /tmp/portal-e2e/instances.tsv \
    --callsign-db /tmp/portal-e2e/callsigns.txt --users-file /tmp/portal-e2e/portal-users \
    --port 8891 --cookie-secure off &
# 另开：printf 'ops:%s\n' "$(openssl passwd -apr1)" > /tmp/portal-e2e/portal-users
# curl -i -c /tmp/jar -d 'user=ops&password=...' http://127.0.0.1:8891/admin/login   → 303 + Set-Cookie
# curl -s -b /tmp/jar 'http://127.0.0.1:8891/admin?view=tunnel'                     → 200 隧道视图
```

预期：Cookie 带 `HttpOnly; SameSite=Lax`（`--cookie-secure off` 时无 Secure，仅本地测试用）；隧道视图显示"采集器未启用"或面板降级原因，不显示 0。

- [ ] **步骤 2：核对规格验收判据**

逐条对 `specs/2026-10-05-...-design.md` §9 AC-1 ~ AC-10；hub 侧相关（AC-4/6/7 的现网部分）留待部署后由运维执行，列出未验证项。

- [ ] **步骤 3：最终提交（如有剩余改动）**

```bash
git status --short
git add -A && git commit -m "portal: end-to-end verification notes for admin auth and tunnel metrics"
```

---

## 自检记录（写计划时执行）

1. **规格覆盖度**：§3→任务 1/2/4，§4→任务 5/6/7，§5→任务 6，§6→任务 3/4，§7→任务 1/2/4/5/6，§8→任务 8，§9→任务 9。无遗漏。
2. **占位符扫描**：无"待定/TODO"；每个代码步骤都有完整代码。
3. **类型一致性**：`Sample` 字段（`in_bps/out_bps/latency_ms/tunnel_state/note`）在采集器、渲染、测试三处命名一致；`UsersFile.verify` 返回 `(bool, reason)` 在 dry-run 与登录两处一致；`_probe_timed` 返回三元组与 `Sampler(probe=...)` 的调用约定一致；`SessionStore/Session.csrf` 在 app 与测试间一致。

已知实现期需现场核验的点（规格 §2.2）：frps 0.71 面板字段真名、SIGHUP 是否生效、hub 上 nginx 是否透传来源 IP、portal unit 的 ExecStart 现状。
