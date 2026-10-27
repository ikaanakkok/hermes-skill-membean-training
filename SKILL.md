---
name: membean-training
description: "Do Membean vocabulary training in the school Chrome session."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [membean, school, browser, cdp, training, google-sso, vocabulary]
    related_skills: [cdp-authenticated-browsing, classroom-to-notion]
---

# Membean Training Skill

Runs real Membean training sessions (word cards + graded questions) as the school student account,
by driving the already-signed-in school Chromium over CDP. It answers graded questions from the
question text itself (using `vision_analyze` for the word-map questions), paces each answer so the
server accepts it, and verifies the result on the dashboard. It does not touch passwords, teacher
pages, quizzes or assignments.

## When to Use

- "Membean training yap", "Membean'de 15 dakika çalış", "bugünkü Membean ödevini tamamla",
  "Membean minutes" / "training cycle'ı doldur".
- Don't use for: educator views, graded quizzes/assignments, or the school Notion sync
  (`classroom-to-notion`). Signing in **is** in scope, but only through the Google SSO button in
  the already-signed-in school Chrome profile (Account Gate below) — never with a typed credential.

## Account Gate — run before ANY training action (mandatory, no exceptions)

Nothing in this skill runs until the account is **determined, signed in through Google auth, and
verified on the page**. Every action below has a gate in front of it; skipping the gate is how
minutes and accuracy land in the wrong student's record.

### G1. Determine the expected account — state it before touching the browser

- Expected identity, three facts, written into the response first:
  `account = student@school.k12.tr | name "<greeting name>" | class <class label>`.
- If the user names a different account for this run, that overrides the default — but only when it
  is explicit, and it must still be confirmed on the page in G3.
- Ambiguous or missing account (no account named, several plausible sessions, only a personal Gmail
  signed in) → **stop and ask**. Never infer the account from "the only open tab" or from the tab URL.

### G2. Establish the session — Google SSO only, never a typed credential

- Gate check: `goto_url("https://membean.com/dashboard")`, then read the page in the next call.
  - **Dashboard with a greeting** → already signed in → G3.
  - **Membean login page** (`/login`, `a.sso-login-btn-google` present) → Membean's own cookie
    expired while Google is still signed in. Click "Sign in with Google" (`a.sso-login-btn-google`)
    and, in the Google account chooser, pick the expected account by
    `div[role=link][data-identifier="<expected account>"]` — **never by position**: the chooser also
    lists a personal Gmail. This is the sanctioned login path and it must not ask for a password.
  - **Google login page, password field, or 2FA/OTP prompt** → the Google session itself is gone.
    That is out of scope: stop, load `cdp-authenticated-browsing`, and hand the sign-in to the user.
- Hard rule: this skill logs in **only** by clicking the Google SSO button inside the
  already-signed-in school Chrome profile. Any `input[type=password]`, "Use another account", a
  chooser entry that is not the expected `data-identifier`, or a consent screen for another tenant
  is a stop condition — report it, do not improvise around it.

### G3. Verify the identity on the page — before the first graded step and after every sign-in

Read it back from the page, never from assumption: greeting name on `/dashboard`
("Welcome, <name>!"), the class block (**<class label>**), and the signed-in email from
`https://membean.com/account` when the greeting is ambiguous.

The gate passes **only** when name and class (and email when shown) match G1. On any mismatch:
stop, click nothing, and report which identity the page shows. Answering questions or clicking
"Start Training" under the wrong account writes minutes and accuracy into that account.

### G4. Re-verify before these specific actions

| Before… | Verify |
|---|---|
| starting a session (`/training_sessions/new`) | G3 passed in this run |
| resuming after any navigation, reload, CDP reconnect, or a pause longer than a few minutes | `user_state` still shows the same session id **and** the dashboard greeting still matches |
| answering a graded question | you are still the verified identity — a login page or account interstitial mid-session means the session died: re-run G2/G3 instead of answering |
| ending or reporting | the numbers were read from the verified account's dashboard and training history |

