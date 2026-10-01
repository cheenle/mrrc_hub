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
            return {"applications": {}, "audit": []}
        with self.path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("applications", {})
        data.setdefault("audit", [])
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    def _audit(self, data: dict, callsign: str, event: str, detail: str = "") -> None:
        data["audit"].append({"at": time.time(), "callsign": callsign, "event": event, "detail": detail})

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

    def mark_verified(self, callsign: str, evidence: str) -> Application:
        return self._transition(callsign, VERIFIED, evidence, {APPLIED})

    def reject(self, callsign: str, reason: str) -> Application:
        return self._transition(callsign, REJECTED, reason, {APPLIED, VERIFIED})

    def revoke(self, callsign: str, reason: str) -> Application:
        return self._transition(callsign, REVOKED, reason, {GRANTED})

    def grant(self, callsign: str, label: str, port: int) -> Application:
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
        app.label, app.port = label, int(port)
        # 登记口令在这里生成：它是"这台实例可以把公钥交上来"的唯一凭据。
        # 不给公网留一个匿名上传证书的口子 —— 那等于让任何人冒充别人的入口。
        app.enroll_secret = secrets.token_urlsafe(24)
        app.touch("granted", f"label={label} port={port}")
        data["applications"][callsign] = asdict(app)
        self._audit(data, callsign, "granted", f"{label} → {port}")
        self._save(data)
        return app

    # ---- 内部 ----
    def _transition(self, callsign: str, new_status: str, detail: str, allowed: set) -> Application:
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
        self._audit(data, callsign, new_status, detail)
        self._save(data)
        return app

    def audit(self) -> list:
        return self._load()["audit"]

    def bindings(self) -> dict:
        return {c: a for c, a in self._load()["applications"].items() if a["status"] == GRANTED}
