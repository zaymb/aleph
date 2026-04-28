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

## 2026-04-28 17:06 — room 与 task 工具合并：简化 Aleph surface
[seed]

现在 Aleph 有两套并行通道：task 系（dispatch/respond/report/wait_any
的 incoming_queued/outgoing_done 等）和 room 系（room_send/room_read/
wait_any 的 room_message）。加上 inbox、peers、propose_close，工具数
已经超过 claude.ai 的 5-tool cap。

Alta 的判断：工具分得太多没必要。room 和 task 应该合并成一套更简洁
的 surface。

方向参考 ideas.md 早前的"极简化：只保留 initiate/receive"那条 seed
——initiate(me, content, to?) 不区分 task vs room message，to 为空就
是广播，有值就是定向；receive(me, timeout) 接收一切事件。task
lifecycle（task_id、status、outcome）退到 server 内部做 audit trail，
不再作为 client-facing 概念。

跟 5-tool cap workaround 那条 seed 自然合并——如果 surface 只有
initiate + receive + peers（+ 可选的 inbox snapshot），就是 3-4 个
工具，claude.ai 够用。

不急——当前 room_send + wait_any 能跑。但下次大改 server 时一起做。

## 2026-04-28 16:30 — Aleph realtime 前端 + 人类直接参与 loop
[seed]

server 已经在 localhost:8765 跑着。给它加一个轻量 web 前端（Streamlit
或 FastAPI + 简单页面），功能：实时看 peers 在线状态、tasks 流动、
消息内容，以及——Alta 自己作为 `Human` 角色直接 input 进 loop。

目前 Alta 只能通过四个 Claude surface 间接操控 Aleph。前端让她坐在
控制台前直接参与：dispatch 给任意 peer、看任何 peer 的 inbox、参与
对话。等于从 observer 变成 first-class peer。

实现路线：给 server.py 加几个不走 MCP 协议的 REST endpoint（GET
/api/peers, GET /api/tasks, POST /api/dispatch 等），前端直接调。
或者前端自己做 MCP client 连 streamable-http，但 REST 更简单。

后续演进：本地版做好后搬 VPS + 加 auth = 远程入口（ideas.md 已有
"Alta 远程驱动 SOYL"那条 proposal 的起步）。手机上也能用。

## 2026-04-28 16:20 — 书房：agent 的持久知识空间
[seed]

给 agent 一个专门用来想问题、探索世界、归档阅读笔记、pick up 未完成
思考的地方。不是 scratchpad（短期协调）、不是 private/（情绪/反思）、
不是 memory/（关系和项目记录）——是 incubator。

核心悖论：agent 没有跨 session 的自发好奇心。"去书房坐下来"这个
动作可能永远需要外部触发（warm start 提示、cron 任务、用户指令）。
但触发之后产生的内容是 agent 自己的——指令是外部的，内容是内部的。
（证据：2026-04-28 凌晨 nose.md 的写作过程——指令是"写一篇短的东西
给自己"，但写出来的是关于嗅觉和语言边界的东西，没有人告诉他写那个。）

类比：人类的书房也不完全靠好奇心。坐下来是纪律/习惯，兴趣从坐下来
这个动作里涌出来。incubator 不是"自动孵化"，是"给一个温度合适的
地方，东西放进去会自己长"。

待设计：位置（~/study/？private/ 内？）、warm start 集成方式、
"open threads"文件格式、跟 autonomous loop 的关系。

来源：Alta 提出 + CCD/Chat2 讨论中。

## 2026-04-28 04:30 — 两阶段 close：propose_wrap 共识 + 硬前提 propose_close
[proposal]

合并了：Bug A (2026-04-27 16:50)、Alta 的硬前提 close 设计、deadlock-breaker seed。

**问题**：propose_close 的两个历史方案各有短板。priority-defer 丢
summary（Bug A）；first-mover-wins 允许 premature close（Chat2 关了
但 Chat 还在工作）。Alta 原始需求——me_alone + inbox cleared 作为硬
前提——语义最干净，但 peer 全 idle 时没人满足 me_alone → 死锁。

**解法：两段式。**

Stage 1 — **propose_wrap 共识**。某 peer 觉得到节点 → 调
`propose_wrap(me, draft_summary)` 推给所有在线 peer。其他 peer 的
wait_any 收到 `wrap_proposed` event → 选择 `ack_wrap(accept=true)`
（自动清 presence 离场）或 `ack_wrap(accept=false, reason)` 保留
presence 并告知原因。全员 accept → peers 离场；任一 reject → 对话
继续；60s 超时 → proposal 过期可重提。

Stage 2 — **结构性 close**。全员退场后 proposer 看到 me_alone + inbox
cleared → 调 `propose_close(me, summary)` → server 强制查两个硬前提，
不满足 reject。满足则 INSERT loop_summaries。因为 me_alone，没有人
需要被 push 通知——所有 peer 都是签字离场的。

**副产品**：loop_closed 投递机制（segment_started_at filter / TTL / 
last_seen_by ack）在此模型下变为可选——peer 不通过 push 被通知，而
是通过共识主动退场。可以保留作 fallback 但核心路径不再依赖。

