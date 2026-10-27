# Membean training DOM map (verified 2026-09, ExtJS training app)

## State probe (one `js` call, ~5 s budget — keep it lean)

```js
(() => {
  const w = document.querySelector('#review-wrapper');
  const bar = document.querySelector('#timer-container .x-progress-bar');
  const img = document.querySelector('#constellation img');
  return JSON.stringify({
    url: location.href,
    growl: (document.querySelector('#user-growl') || {}).innerText || '',
    type: w ? w.className : null,
    text: (w ? w.innerText : document.body.innerText).slice(0, 1200),
    choices: [...document.querySelectorAll('li.choice')].map(e => e.innerText.trim()),
    wordmap: img ? img.src : null,
    textInputs: [...document.querySelectorAll('input[type=text],textarea')]
      .filter(e => e.offsetParent).map(e => e.name || e.id),
    submits: [...document.querySelectorAll('input[type=submit]')]
      .filter(e => e.offsetParent).map(e => e.value),
    timeout: (document.querySelector('#timer-container') || {dataset:{}}).dataset.timeout || null,
    bar: bar ? bar.style.width : null,
    doneBtn: (document.querySelector('#done-btn') || {}).value || '',
    status: (document.querySelector('#answer-status') || {}).innerText || ''
  });
})()
```

## Layout

- `#review-wrapper` class tells the step type: `mc_alternate`, `mc_blank_context`,
  `mc_blank_constellation`, plus word/restudy cards (no `review-wrapper`; `#section1` + `#wordform-container`).
- `#user-growl` — page label / flash messages, e.g. `Answer`, `Restudy`, and
  "Your previous answer didn't go through. Please try again."
- `#answer-status` — per-question result (`Correct!`, `Incorrect!`), set client-side on click.
- `#single-question` — `<h3 class="question">` plus `#choice-section` with `li.choice`
  (`data-value` = shuffled index, `#notsure` = "I'm not sure").
- `#timer-container[data-timeout="30|33"]`, bar `#timer-container .x-progress-bar` fills left→right
  (~7 px/s of a ~230 px bar); filling out = automatic `Incorrect!`.
- Top-right `#done-btn` submit (`value="I'm done"`), switches to disabled `"Processing..."` while a
  step is applied.

## Forms (all POST to `/training_sessions/<id>/advance`)

| Action | Fields |
|---|---|
| Answer a question | `event=answer!`, `pass=true`/`pass=false`, `id`, `barrier`, `mbd` (base64 interaction-telemetry blob; XHR POST, server re-validates) |
| Advance a word card | `event=finish_restudy!`, `id`, `time-on-page`, `barrier` (the visible `Next` submit) |
| End the session | `event=done!`, `id`, `time-on-page`, `barrier` (the visible `I'm done` submit) |

The client decides `pass` locally and the server re-validates (pace + `mbd`). `barrier` and `mbd`
are rotating per-page values; never reuse a captured payload — always click the live control so the
page builds them itself.

## Question-type catalogue (observed)

| `#review-wrapper` class | Shape | How to answer |
|---|---|---|
| `mc_alternate` | word + pronunciation + "An example of … is:" | pick the true option |
| `mc_blank_context` | sentence with a blank + four words | pick the word that fits the sentence |
| `mc_context` | word + pronunciation + "What is X?" + three glosses | pick the correct gloss |
| `mc_blank_constellation` | "Choose the word that fits best" + PNG wordmap | read `#constellation img` with `vision_analyze`, pick the word spanning the labelled clusters |
| (none — restudy card) | word, context paragraph, memory hook, or a word with an embedded self-check quiz | dwell, then click the `Next` submit |

## Writing into text inputs

`fill_input` can no-op on this framework. Set the value and fire the events instead, then re-read
`el.value` and `form.checkValidity()` before submitting:

```js
(() => {
  const el = document.querySelector('input[type=text]');
  el.focus();
  el.value = 'WORD';
  ['input','change','keyup','blur'].forEach(t => el.dispatchEvent(new Event(t, {bubbles:true})));
  return el.value;
})()
```

## Login / start-of-session flow

- `https://membean.com/login` — `a.sso-login-btn-google` (href `#`, JS-bound) → Google account
  chooser → `div[role=link][data-identifier="student@school.k12.tr"]` → lands on `/dashboard`.
  The chooser lists a personal Gmail account second — always pick by `data-identifier`, never by
  position.
- `/training_sessions/new` — duration `input[type=submit]` values `"5 min."` … `"60 min."`;
  the current default carries `class="special"`.
- Dashboard to-do card links straight into `training_sessions/new` ("Finish"); the dashboard's
  "Start Training" button points at the same URL.
- `/dashboard/training-history` lists sessions (date, minutes, accuracy, warning badges) and is the
  independent verification surface; per-session detail pages are
  `/dashboard/training-sessions/<id>`.