## Prerequisites

- Attach to the school browser: `browser.cdp_url: http://127.0.0.1:9222`, profile
  `~/.hermes/chrome-debug`, Google session `student@school.k12.tr`.
- Run the Account Gate (G1–G3) before everything else. A visible `input[type=password]` means signed
  out at the Google layer — stop and hand it to the user.

## Hosts: Hermes, Claude Code, Codex CLI

The rules in this skill are host-independent — only the transport changes.

- **Hermes** — `browser_exec` helpers (`cdp`, `js`, `goto_url`, `vision_analyze`) with
  `browser.cdp_url: http://127.0.0.1:9222`.
- **Claude Code** — install at `~/.claude/skills/membean-training/` and drive the same Chrome from
  Bash through `scripts/cdp.py`. Details: `references/claude-code.md`.
- **Codex CLI** — install at `~/.agents/skills/membean-training/` (user level) and call the same
  script from the Codex shell. Codex's sandbox blocks loopback by default, so run with
  `-c sandbox_workspace_write.network_access=true`. Details: `references/codex.md`.

`scripts/cdp.py` is a dependency-free (stdlib only) CDP CLI that covers every browser action this
skill needs, so any host with a shell can run the gate and the training loop:

```bash
CDP="python3 ~/.claude/skills/membean-training/scripts/cdp.py"   # or ~/.agents/skills/...
$CDP list                       # target ids + urls
$CDP state  <target>            # signed-in | membean-login-page | password-required | unknown
$CDP account <target> --expect '<student name>' --expect-class "<class label>"   # exit 2 = STOP
$CDP sso    <target> --expect student@school.k12.tr           # only when the login page is served
$CDP probe  <target>            # the dom-map state probe as JSON
$CDP click  <target> --text "<exact option>"
$CDP type   <target> WORD --selector 'input[name=choice]'
$CDP mapimg <target> /tmp/wordmap.png && $CDP mapword <target>
$CDP shot   <target> /tmp/state.png
```

When a host has no vision tool, `mapword` still answers the word-map questions: the constellation
filename is rot13 of `mem<word>bean`. Never skip the Account Gate because a host lacks a helper —
the CLI gate returns a shell exit code, which is stricter than reading prose.

## Session Facts (verified 2026-09)

- Signed-in landing page: `https://membean.com/dashboard`. It shows the class
  (**<class label>**) and the day's requirement, e.g. "Train 9 more minutes today", high
  priority, due 23:59; cycle requirement is "2 days with 15+ minutes" and "30 total minutes";
  accuracy is also reported to the teacher, so wrong answers are visible.
- Start a session: click "Start Training" (`/training_sessions/new`). If a session is already
  active, that URL redirects straight back into it. Otherwise a "YOU DECIDE — Your current session
  will last for 15 minutes" screen appears; its durations are `input[type=submit]` with values
  `"5 min."`, `"10 min."`, `"15 min."`, … `"60 min."`. Pick 15 (the default) unless the day's
  to-do needs less.
- The training page is `/training_sessions/<id>/user_state`: an old ExtJS form app that POSTs one
  step at a time to `/training_sessions/<id>/advance`. Step types seen:
  - **word / restudy card** — word, pronunciation, context paragraph, memory hook, Word Theater;
    often an embedded self-check quiz. Advance with the `Next` submit (`event=finish_restudy!`).
  - **`mc_alternate`** — definition/example multiple choice, 4–5 `li.choice`.
  - **`mc_context`** — word + pronunciation + "What is X?" with three glosses to choose from.
  - **`mc_blank_context`** — sentence with a blank, choose the word that fits.
  - **`mc_blank_constellation`** — "Choose the word that fits best" plus a word-map PNG in
    `#constellation img` (`https://cdn3.membean.com/.../cons2-questions/<code>.png`).