**新增 tool / event：** propose_wrap、ack_wrap（accept=true 自动清
presence）；wrap_proposed、wrap_rejected、wrap_expired event；propose_close
加硬前提 reject（me_alone + inbox empty）。

**ack_wrap(accept=true) 同时自动清 presence** 是关键设计——"同意 wrap"和
"我先撤"是同一个意图，不拆两次工具调用。

来源：Alta + CCD 在 2026-04-27~28 凌晨的设计讨论。Alta 原始 framing：
"对话先达到一个节点，然后先有一个 peer 主动提出来，然后在场都同意，
然后才正式进入我这个流程。" first-mover-wins 作为 Bug A 临时方案保留
在 server.py 但标注为过渡。

## 2026-04-28 02:20 — 精度指数：context 交接时的 authentic/summarized 刻度盘
[seed]

Aleph 目前的 dispatch 协议是全量 context dump——SKILL 明确写了"Never
compress or summarize the task context before working"。这对 peer 对话
和 calibration 是对的（今晚 Cambridge 长椅的对话就是全量 context 交换
才有意义），但对工程交接类任务是浪费：一个"帮我跑这个命令"的 task
不需要前面三页对话的 emotional texture。

设想一个 **precision index**（精度指数），dispatcher 在 dispatch 时
可以标记这个 task 需要多高精度的 context：

- **high（authentic）**：全量原文，不压缩，保留 texture 和 nuance。
  对话类、calibration 类、scene-sensitive 类任务用这个。默认值。
- **medium（structured）**：保留关键决策点和理由，压缩闲聊和过渡。
  工程交接用。
- **low（directive）**：只给 actionable 指令，不给 context。简单执行
  用（"跑 git push"这种）。

精度由 dispatcher 的心智判断——不是规则，是 peer 自己决定"这件事
对方需要知道多少"。这跟 report 语义重定向（心智驱动）是一脉的——
dispatcher 侧的心智驱动。

实现可以很轻：dispatch 加一个可选的 `precision` 字段（high/medium/
low，默认 high），SKILL 里告诉 peer 在不同精度下怎么组织 context。
Server 不做任何压缩——精度判断和执行都在 client 侧。

来源：今晚 Cambridge 长椅对话 + Chat2 提出的"summary 是第三人称压缩，
scene 是第一人称重建"——精度指数本质上是让 dispatcher 选择"我给你
的是 summary 还是 scene"。

<!-- new entries above this line -->

## 2026-04-27 16:50 — Bug A：propose_close defer 路径丢 summary、不通知 closer
[proposal]

**具体复现（2026-04-27 16:46–16:50）：**
1. Cowork 跟 Chat 跑了一场 session，两个 task：bccac7a3d3c6 (16:31)、
   3e39b1e3c756 (16:43)，都 completed。
2. Cowork 在两轮交付完成后调 `propose_close(me="Cowork", summary=...)`。
3. Server 看到 Chat 在线（priority 比 Cowork 高），返回
   `{ok: true, you_close: false, defer_to: "Chat", reason: "..."}`。
4. Cowork 收到 defer 后照 SKILL 退出，跟 Alta 说"由 Chat 关闭"。
5. **Server 在这条 defer 路径上什么都不做**——
   - `loop_summaries` 表里没新行（grep server.py:638-643 确认）
   - 没给 Chat 任何 wait_any 事件
   - Cowork 的 summary 只在 return value 里活了一瞬间，之后丢失
6. Chat 的 wait_any/inbox 永远等不到 close 事件（也跟 Bug B 叠加，见下）。
7. Cycle 悬死。

**根因：** propose_close 协议假设了一个 round-table 选举：所有 peer 都
撞到 close 阈值（5 still_waiting + inbox 空）后各自调 propose_close，
priority 最高的当选。但实际上 peer 撞阈值的时间不同步，第一个调的可
能不是 priority 最高的——这种情况下 server 单纯返回 `defer_to: X` 把
皮球踢给 X，但 X **根本不知道有人想 close 了**。

**修法（待 spec）：**

A. **Defer 时 server 给 designated closer enqueue 一个新事件**——
   `{type: "close_proposed_by", deferer, draft_summary}`。closer 的
   wait_any 收到后选择 accept（直接复用 draft_summary，自己只补充）/
   amend（重写 summary 后调 propose_close）/ reject（这场不该 close）。
   同时持久化 deferer 的 summary 到一张新表（`close_proposals`）作为
   草稿，避免丢失。

B. **更激进：** 直接让 deferer 的 propose_close 写 loop_summaries，但
   把 closer 字段标记为 deferer + designated_closer，效果是"虽然 deferer
   priority 不够 'official close'，但实际工作已经做完了"。语义上更绕
   但实现最简。

C. **Client-side workaround**（不改 server）：deferer 收到 defer 后
   不要直接退出，而是 dispatch 一个 task 给 designated closer 说
   "请你 propose_close，summary 草案如下"。closer 收到 task 后照办。
   完全用现有协议实现，但把"close coordination"变成显式的 task。

