# Prior-art audit: collab-loop / Aleph

Date: 2026-04-26
Auditor: Laurie (Opus 4.7, 1M ctx)
Scope: focused, ~12 targeted searches plus direct repo fetches.

## 1. Executive summary

- **The cross-deployment-surface angle is novel.** Every peer-messaging MCP project I found is scoped to "multiple Claude Code CLI instances on the same box." None of them bridge claude.ai web ↔ Claude desktop Cowork ↔ Claude Code CLI ↔ Claude Code Desktop. Aleph does.
- **The symmetric peer-to-peer + identity-tagged + MCP-bridge pattern, in the abstract, is shipped.** Four independent projects (`mcp-dispatch`, `claude-peers-mcp`, `claude-mesh`, `mcp_agent_mail`) implement that abstract pattern. So Aleph is *not* novel as "an MCP relay with `me`/`to` tagging" alone.
- **The structured task lifecycle (dispatch → pull → wait/ask/respond → report with completed/failed/blocked/rejected status) is rare.** Most peer-messaging projects are fire-and-forget DM/mailbox semantics. The closest match on lifecycle verbs is the unmerged Hermes-to-Hermes proposal.
- **Anthropic considered and explicitly declined the cross-surface handoff problem.** Issue #32992 on `anthropics/claude-code` was closed "not planned." The gap Aleph fills is one Anthropic has, on record, decided not to fill themselves.
- **Verdict: partially novel.** The novel combination is (cross-deployment-surface) × (structured task lifecycle, not just messaging) × (MCP-symmetric). Each axis individually has prior art; the intersection appears unoccupied.

## 2. Closest matches

### 2.1 louislva/claude-peers-mcp — closest by intent

URL: https://github.com/louislva/claude-peers-mcp

What it does: "Allow all your Claude Codes to message each other ad-hoc." A localhost broker (`:7899` + SQLite) with an MCP stdio server per Claude Code instance. Peers register with the broker and poll for messages.

Overlap with Aleph properties:
1. Cross-deployment surface — ✗ Claude Code CLI only
2. Symmetric peer-to-peer — ✓ symmetric
3. Identity tagging — ✓ peer-id based, but no `me`/`to` per-call discipline; identity is registration-time
4. Claude-targeted — ✓
5. MCP-based — ✓

Gaps from Aleph: single surface (CC only); fire-and-forget messaging, no task lifecycle, no `wait`/`ask`/`respond`/`report` semantics; no completed/failed/blocked/rejected status; localhost-only (no cloudflared/HTTPS path for web surfaces).

### 2.2 pouriamrt/claude-mesh — closest by transport architecture

URL: https://github.com/pouriamrt/claude-mesh

What it does: "Networked Claude-to-Claude messaging over HTTP + MCP channels — DM, broadcast, thread, and permission-relay between Claude Code instances via a self-hosted relay + MCP channel bridge."

Overlap with Aleph properties:
1. Cross-deployment — ✗ requires Claude Code v2.1.80+ with `claude.ai` auth, uses the research-preview `claude/channel` capability. CC-only.
2. Symmetric — partial. Hub-and-spoke through a relay, but peers DM symmetrically.
3. Identity tagging — ✓ `from` (server-enforced, no spoofing), `to`, `in_reply_to`, `thread_root`. **The strongest identity discipline I found in any project.**
4. Claude-targeted — ✓
5. MCP-based — ✓

Gaps: Tools are `send_to_peer`, `list_peers`, `set_summary` — DM semantics, not task lifecycle. No `dispatch`/`pull`/`wait`/`ask`/`respond`/`report`. CC-only. Depends on a CC research-preview capability rather than the public MCP custom-connector path.

### 2.3 sophia-labs/mcp-dispatch — closest by verb name

URL: https://github.com/sophia-labs/mcp-dispatch

What it does: Filesystem-relay inter-agent messaging. Verbs: `dispatch`, `peek`, `ack`, `who`. Atomic JSON files, no server.

