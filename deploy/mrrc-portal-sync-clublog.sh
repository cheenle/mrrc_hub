#!/usr/bin/env bash
# 把留言版的 Club Log 呼号库换进门户（UC-H10 的权威核验依据）。
#
#   sudo ./mrrc-portal-sync-clublog.sh
#
# 源：/home/cheenle/feedback/clublog_users.json —— 由 `vlsc-feedback-db.timer`
#     每天 03:00 从 clublog.org 刷新（与站内留言版是同一份数据，同源是刻意的：
#     两个入口对同一呼号必须给出同一个结论）。
# 目标：/var/lib/mrrc-hub/portal/clublog_users.json —— 服务账号 `mrrcportal` 只读。
#
# 三条约束，每一条都对应一次差点发生的事故：
#
# 1. **规模门**（MRRC_CLUBLOG_MIN_ENTRIES，默认 10 万）：源必须解析得开、条数够。
#    空库或半截下载换进去，等于把"核验"悄悄降级成"全部转人工"—— 而页面照常、
#    服务照常，没有任何报错。所以宁可拒绝替换。
# 2. **原子替换**：同目录临时文件 + `mv`（同一个文件系统的 rename）。门户是长驻进程，
#    读到写了一半的 36 MB 会解析失败。
# 3. **不重启门户**：`ClubLogVerifier` 按 (mtime, size) 判新鲜度，文件一换，下一次
#    核验就用新库。每天重启一次门户会让所有管理会话失效，不能拿它当同步手段。
set -euo pipefail

SRC="${MRRC_CLUBLOG_SRC:-/home/cheenle/feedback/clublog_users.json}"
DEST="${MRRC_CLUBLOG_DEST:-/var/lib/mrrc-hub/portal/clublog_users.json}"
MIN_ENTRIES="${MRRC_CLUBLOG_MIN_ENTRIES:-100000}"

if [ ! -s "$SRC" ]; then
	echo "[ERROR] 源呼号库不存在或为空: $SRC" >&2
	exit 1
fi

# 规模门：解析一次，同时证明它是合法 JSON、拿到条数（顶层对象或数组都认）。
count=$(python3 - "$SRC" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception as exc:  # noqa: BLE001
    print(f"无法解析: {exc}", file=sys.stderr)
    raise SystemExit(1)
try:
    n = len(data)
except TypeError:
    print("顶层既不是对象也不是数组", file=sys.stderr)
    raise SystemExit(1)
if n == 0:
    print("空库", file=sys.stderr)
    raise SystemExit(1)
print(n)
PY
) || {
	echo "[ERROR] 源呼号库不可用（不是合法 JSON？）: $SRC" >&2
	exit 1
}

if [ "$count" -lt "$MIN_ENTRIES" ]; then
	echo "[ERROR] 源呼号库只有 $count 条（门限 ${MIN_ENTRIES}），拒绝替换 —— 空库会把核验降级成全员人工" >&2
	exit 1
fi

dest_dir=$(dirname "$DEST")
if [ ! -d "$dest_dir" ]; then
	echo "[ERROR] 目标目录不存在: $dest_dir" >&2
	exit 1
fi

# 内容没变就不碰：换一次文件会让门户下次核验重建一次索引（36 MB，1–2 s）。
if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
	echo "[OK] 呼号库未变化（$count 条），未替换"
	exit 0
fi

tmp=$(mktemp "$dest_dir/.clublog_users.XXXXXX")
trap 'rm -f "$tmp"' EXIT
cat "$SRC" >"$tmp"
chmod 0640 "$tmp"
# 只有 root 能改属主；在别的身份下跑（例如测试）就沿用当前属主。
if [ "$(id -u)" -eq 0 ]; then
	chown mrrcportal:mrrcportal "$tmp"
fi
mv -f "$tmp" "$DEST"
trap - EXIT

size=$(wc -c <"$DEST" | tr -d ' \t')   # 可移植：BSD stat 没有 -c
echo "[OK] 呼号库已更换：$count 条，$((size / 1048576)) MB，源 $SRC → $DEST"
echo "[INFO] 门户下次核验即用新库（按 mtime/size 判新鲜度），无需重启"
