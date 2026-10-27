# Membean Training — Hermes Agent skill

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill that runs a real Membean
vocabulary training session (word cards + graded questions) inside a **signed-in school Chrome
profile**, by driving it over the Chrome DevTools Protocol.

It answers graded questions from the question text itself (and reads word-map PNGs with a vision
model), paces each answer so the server accepts it, and verifies the result on the dashboard instead
of trusting the click.

> This is built for the Membean web trainer and one study account. It never types a password, never
> reads answers out of the DOM, and never touches teacher pages, quizzes or assignments.

## The account gate (the point of this skill)

Before **any** training action, three things must be true and stated out loud:

1. **G1 — the expected account is determined.** Email + greeting name + class label, written down
   before the browser is touched. Ambiguous or missing → stop and ask; never infer it from "the only
   open tab".
2. **G2 — the session is established through Google SSO only.** If `/dashboard` serves the Membean
   login page, click *Sign in with Google* and pick the account in the chooser by
   `data-identifier`, never by position (the chooser also lists a personal Gmail). Any password
   field, 2FA prompt or "Use another account" → stop, hand the sign-in to the human.
3. **G3 — the identity is verified on the page.** Greeting name, class block, and (when ambiguous)
   the account email must match G1. Mismatch → click nothing.

The gate is re-run (G4) before starting a session, after any reload/reconnect/pause, before answering
after a sign-in interstitial, and before reporting numbers. Answering questions under the wrong
account writes minutes and accuracy into someone else's record — that is the failure this gate
exists to prevent.

## What's inside

- `SKILL.md` — the procedure: account gate, session start, step-by-step training loop, refusal and
  hang recovery, accuracy discipline, verification, pitfalls.
- `references/dom-map.md` — verified selector/state map: state probe, form fields, question-type
  catalogue, login flow, history pages.

Hard-won details encoded there include: answer pacing is validated server-side (8–15 s dwell, faster
= "didn't go through" refusal), the 30–33 s per-question timer, text inputs need real `char` key
events rather than `.value = ...` (synthetic values grade as Incorrect), `cloze_background` word
length comes from `maxLength + 1`, and word-map PNGs are fetched through the page and passed to the
vision model locally.

## Requirements

- Hermes Agent with the `browser_exec` toolset (CDP helpers: `cdp`, `js`, `goto_url`, …).
- A Chrome/Chromium started with `--remote-debugging-port=9222` and a profile that is already signed
  in to the school Google account, e.g.:

  ```bash
  google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.hermes/chrome-debug"
  ```

  and in `~/.hermes/config.yaml`:

  ```yaml
  browser:
    cdp_url: http://127.0.0.1:9222
  ```
- A vision-capable model for the word-map questions (`vision_analyze`).

## Install

```bash
git clone https://github.com/ikaanakkok/hermes-skill-membean-training.git
cp -r hermes-skill-membean-training \
  "$HOME/.hermes/skills/productivity/membean-training"
```

Then load it in a session with `skill_view(name='membean-training')`.

## Usage

Ask for it in plain language, e.g. *"do today's Membean training, 15 minutes"*. The agent will run
the account gate first, report the verified identity, then drive the session and report minutes and
accuracy from the dashboard.

Membean reports accuracy to the teacher. The skill therefore aims for accurate answers, keeps the
session at its chosen length, and reports misses honestly instead of faking a percentage.

## Scope and ethics

Use it on an account you are allowed to use, and mind your school's rules on automated study tools.
The skill is written to behave like a diligent student (real dwell times, real answers, no DOM answer
scraping, no credential handling), but responsibility for using it stays with you.

## License

MIT — see [LICENSE](LICENSE).
