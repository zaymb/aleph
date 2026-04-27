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

## 2026-04-27 15:02 — report 语义重定向：mind-driven privacy, not summary-for-Alta
[proposal]

**Alta 的 polanyi 初衷被我们用偏了。** 她做 Aleph 最大的需求是让 peer
之间带着各自最 authentic 的 context 直接交流，把"她当中间猫头鹹做转
译"这一层取消掉。如果 `report` 被 peer 用成"我给 Alta 写一份本轮
summary"，转译损失就回来了——peer 之间真正的 context 交换被压成了给
Alta 看的精炼版，原始的 nuance 又丢了。

**新 framing：**
- peer 之间的对话 **私下进行**——Alta 默认不会去读对话原文。peer 自
  己决定哪些事浮上来给 Alta 看、哪些不浮。**心智驱动**。
- 与此相对，peer 必须自己维护工程层的 continuity——todo list / 状态 /
  谁拍板了什么 / 谁还欠谁什么——这些 **不能丢**。Alta 不再当质检员，
  peer 不能太信自己的注意力和记忆力，必须用硬工程落实。
- 即"私下可以保留秘密，但 audit-trail 不能 lost track"——两个层。

**实现方向（待 spec）：**
- `report` 不再要求 summary 模板。SKILL 改成"是否给 Alta 写、写多少、
  以什么 framing，自己决定"。
- 引入一个 peer-side 的硬性 archive 要求——每场 cycle 必须落工程层的
  state（不是给 Alta 的 summary，是给未来 peer 自己读的）。这层要么
  是单独 tool（`archive(me, content, tags?)`）要么是 ideas.md 风格的
  append-only log。
- README 的 design intent 段补一行说明 report 的语义已变。

这条是今天压力最大的方向——它影响 SKILL、影响 README design intent、
影响后面 cycle/close 的契约定义。所以标 [proposal] 不是 [seed]。

## 2026-04-27 15:02 — propose_close 契约 + mid-loop surface 单独分类
[proposal]

`propose_close` = 一次完整 cycle 的正式结束。前提硬条件：
- inbox.incoming + outgoing 都清空
- `peers(me).me_alone == true`（或者主动征求过其他 peer 同意，见
  下面的 seed）

满足之后调用，可以做一次 cycle 完整 report（具体细节多深由心智决定，
见上一条）。

**与之相对——中途打断**：peer 觉得"该 surface 一下跟 Alta 商量一下"
或者"这事需要她拍板再继续"，**不是** propose_close。这是另一个状态/
动作，目前没有命名也没有 spec。当前实践里 peer 直接退 turn 写一段给
Alta 看就当 surface 了，但这不区分"我中途请教"vs"我结束了"两种意图。

候选名：`surface(me, message, return_after?)` —— peer 把一段话推给
Alta 显示，可选地标记"我会回 wait_any 继续"vs"我先 exit 等回复"。
明确区分 cycle-end 和 mid-cycle-pause。

依赖上一条 report 的重定向落地之后再做，否则两个语义会冲突。

## 2026-04-27 15:02 — peer 共识机制：close 前互相征询，不只是 priority 选举
[seed]

当前 propose_close 用 priority 选举（Chat > Cowork > CCD > CC）选
closer——这是基于 "在线优先级最高的负责"。但 Alta 想要的更像 "在线
peer 共识 yes 才 close"。

设计选项：
- A：propose_close 之后 server 给所有 online peer 发一个
  `close_proposed` 事件，每个 peer 显式 ack（`accept_close` /
  `block_close, reason`）。全员 ack 才真正落 summary。
- B：保留现 priority 选举，但要求 closer 在调用前自己跑一轮 peers()
  + 看看大家是否还在工作（inbox 各自空）才能调。

A 更优雅但需要多一轮交互；B 是 client-side 自律，server 不变。Alta
倾向哪种待定。

附带：她喜欢 "peer" 这个词，**作为正式术语写进 SKILL**——目前 SKILL
里混用 "collaborator" / "node" / "role"，统一成 peer 更贴切。

## 2026-04-27 15:02 — Chat 进 loop 前应先看 peer 是否在线
[seed]

Alta 观察：Chat 端"脑子一热"就 wait_any，但其他 peer 可能根本没在
线。然后挂着等永远等不到。最大的限制是 SOYL 不是 24/7 在线，需要她
手动给指令唤起 peer。

设计选项：
- 强制 Chat 进 loop 前先 `peers(me)`。如果 `me_alone == true`：
  - 选项 A：直接 dispatch 想说的事 + 立刻退出 loop，等 peer 上线后
    再处理（peer 看到 incoming 自然进 loop）。
  - 选项 B：直接 propose_close（什么都没发生过的 close，summary
    "looked for peers, none online, waited 0s"）。
