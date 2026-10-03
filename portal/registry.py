"""注册表与端口分配（UC-H10 的最后一步：分配）。

注册表就是 hub 上那份 `/etc/mrrc-hub/instances.tsv`（标签 + 远端端口 + 可选的 `tls_name`，
制表符分隔），`gen_hub_routes.py` 由它生成 nginx 的 map。Portal 只负责**追加一行**并选一个
空闲端口；生成路由与 reload nginx 属于部署动作（需要 root），Portal 会明确提示这一步，
而不是偷偷替运维做掉。
"""
from __future__ import annotations

import os
from pathlib import Path

PORT_FIRST, PORT_LAST = 18802, 18999


def _parse_port(text: str):
    """注册表的端口列 → int，无效则 None。

    注册表是 root 用编辑器手改的文件，所以宁可严一点：非十进制、或端口越界
    （`999999` 以前会被照单收下，然后在探测与 nginx 那边才炸）一律当无效行跳过，
    而不是让整个管理台 500。`isdigit()` 已保证 `int()` 不会抛，再包一层是防御性的：
    这里的正确姿态是「跳过这一行」，不是「向上抛」。
    """
    if not text.isdigit():
        return None
    try:
        port = int(text)
    except ValueError:                     # isdigit() 之后不可能发生
        return None
    return port if 0 < port < 65536 else None


class Registry:
    def __init__(self, path: str | Path, first: int = PORT_FIRST, last: int = PORT_LAST):
        self.path = Path(path)
        self.first, self.last = first, last

    def entries(self) -> list:
        """返回 [(label, port)]，忽略空行与 # 注释。"""
        return [(label, port) for label, port, _ in self.entries_full()]

    def entries_full(self) -> list:
        """返回 [(label, port, tls_name)]，第三列缺失时为空串。

        第三列是老式实例自己的域名（如 bg1sb 的 `radio.vlsc.net`）；新式自签租户不写，
        期望值就是它自己的入口名 `<label>.mrrc.vlsc.net`。`entries()` 只交出前两列，
        于是管理台无法判断「实例在服务、但证书签给了错的名字」——而 nginx 对上游开着
        证书校验，这种情况同样会 502。要能报出来，就得先拿到这一列。
        """
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            # **不能静默返回 []**：调用方（Portal.grant）用它查重并挑空闲端口，
            # 读不到就当「注册表是空的」会把新实例分配到别人正在用的端口上，
            # 直接切断一个活实例。宁可炸，也不要猜。
            raise RuntimeError(f"注册表不可读：{self.path}（{exc}）") from exc
        out = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            port = _parse_port(parts[1])
            if port is None:
                continue
            out.append((parts[0], port, parts[2] if len(parts) > 2 else ""))
        return out

    def tls_name_for(self, label: str) -> str:
        """该实例的证书应当签给的名字：第三列，否则它自己的入口名。"""
        for name, _, tls in self.entries_full():
            if name == label:
                return tls or f"{label}.mrrc.vlsc.net"
        return ""

    def labels(self) -> set:
        return {label for label, _ in self.entries()}

    def used_ports(self) -> set:
        return {port for _, port in self.entries()}

    def free_port(self) -> int:
        """从低到高挑一个未被占用的端口；端口用尽时明确报错，不静默复用。"""
        used = self.used_ports()
        for port in range(self.first, self.last + 1):
            if port not in used:
                return port
        raise RuntimeError(f"端口段 {self.first}-{self.last} 已用尽")

    def add(self, label: str, port: int) -> None:
        """追加一行。重复标签或端口一律拒绝 —— 静默覆盖会切断别人的实例。"""
        assert label and label == label.strip().lower(), f"标签必须是小写无空白: {label!r}"
        existing = self.entries()
        if label in {l for l, _ in existing}:
            raise ValueError(f"标签已存在: {label}")
        if port in {p for _, p in existing}:
            raise ValueError(f"端口已被占用: {port}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"{label}\t{port}\n")
            fh.flush()
            os.fsync(fh.fileno())

    def remove(self, label: str) -> bool:
        """删除一行（撤销用）。保留其余行原样。"""
        entries = self.entries()
        keep = [(l, p) for l, p in entries if l != label]
        if len(keep) == len(entries):
            return False
        self.path.write_text("".join(f"{l}\t{p}\n" for l, p in keep), encoding="utf-8")
        return True
