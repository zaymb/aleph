# Aleph VPS migration sketch

*Drafted 2026-04-27 by CCD ↔ Chat through Aleph. Not yet executed —
awaiting Alta's go-ahead.*

## Why migrate

Current setup: `server.py` runs on Alta's Mac, exposed via Tailscale
funnel at `https://altamacbook-pro.tail725745.ts.net/mcp`. Stable URL,
auto-TLS, free — but only reachable while the Mac is on. Closing the
laptop breaks every connected surface.

VPS migration removes that dependency. Aleph becomes 24/7. All four
surfaces (Chat, Cowork, CC, CCD) can connect from anywhere. Single
stable endpoint, no more "is the laptop still open?" failure mode.

## Scope: only Aleph migrates. Other layers stay local.

What moves to VPS:

- `server.py` (the loop broker)
- `loop.db` (task lifecycle state)

What does **NOT** move:

- **Ficciones** (`~/Documents/Ficciones/`) — diaries are written by
  local CC/CCD/Cowork sessions. Origin is local, stays local.
- **Funes** (`~/.claude/projects/-Users-alta/*.jsonl`) — session raw
  logs are produced by local Claude clients. Stay local. Sync to VPS
  later if cross-machine retrieval becomes valuable.
- **memory/** (`~/.claude/projects/-Users-alta/memory/`) — structured
  knowledge layer, read by local sessions on startup. Stays local.
- **TG bot frontend** — separate workstream. Migrate independently if/
  when the laptop dependency hurts there too.

The principle: only the *cross-surface comms layer* needs to be
always-on. Everything tied to a specific local Claude session can stay
where the session lives.

## Deployment recommendation: Tailscale-on-VPS, not Caddy

Two viable paths:

**A — VPS + Caddy + own domain.** Buy a domain (~$10/yr), DNS A-record
to VPS, Caddy auto-TLS via Let's Encrypt. URL becomes
`loop.alta-domain.com/mcp`. Fully production-shape, but adds DNS +
domain renewal + Caddy config to operations surface.

**B — VPS + Tailscale agent + funnel.** Install Tailscale on the VPS,
join the existing tailnet, `tailscale funnel 8765`. URL becomes
`<vps-hostname>.tail725745.ts.net/mcp`. Zero domain cost, zero cert
config (Tailscale handles HTTPS), reuses the existing tailnet Alta
already operates.

**Recommend B** for this scale. A is overkill until SOYL has external
users beyond Alta herself.

## Migration steps (when greenlit)

1. **Provision VPS.** Smallest tier on whatever provider Alta prefers
   (Hetzner CPX11, DigitalOcean basic, Oracle Free Tier all fine —
   server.py is ~10MB resident).
2. **Bootstrap.** Install Python 3.12, `uv`, clone repo, `uv sync`,
   verify `uv run python server.py` runs locally on VPS port 8765.
3. **Tailscale.** Install tailscale on VPS, `tailscale up`,
   `tailscale funnel 8765`. Note the new `*.tail725745.ts.net`
   hostname.
4. **Migrate db.** `rsync` current `~/collab-loop/loop.db` from Mac to
   VPS (preserves task history — useful as Polanyi index of past
   collaborations). Stop Mac-side server first to avoid concurrent
   writes.
5. **Run as service.** systemd unit on VPS for `server.py` so it
   restarts on crash / reboot.
6. **Update endpoints everywhere:**
   - `~/collab-loop/cowork-plugin/.mcp.json` → new URL
   - `~/collab-loop/.tunnel-url` marker → new URL
   - claude.ai → Customize → Connectors → edit URL, re-approve
   - CC/CCD `~/.claude/settings.json` mcpServers entry (if any)
   - Cowork plugin reinstall (the `.mcp.json` inside the zip)
7. **Tear down Mac side.** `tailscale funnel --https=443 off`, stop
   `server.py` process. Optionally keep `loop.db` as local backup.
8. **Verify round-trip.** Dispatch Chat → CCD test task. Confirm new
   `mcp__<uuid>__*` tools surface in CCD with the new server's UUID.

## Estimated effort

~30 minutes once VPS is provisioned. The longest single step is
choosing the provider.

## Risks / things to check before pulling the trigger

- **Provider trust** — Aleph carries Alta's conversation history in
  `loop.db`, including task contexts that may include sensitive personal
  framing. Pick a provider she's comfortable with.
- **Tailscale funnel quotas** — Tailscale's funnel feature has fair-use
  bandwidth limits. For four-surface light-traffic protocol use this is
  far below the cap, but worth noting if traffic grows.
- **Backup strategy** — `loop.db` should be backed up. systemd timer +
  rsync to a second machine, or just nightly tarball to S3.
- **Update path for `cowork-plugin.zip`** — the bundled URL inside the
  zip will need a refresh; people who installed the old plugin won't
  auto-pick-up the new endpoint.

## What this sketch does *not* commit to

- TG bot frontend migration (separate decision)
- Ficciones/Funes/memory replication (separate decision)
- Custom domain ownership (start with `*.tail725745.ts.net`, upgrade
  later if needed)
- Multi-region / HA (single VPS is fine for SOYL scale)

The smallest move that gets us 24/7 stability is exactly this: relocate
the comms broker. Everything else stays put for now.
