# sdd-guardian — `mrrc_hub` project instance

本目录是 sdd-guardian 的**工程实例**（规则 + 索引 + 引擎副本）。
引擎（生命周期、CLI 语义）是全局技能 `~/.pi/agent/skills/sdd-guardian/`，
本实例只提供"这个项目的"内容。

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 项目级铁律与六阶段循环（含**引擎副本**说明） |
| `harness/constraints.json` | 17 条规则：6 block / 4 warn / 7 info，全部由评审取证驱动 |
| `harness/index.json` | 9 个主题 → SDD 章节的活引用（不复制内容，查询时从 `SDD/*.md` 切片） |
| `harness/sdd_context.py` | 引擎副本，含 2 处 `# LOCAL PATCH (mrrc_hub)` |

## 常用命令

```bash
H=.agents/skills/sdd-guardian/harness/sdd_context.py

python3 $H prime                                   # 铁律摘要
python3 $H brief --task "隧道心跳与 PTT 释放"        # 按主题拉 sdd + 约束
python3 $H brief crypto/tunnel.py                  # 按文件拉（实现后）
python3 $H sdd AD-H06                              # 单条：AD-H06 / NFR-H006 / UC-H05
python3 $H sdd sec:15.3                            # 章节：15.3 / ch:9
python3 $H check --staged                          # 提交闸门（exit 2 = 有 block 违规）
python3 $H trace docs/some-spec.md                 # spec ↔ SDD 引用审计（建议性）
```

## 规则来源（不是凭空的清单）

每条 block/warn 都对应一处**取证**的事实，而不是通用最佳实践：

| 规则 | 取证 |
|---|---|
| `hub-no-direct-ptt-write` | `mrrc_modern/server.py` 的 dead-man switch 只在真正断线时触发；key-owner 仲裁（`_ptt_key_ws`）已存在，第二写者会破坏它 |
| `hub-token-not-in-url` | `static/ft710_main.js` / `static/listen.js` 把 30 天令牌拼进 `?token=`；`support_bundle.py` 的脱敏正则注释已点出该问题 |
| `hub-tls-verify-off` | `deploy_listen_proxy.sh` 全篇 `proxy_ssl_verify off` |
| `hub-log-no-raw-request-uri` | 实例跑 `uvicorn` 默认访问日志；nginx 侧记录 `$request_uri` 即泄露 query 中的凭证 |
| `hub-cookie-name-not-instance-auth` | 通配子域下 Access 与实例共享同一 origin；实例 `AUTH_COOKIE` 且 `httponly=False` |
| `hub-bandwidth-budget-sync` | `opus_rx.py` `DEFAULT_BITRATE=64000`；`/WSspectrum` 1701 B/帧 × 30 fps ≈ 408 kbps（占单会话 86%） |

完整取证见 [`../../../docs/2026-09-30-fleet-hub-design-review.md`](../../../docs/2026-09-30-fleet-hub-design-review.md)。