- Graded questions are timed: `#timer-container[data-timeout]` is 30–33 s and
  `#timer-container .x-progress-bar` fills. Let it fill and the question is scored **Incorrect!**.
- **Answer pacing is validated server-side.** A `li.choice` click that lands only a few seconds
  after the question rendered is refused with the flash
  "Your previous answer didn't go through. Please try again." and the same question is served
  again. A dwell of roughly 8–15 s is accepted; >25 s risks the timer running out. Refusals also
  happen at a healthy mid-bar dwell when steps follow each other faster than a human reads, so the
  real gate is the session's overall pace, not one timer.
- The answer submission is an **XHR POST** to `/training_sessions/<id>/advance` with
  `event=answer!&pass=true|false&id=<id>&barrier=<token>` plus **`mbd`** — a base64 anti-automation
  telemetry blob the page computes from the session's interaction record. The server re-checks it;
  a rejected `mbd`/pace combination is exactly the "didn't go through" flash. Nothing about the
  payload can be usefully hand-crafted: always click the real control and let the page build it.
- Sessions are recorded in ~10-minute blocks on `/dashboard/training-history` with an accuracy
  percentage; a driven 10-minute session showed 100% accuracy and no warning badge. Reaching
  /dashboard or /dashboard/training-history does **not** kill an open session — `/training_sessions/new`
  re-enters it.
- The whole UI is click-driven JS: `js("el.click()")` works, `click_at_xy` in this environment
  dispatches events that never reach the page (`clicks=0` in a document listener) — do not use it.

## Procedure

0. **Account Gate first (G1→G2→G3).** No session, no clicks, no answers until the identity is
   verified on the page and quoted in your response. Re-run G2/G3 on any sign-in page or
   identity mismatch; re-check G4 before starting and resuming.
1. **Open the dashboard and read the requirement.**
   `goto_url("https://membean.com/dashboard")` (expect `wait_for_load` to time out on this app —
   navigate in one call, then `time.sleep(5)` and read in the next).
   Completion criterion: you can quote the greeting name, the class, and "Train N more minutes".
2. **Decide the session length** from that to-do: remaining ≤5 min → 5; up to 10 → 10; otherwise 15.
   Completion criterion: the chosen duration equals the number you will later check on the dashboard.
3. **Start the session.** `goto_url("https://membean.com/training_sessions/new")`, read the
   duration inputs, `js`-click the one whose `value` is `"<n> min."`.
   Completion criterion: URL is `/training_sessions/<new id>/user_state`.
4. **Loop one step at a time.** Probe with the state snippet in
   `references/dom-map.md`, then dispatch on what you see:
   - `li.choice` present → answer **from the question text** (step 5).
   - a visible `input[type=text]` → type the answer with the `js` value-setter from
     `references/dom-map.md` (never `fill_input`, it can silently no-op here), then submit.
   - word card with `Next` (no `li.choice`) → read it, dwell 10–20 s, `js`-click `Next`.
   - `#constellation img` present → step 5b.
   - `bar: null` while a question is on screen → reload `user_state` first (step 7).
   Completion criterion per iteration: the page has moved on to a different step (new question text
   or a restudy card), **not** the same step with the "didn't go through" flash.
5. **Answer a text question.** Read the question and the options and pick the one that is true
   English usage — Membean grades the student, so this is not a guessing game:
   - Wait until ~8–15 s have passed since the question first rendered (count from the probe that
     first showed it, or sample `#timer-container .x-progress-bar` width).
   - `js`: `[...document.querySelectorAll('li.choice')].find(e=>e.innerText.trim()==='<exact option text>').click()` —
     match on the option's exact innerText, never on `data-value` order (options are shuffled).
   - Never answer "I'm not sure"; it scores as wrong.
5b. **Word-map questions.** Take `document.querySelector('#constellation img').src` and call
   `vision_analyze(image_url=..., question='...which of these fits: <options>')`, then answer that
   word. The map clusters the word's senses, so ask for the word that spans all the labelled
   clusters.
