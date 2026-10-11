"""申请、核验与授予的状态机 + 追加式审计（UC-H10 的主干）。

状态流转（每一步都写审计）：

    applied ──verify──▶ verified ──grant──▶ granted
       │                   │                  │
       └──reject──▶ rejected└──reject──▶ rejected        granted ──revoke──▶ revoked

**硬性安全前置**：`grant()` 只接受 `verified` 的申请。这不是约定，是断言 ——
呼号是公开标识、入口可枚举，所以在核验之前给出任何访问权都等于把真实持照者的
身份交给任何会打字的人（详见 `callsign.py` 顶部的论证）。
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

APPLIED, VERIFIED, REJECTED, GRANTED, REVOKED = "applied", "verified", "rejected", "granted", "revoked"


#: 协助窗口的状态。`pending` = 门户已分配端口、等实例把代理挂上；`open` = 心跳在走。
HELP_PENDING, HELP_OPEN, HELP_CLOSED = "pending", "open", "closed"

#: 心跳消失多久算这个窗口已死。比实例的 20 秒心跳宽得多：一次网络抖动不该让门户
#: 把端口判死并回收（那时 frpc 那边还占着它，回收就等于把这个端口发给下一个客户）。
HELP_STALE_SECONDS = 300

#: 协助窗口的上限（分钟）。与实例侧的 help_session.MAX_WINDOW_MINUTES 同值：
#: 两边都夹一次，因为一边被改动时另一边不该跟着松开。
HELP_MAX_MINUTES = 180


@dataclass
class HelpSession:
    """一次远程协助在门户这边的记录。

    **没有口令字段，而且这是有意的**：门户不是口令的保管人——客户开了窗口之后，口令
    只存在于他的应用进程内存里，由他口头/短信告诉支持者。一个不存在的字段，也就不会
    出现在日志、页面、备份或某次取证里（设计 §4.3）。
    """
    callsign: str
    port: int
    username: str = ""
    state: str = HELP_PENDING
    started_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    last_heartbeat: float = 0.0
    connections: int = 0
    closed_reason: str = ""
    #: 运维按下「强制结束」后置位，由下一次心跳读走——实例方向是唯一的既有通道，
    #: 门户没有反向连接可用（设计 §4.3）。
    revoke: bool = False


@dataclass
class Application:
    callsign: str
    contact: str = ""
    product: str = ""
    status: str = APPLIED
    evidence: str = ""
    label: str = ""
    port: int = 0
    enroll_secret: str = ""      # 一次性登记口令：实例凭它提交自签证书（见 app.py 的 /enroll）
    #: 申请方凭它查询自己这条申请的状态（应用在设置里申请后保存它；不进 URL，走 POST 体）。
    #: 它只够读**自己**这条申请，拿不到别人的，也改不了任何状态。
    request_token: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list = field(default_factory=list)

    def touch(self, event: str, detail: str = "") -> None:
        self.updated_at = time.time()
        self.history.append({"at": self.updated_at, "event": event, "detail": detail})


class Store:
    """单文件 JSON 存储（原子写）。

    规模假设：这是给几百套实例、单个维护者用的内部 Portal，不是多写并发的服务。
    因此用"读-改-写 + 原子替换"就够了；真要并发，加锁也在这一层。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ---- 读写 ----
    def _load(self) -> dict:
        if not self.path.exists():
            # 新库的骨架要与"文件已存在"那条路径**同一形状**：少了 help 这个键，
            # 第一条协助记录就会 KeyError（2026-10-12 被测试抓到）。
            return {"applications": {}, "audit": [], "help": {}}
        with self.path.open(encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as exc:
                # 不按“空库”继续：那会把损坏错报成“没有申请”，乃至被下一次写入覆盖。
                raise RuntimeError(f"portal 存储损坏，拒绝当作空库：{self.path}: {exc}") from exc
        data.setdefault("applications", {})
        data.setdefault("audit", [])
        data.setdefault("help", {})
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    def _audit(self, data: dict, callsign: str, event: str, detail: str = "", actor: str = "") -> None:
        data["audit"].append({"at": time.time(), "callsign": callsign, "event": event,
                              "detail": detail, "actor": actor})

    def record_login(self, event: str, user: str, ip: str) -> None:
        """登录事件（login_ok / login_failed / login_locked）——没有呼号，actor = 尝试的用户名。

        长度封顶：用户名与来源 IP 都来自请求，不能任由超长字符串把审计文件撑大。
        """
        data = self._load()
        self._audit(data, "", event, f"user={user[:40]} ip={ip[:45]}", actor=user[:40])
        self._save(data)

    # ---- 远程协助（call help）----
    def help_get(self, callsign: str) -> HelpSession | None:
        raw = self._load()["help"].get(callsign)
        return HelpSession(**raw) if raw else None

    def help_all(self) -> dict:
        """{callsign: 记录字典} —— 视图与清单都要一份全量。"""
        return dict(self._load()["help"])

    def help_put(self, session: HelpSession, event: str = "", detail: str = "",
                 actor: str = "") -> HelpSession:
        data = self._load()
        data["help"][session.callsign] = asdict(session)
        if event:
            self._audit(data, session.callsign, event, detail, actor=actor)
        self._save(data)
        return session

    def help_expire_stale(self, now: float | None = None,
                          grace: float = HELP_STALE_SECONDS) -> list[str]:
        """把心跳断了超过 grace 的窗口标成关闭，返回被动关闭的那些呼号。

        不回收端口以外的任何东西：端口在这里才真正可用（这条记录是它的唯一占用者），
        而释放得晚一点只会让下一个请求多等一次——释放早了却会把端口发给别人，
        而 frpc 那边还挂着它（2026-10-11 的端口互踩事故就是这么来的）。
        """
        now = time.time() if now is None else now
        data = self._load()
        closed = []
        for callsign, raw in list(data["help"].items()):
            if raw.get("state") == HELP_CLOSED:
                continue
            last = float(raw.get("last_heartbeat") or raw.get("started_at") or 0)
            if now - last <= grace:
                continue
            raw["state"] = HELP_CLOSED
            raw["closed_reason"] = "heartbeat_lost"
            data["help"][callsign] = raw
            self._audit(data, callsign, "help_closed", "heartbeat_lost")
            closed.append(callsign)
        if closed:
            self._save(data)
        return closed

    # ---- 用例 ----
    def get(self, callsign: str) -> Application | None:
        raw = self._load()["applications"].get(callsign)
        return Application(**raw) if raw else None

    def apply(self, callsign: str, contact: str = "", product: str = "") -> Application:
        """规范化后已由调用方完成；这里只做**查重**。

        同一个规范化呼号已有记录时**绝不静默覆盖** —— 这是 UC-H10 的异常分支：
        呼号已被绑定要走申诉/转移，而不是被第二个申请人顶掉。
        """
        data = self._load()
        existing = data["applications"].get(callsign)
        if existing and existing["status"] in (APPLIED, VERIFIED, GRANTED):
            raise ValueError(f"{callsign} 已存在申请（状态 {existing['status']}），走申诉/转移流程")
        app = Application(callsign=callsign, contact=contact, product=product,
                        request_token=secrets.token_urlsafe(24))
        app.touch("applied", f"contact={contact!r} product={product!r}")
        data["applications"][callsign] = asdict(app)
        self._audit(data, callsign, "applied", f"product={product!r}")
        self._save(data)
        return app

    def mark_verified(self, callsign: str, evidence: str, actor: str = "") -> Application:
        return self._transition(callsign, VERIFIED, evidence, {APPLIED}, actor=actor)

    def reject(self, callsign: str, reason: str, actor: str = "") -> Application:
        return self._transition(callsign, REJECTED, reason, {APPLIED, VERIFIED}, actor=actor)

    def revoke(self, callsign: str, reason: str, actor: str = "") -> Application:
        return self._transition(callsign, REVOKED, reason, {GRANTED}, actor=actor)

    def grant(self, callsign: str, label: str, port: int, actor: str = "") -> Application:
        """授予 —— **只接受已核验的申请**（安全前置，见模块说明）。"""
        data = self._load()
        current = data["applications"].get(callsign)
        if not current:
            raise KeyError(callsign)
        if current["status"] != VERIFIED:
            raise PermissionError(
                f"拒绝授予：{callsign} 当前状态 {current['status']}，只有 {VERIFIED} 才可授予"
            )
        app = Application(**current)
        app.status = GRANTED
        try:
            app.port = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"端口必须是十进制整数，得到 {port!r}") from exc
        app.label, app.port = label, app.port
        # 登记口令在这里生成：它是"这台实例可以把公钥交上来"的唯一凭据。
        # 不给公网留一个匿名上传证书的口子 —— 那等于让任何人冒充别人的入口。
        app.enroll_secret = secrets.token_urlsafe(24)
        app.touch("granted", f"label={label} port={port}")
        data["applications"][callsign] = asdict(app)
        self._audit(data, callsign, "granted", f"{label} → {port}", actor=actor)
        self._save(data)
        return app

    # ---- 内部 ----
    def _transition(self, callsign: str, new_status: str, detail: str, allowed: set,
                    actor: str = "") -> Application:
        data = self._load()
        current = data["applications"].get(callsign)
        if not current:
            raise KeyError(callsign)
        if current["status"] not in allowed:
            raise ValueError(f"{callsign} 状态 {current['status']} 不允许转为 {new_status}")
        app = Application(**current)
        app.status = new_status
        if new_status == VERIFIED:
            app.evidence = detail
        app.touch(new_status, detail)
        data["applications"][callsign] = asdict(app)
        self._audit(data, callsign, new_status, detail, actor=actor)
        self._save(data)
        return app

    def audit(self) -> list:
        return self._load()["audit"]

    def bindings(self) -> dict:
        return {c: a for c, a in self._load()["applications"].items() if a["status"] == GRANTED}
