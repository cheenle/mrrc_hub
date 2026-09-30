"""呼号：规范化与合法性判定（UC-H10 第一步）。

**为什么必须核验（本模块存在的理由）**

呼号是**公开标识**：它在电台执照上、在 QRZ 之类的呼号库里、在每一次通联记录里。
按 AD-H15，入口名就是呼号（`<呼号>.mrrc.vlsc.net`），所以：

1. **入口可被枚举** —— 呼号是可猜的公开信息，实例存在性必然可枚举（I-H9 已结案接受）。
   于是"别人猜不到"永远不能作为防线；能作为防线的只有"核验过才给访问权"。
2. **冒用成本极低** —— 任何人都能输入 `BG1SB`。若不核验，就等于把一个真实持照者的
   身份、以及一个能发射的电台，交给任何会打字的人。
3. **一次授予是长期的** —— 访问权一旦发出，撤销需要人工介入（`revoke`），
   所以错授的代价远大于拒授。

因此本流程把核验放在**授予之前**（见 `store.grant` 里的硬性前置条件），
而不是"先给用、有问题再说"。
"""
from __future__ import annotations

import re

# 业余呼号的常见形态：前缀(1-3 字母数字) + 分区数字 + 后缀(1-4) + 可选 /操作标识。
# 这是**有意简化**的判定：真实世界的呼号形态远多于正则所能覆盖（特殊事件台、
# 临时呼号、多国连缀等）。所以正则只负责挡掉明显无效的输入，边界情形交给
# 人工复核（ManualVerifier）—— 这正是核验环节存在的意义。
CALLSIGN_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(/[A-Z0-9]{1,4})?$")


class InvalidCallsign(ValueError):
    """输入不可能是一个呼号（规范化后仍不合法）。"""


def normalize(raw: str) -> str:
    """把用户输入规范成唯一形式。

    规则（AD-H15）：去空白、全大写、全角连字符与下划线归一为斜杠。
    `bg1sb` 与 `BG1SB` 必须是同一个租户 —— 大小写不敏感是 DNS 与 Host 层的
    既有事实，规范化只是让应用层与它一致。
    """
    if raw is None:
        raise InvalidCallsign("空呼号")
    text = str(raw).strip()
    text = text.replace("－", "/").replace("_", "/").replace("／", "/")
    text = re.sub(r"\s+", "", text).upper()
    if not CALLSIGN_RE.match(text):
        raise InvalidCallsign(f"不合法或超出可自动判定的范围: {raw!r} → {text!r}")
    return text


def is_normalized(value: str) -> bool:
    """判断一个字符串是否已经是规范形式（用于存储层自检）。"""
    try:
        return normalize(value) == value
    except InvalidCallsign:
        return False


def label_for(callsign: str, product: str | None = None) -> str:
    """把呼号变成注册表标签（AD-H15 + §7.x.1 标签规则）。

    主产品用**裸呼号**（小写，因为标签受 `[a-z0-9-]+` 约束，与 nginx 通配 vhost 一致）；
    附加产品加产品后缀，如 `bg1sb-legacy`。
    """
    base = callsign.split("/")[0].lower()
    if product in (None, "", "modern"):
        return base
    slug = re.sub(r"[^a-z0-9]+", "-", str(product).lower()).strip("-")
    if not slug:
        raise ValueError(f"产品名无法构成合法标签: {product!r}")
    return f"{base}-{slug}"