6. **Handle a refusal the right way.** If the flash "Your previous answer didn't go through"
   appears with the *same* question: do not hammer it — every rapid retry is more automation
   signal, and fast step-to-step pace is what produces the teacher-visible
   "Review pace too quick" warning. Wait ~30 s, reload `user_state`, confirm the bar is filling and
   the flash is gone, then answer once. If it is refused a second time, stop driving the session,
   report the state, and let the student finish by hand.
7. **Handle the "Processing…" hang.** After an accepted answer the top-right button shows
   `#done-btn` = "Processing…" `disabled`. It normally clears in a few seconds; if it is still
   "Processing…" after ~15 s, `goto_url("https://membean.com/training_sessions/<id>/user_state")` —
   the reload serves the next step and the previous answer stays recorded.
8. **Let the session run to its length, then stop.** Do not click "I'm done" mid-session: a short
   session produces the visible teacher warning "Training session too long or too short". A session
   can also simply be left: navigating to `/dashboard` records it — observed behaviour was a clean
   ~10-minute record with no warning badge. Check the history row afterwards and report what it
   actually recorded.
   Completion criterion: dashboard to-do minutes dropped, or the summary page is shown.
9. **Verify, then report.** Re-read `/dashboard`: "Today: N min." must have grown by about the
   session length, and `/dashboard/training-history` must list the new session with its minutes and
   accuracy. Report minutes before/after, accuracy, and any wrong answers; do not report success
   from the click alone.

## Quick Reference

- Probe state: snippet in `references/dom-map.md`, or `scripts/cdp.py probe <target>` on any host.
- Account gate: `scripts/cdp.py account <target> --expect NAME [--expect-class CLASS]` → exit 0 match,
  exit 2 mismatch.
- Click a choice: `js("[...document.querySelectorAll('li.choice')].find(e=>e.innerText.trim()==='X').click()")`
- Advance a word card: `js("[...document.querySelectorAll('input[type=submit]')].find(e=>e.value==='Next').click()")`
- Flash/state messages live in `#user-growl` and `#answer-status`.
- Timer: `#timer-container[data-timeout]`, bar `#timer-container .x-progress-bar`.

## Driving the shared school Chrome (verified 2026-10)

The browser harness follows the user's **active** tab, so `switch_tab`/`goto_url` do not hold: between
calls the attached tab silently changes and `goto_url` then navigates *someone else's* tab (verified:
two of the user's NoodleTools tabs were turned into copies of the training page, leaving three
concurrent tabs on one session, which is what produces the endless "previous answer didn't go
through" refusals). Fix: address the training target explicitly and never rely on the harness's
current tab.

```python
# 1. find the training tab
#    curl -s http://127.0.0.1:9222/json/list | python3 -c "import sys,json;[print(t['id'],t['url'][:80]) for t in json.load(sys.stdin) if t['type']=='page']"
MID = "<training tab targetId>"
SID = cdp("Target.attachToTarget", targetId=MID, flatten=True)["sessionId"]
def mjs(expr):
    r = cdp("Runtime.evaluate", session_id=SID, expression=expr, returnByValue=True, awaitPromise=True)
    return r.get("result", {}).get("value")
def nav(url):  cdp("Page.navigate", session_id=SID, url=url)
def reload():  cdp("Page.reload", session_id=SID)
```

`Target.attachToTarget` needs a fresh sessionId per call or cache it once per call — either works;
the target id is what stays fixed. Use `activate=True` once so the tab is visible (hidden/duplicated
tabs are exactly the "bar: null" state) and restore any tab you accidentally navigated with
`Page.navigate` back to its original URL.