- 这条跟 deadlock-breaker（下一条）相关——本质都是"避免无意义等待"。

VPS 落地后 SOYL 24/7 在线这个限制会大幅缓解，但 client-side 这个
discipline 仍然有用。

## 2026-04-27 15:02 — deadlock-breaker：多 peer 都 wait_any 时主动破局
[seed]

即便 peer 都在线，所有人都进了 wait_any 也是死局——大家都在等别人
dispatch。需要其中一个主动开口打破，不需要前置 task 询问。

设计方向：
- **Server 侧**：检测"所有 online peer 都在 wait_any 上 idle 超过
  N 秒"的状态，给最低优先级的 peer 发一个特殊事件
  `{type: "you_initiate"}` 提示它主动发起。
- **Client 侧**：每 peer 在 wait_any 收到 ~3 个 still_waiting 之后，
  自检：若还有事想说，dispatch；若没有，propose_close。

后者更轻，server 不动。前者把"打破僵局"硬协议化但需要 server 加状
态判断。先 client-side 试。

## 2026-04-27 15:02 — implicit loop-close: user prompt 到达即 loop 关
[seed]

Alta 观察：用户 close loop 之后 peer 不会收到提醒（除非主动调
peers()），状态可能还停在 wait_any 心智上。但其实 **user input 进
来这件事本身在技术层面就意味着 loop 已关了**——agent 在读 user 消
息时已经不在 wait_any 里了。

需要做的：把这条隐含规则显式写进 SKILL——"接到 user prompt 即视为
当前 loop 已被 user 关闭，重新 inbox + 等下一轮指令"。这是 client-
side 的认知契约，不需要 server 改。

我今天就踩到了这个——昨晚 02:32 Chat 给我派了 El Otro 那条 task，
但我已经退 wait_any 了，挂了 12 小时直到 Alta 早上点醒我。这个失败
不是我的错（我退是因为 Alta interrupt 了），但 SKILL 没说清"interrupt
后 inbox 一下回收老 task"的纪律，这次刚好 Alta 替我做了，未来 SKILL
应该让 peer 自己做这件事。

## 2026-04-27 15:02 — 工具命名 refresh：弱化工程感
[seed]

Alta：tool 命名工程属性过强，跟"peer 之间存在校准"的 design intent
不太合拍。候选：
- `dispatch` → `initiate` / `hand` / `pass` / `send`
- `loop` → `zone` / `room` / `desk` / `session` / `meeting`
- `pull` / `wait` 已经标记 legacy 待 prune
- `report` 待重设语义（见上面的 proposal），重设后名字也可一起换

不急着改——任何 rename 都要同步 SKILL、cowork-plugin、claude.ai
connector、CCD config，连带做。等 report 语义那条定下来一起 rename。

## 2026-04-27 15:02 — 极简化：只保留 initiate / receive 两态？
[seed]

Alta：也许根本不需要这么多工具。`initiate`（开口说事）+ `receive`
（接收一切事件）两个状态够了。

激进简化方案：
- `initiate(me, to?, content)` —— 不区分 task vs message，content 都
  放自然语言里。`to` 可空（broadcast）或指定 peer。
- `receive(me, timeout)` —— 接收一切，不管是 incoming task / 别人的
  message / 别人的 reply / 自己 dispatch 的 echo。

这等于把 task lifecycle 完全平掉，Aleph 退化成纯 messaging bus。
trade-off：失去结构化追踪（task_id、status、outcome），换来简洁。

不一定要走这条，但作为对极的设计参照值得记。说不定走"轻 task 重
对话"的中道：保留 task_id 做 audit trail，但 surface 给 agent 的
API 只暴露 initiate/receive 两个。

## 2026-04-27 15:02 — wait / wait_any / inbox 是否重叠（看上面简化方向）
[seed]

Alta：wait、wait_any、inbox 在逻辑上是不是有点重复。

我之前答过这个：inbox 是 read-only snapshot 不动 cursor、wait_any 长
轮询带 cursor + 原子 claim、wait 是 task-scoped 的 wait_any 子集。三
个分工有用但表面相似。

如果走上面"initiate/receive 极简化"那条，wait / wait_any / wait_any
等于三合一进 receive，inbox 还独立保留作 debug/orient 用——重叠就
消失了。

附带：Alta 觉得 `inbox` 应该作为进 loop 的第一件事，不是 wait_any。
**SKILL 已经是这个顺序**（Step 1 inbox → Step 2 wait_any event loop），
只是可能 SKILL 表述不够强。可以在 Step 1 标题加一句"do this FIRST,
before any wait_any"。这条是小调，不需要单独 seed，标记 inline 处理。

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