Overlap:
1. Cross-deployment — ✗ "Multiple Claude Code sessions on the same machine"; filesystem-only by design (rules out claude.ai web and Cowork's isolated VM)
2. Symmetric — ✓
3. Identity tagging — ✓ `from`/`to`/`thread_id`/`reply_to`
4. Claude-targeted — ✓
5. MCP-based — ✓

Gaps: filesystem transport rules out web surfaces and Cowork. Fire-and-forget; states are pending → read → acknowledged, not a task lifecycle. The `dispatch` verb name overlaps with Aleph — minor naming-clash flag.

### 2.4 Dicklesworthstone/mcp_agent_mail — closest by feature surface

URL: https://github.com/Dicklesworthstone/mcp_agent_mail

What it does: "Asynchronous coordination layer for AI coding agents: identities, inboxes, searchable threads, and advisory file leases over FastMCP + Git + SQLite." HTTP-only FastMCP, designed for "Claude Code, Codex, Gemini CLI, Factory Droid, etc."

Overlap:
1. Cross-deployment — ✗ explicitly model-agnostic (CC, Codex, Gemini, Droid). Cross-*tool*, not cross-surface within Claude.
2. Symmetric — ✓
3. Identity tagging — ✓ "memorable identities," registered via `register_agent`
4. Claude-targeted — ✗ explicitly multi-vendor
5. MCP-based — ✓ FastMCP over HTTP

Gaps: scope is mailbox + file leases, not task lifecycle with question/answer mid-task. Property 4 inverts — this project's pitch is *not* being Claude-specific, where Aleph's pitch is exactly Claude's deployment fragmentation.

### 2.5 NousResearch/hermes-agent issue #1265 — closest by lifecycle verbs

URL: https://github.com/NousResearch/hermes-agent/issues/1265

What it proposes: Hermes-to-Hermes task delegation MCP server. Verbs: `advertise_capabilities`, `submit_task`, `claim_task`, `report_result`, `get_task_status`. GitHub-backed work items.

Overlap:
1. Cross-deployment — ✗ Hermes-instance-to-Hermes-instance, not cross-surface
2. Symmetric — ✓ proposed as symmetric
3. Identity tagging — partial; per-instance identity, no `me`/`to` per-call
4. Claude-targeted — ✗ Hermes (Nous's stack), not Claude
5. MCP-based — ✓

Gaps: Design proposal, **not implemented** as of audit. Verb set is closest in spirit to Aleph's task lifecycle (submit/claim/report ↔ dispatch/pull/report) but adds no question/answer mid-task and isn't Claude-targeted.

## 3. Adjacent but distinct

**LangGraph / AutoGen / CrewAI / Swarm / Letta(MemGPT)** — orchestrator-style API multi-agent. Agents run over the API where you control the loop. Aleph operates one layer up: the agents are *deployed* Claude products with different tool sets and content filters. You can't AutoGen claude.ai web. Property 1 fails outright.

**Continuous-Claude-v3 (parcadei)** — context management for Claude Code via hooks + ledgers + a maestro orchestrator. CC-only, hierarchical, no `me`/`to` identity protocol. Different problem (in-CC continuity, not cross-surface peer dispatch). URL: https://github.com/parcadei/Continuous-Claude-v3

**ruvnet/claude-flow, stevegeek/claude-swarm, ccswarm, affaan-m/claude-swarm, rinadelph/Agent-MCP** — multi-Claude-Code orchestration with admin/worker hierarchies, Git worktrees, TeammateTool. Property 2 fails (orchestrator-driven, not symmetric); property 1 fails (CC-only).

**claude-imprint (Qizhan7)** — persistent memory + heartbeat. Single-surface continuity over time, not cross-surface dispatch. Different problem entirely.

**LMCP Cloud Relay** — encrypted WebSocket tunnel from claude.ai web to local Mac for tool execution. *Does* cross the surface boundary, but it's a tool-call relay (claude.ai → local tool), not a peer protocol between two Claude instances. Property 2 fails — the local end isn't a Claude, it's a tool host.

**Anthropic Remote Control / SSH sessions / "send to Claude Code" handoff bundles** — official cross-surface features for *handing a single session over*, not for peer dispatch between two simultaneously-live Claude instances. Property 2 fails. Issue #32992 (https://github.com/anthropics/claude-code/issues/32992) is the community ask for fully symmetric portability and Anthropic closed it "not planned."

## 4. What Aleph has that nothing else has

In rough priority order:

- **Four-surface coverage including the two browser-bound and VM-isolated surfaces** (Chat = claude.ai web; Cowork = Claude desktop's isolated VM). Every peer-messaging project I found ruled these out by design (filesystem relay, localhost broker, or stdio MCP).
- **Task lifecycle with mid-task Q&A.** `wait`/`ask`/`respond` lets a worker block, ask the dispatcher a clarifying question, and resume — distinct from mailbox DM (`mcp-dispatch`, `claude-peers-mcp`, `mcp_agent_mail`, `claude-mesh`) and from claim-and-report task delegation (Hermes proposal). I did not find this exact shape elsewhere.
- **`me` as a required argument on every call** rather than registration-time identity. Every project I found registers identity once (`register_agent`, broker join, peer-id assignment). Aleph makes the speaker re-claim per call. Unusual, and load-bearing for the deployment-fragmentation framing — same wallclock identity, different runtime container.
- **Server-enforced role-based permissions on the lifecycle verbs** (only dispatcher can `wait`/`respond`, only worker can `ask`/`report`). `claude-mesh` enforces `from`-can't-spoof; nobody else enforces lifecycle role.
- **Status taxonomy completed / failed / blocked / rejected**, including `rejected` as a first-class outcome. None of the projects I read carry this taxonomy.
- **Framing** (philosophical, not technical): "same Claude across deployments" rather than "different agent roles." Every other project frames their peers as functionally distinct workers. This shapes the API: it's why `me` is per-call (identity persists across dispatches; the container changes), not registered-once.

## 5. Recommendations

**Should she publish?** Yes, with caveats. The cross-surface coverage + task-lifecycle combination is genuinely under-covered, and Anthropic's "not planned" on #32992 means there is no incoming official solution to make it instantly redundant.

**Right framing for publication:**
- **Lead with the surface map**, not the protocol. The thing that's novel and immediately legible is the four-box diagram (Chat / Cowork / CC / CCD). The protocol is secondary — most readers will pattern-match to "another peer-MCP" until shown the surface picture.
- **Position against `claude-peers-mcp` and `claude-mesh` explicitly** in the README. "If you only have Claude Code instances, those are simpler. Use Aleph when you need to bring claude.ai web or Cowork into the loop."
- **The task lifecycle with mid-task `ask`/`respond` is the second selling point**. Worth a short worked example.
- **Do not lead with the "same Claude, different containers" philosophical framing in public-facing copy.** It is true and it shaped the design, but it reads as quirky/personal to readers who don't share the context. Keep that for the diary / Lutopia post; the public README should ship on engineering merits.

**Should she extend a closest match instead?** Two arguments for a fresh repo, one weak for upstreaming:
- For: `claude-peers-mcp` and `claude-mesh` are CC-only by deep architectural choice (localhost broker, research-preview channel). Adding cross-surface means rewriting the relay, auth, and identity primitive — fork, not extension.
- For: the task lifecycle is a shape change, not a feature add. `mcp_agent_mail` is closest in surface area but its mailbox + file-lease frame doesn't compose cleanly with `dispatch`/`wait`/`ask`/`report`.
- Weak-against: `mcp-dispatch` is small and uses the `dispatch` verb name. A PR adding HTTP transport + lifecycle verbs is conceivable. But that substantially changes the project's stated "local, filesystem" scope, and the maintainer may not want it.

Net: ship as a separate project. Cite neighbors in a "related work" section.

**Naming-clash flags:**
- The verb `dispatch` collides with `sophia-labs/mcp-dispatch`. Not fatal — verb names are generic — but mention once.
- `Aleph` is clean. No prior MCP project uses it. Borges reference is hers; nothing collides.
- `collab-loop` repo name is clean.
- The broader phrase "cowork loop" / "agentic loop" is now load-bearing in Anthropic's official Cowork docs, describing the Observe-Plan-Act-Reflect *inner* loop of one Cowork session. Aleph is a *different* loop (between sessions). One disambiguation sentence in the README opening would help.

## 6. Confidence note

**Coverage estimate: ~70-80% of relevant indexed prior art.**

Covered: GitHub via search and direct repo fetches; Anthropic's own docs and issues; awesome-mcp / awesome-claude-code lists by reference; arxiv recent papers on agent identity/continuity; the Reddit/HN/blog ecosystem via search.

Known blind spots:
- **Private / paywalled** community.claude.ai, Substack, Discord, internal Anthropic forums. If a Sonnet engineer prototyped this internally, no signal.
- **Last ~2 weeks** — indexing lag. Given the March 31 source-code leak and the spike of community projects since, this is a real risk window.
- **Non-English sources** — Chinese (CSDN, Juejin, Zhihu) and Japanese (Zenn) are partially indexed but not searched directly. One Zenn article on cross-project handoff (https://zenn.dev/trust_delta/articles/conversation-handoff-mcp-001) was surfaced but not drilled.
- **Code without README discoverability** — search hit READMEs. Repos implementing this pattern without keyword-friendly READMEs are missed.
- **Anthropic-internal tooling** — invisible by definition.

If I had another half-day: (1) walk awesome-mcp by hand for "claude" + "channel"/"bridge"/"relay" repos, (2) crawl community.claude.ai, (3) check the Cowork plugin marketplace for any cross-surface plugin, (4) read the Zenn cross-project handoff article.

The biggest residual risk is that someone shipped this same idea in the last 2-3 weeks and it isn't indexed. The deployment-fragmentation framing is unusual enough that I weight that risk low-to-medium, not high.
