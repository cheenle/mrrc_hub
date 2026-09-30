"""核验器：把"这个呼号是谁的"变成一个可审计的结论。

两种实现，按需要组合：

* `CallsignListVerifier` —— 比对一份本地呼号库文件（一行一个呼号）。运维可以定期
  从公开呼号库导出；这一步把"人工查一遍"变成"机器比对，边界情形才人工看"。
* `ManualVerifier` —— 默认。把申请留在待核验队列里，由持照人上传执照材料或由
  维护者确认。**永远可用**，也是边界情形的兜底（正则无法覆盖的特殊呼号形态）。

设计上的两个"故意"：

1. 核验结果**只回答"能不能证明"**，不回答"要不要给访问权"。授予是另一步（store.grant），
   且带硬性前置条件。分开的好处是：核验逻辑可以随便替换，安全前置不会跟着松动。
2. 未通过核验**不是错误**，是正常分支（`VerificationOutcome.UNVERIFIED`）——
   真实世界里多数申请会落在这里，等人工确认。把它当异常处理会让流程变脆。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from portal import callsign as cs


class VerificationOutcome(str, Enum):
    VERIFIED = "verified"          # 有据可依，可直接进入授予
    UNVERIFIED = "unverified"      # 待人工核验（正常分支，不是失败）
    REJECTED = "rejected"          # 明确不通过（例如已在库中被标记为他人/冒用）


@dataclass
class VerificationResult:
    outcome: VerificationOutcome
    evidence: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is VerificationOutcome.VERIFIED


class CallsignListVerifier:
    """与本地呼号库列表比对。库文件一行一个呼号（`#` 起注释）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _known(self) -> set:
        if not self.path.exists():
            return set()
        out = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip().upper()
            if line:
                out.add(line)
        return out

    def check(self, callsign: str) -> VerificationResult:
        known = self._known()
        if not known:
            return VerificationResult(VerificationOutcome.UNVERIFIED, f"呼号库为空或不存在: {self.path}")
        base = callsign.split("/")[0]
        if base in known:
            return VerificationResult(VerificationOutcome.VERIFIED, f"命中呼号库 {self.path}")
        return VerificationResult(VerificationOutcome.UNVERIFIED, f"呼号库中未收录 {base}，转人工核验")


class ClubLogVerifier:
    """以 Club Log 呼号库为权威依据（与站内留言版同源）。

    数据是 clublog.org 的 `clublog-users.json`（27 万条），键形如 `4X/BG1SB`、
    `1A0C_14`、`BG1SB` —— 用 `callsign.base_callsign()` 提取基准呼号建索引。

    判定语义：**命中即可证明该呼号存在于公开通联记录中**（这就是"核验"能给的最强
    证据）；未命中**不等于假**（新执照、低活跃、Club Log 未使用者都不在库里），
    所以返回 UNVERIFIED 转人工，而不是 REJECTED。这一点很重要：把"查不到"当成
    "冒用"，会拒掉真实的新用户。
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._index: set | None = None

    def _load(self) -> set:
        if self._index is not None:
            return self._index
        if not self.path.exists():
            self._index = set()
            return self._index
        try:
            with self.path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:                      # noqa: BLE001
            raise RuntimeError(f"Club Log 呼号库无法解析: {self.path}: {exc}") from exc
        keys = raw.keys() if isinstance(raw, dict) else raw
        index = set()
        for key in keys:
            base = cs.base_callsign(key)
            if base:
                index.add(base)
        self._index = index
        return index

    def check(self, callsign: str) -> VerificationResult:
        index = self._load()
        if not index:
            return VerificationResult(VerificationOutcome.UNVERIFIED, f"Club Log 呼号库不可用: {self.path}")
        if callsign in index:
            return VerificationResult(VerificationOutcome.VERIFIED,
                                      f"Club Log 呼号库命中（{len(index)} 个基准呼号）")
        return VerificationResult(VerificationOutcome.UNVERIFIED,
                                  "Club Log 呼号库未收录（新执照/低活跃也可能如此），转人工核验")


class ManualVerifier:
    """默认核验器：一切转人工，由 Portal 的待核验队列承载。"""

    def check(self, callsign: str) -> VerificationResult:
        return VerificationResult(VerificationOutcome.UNVERIFIED, "需人工核验（上传执照材料或维护者确认）")


class ChainVerifier:
    """按顺序询问多个核验器，先给出确定结论者胜出。"""

    def __init__(self, *verifiers):
        self.verifiers = list(verifiers)

    def check(self, callsign: str) -> VerificationResult:
        pending = None
        for verifier in self.verifiers:
            result = verifier.check(callsign)
            if result.outcome is VerificationOutcome.VERIFIED:
                return result
            if result.outcome is VerificationOutcome.REJECTED:
                return result
            pending = pending or result
        return pending or VerificationResult(VerificationOutcome.UNVERIFIED, "没有可用的核验器")
