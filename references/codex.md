# Running this skill in Codex CLI

Codex discovers skills as directories containing `SKILL.md` (frontmatter: `name`, `description`).
User-level skills live in `~/.agents/skills/<name>/` and are available in every repository;
repository skills live in `.agents/skills/`; `/etc/codex/skills` is the system level. Verified with
`codex-cli 0.159.3`. The layout of this repo already matches, so installation is a copy.

## Install

```bash
git clone https://github.com/ikaanakkok/hermes-skill-membean-training.git
mkdir -p ~/.agents/skills
cp -r hermes-skill-membean-training ~/.agents/skills/membean-training
ls ~/.agents/skills/membean-training/SKILL.md     # must sit at exactly this depth
```

Per-repository instead: `mkdir -p .agents/skills && cp -r … .agents/skills/membean-training`.

Codex lists skills by name + description at session start and loads the body only when it picks the
skill, so `references/` and `scripts/` cost nothing until they are used.

## Invoke

- Interactive: `/skills` and pick `membean-training`, or type `$membean-training` to mention it,
  or just ask *"do today's Membean training, 15 minutes"*.
- Non-interactive:

```bash
codex exec -s workspace-write -c sandbox_workspace_write.network_access=true \
  "Do today's Membean training for 15 minutes and report minutes + accuracy."
```

Codex refuses to run outside a git repository — run it from this skill's clone (it is one) or from
any repo you have `cd`'d into.

## Network: the one flag that matters (verified)

Codex sandboxes shell commands, and **loopback is blocked by default** inside that sandbox:

```bash
$ codex sandbox -c sandbox_mode='"workspace-write"' -- curl -sS -m 5 http://127.0.0.1:9222/json/version
curl: (7) Failed to connect to 127.0.0.1 port 9222 after 0 ms: Could not connect to server

$ codex sandbox -c sandbox_mode='"workspace-write"' \
    -c sandbox_workspace_write.network_access=true -- curl -s -m 5 -o /dev/null \
    -w 'http=%{http_code}\n' http://127.0.0.1:9222/json/version
http=200
```

So either run with network access enabled:

```bash
codex exec -s workspace-write -c sandbox_workspace_write.network_access=true "<task>"
```

or, if your build's sandbox misbehaves (bubblewrap/user-namespace errors are common when Codex is
launched from a service context), use process boundaries instead of the sandbox:

```bash
codex exec -s danger-full-access "<task>"
```

Put the flag in `~/.codex/config.toml` if you always want it:

```toml
sandbox_mode = "workspace-write"

[sandbox_workspace_write]
network_access = true
```

## Tool mapping — Hermes helper → Codex CLI

Hermes drives the browser with `browser_exec` helpers. Codex has a shell, so every helper maps to one
`scripts/cdp.py` command (dependency-free, Python 3.8+). Use the absolute path, because Codex's shell
starts in the workspace directory:

```bash
CDP="python3 $HOME/.agents/skills/membean-training/scripts/cdp.py"
```

| Hermes | Codex CLI |
|---|---|
| `goto_url(url)` | `$CDP nav <target> URL --wait 3` |
| `js(expr)` | `$CDP eval <target> '<expr>'` |
| long JS snippets | `$CDP eval-file <target> snippet.js` |
| typing into a cloze input | `$CDP type <target> WORD --selector 'input[name=choice]'` |
| clicking an option | `$CDP click <target> --selector 'li.choice'` / `--text "exact option"` |
| state probe from `references/dom-map.md` | `$CDP probe <target>` |
| dashboard identity read | `$CDP state <target>`, `$CDP account <target> --expect NAME --expect-class CLASS` |
| `vision_analyze(CDN url)` | `$CDP mapimg <target> /tmp/wordmap.png` then `$CDP mapword <target>` or `codex exec -i /tmp/wordmap.png "…"` |

`<target>` is a target-id prefix (4+ chars) or a URL substring; `list` prints them. Pass one
explicitly — the skill forbids driving "whatever tab happens to be current".

## The account gate from a shell

SKILL.md's gate (G1–G4) is executable; `account` exits **0** only on a match and **2** on any
mismatch, so the shell exit code is the gate:

```bash
CDP="python3 $HOME/.agents/skills/membean-training/scripts/cdp.py"

$CDP open https://membean.com/dashboard
$CDP list
$CDP state  <target>        # signed-in | membean-login-page | password-required | unknown
$CDP account <target> --expect "<student name>" --expect-class "English L10 (I)"
echo "gate exit: $?"        # 0 = verified · 2 = stop and report

# only when state says membean-login-page (Google SSO, account chosen by identifier)
$CDP sso <target> --expect student@school.k12.tr
```

Membean shows no account email in the student UI, so the gate matches the dashboard greeting, the
class label, and the `user_id` fingerprint Membean embeds in outbound links (e.g. `3951527`). Pass
whichever of those you know. A password field, 2FA prompt or "Use another account" screen is a hard
stop — Codex must hand the sign-in back to the human.

## Images in Codex

- Attach at start: `codex exec -i /tmp/wordmap.png "Which word spans these clusters? Options: …"`
- Or skip vision entirely: `$CDP mapword <target>` decodes the constellation filename
  (rot13 of `mem<word>bean`) and prints the word — that is enough to answer the map questions,
  which is why the skill works in hosts without image reading.

## Session checklist

1. `cdp.py list` shows the school Chrome (proves the network flag works).
2. `cdp.py account …` exits 0 and the greeting/class are quoted in the answer.
3. `cdp.py probe` on the training tab shows a `type`, a filling `bar`, and choices/submits.
4. After the session: `/dashboard` minutes grew, `/dashboard/training-history` has the row with no
   warning badge.

## Notes and pitfalls

- `-s workspace-write` alone is not enough — without `sandbox_workspace_write.network_access=true`
  every CDP call fails with `curl: (7) / Failed to connect`.
- Sessions kept open and untouched get closed server-side ("you were inactive"), so drive
  continuously; do not pause between steps to summarise.
- `codex exec` exits when done, which kills an in-flight training session mid-way. For sessions
  longer than a couple of minutes prefer the interactive TUI, or keep one `codex exec` turn doing the
  whole loop.
- Codex's shell starts fresh per command: keep `CDP=…` in each command instead of exporting once.
