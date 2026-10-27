# Membean Training — portable Agent Skill

A skill that runs a real Membean vocabulary training session (word cards + graded questions) inside a
**signed-in school Chrome profile**, by driving it over the Chrome DevTools Protocol.

It works in three hosts from the same directory layout — **Hermes Agent**, **Claude Code** and
**Codex CLI** — because the rules live in `SKILL.md`, and every browser action is available as a
one-line shell command through a dependency-free helper (`scripts/cdp.py`).

It answers graded questions from the question text itself (and reads word-map PNGs with a vision
model when the host has one), paces each answer so the server accepts it, and verifies the result on
the dashboard instead of trusting the click.

> Built for the Membean web trainer and one study account. It never types a password, never reads
> answers out of the DOM, and never touches teacher pages, quizzes or assignments.

## The account gate (the point of this skill)

Before **any** training action, three things must be true and stated out loud:

1. **G1 — the expected account is determined.** Name + class label (+ email/fingerprint where the
   page shows one), written down before the browser is touched. Ambiguous or missing → stop and ask;
   never infer it from "the only open tab".
2. **G2 — the session is established through Google SSO only.** If `/dashboard` serves the Membean
   login page, click *Sign in with Google* and pick the account in the chooser by `data-identifier`,
   never by position (the chooser also lists a personal Gmail). Any password field, 2FA prompt or
   "Use another account" → stop, hand the sign-in to the human.
3. **G3 — the identity is verified on the page.** Greeting name + class label (+ the `user_id`
   fingerprint Membean embeds in outbound links) must match G1. Mismatch → click nothing.

The gate is re-run (G4) before starting a session, after any reload/reconnect/pause, before answering
after a sign-in interstitial, and before reporting numbers. Answering questions under the wrong
account writes minutes and accuracy into someone else's record — that is the failure this gate
exists to prevent.

The gate is executable, not just prose:

```bash
$ cdp.py account <target> --expect '<student name>' --expect-class '<class label>'
{ "verdict": "match", ... }      # exit 0
                                 # exit 2 = STOP, report which identity the page shows
```

## What's inside

- `SKILL.md` — the procedure: account gate, session start, training loop, refusal/hang recovery,
  accuracy discipline, verification, pitfalls, and the per-host transport map.
- `scripts/cdp.py` — stdlib-only CDP CLI (Python 3.8+, no pip installs): target discovery, state and
  identity probes, Google SSO click, JS eval, real key events, screenshots, word-map fetch/decode.
- `references/dom-map.md` — verified selector/state map, form fields, question-type catalogue.
- `references/claude-code.md` — Claude Code install, tool mapping, permissions, worked session.
- `references/codex.md` — Codex CLI install, the loopback-network flag, tool mapping, worked session.

Hard-won details encoded there include: answer pacing is validated server-side (8–15 s dwell, faster
= "didn't go through" refusal), the 30–33 s per-question timer, text inputs need real `char` key
events rather than `.value = ...` (synthetic values grade as Incorrect), `cloze_background` word
length comes from `maxLength + 1`, and word-map PNGs are fetched through the page (the CDN answers
403 to direct fetches) with the image filename as a rot13 fallback (`mem<word>bean`).

## Requirements

- A Chrome/Chromium started with remote debugging and a profile already signed in to the school
  Google account:

  ```bash
  google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.hermes/chrome-debug" &
  ```

- Python 3.8+ (standard library only) for `scripts/cdp.py`.
- Optional: a vision-capable model for word-map questions. Without one, `cdp.py mapword` decodes the
  word from the image filename.

## Install

### Hermes Agent

```bash
git clone https://github.com/ikaanakkok/hermes-skill-membean-training.git
cp -r hermes-skill-membean-training \
  "$HOME/.hermes/skills/productivity/membean-training"
```

Set `browser.cdp_url: http://127.0.0.1:9222` in `~/.hermes/config.yaml`; the skill then uses the
`browser_exec` helpers directly (`cdp`, `js`, `goto_url`, `vision_analyze`). Load it with
`skill_view(name='membean-training')`.

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -r hermes-skill-membean-training ~/.claude/skills/membean-training
```

Invoke with `/membean-training` or plain language. Bash + Read are the only tools it needs:

```json
{ "permissions": { "allow": ["Bash(python3 *cdp.py *)", "Read(~/.claude/skills/membean-training/**)"] } }
```

Full mapping and a worked session: [`references/claude-code.md`](references/claude-code.md).

### Codex CLI

```bash
mkdir -p ~/.agents/skills
cp -r hermes-skill-membean-training ~/.agents/skills/membean-training
```

Codex's sandbox blocks loopback by default, so the CDP port is unreachable until you allow network:

```bash
codex exec -s workspace-write -c sandbox_workspace_write.network_access=true \
  "Do today's Membean training for 15 minutes and report minutes + accuracy."
```

Invoke interactively with `/skills` (picker) or `$membean-training`. Full mapping and the verified
sandbox evidence: [`references/codex.md`](references/codex.md).

## The CDP helper

```bash
CDP="python3 <skill-dir>/scripts/cdp.py"
$CDP list                     # page targets
$CDP state  <target>          # signed-in | membean-login-page | password-required | unknown
$CDP account <target> --expect NAME [--expect-class CLASS]   # gate: exit 0 ok / 2 mismatch
$CDP sso    <target> --expect EMAIL      # Google SSO, account chosen by data-identifier
$CDP nav    <target> URL --wait 3        # navigate (Membean needs the full 3 s)
$CDP probe  <target>          # training-step state probe as JSON
$CDP click  <target> --text "exact option"   # or --selector 'li.choice'
$CDP type   <target> WORD --selector 'input[name=choice]'    # real key events + Enter
$CDP key    <target> ENTER|TAB|ESC|SPACE
$CDP eval   <target> '<js>'   # or eval-file for long snippets
$CDP shot   <target> out.png
$CDP mapimg <target> out.png  # word-map PNG fetched through the page
$CDP mapword <target>         # rot13 filename -> the word (no vision needed)
```

`<target>` is a target-id prefix (4+ chars) or a URL substring. Pass one explicitly: this skill never
drives "whatever tab happens to be current" — a stolen tab is how the endless
"previous answer didn't go through" refusals start.

## Usage

Ask in plain language, e.g. *"do today's Membean training, 15 minutes"*. The agent runs the account
gate first, reports the verified identity, then drives the session and reports minutes and accuracy
from the dashboard.

Membean reports accuracy to the teacher. The skill therefore aims for accurate answers, keeps the
session at its chosen length, and reports misses honestly instead of faking a percentage.

## Scope and ethics

Use it on an account you are allowed to use, and mind your school's rules on automated study tools.
The skill is written to behave like a diligent student (real dwell times, real answers, no DOM answer
scraping, no credential handling), but responsibility for using it stays with you.

## License

MIT — see [LICENSE](LICENSE).
