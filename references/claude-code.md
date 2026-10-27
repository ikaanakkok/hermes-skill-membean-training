# Running this skill in Claude Code

Claude Code reads personal skills from `~/.claude/skills/<name>/SKILL.md` (project skills from
`.claude/skills/<name>/`). This skill's layout is already Agent-Skills compatible, so installation is a
copy — no conversion.

## Install

```bash
git clone https://github.com/ikaanakkok/hermes-skill-membean-training.git
mkdir -p ~/.claude/skills
cp -r hermes-skill-membean-training ~/.claude/skills/membean-training
ls ~/.claude/skills/membean-training/SKILL.md        # must exist at this exact depth
```

`references/` and `scripts/` ride along; Claude Code keeps them out of context until the skill loads
and the agent opens them.

## Launch with the Chrome already running

The skill drives a Chrome that was started with remote debugging — start it before the session:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.hermes/chrome-debug" &
python3 ~/.claude/skills/membean-training/scripts/cdp.py list   # sanity: prints page targets
```

Chrome's `--chrome` integration is **not** used and not needed; everything goes through CDP.

## Invoke

Interactive session, either of:

- `/membean-training` — explicit skill invocation (skills resolve as slash commands).
- Plain language: *"today's Membean training, 15 minutes"* — Claude matches on the skill description.

Print mode:

```bash
claude -p "Do today's Membean training for 15 minutes and report minutes + accuracy." \
  --allowedTools 'Bash,Read' --max-turns 40
```

Keep `Bash` allowed (that is how it drives the browser) and keep `Read` allowed (word-map PNGs).

## Tool mapping — Hermes helper → Claude Code

Hermes skills call `browser_exec` helpers (`goto_url`, `js`, `cdp`, `vision_analyze`). In Claude Code
those do not exist; every one of them has a one-line shell equivalent through
`scripts/cdp.py` (dependency-free, Python 3.8+). Use an absolute path:

```bash
CDP="python3 $HOME/.claude/skills/membean-training/scripts/cdp.py"
```

| Hermes | Claude Code |
|---|---|
| `goto_url(url)` | `$CDP nav <target> URL --wait 3` |
| `js(expr)` | `$CDP eval <target> '<expr>'` |
| `js()` with a long snippet | write it to a file, `$CDP eval-file <target> file.js` |
| `cdp("Input.dispatchKeyEvent", …)` | `$CDP type <target> WORD --selector 'input[name=choice]'` |
| `click_at_xy` | not needed — `$CDP click <target> --selector CSS` / `--text "exact option"` |
| `vision_analyze(image_url=CDN)` | `$CDP mapimg <target> /tmp/wordmap.png` then `Read /tmp/wordmap.png` |
| state probe from `references/dom-map.md` | `$CDP probe <target>` |
| dashboard identity read | `$CDP state <target>` / `$CDP account <target> --expect NAME --expect-class CLASS` |

`<target>` is a target-id prefix (4+ chars) or a URL substring; `list` prints them. Always pass one —
the skill forbids driving "whatever tab happens to be current".

## The account gate from a shell

The gate in SKILL.md (G1–G4) is executable, not just prose — `account` exits **0** only on a match:

```bash
CDP="python3 $HOME/.claude/skills/membean-training/scripts/cdp.py"

$CDP open https://membean.com/dashboard          # or reuse an existing Membean tab
$CDP list
$CDP state  <target>                             # signed-in | membean-login-page | password-required
$CDP account <target> --expect "<student name>" --expect-class "English L10 (I)"
echo "gate exit: $?"                             # 0 = identity verified, 2 = mismatch (stop)

# only if state says membean-login-page: Google SSO, account picked by identifier
$CDP sso <target> --expect student@school.k12.tr
```

Membean does not print the account email anywhere in the student UI, so the gate matches on the
dashboard greeting, the class label, and the account fingerprint (`user_id` it embeds in outbound
links, e.g. `3951527`) — pass whichever of those you know to `--expect`.

Anything that demands a password, a 2FA code, or an "Use another account" flow stops the skill:
Claude Code must hand that back to you, never type it.

## Permissions (avoid a prompt per command)

`~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 *cdp.py *)",
      "Read(~/.claude/skills/membean-training/**)"
    ]
  }
}
```

Adjust the path if you installed at project level. Do not grant `--dangerously-skip-permissions` for
this: the skill needs exactly `Bash` + `Read`.

## Session checklist

1. `cdp.py list` shows the school Chrome.
2. `cdp.py account …` exits 0 and the greeting/class were quoted in the reply.
3. `cdp.py probe` on the training tab returns a `type`, a filling `bar`, and choices/submits.
4. After the session: `/dashboard` minutes grew, `/dashboard/training-history` has the row with no
   warning badge.

## Notes and pitfalls

- Claude Code's Bash tool may run each command in a fresh shell — keep `CDP` in every command rather
  than exporting it once.
- `wait_for_load`-style waiting is not available: `cdp.py nav/reload` sleep 3 s by default
  (`--wait`), then `probe` again. Membean's ExtJS bundle needs the full 3 s.
- If `Read` refuses the PNG, use `$CDP mapword <target>` — the constellation filename is rot13 of
  `mem<word>bean`, which names the word without any vision call.
