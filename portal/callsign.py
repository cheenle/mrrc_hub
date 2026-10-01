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

# 规则**逐条对齐站内留言版**（/home/cheenle/feedback/callsign.py）—— 两个系统必须
# 对同一个呼号给出同样的结论，否则用户会在一个入口通过、在另一个入口被拒。
#
# 基准呼号：可选 1 位数字前缀（9M2 / 4X 这类）+ 1-2 字母 + 1 位数字 + 1-3 字母。
CALLSIGN_RE = re.compile(r"^[0-9]?[A-Z]{1,2}[0-9][A-Z]{1,3}$")

# 便携/特殊分隔符：注册只接受**基准呼号**，故含这些字符一律拒绝（与留言版一致）。
SEPARATORS = "/_.-"


class InvalidCallsign(ValueError):
    """输入不可能是一个呼号（规范化后仍不合法）。"""


def normalize(raw: str) -> str:
    """规范化：去空白、转大写、去掉全角字符带来的歧义。

    `bg1sb` 与 `BG1SB` 必须是同一个租户 —— 大小写不敏感是 DNS 与 Host 层的既有事实，
    规范化只是让应用层与它一致（AD-H15）。

    **只接受基准呼号**：含 `/ _ . -` 的输入（`BG1SB/P`、`4X/BG1SB`）一律拒绝，
    与留言版一致。理由：注册的是**身份**，便携/前缀属于操作状态，不该进租户名；
    而 `label_for` 要用它拼 DNS 标签，斜杠与点在那里也不合法。
    """
    if raw is None:
        raise InvalidCallsign("空呼号")
    text = re.sub(r"\s+", "", str(raw)).upper()
    if not text:
        raise InvalidCallsign("空呼号")
    if any(ch in text for ch in SEPARATORS):
        raise InvalidCallsign(
            f"只接受基准呼号，不含 {'/'.join(SEPARATORS)}（收到 {raw!r}）——"
            "便携/前缀等操作标识不用于租户名"
        )
    if not CALLSIGN_RE.match(text):
        raise InvalidCallsign(f"呼号格式不正确（示例：BG1SB）: {raw!r}")
    return text


def base_callsign(key: str) -> str:
    """从 Club Log 原始键提取基准呼号（与留言版同一套语义）。

    '4X/BG1SB' → 'BG1SB'（取 / 右侧合法段）
    'BG1SB/P'  → 'BG1SB'（P 不合法则取左侧）
    '1A0C_14'  → '1A0C'（去掉 _ 后缀）
    'BG1SB'    → 'BG1SB'；'SOS' → ''（提取失败）
    """
    if not isinstance(key, str):
        return ""
    k = key.strip().upper()
    if not k:
        return ""
    if "/" in k:
        for part in reversed([p for p in k.split("/") if p]):
            if is_valid_format(part):
                return part
        return ""
    if "_" in k:
        k = k.split("_", 1)[0]
    return k if is_valid_format(k) else ""


def is_valid_format(value: str) -> bool:
    """基准呼号格式校验（输入须已规范化）。"""
    return bool(CALLSIGN_RE.match(value or ""))


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
