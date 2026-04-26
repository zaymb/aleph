---
description: Push aleph/SKILL.md body to claude.ai's cloud aleph skill via Chrome MCP (no zip upload needed)
---

Sync the local `~/collab-loop/aleph/SKILL.md` to the cloud-hosted
aleph skill on claude.ai. Bypasses zip upload by using the Edit-text path.

**Prerequisites:**
- Chrome must be open with the Claude extension active (check
  `mcp__Claude_in_Chrome__list_connected_browsers` returns a browser).
  If empty, ask the user to open a Chrome tab so the extension wakes up.
- User must already be signed into claude.ai in that browser.

**Procedure:**

1. **Extract the SKILL body** (everything after the YAML frontmatter):
   ```bash
   awk '/^---$/{c++; next} c==2' ~/collab-loop/aleph/SKILL.md > /tmp/aleph-body.md
   ```
   Read the result. Verify it starts with `# Collaborator mode (aleph)`
   or similar heading.

2. **Connect to Chrome:**
   - `list_connected_browsers` → pick the first one (or only one)
   - `select_browser` with its deviceId
   - `tabs_context_mcp({createIfEmpty: true})` → grab a tabId

3. **Navigate to the skill editor:**
   - `navigate(tabId, "https://claude.ai/customize/skills")`
   - `find(tabId, "aleph skill button")` → click the aleph row
   - `find(tabId, "More options for aleph")` → click it
   - `find(tabId, "Edit menu item, not Edit with Claude")` → click it
     (Read the menu via `read_page(ref_id=...)` if find returns wrong ref —
     menu items are typically labeled "Edit" / "Edit with Claude" /
     "Replace" / "Download" / "Uninstall".)

4. **Inject the new body:**
   - `find(tabId, "Instructions textarea editor for skill body")` → get ref
   - `form_input(tabId, ref, value=<body content from step 1>)`
   - The tool will return a diff (previous → new); confirm new content
     is what you intended.

5. **Save:**
   - `find(tabId, "Save button in the edit dialog")` → click it
   - `screenshot(tabId)` to verify the "Saved changes to aleph" toast.
   - Read the page heading to confirm "Last updated: <today>".

6. **Report:** tell Alta success with the new "Last updated" date, or
   failure with the specific step that broke.

**Don't:**
- Touch Skill name or Description fields. Only Instructions changes.
- Use `Replace` from the dropdown — it opens a native file picker that
  Chrome MCP can't drive (file_upload returns "Not allowed" by browser
  security policy). Edit-text is the only working path.
- Disable or move the skill. Just update body.

**On failure:**
- `Not allowed` from `file_upload` → you accidentally went the Replace
  path, retry with Edit.
- `list_connected_browsers` empty → ask user to open a Chrome tab and
  retry.
- "Saved" toast doesn't appear → screenshot, check for validation
  errors, report to user.