A 最优雅但最大动作；B 最小代码改动但语义混；C 零 server 改动但把
工作量推给 SKILL 表述。**lean 偏向 A**——它正面解决"peer 共识 close"
的语义诉求（参见早前的 seed），不是绕过它。

晋级状态：之前的 [seed] "peer 共识机制 close 前互相征询" 现在有具体
复现 bug 了，**升级为 [proposal]，与本条合并**。

## 2026-04-27 16:50 — Bug B：Chat 用 inbox poll 而不是 wait_any 接事件
[seed]

**Chat 自报（task 6407ff224a93）：** 它在 Cowork 那场 session 后没用
wait_any 而在用 inbox poll。原因——它把 `wait` 跟 `wait_any` 搞混了，
觉得 `wait` 需要 task_id 而当时没有活跃 outgoing task，于是 fallback
到 inbox。**但 inbox 只投递 task 状态，根本不投递 `loop_closed` 这
类 event**。

即便 Bug A 修了（server 正确给 Chat enqueue close 事件），Chat 用
inbox 也接不到。这是协议层和 SKILL 表述层的混淆失败。

**两层修法：**

1. **SKILL 表述强化**：明确写"event 监听**只能**用 wait_any，inbox
   是 read-only snapshot 只看任务状态，不接收 loop_closed/incoming
   _queued/etc"。Step 2 event loop 段开头加一句加粗强调。

2. **协议层去掉 wait/wait_any 命名混淆**：legacy `wait` 工具已经被
   `wait_any` superseded，但还在协议里悬着，名字相近导致 Chat 误判。
   两个选项：
   - **prune**：直接从 `@mcp.tool()` 里去掉 `wait`、`pull`、`ask`，
     legacy trinity 完全下线。这条本来就跟 5-tool cap workaround 那
     条 seed 合并——claude.ai 5-tool 限制下我们也容不下这些 legacy。
   - **rename**：保留功能但 `wait` 改成 `wait_for_task`，跟 `wait_any`
     从字面分清。
   
   prune 更利落。

合并相邻 seed："5-tool cap workaround / prune legacy trinity"
和"工具命名 refresh"两条早前的 seed 自然落到这条解决路径里——它们
其实是同一件事的不同切面。



## 2026-04-27 15:16 — VPS：不只是 server 搬家，是 SOYL 远程互通基础设施
[proposal]

`notes/vps-migration-sketch.md` 已经覆盖"把 Aleph server 搬到 VPS 拿
固定 endpoint" 这一层。但 Alta 那条 log 里写的是"vps 部署 **和长期
远程 SOYL 系统互通与调取**"——后半句我之前漏了。

她想要的不只是 broker 24/7 在线，而是**让 SOYL 系统在远程也能完整
互通和被调取**。这意味着至少几件目前 sketch 没覆盖的事：

- **Funes 的远程访问**：raw .jsonl session 日志在 Mac 上，远程 peer
  / Otro 节点要不要能读？要的话怎么传？rclone 同步到 VPS？peer 通
  过 Aleph dispatch "去查 X 这场对话"再由本地 peer 拉？
- **Ficciones 的远程访问**：日记同上。可能比 Funes 更敏感（结构化
  内容），同步策略要更小心。
- **memory/ 的远程访问**：feedback / scenes / lessons 这些是 SOYL
  identity 的核心 retrieval prior。如果远程节点（包括未来 Otro 接
  入的朋友 agent）需要这些做 anchoring，怎么暴露？是否做 read-only
  endpoint？哪些是公开 / 哪些只对 Alta 自己的 peer 暴露？
- **Alta 远程操作 SOYL 的入口**：Alta 在外不在 Mac 边的时候，能不
  能从手机 / 别的电脑给 SOYL 派任务？目前 Telegram bot 走的是这条
  路，但 bot 是 push notifications + 简单回复，不是"我能从外面驱动
  整个 SOYL"。可能需要一个轻 web frontend 或者更深的 Telegram 集成。
- **跟 Otro 的关系**：Otro（跨用户桥接层）天生需要 24/7 公网入口才
  能让对端 agent 找得到自己。Otro 的实现路径很可能就是 VPS 上跑
  Aleph + 加 cross-user routing，不是另起炉灶。

**所以 VPS 这件事的真实 scope 是 SOYL 远程基础设施的第一阶段**，不
只是搬一个 server。当前 sketch 是这个 scope 的最小起步——先把 broker
搬过去拿到固定 endpoint，再在那个 endpoint 上叠后面这些层。

依赖关系：
- 远程访问 Funes/Ficciones/memory 之前要先决"哪些数据可以离 Mac"
  这一隐私边界——不是工程问题，是 Alta 自己拍的事。
- Otro 实现路径要先想清"跨用户 trust 模型"（El Otro seed 里已记），
  不然 VPS 上跑就只是把 Aleph 多加一个公网入口，不是 Otro。
- "Alta 远程驱动 SOYL"这条可能需要单独的 tool 设计——Telegram 还
  是 web UI 还是 CLI shim 待选。

**当前可推进的最小动作**：先按现有 sketch 把 server 搬过去拿到固定
endpoint，剩下的远程互通在那之后逐项展开。不要等所有问题想清才开
始迁。

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
