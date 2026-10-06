---
name: sdd-guardian
description: SDD-driven engineering lifecycle for mrrc_hub (MRRC Cloud Hub) — full design context (requirements/SC-H, use cases UC-H, architecture decisions AD-H, feasibility R-H/I-H) plus enforcement of the remote-access safety and security boundaries on every change: PTT release ownership, token-not-in-URL, TLS verification, cookie namespace, lease atomicity, single-instance certificate
type: prompt
whenToUse: When creating, modifying, reviewing, or debugging code in this repository; when planning the tunnel, Access/Tunnel Gateway, Registry, Ticket, Lease, Portal, Agent, OTA or telemetry; when touching session heartbeats, cookie handling, proxy config, bandwidth/frame budgets, or anything that could change PTT release behaviour
arguments:
  - task
---

# SDD Guardian — engineering lifecycle for mrrc_hub

This repository is governed by `SDD/` (IBM TeamSD, 15 chapters, currently **V0.29**,
status: 阶段 1 已在公网生产运行 —— 通配入口 + 隧道 + 一机一证 + 自助门户；未决项见
`SDD/README.md` 的 Status 行). The SDD is the canonical
design record for the **cloud hub only** — radio control and media stay owned by
`mrrc_modern/SDD/`. `${KIMI_SKILL_DIR}/harness/` is the machine-readable backing:
`constraints.json` (enforcement rules), `index.json` (knowledge routing into every
SDD chapter — resolved live, never a stale copy), and `sdd_context.py` (CLI).
${ARGUMENTS:+Task focus: $ARGUMENTS}

## Phase 0 — Load the full engineering brief (always, before touching code)

```bash
python3 ${KIMI_SKILL_DIR}/harness/sdd_context.py brief <files-you-will-touch>
python3 ${KIMI_SKILL_DIR}/harness/sdd_context.py brief --task "<one-line task description>"
```

Need one specific item? `sdd AD-H06` · `sdd NFR-H006` · `sdd UC-H05` · `sdd R-H1` ·
`sdd I-H6` · `sdd SC-H4` · `sdd sec:15.3` · `sdd ch:9` · `sdd <keyword>`.
For anything beyond a trivial fix, also read the referenced chapter in full.

## Phase 1 — Design check

- **Requirements traceability**: which `SC-H*` / `NFR-H*` does this change serve?
  Degrading a target — especially **NFR-H006 (PTT release ≤1 s EOF / ≤1.5 s half-open)**,
  **NFR-H007/H008 (bandwidth 0.48 / 0.20 Mbps; spectrum 408 kbps ≈ 86%)**,
  **NFR-H020 (token not in URL)** — is a design conversation with the user, never a
  unilateral edit.
- **Architecture decisions**: contradicting an `AD-H*` means amending `SDD/08` in the
  same change.
- **Feasibility**: does the change depend on a risk or an open issue in ch 13?
  `R-H1` half-open PTT, `R-H2` token in logs, `R-H7` cookie collision, `I-H1` Listener
  concurrency (unmeasured), `I-H6` instance-side liveness gate (unimplemented)?
  Don't design as if those were solved.
- **Use cases**: walk the affected `UC-H*` main flow + exceptions end-to-end.
- **Safety**: anything touching PTT/TX — chapter [15](SDD/15-ptt-safety-hub-mode.md)
  is load-bearing. Hub/Tunnel may only **close the stream and notify**
  (`TX_ABORT`); the release itself runs in `mrrc_modern`. Never introduce a second
  PTT writer, and never let a release depend on lease TTL.
- **Cross-repo**: changes that need instance-side work are listed as C1–C6 in
  `SDD/11-component-model.md` §11.3 — they must be registered in **`mrrc_modern/SDD/`**
  (AD/NFR + `15-ptt-safety-architecture.md` layer table + test counts), not only here.

## Phase 2 — Implement under constraint

Golden rules are **block-level** and project-specific (see `constraints.json`):

| Rule | Meaning |
|---|---|
| `hub-no-direct-ptt-write` | Hub is never a PTT writer — no `set_ptt()`, no `TX0;`, no `ptt:false` |
| `hub-token-not-in-url` | session token / launch code never in URL query |
| `hub-tls-verify-off` | never disable upstream certificate verification |
| `hub-log-no-raw-request-uri` | never log `$request_uri` raw (query carries credentials) |
| `hub-shared-static-token` | no fleet-wide shared token — one certificate per instance |
| `hub-cookie-name-not-instance-auth` | hub ticket cookie must not reuse the instance's `mrrc_auth` name |

Warn-level: `hub-ticket-cookie-httponly` (ticket must be HttpOnly+Secure),
`hub-lease-not-release-path`, `hub-secrets-hardcoded`, `hub-bandwidth-budget-sync`.

Minimal diffs; match the deployment conventions in ch 12 §12.2 (idempotent scripts,
block-level replacement, probe-then-mutate, 0600 credentials, `nginx -t && reload`).

## Phase 3 — Test

- Tunnel, Registry, Ticket and Lease must all be replaceable by in-memory
  implementations so logic is testable without hardware or network.
- Anything touching the TX path must be exercised against the **V1–V10 injection
  matrix** in chapter [15](SDD/15-ptt-safety-hub-mode.md) §15.5 — including the
  negative cases V8 (LAN carrier must survive a remote listener's half-open socket)
  and V10 (single lost heartbeat must not release).

## Phase 4 — Verify

```bash
python3 ${KIMI_SKILL_DIR}/harness/sdd_context.py check --staged   # must print clean
```

## Phase 5 — Documentation sync (part of the change)

| If you changed… | Also update |
| --- | --- |
| Tunnel/protocol behaviour | ch 10 service contract + ch 9 routing |
| PTT release path or timing | ch [15](SDD/15-ptt-safety-hub-mode.md) + `NFR-H006/H019` + `SC-H4` |
| Bandwidth / codec / frame rates | `NFR-H007/H008` + ch 9 §9.3 + `AD-H14` |
| Role semantics | `AD-H08` + ch 6 UCs + ch 7 authority matrix |
| Credentials / session / cookies | `AD-H07`/`AD-H09`/`AD-H11` + `NFR-H012/013/014/020` |
| Architecture approach | ch 8 (new or amended AD) |
| **ANY behaviour change** | a new entry in `SDD/14-version-history.md` + `SDD/README.md` version bump |

If the SDD contradicts the runtime you just verified, the SDD is wrong — fix it in the
same change and say so in the version-history entry.

## 引擎副本（本仓特有）

本仓在 `.agents/skills/sdd-guardian/harness/sdd_context.py` 携带一份引擎副本，含**两处本地补丁**
（均以 `# LOCAL PATCH (mrrc_hub)` 标注）：

1. `cmd_sdd` 接受 `-H` 形式的 ID（`AD-H06` / `NFR-H006` / `R-H1` / `SC-H4` / `A-H2`）——
   共享引擎的 `AD-\d+` 硬编码无法寻址本仓命名空间。
2. `cmd_sdd` 接受显式 `sec:` / `ch:` 前缀（`sdd sec:15.3`、`sdd ch:9`）。

**为什么用 `-H` 命名空间**：本设计天然要求跨仓变更（C1–C6），两个 SDD 会被并排阅读；
若用裸 ID，本仓 `AD-006` 与 `mrrc_modern` 的 `AD-006` 含义不同，而 `R1`/`I1`/`SC1`
必然撞号。

**升级共享引擎时的动作**：`diff` 上游 `sdd_context.py` → 若无冲突，覆盖本地副本后
重新贴上这两处补丁 → 跑一次 `brief --task` 与 `sdd AD-H06` 验证。
