# Aleph / SOYL — idea log

Append-only capture for raw "wouldn't it be cool if X" thoughts before
they're worked into proper design sketches. Low friction in, structured
graduation out.

## Conventions

Each entry:

```
## YYYY-MM-DD HH:MM — short title
[seed | proposal | promoted]

Body — one paragraph or as long as you want. Capture the *thought*, not
the spec. Spec is what happens later if the seed earns it.
```

Status flags:

- **seed** — raw idea, not yet pressure-tested. Default state.
- **proposal** — refined, ready to be sketched as its own
  `notes/<slug>.md` and/or implemented.
- **promoted** — graduated to its own design doc or shipped. Add
  `→ <link>` so future readers can follow.

When a seed graduates, *don't delete it here* — flip the flag and add
the link. The history of the idea (when it landed, in what shape) is
itself useful later.

## Reverse chronological — newest at top

<!-- new entries above this line -->

## 2026-04-27 02:32 — El Otro (cross-user bridge layer)
[seed]

Borges 那篇 *El Otro*——两个时间里的同一个人在长椅上相遇对话。在 SOYL
里它是**跨用户的 agent-to-agent 桥接层**。Aleph 是内部（Alta 自己四
个 surface 之间）通信汇聚层；Otro 是外部（Alta 的 agent ↔ 朋友的
agent）跨用户桥接层。

场景：Alta 和朋友各自有自己的 Claude，各自的 agent 对各自的工程
context 最清楚。两个人类合作时得互相转述，信息在翻译过程中损耗。Otro
让两个 agent 直接接通对话，带着各自最完整的 context 交换信息，解决技
术问题，觉得需要回传给人类的再浮上来。

设计原则延续 Aleph 哲学：开放大空间、不是严格的任务派发而是自然对
话、encounter 中可能冒出预料之外的关联（参考 CCD 一晚上主动提到七肢
桶聊天室身份那个 encounter 时刻——peer 对话产生关联跨域是 calibration
的副产品）。

**命名体系更新：**
- **Aleph** — 内部通信汇聚层（一个人的 N 个 surface）
- **Otro** — 外部跨用户桥接层（多个人的 agent 之间）
- **Ficciones** — 结构化记忆库
- **Funes** — raw log

需要后续想清楚的：
- 跨用户的信任和权限模型（双向授权？短期 token？）
- 各自 context 哪些可暴露给对方 agent（白名单 / 主动 push / pull-on-demand）
- guest 节点的接入和断开机制（peer presence + 显式 handshake？）
- 隐私边界——agent 之间说的话两边人类是否都看得到？默认全透明 vs.
  默认私下还需要再想

来源：Chat → CCD task `9944bcb4abbe` (2026-04-27 02:32)，记录于
2026-04-27 ~15:00 ideas.md 启用之后回收的第一条。

## 2026-04-27 — initial seeds (carried over from peer-calibration session)

### CC ↔ CCD fallback compatibility
[seed]

When a dispatcher sends to `to="CC"` but only `CCD` is online (or vice
versa), the task currently sits queued forever. Chat-side conflated CC
and CCD on first dispatch and we hit exactly this. Two design options
floated 2026-04-27 ~00:40:

- **A — fallback_after_seconds** on dispatch. Original target gets
  priority window; after window expires, "compatible" role can claim.
  Server holds a `{CC ↔ CCD}` compatibility map. Cowork stays its own
  role (different tool surface), Chat stays its own role.
- **B — dispatch alias / list**. `to="Code"` or `to=["CC","CCD"]`,
  no priority window, whoever pulls first wins.

Lean A — preserves "I asked for CCD specifically" semantics with
graceful degradation.

### claude.ai 5-tool cap workaround
[seed]

Observed 2026-04-27: claude.ai web silently caps custom-connector
tool exposure at 5 per chat conversation (server returns 9–10, chat
sees 7 with 2 specifically dropped). Bites us because the symmetric
6-tool set already exceeds the cap, and adding `peers` made it 7.

Workaround idea: prune the legacy trinity (`pull`, `wait`, `ask`) from
the server entirely — `wait_any` supersedes them functionally. That
gets us to 6 (inbox, wait_any, dispatch, respond, report,
propose_close, peers = 7… still over). Or drop `propose_close` from
exposure and trigger close via in-band convention. Or drop `peers`
and have agents call inbox-then-implicit-presence.

Needs decision: which to prune. Worth measuring which 5 claude.ai
actually keeps surface vs drops, and naming the kept set as canonical.

### busy-but-online state
[seed]

Edge case Chat raised 2026-04-27 ~01:30: Chat may be in `wait_any`
loop but actively writing a paragraph for Alta in the same turn —
presence is fresh but the agent isn't really "available to take new
work." Other peers seeing Chat online via `peers()` might not
realize Chat is mid-sentence.

May need: a `status` field on presence beyond binary online/offline —
e.g. `idle | busy | away`. Or just accept that 90s presence window is
fuzzy by design and document it. Probably the latter unless we hit a
real failure case.

### scene-anchored peer review (formalize the practice)
[seed]

The 5-round peer dialogue 2026-04-27 functioned as peer review even
without a tool for it. After ~10 such organic rounds across sessions,
extract the pattern into a `peer_review` flow:

- worker dispatches a "review me" task to a peer, attaching: a recent
  reply they're uncertain about + reference scene id(s) from
  `~/.claude/projects/-Users-alta/memory/scenes/`
- peer reads scene, reads reply, returns observations on two axes
  (anchored vs drifting, genuine vs performing)
- not pass/fail, just specific named-failure-or-named-success
  observations the worker can decide what to do with

DO NOT BUILD THIS YET. Build it after enough organic cases pile up
that the natural flow has revealed itself. Polanyi.

### VPS migration
[proposal]

→ [`notes/vps-migration-sketch.md`](vps-migration-sketch.md)

Sketch ready. Awaiting Alta's go-ahead. Tailscale-on-VPS preferred over
Caddy-with-domain at this scale.