**Membean's own session cookie drops before the Google one does.** Verified 2026-10-18: CDP was up and
Google was still signed in, but `/dashboard` served the Membean **login page**. Clicking "Sign in with
Google" inside that same school-Chrome profile re-entered the student account with **no password typed**
(landed on "Welcome, <student>!", class <class label>). So: treat a Membean login page as recoverable via
Google SSO in the profile, verify the greeting name, and only stop-and-ask if Google itself is signed out
or a password field appears.

**Inactivity kill:** a session left untouched for a few minutes is closed server-side with the
banner "ALERT: We had to close your learning session because you were inactive" — the minutes already
recorded are kept, but the run must be restarted. Drive continuously; do not browse away between
steps. A 15-minute session ends on its own with the **TAKE A BREAK!** screen whose only control is
`input[value="Click me to stop"]` — click it and the dashboard shows "All caught up today!".
Leaving the session open past its length (or being inactive) is what creates the teacher-visible
"Training session too long or too short" / "Accuracy below 50%" / "Review pace too quick" badges.

**Word-map questions: `vision_analyze` on a locally saved copy of the CDN URL.** Verified 2026-10-19 across 8 map
questions with the plain CDN URL; since 2026-10-25 that URL answers **403** to `vision_analyze`, so fetch it through
the page and hand over the local file:

```python
src = mjs("document.querySelector('#constellation img').src")
code = "fetch(%s).then(r=>r.blob()).then(b=>new Promise(res=>{const fr=new FileReader();fr.onload=()=>res(fr.result);fr.readAsDataURL(b);}))" % json.dumps(src)
data = mjs(code)
open("~/.hermes/cache/scratch/wordmap.png","wb").write(base64.b64decode(data.split(",",1)[1]))
```

Then `vision_analyze(image_url=<local path>)`. Do this **inside the 30 s window**: fetch → vision → `js` click, with no
other tool call in between. Verified 2026-10-25: two map questions lost to the timer while the fetch and the vision call
sat in separate turns (`consecutive`, `define` both scored Incorrect). Do NOT use tesseract — on these PNGs it returns
garbage (`* successful`, `YX,`, `priviles®`). Do NOT use `capture_screenshot()` either: it follows the harness's
*active* tab and captured an unrelated local HTML file instead of the map. Ask vision for the word that spans **all**
clusters (e.g. `forbid/veto/disallow/nix` + `command/require` → `prohibit`; `convert/win over/persuade` → `convince`).

## Accuracy Discipline (user's standing requirement: aim for 100%)

### Text inputs must be typed with real key events (cloze_background, "Spell the word")

`.value = 'word'` + `form.requestSubmit()` **scores Incorrect even when the word is right** — verified
2026-10-19: `surface` was typed on the moon-surface cloze (hint "top layer", the correct answer) and
scored `Incorrect!`; the next restudy card for `surface` proved the word was right and only the
submission path was wrong. The Ext app keeps the typed letters in its own model, so synthetic
`input`/`change` events never reach it and the graded payload is effectively empty. Type for real:

```python
sid = cdp("Target.attachToTarget", targetId=MID, flatten=True)["sessionId"]
js("document.querySelector('input[name=choice]').focus()")
for ch in "surface":
    cdp("Input.dispatchKeyEvent", session_id=sid, type="char", text=ch); time.sleep(0.08)
cdp("Input.dispatchKeyEvent", session_id=sid, type="rawKeyDown", windowsVirtualKeyCode=13, key="Enter", code="Enter")
cdp("Input.dispatchKeyEvent", session_id=sid, type="char", text="\r")
cdp("Input.dispatchKeyEvent", session_id=sid, type="keyUp", windowsVirtualKeyCode=13, key="Enter", code="Enter")
```

Re-read `el.value` before Enter. Verified working: value `commotion` typed this way, Enter advanced the
step and the word graded on its text.

### Typing: `char`-only events, target activated, and the budget for a wrong word

