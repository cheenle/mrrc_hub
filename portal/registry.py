"""注册表与端口分配（UC-H10 的最后一步：分配）。

注册表就是 hub 上那份 `/etc/mrrc-hub/instances.tsv`（标签 + 远端端口，制表符分隔），
`gen_hub_routes.py` 由它生成 nginx 的 map。Portal 只负责**追加一行**并选一个空闲端口；
生成路由与 reload nginx 属于部署动作（需要 root），Portal 会明确提示这一步，
而不是偷偷替运维做掉。
"""
from __future__ import annotations

import os
from pathlib import Path

PORT_FIRST, PORT_LAST = 18802, 18999


class Registry:
    def __init__(self, path: str | Path, first: int = PORT_FIRST, last: int = PORT_LAST):
        self.path = Path(path)
        self.first, self.last = first, last

    def entries(self) -> list:
        """返回 [(label, port)]，忽略空行与 # 注释。"""
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                out.append((parts[0], int(parts[1])))
        return out

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
