#!/usr/bin/env python3
"""呼号库同步链：Verifier 的热重载 + 同步脚本的规模门 + timer 的落点。

运行：python3 tests/test_clublog_sync.py

为什么这三组要一起测：它们各自都能"看起来正常"却让核验悄悄失效。
- Verifier 若只在启动时读一次，换库就要重启门户 —— 而因为怕重启，人就不换库；
- 脚本若没有规模门，一个空库/半截下载会把"核验"降级成"全员人工"，页面毫无异常；
- timer 若指向错的 unit，脚本再好也从不运行（2026-10-02 的路由定时器就是这样
  静默失效了两个月）。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portal.verify import ClubLogVerifier, VerificationOutcome  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILS.append(label)


def write_db(path: pathlib.Path, keys: list[str]) -> None:
    path.write_text(json.dumps({k: {"lastqso": "2026-01-01"} for k in keys}), encoding="utf-8")


def test_verifier_reloads_when_the_file_is_replaced() -> None:
    """同步换库后，**同一个实例**必须看见新呼号 —— 否则只能靠重启门户。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = pathlib.Path(tmp) / "clublog_users.json"
        write_db(db, ["4X/BG1SB"])
        v = ClubLogVerifier(db)
        check(v.check("BG1SB").outcome is VerificationOutcome.VERIFIED, "旧库里的呼号应命中")

        # 换库：新呼号进来、旧呼号不在新库里（模拟真实覆盖，而不是追加）
        time.sleep(0.01)  # 让 mtime 明确变化（有的文件系统秒级粒度）
        new = pathlib.Path(tmp) / "new.json"
        write_db(new, ["BG2NEW"])
        os.replace(new, db)

        check(v.check("BG2NEW").outcome is VerificationOutcome.VERIFIED,
              "换库后同一个 Verifier 必须看见新呼号（热重载）")
        check(v.check("BG1SB").outcome is VerificationOutcome.UNVERIFIED,
              "换库后旧呼号不应再命中（证明真的重建了索引，不是只能追加）")


def test_verifier_survives_a_missing_file() -> None:
    """库文件不见了只应转人工，不能抛异常把申请打成 500。"""
    with tempfile.TemporaryDirectory() as tmp:
        v = ClubLogVerifier(pathlib.Path(tmp) / "nope.json")
        check(v.check("BG1SB").outcome is VerificationOutcome.UNVERIFIED, "缺失时应转人工")
        check(v.check("BG1SB").outcome is not VerificationOutcome.REJECTED, "缺失不得判为冒用")