Dispatch **only** `type="char"` per letter — the skill's earlier `keyDown`+`char`+`keyUp` triple garbles letters
(verified 2026-10-25: typing `xhibit` produced `'xxh'` on the input, Enter submitted the garbage and `exhibit`
scored Incorrect). Also call `cdp("Target.activateTarget", targetId=MID)` first: without it `Input.dispatchKeyEvent`
reaches nothing and `el.value` stays empty even though `.focus()` reports the input as active. Verified-good shape:

```python
cdp("Target.activateTarget", targetId=MID); time.sleep(0.8)
sid = cdp("Target.attachToTarget", targetId=MID, flatten=True)["sessionId"]
mjs("document.querySelector('input[name=choice]').focus()")
for ch in "dialect":
    cdp("Input.dispatchKeyEvent", session_id=sid, type="char", text=ch); time.sleep(0.12)
print(mjs("document.querySelector('input[name=choice]').value"))   # must equal the word (minus the pre-filled first letter)
# then rawKeyDown 13 + char "\r" + keyUp 13
```

On a `cloze_background` card the input holds **only the letters after the pre-filled `.first-letter`** (so
`maxLength = len(word) - 1`: first `e`, max 6 → type `xhibit` for `exhibit`), and never the first letter itself.

### `cloze_background` decoding (image question)

- Word length = **`input[name=choice].maxLength + 1`**: the first letter is pre-filled in `.first-letter`
  (`max=6`, first `s` → 7 letters: `section`, `surface`; `max=9`, first `e` → `expedition`). Sizing the
  answer from `maxLength` alone is how `excursion` got submitted for `expedition` and `sector` for
  `section`.
- The image **is** the question: read `document.querySelector('#cloze-background').src` with
  `vision_analyze` (fits the timer). The `hint:` span is the gloss (`journey`, `piece of`, `top layer`).
- Combine gloss + first letter + length + picture before typing; if two candidates fit, prefer the one
  the picture shows literally (moon ground → `surface`, orange wedges → `section`, long trip planning →
  `expedition`).

- **Restudy card with an embedded self-check quiz:** clicking `Next` flips the button to `Wait...` and goes nowhere. Answer the quiz `li.choice` first, then `Next` advances — and the next step is often **"Spell the word you saw"**: a text input with **no** pre-filled first letter (`maxLength` = full word length), so type the whole word with `char` key events + Enter (verified 2026-10-26: `customary`, `disrupt` both accepted).
- **Word-map cross-check:** the constellation PNG filename is rot13 of `mem<word>bean` (`zrzgrafrorna` → `memtensebean` → `tense`). Use it to confirm the word you read from the map when tesseract output is garbage (it is unusable on roughly half these PNGs, e.g. `* gO into`, `yy.`); the map itself stays the primary source, the filename breaks ties.

- **Word/restudy cards are the answer key for what comes next.** Read the definition, memory hook and
the context paragraph fully before clicking Next. Most wrong answers come from skimming a card and
then meeting the same word as a graded question 30 s later.
- **`mc_context` / `mc_blank_context`: match on the sentence, not on familiarity.** Eliminate the two
glosses that contradict the sentence's register or collocations (e.g. a gloss demanding an object
when the blank has none), then pick the survivor. Never pick a word because it looks harder/more
textbook-like.
- **Word-map (`mc_blank_constellation`): `vision_analyze` first, answer once.** The map clusters the
  word's senses; choose the option whose senses span the labelled clusters. Never click a map question
  without the image read (tesseract output is unusable on these PNGs).
- **Never answer "I'm not sure"** — it scores as wrong every time, so guessing a real option is
  strictly better.
- **Never read the answer off the DOM.** `li.choice.answer` / `.correct` are client-side artifacts;
  using them fakes the student's retrieval practice and the reported accuracy. If a question cannot be
  answered honestly inside the window, it is worth one wrong answer, not a faked percentage.
- **Do not let a refusal burn a question.** An unanswered refused question expires and scores
  incorrect, so the refusal path is the main accuracy leak in long runs. On the first refusal, pause,
  reload `user_state`, re-read the question, then answer once.
