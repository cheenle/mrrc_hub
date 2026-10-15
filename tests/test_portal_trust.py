#!/usr/bin/env python3
"""`portal/trust.py` 的测试：hub 侧信任链的漂移判据（不碰硬件、不开端口、不要 root）。

运行：python3 tests/test_portal_trust.py   （也兼容 pytest）

守的是 2026-10-16「换机后入口 502」那一次的三个结论：

① **登记了证书、但没重跑生成器** ⇒ nginx 不信任它 ⇒ 入口 502，而页面上必须能说出来
   （判据：登记的证书在不在信任包里 —— 生成器是**逐字拼接**，所以文本包含就是精确判据）。
② **生成器跑了、但 nginx 没 reload** ⇒ 同样 502。这一条**不能**拿 `trust-bundle.pem` 的
   mtime 当判据：生成器内容没变也会重写它（实测 bundle 00:32:08 / worker 00:27:35，而四个
   活着的入口其实都正常）—— 拿 mtime 判会造出一条永远在闪的假警报，那比不报更糟。
③ **退役的实例证书**（有证书、注册表里已经没它了）按设计就不并入信任包：那是事实，
   不是故障，不能报成漂移。
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal import trust  # noqa: E402

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def pem(tag: str) -> str:
    """一个身体唯一的 PEM（DER 是随便编的 —— 本模块只做哈希与包含，不解析证书）。"""
    der = (tag.encode() + b"\x30" * 20) * 3
    body = base64.encodebytes(der).decode().strip()
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----\n"


def fake_proc(tmp: Path, btime: float, workers: dict, others: bool = True) -> Path:
    """一个假的 /proc：`stat` 里给 btime，另造几个进程目录。

    worker 的 comm 故意带空格与括号（`(nginx worker (pool))`）—— 内核只在**最后一个**
    ')' 收尾，用 `split()[21]` 那种朴素写法会在这里读错字段。
    """
    proc = tmp / "proc"
    proc.mkdir(parents=True, exist_ok=True)
    (proc / "stat").write_text(f"cpu 1 2 3\nbtime {int(btime)}\n", encoding="utf-8")
    hz = os.sysconf("SC_CLK_TCK")
    for pid, (ticks, cmd, comm) in workers.items():
        d = proc / str(pid)
        d.mkdir(exist_ok=True)
        (d / "cmdline").write_bytes(cmd)
        fields = ["S", "1"] + ["0"] * 17 + [str(int(ticks))] + ["0"] * 10
        (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n", encoding="utf-8")
    if others:
        d = proc / "4242"
        d.mkdir(exist_ok=True)
        (d / "cmdline").write_bytes(b"python3 /opt/mrrc-hub/portal/app.py\x00")
        (d / "stat").write_text("4242 (python3) " + " ".join(["S"] * 40) + "\n", encoding="utf-8")
    _ = hz
    return proc


def test_fingerprint_is_the_der_hash_and_is_stable():
    a, b = pem("aa"), pem("bb")
    check(len(trust.fingerprint_of_pem(a)) == 64, "指纹是 64 位十六进制（DER SHA-256）")
    check(trust.fingerprint_of_pem(a) == trust.fingerprint_of_pem(a), "同一张证书指纹稳定")
    check(trust.fingerprint_of_pem(a) != trust.fingerprint_of_pem(b), "不同证书指纹不同")
    check(trust.fingerprint_of_pem("not a pem") == "", "非 PEM ⇒ 空串（诚实降级，不猜）")
    check(trust.fingerprint_of_pem("") == "", "空串 ⇒ 空串")
    check(len(trust.short_fp(trust.fingerprint_of_pem(a))) == 16, "短形式 16 字符（给人看）")


def test_bundle_contains_is_verbatim_like_the_generator():
    """生成器写 bundle 用的是 `cert.read_text().rstrip()` 再拼接 —— 判据必须与它同口径。"""
    head = pem("aa")
    tail = pem("bb")
    bundle = "<系统 CA 占位>\n" + head.rstrip() + "\n" + tail.rstrip() + "\n"
    check(trust.bundle_has_cert(bundle, head), "在包里的那张 ⇒ True")
    check(trust.bundle_has_cert(bundle, tail), "另一张也在 ⇒ True")
    check(not trust.bundle_has_cert(bundle, pem("cc")), "不在包里的 ⇒ False")
    check(not trust.bundle_has_cert("", head), "空包 ⇒ False（不是「都算在」）")
    check(not trust.bundle_has_cert(bundle, ""), "空证书 ⇒ False")


def test_last_reload_time_picks_the_newest_worker():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        hz = os.sysconf("SC_CLK_TCK")
        proc = fake_proc(tmp, 1_000_000, {
            101: (60 * hz, b"nginx: worker process\x00", "nginx worker (pool)"),
            102: (600 * hz, b"nginx: worker process\x00", "nginx"),      # 最近一次 reload
            103: (900 * hz, b"nginx: master process /usr/sbin/nginx\x00", "nginx"),  # master 不算
        })
        got = trust.last_reload_time(proc)
        check(got == 1_000_600, f"取最近那个 worker 的启动时刻（得到 {got}）")
        check(trust.last_reload_time(tmp / "缺失") is None, "路径不存在 ⇒ None（无法判断）")
        (proc / "stat").write_text("cpu 1 2 3\nbtime 不是数字\n", encoding="utf-8")
        check(trust.last_reload_time(proc) is None, "畸形 btime ⇒ None，不抛异常")
        (proc / "stat").write_text("cpu 1 2 3\n", encoding="utf-8")
        check(trust.last_reload_time(proc) is None, "没有 btime 行 ⇒ None")
        check(trust._starttime_ticks("垃圾") is None, "畸形 stat ⇒ None")
        check(trust._starttime_ticks("1 (x) S 1") is None, "字段不够 22 个 ⇒ None")


def test_drift_separates_real_drift_from_retired():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cert_dir = tmp / "instance-certs"
        cert_dir.mkdir()
        good, missing, retired = pem("good"), pem("missing"), pem("retired")
        (cert_dir / "bg1aa.pem").write_text(good, encoding="utf-8")
        (cert_dir / "bg2bb.pem").write_text(missing, encoding="utf-8")
        (cert_dir / "bg9zz.pem").write_text(retired, encoding="utf-8")
        (cert_dir / ".bg1aa.pem.tmp").write_text("登记过程中的临时文件", encoding="utf-8")
        (tmp / "instances.tsv").write_text("bg1aa 18801\nbg2bb 18802\nbg3cc 18803\n",
                                           encoding="utf-8")
        bundle = tmp / "trust-bundle.pem"
        bundle.write_text("<系统 CA>\n" + good.rstrip() + "\n", encoding="utf-8")

        rep = trust.drift(tmp / "instances.tsv", cert_dir, bundle, reload_at=9e9)
        check(rep["missing"] == ["bg2bb"], f"登记了但没进信任包 ⇒ missing（得到 {rep['missing']}）")
        check(rep["retired"] == ["bg9zz"], f"有证书但不在注册表 ⇒ retired（得到 {rep['retired']}）")
        check(rep["no_cert"] == ["bg3cc"], f"注册表里有、从未登记 ⇒ no_cert（得到 {rep['no_cert']}）")
        check(rep["enrolled"] == 2, "enrolled 只数注册表里的（临时文件与退役的不算）")
        check(rep["bundle_readable"] is True, "读到信任包 ⇒ True")

        # 注册表/信任包都读不到时：**不许**把"读不到"说成"漂移"，也不许说成"没事"
        rep2 = trust.drift(tmp / "缺失.tsv", tmp / "缺失目录", tmp / "缺失包", reload_at=None)
        check(rep2["missing"] == [] and rep2["retired"] == [] and rep2["no_cert"] == [],
              "什么都读不到时报空列表（不编事实）")
        check(rep2["bundle_readable"] is False, "读不到信任包要显式说出来")


def test_drift_flags_reload_but_ignores_the_bundle_mtime():
    """**这条是防假警报的**：生成器内容没变也会重写 trust-bundle.pem。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cert_dir = tmp / "instance-certs"
        cert_dir.mkdir()
        (cert_dir / "bg1aa.pem").write_text(pem("aa"), encoding="utf-8")
        reg = tmp / "instances.tsv"
        reg.write_text("bg1aa 18801\n", encoding="utf-8")
        bundle = tmp / "trust-bundle.pem"
        bundle.write_text(pem("aa"), encoding="utf-8")

        t0 = 1_000_000.0
        os.utime(reg, (t0, t0))
        os.utime(cert_dir / "bg1aa.pem", (t0, t0))
        os.utime(bundle, (t0, t0))

        rep = trust.drift(reg, cert_dir, bundle, reload_at=t0 + 100)
        check(rep["stale_reload"] is False, "reload 晚于一切写入 ⇒ 不报")

        # nginx 没 reload（worker 起得更早）⇒ 必须报，并说清是哪一次写入
        rep = trust.drift(reg, cert_dir, bundle, reload_at=t0 - 100)
        check(rep["stale_reload"] is True, "有写入晚于 nginx 上次 reload ⇒ 报")
        check("bg1aa.pem" in (rep["newest_write"].get("what") or ""),
              f"说清最近写入是哪个文件（得到 {rep['newest_write']}）")
        check(len(rep["newest_write"].get("files") or []) == 2,
              "同一秒里的多次写入**并列全列**（证书与注册表都不能被隐掉）")

        # 宽限期内**不报**：timer 每 30 s 才跑一次，刚登记完的那几十秒里
        # "nginx 还没重载"是**正常状态**。不宽容期 ⇒ 每次 enroll 都红一下。
        rep = trust.drift(reg, cert_dir, bundle, reload_at=t0 - 20)
        check(rep["stale_reload"] is False,
              "刚写入 20 s（< 3 个 timer 周期）⇒ 不报警，等 timer 自己来")
        rep = trust.drift(reg, cert_dir, bundle, reload_at=t0 - 200)
        check(rep["stale_reload"] is True and rep["stale_seconds"] > 0,
              "200 s 还没重载 ⇒ 报，并给出等了多久")

        # 关键：只把信任包重写一遍（内容逐字不变、mtime 变新）**不许**触发报警
        os.utime(bundle, (t0 + 500, t0 + 500))
        rep = trust.drift(reg, cert_dir, bundle, reload_at=t0 + 100)
        check(rep["stale_reload"] is False,
              "信任包被重写但内容没变 ⇒ 不算「待重载」（否则就是一条永远在闪的假警报）")

        # 拿不到 nginx worker（None）⇒ 无法判断，按“不报警”处理
        rep = trust.drift(reg, cert_dir, bundle, reload_at=None)
        check(rep["stale_reload"] is False, "reload_at 未知 ⇒ 不报警（诚实降级）")

        # 注册表被改（加了一个实例）同样要算“待重载”：map 变了，nginx 得重读
        reg.write_text("bg1aa 18801\nbg2bb 18802\n", encoding="utf-8")
        os.utime(reg, (t0 + 900, t0 + 900))
        rep = trust.drift(reg, cert_dir, bundle, reload_at=t0 + 100)
        check(rep["stale_reload"] is True, "注册表改过（map 变了）也算待重载")
        check("instances.tsv" in (rep["newest_write"].get("what") or ""), "并指出是注册表")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ trust 测试通过（{len(tests)} 组）：DER 指纹 / 逐字包含 / worker 启动时刻 / "
          f"真漂移与退役之分 / 信任包 mtime 不产生假警报")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