def run_sync(src: pathlib.Path, dest: pathlib.Path, min_entries: int) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "MRRC_CLUBLOG_SRC": str(src),
        "MRRC_CLUBLOG_DEST": str(dest),
        "MRRC_CLUBLOG_MIN_ENTRIES": str(min_entries),
    })
    return subprocess.run(
        ["bash", str(ROOT / "deploy/mrrc-portal-sync-clublog.sh")],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_sync_installs_a_fresh_db_atomically() -> None:
    """正常路径：换进去、字节一致、权限 0640。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        src = tmpd / "src.json"
        write_db(src, ["BG1SB", "BG2NEW", "BA4EG"])
        dest = tmpd / "portal" / "clublog_users.json"
        dest.parent.mkdir()
        dest.write_text("{}", encoding="utf-8")

        r = run_sync(src, dest, 3)
        check(r.returncode == 0, f"正常同步应 exit 0（实际 {r.returncode}: {r.stderr.strip()}）")
        check(dest.read_bytes() == src.read_bytes(), "目标应与源逐字节一致")
        check((dest.stat().st_mode & 0o777) == 0o640, "目标权限应为 0640")
        check(not list(dest.parent.glob(".clublog_users.*")), "不得留下临时文件")


def test_sync_refuses_a_too_small_database() -> None:
    """规模门：小库必须被拒，且**目标保持原样**（不能先删再写）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        src = tmpd / "src.json"
        write_db(src, ["BG1SB", "BG2NEW"])
        dest = tmpd / "clublog_users.json"
        dest.write_text('{"KEEP": 1}', encoding="utf-8")

        r = run_sync(src, dest, 100)
        check(r.returncode == 1, f"小库应 exit 1（实际 {r.returncode}）")
        check("门限" in (r.stderr + r.stdout), "错误信息应说明门限")
        check(dest.read_text(encoding="utf-8") == '{"KEEP": 1}', "被拒时目标文件不得被改动")


def test_sync_refuses_invalid_json() -> None:
    """半截下载不是 JSON：同样拒绝，目标不动。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        src = tmpd / "src.json"
        src.write_text('{"BG1SB": {"lastqso": ', encoding="utf-8")  # 截断
        dest = tmpd / "clublog_users.json"
        dest.write_text('{"KEEP": 1}', encoding="utf-8")

        r = run_sync(src, dest, 1)
        check(r.returncode == 1, f"坏 JSON 应 exit 1（实际 {r.returncode}）")
        check(dest.read_text(encoding="utf-8") == '{"KEEP": 1}', "被拒时目标文件不得被改动")


def test_sync_is_a_noop_when_content_is_identical() -> None:
    """同内容不替换：省掉一次 36 MB 索引重建。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        src = tmpd / "src.json"
        write_db(src, ["BG1SB", "BG2NEW", "BA4EG"])
        dest = tmpd / "clublog_users.json"
        dest.write_bytes(src.read_bytes())
        before = dest.stat().st_ino, dest.stat().st_mtime_ns

        r = run_sync(src, dest, 3)
        check(r.returncode == 0, "同内容应 exit 0")
        check("未变化" in r.stdout, "应说明未变化")
        check((dest.stat().st_ino, dest.stat().st_mtime_ns) == before, "同内容不应替换文件（inode/mtime 不变）")


def test_timer_and_service_are_wired_to_the_script() -> None:
    """timer → service → 脚本路径；每天一次、在留言版刷新之后。"""
    timer = (ROOT / "deploy/systemd/mrrc-portal-sync-clublog.timer").read_text(encoding="utf-8")
    service = (ROOT / "deploy/systemd/mrrc-portal-sync-clublog.service").read_text(encoding="utf-8")
    check("OnCalendar=*-*-* 04:30:00" in timer, "timer 应每天 04:30 跑（晚于 03:00 的源刷新）")
    check("Persistent=true" in timer, "错过要补跑（单机 VPS 会维护重启）")
    check("Unit=mrrc-portal-sync-clublog.service" in timer, "timer 应指向同步 service")
    check("ExecStart=/usr/local/sbin/mrrc-portal-sync-clublog.sh" in service,
          "service 应执行 /usr/local/sbin 下的脚本（门户 UI 复制的也是这个路径）")


def test_portal_ui_points_at_the_real_script() -> None:
    """UI 里"立即刷新呼号库"的复制命令必须指向真实存在的脚本名。

    2026-10-25 的实际状况：UI 让你复制 `sudo /usr/local/sbin/mrrc-portal-sync-clublog.sh`，
    而机器上从来没有这个脚本 —— 复制命令变成了死命令，文档还把它写成"每天 04:30 在跑"。
    """
    views = (ROOT / "portal/views.py").read_text(encoding="utf-8")
    check("/usr/local/sbin/mrrc-portal-sync-clublog.sh" in views, "UI 应给出同步命令")
    check((ROOT / "deploy/mrrc-portal-sync-clublog.sh").exists(), "仓库里应有这个脚本")
    check(os.access(ROOT / "deploy/mrrc-portal-sync-clublog.sh", os.X_OK), "脚本应可执行")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    if FAILS:
        print(f"❌ {len(FAILS)} 项不合格:")
        for f in FAILS:
            print("   -", f)
        return 1
    print(f"✅ 呼号库同步测试通过（{len(tests)} 组）：Verifier 热重载/缺文件降级/"
          "原子替换与权限/规模门拒绝且目标不动/坏 JSON 拒绝/同内容 no-op/timer→service→脚本/UI 命令指向真脚本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