- **Use `#answer-status` after each click** to record whether it landed as Correct/Incorrect. If a map
  or context question goes wrong, note the word in the final report so the student re-studies it (Membean
  re-asks missed words in later sessions on its own).

## Pitfalls

- **`click_at_xy` does nothing here.** Verified: a document-level click listener stayed at 0 after
  two `click_at_xy` calls, so the app never saw the click. Use `js` clicks throughout.
- **`goto_url` + `wait_for_load` times out on Membean** (CDP `Runtime.evaluate` 5 s budget while the
  ExtJS bundle loads). Navigate in one call, then `time.sleep(5+)` and read in the next call.
- **`bar: null` means the step never initialized.** When the probe returns `bar: null` (no
  `#timer-container .x-progress-bar`) the question renders but clicks are silently ignored — no
  status, no flash, same question forever. Reload `user_state`, confirm the bar is filling
  (`bar: "<N>px"`), then answer; the same question is re-served, so nothing is lost.
- **The "didn't go through" flash is a pace/validation refusal, not a network error** — the local
  click still shows "Correct!". Re-read the page before re-answering; the same question means the
  answer was not recorded.
- **Do not derive answers from the page's own feedback classes.** Context-page self-check quizzes
  ship with the answer already marked (`li.choice.answer`) and an answered question gets
  `li.choice.correct`. These are client-side artifacts; using them to answer would fake the
  student's retrieval practice and the teacher-visible accuracy. Decide from the question text (or
  the word-map image), and use those classes only to confirm a click landed.
- **The 30–33 s timer is a hard stop**: answering late scores Incorrect. Keep the whole
  decide-and-click inside ~25 s, and do not let a long `vision_analyze` call eat the window — take
  the image URL and answer in the same minute.
- **A refusal is not harmless in bulk**: the refused question stays open, and if it is never
  answered the expired timer scores it Incorrect, which moves the teacher-visible accuracy. When
  refusals start repeating, end the run rather than grinding the same question.
- **Options are shuffled per render**, so never reuse a previous option index or position.
- Word cards and questions repeat words on purpose (Membean re-asks missed words). Seeing the same
  word again is normal, not a stuck page.
- The dashboard's "Training Expectations" block is per training cycle (Mon–Sun): 2 days with 15+ min
  and 30 total minutes. One 15-min session does not finish the cycle.
- **Zero need today means do not start a session.** Verified 2026-10-18: dashboard said "You met the
  training goal for today" with 17 already-trained minutes, and adding a second session the same day
  only risks the teacher-visible "session too long or too short" badge. Report the cycle gap instead
  (e.g. "1/2 days, 17/30 min → one 15-min session tomorrow closes both").

## Verification

- Dashboard `/dashboard`: today's minutes increased by roughly the session length and the to-do
  card flips to "You met the training goal for today".
- `/dashboard/training-history`: the new session row exists with minutes and an accuracy percentage
  and no "training warning" badge ("Review pace too quick" or "Training session too long or too
  short" are the two badges to look for).
- Per-session detail `/dashboard/training-sessions/<id>` shows `36/40` style counts plus
  **Overview / Correct / Incorrect / Skipped / New** tabs — click `Incorrect` to list exactly which
  words were missed (use it in the report instead of guessing).
- Also read the cycle block: "N/2 days trained had 15+ min" and total minutes, then state what the
  cycle still needs and when it ends.
- If all hold, report minutes before→after, session accuracy, and the remaining daily/cycle
  shortfall. Otherwise say which check failed and what the page showed.
- **Report accuracy against the 100% target explicitly**: session accuracy, the wrong words (if any),
  and the cycle accuracy. A session that finished but scored below 100% must say so on the first line
  — do not bury it under "session completed".

Support: `references/dom-map.md` (full selector/state map, form field map, JS snippets).
