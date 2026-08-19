# resume-fill — Plan

A local CLI that turns a canonical record of your career into a job-specific résumé and cover
letter, and drafts LinkedIn profile copy from your blog.

Status: **implemented, M0–M6.** Design produced from a `/grill-me` session on 2026-07-25; built
2026-07-26. Every open question in §9 is now answered — see that section for what was decided and
why. §10 records what the build itself turned up.

---

## 1. What it does

Three commands' worth of behaviour:

1. **Résumé** — given a job description, generate a tailored, ATS-parseable PDF résumé scored
   against that JD.
2. **Cover letter** — given the same JD, generate a tailored cover letter PDF.
3. **LinkedIn draft** — read the blog, propose new headline / About / experience copy, and show it
   as a diff against your current profile. **You** paste it in.

Every generation run picks one of three modes: `--resume`, `--cover`, or `--both`.

---

## 2. Constraints discovered during design

These are facts, verified during the session, that shaped the decisions below.

| Constraint | Consequence |
|---|---|
| LinkedIn has **no public write API** for profile fields. Free tier (Sign In with LinkedIn / OIDC) is read-only; `w_member_social` writes to the *feed*, not the profile. Profile write is gated behind effectively-closed partner programs. | The "auto-update LinkedIn" feature becomes draft-and-paste. No browser automation — that violates LinkedIn User Agreement §8.2 and risks a ban on the exact profile being polished. |
| **Nothing reproduces an ATS score.** ⚠️ Amended 2026-08-19: this row used to say no ATS scores at all, which was true when written. Greenhouse shipped Talent Matching (Sep 2025) and Lever shipped Talent Fit (Jun 2025); Workday, Ashby and iCIMS score too. What survives is sharper — each scores against an employer's own calibration nobody outside can see, each is documented as advisory input to a human, and no vendor documents auto-rejection on résumé *content*. Jobscan-style "scores" remain vendor heuristics. | The score in this tool is an explicitly-labelled *local proxy*, not a real-world metric. The guarantee that actually matters is parse survival — every one of those systems runs on what its parser extracted. |
| A blog contains narrative, not skeleton. No employers, titles, dates, degree, or contact info. | The blog cannot be the résumé's source of truth. It is an *evidence layer* over a canonical `profile.yaml`. |
| Machine has Node 22.15, Python 3.10.10, uv 0.11.28, gh 2.96. **No** Word, LibreOffice, pandoc, Typst, or LaTeX. | PDF rendering must bring its own engine — Playwright's bundled Chromium. |
| No LLM keys in environment. `infinance` already uses the `openai` SDK against a configurable `LLM_BASE_URL` (`infinance/analyze.py:504`). | Mirror that convention. Cerebras / DeepSeek become a two-line `.env` swap. |

---

## 3. Decisions locked

| # | Decision | Rejected alternative |
|---|---|---|
| 1 | LinkedIn = generate draft + diff, user pastes manually | Playwright automation of the live account (ToS violation, ban risk) |
| 2 | Canonical `profile.yaml`, auto-seeded from LinkedIn data export + existing résumé PDF; blog is an evidence layer | Blog as sole source (produces résumés with no dates or employers) |
| 3 | Python CLI on uv | Local web UI; hosted app; Claude Code skill |
| 4 | Numeric ATS proxy score **plus** auto-iterate loop, on top of parse-proofing and a keyword coverage report | Parse-safety only, no number |
| 5 | **Strict grounding, hard block.** Validator rejects any claim not traceable to `profile.yaml` or the evidence corpus; unmatched JD keywords are reported as gaps, never inserted | Allowing "adjacent skill" inference or unverified-but-flagged claims |
| 6 | PDF only, rendered HTML/CSS → Playwright Chromium | DOCX; dual-format; Typst |
| 7 | OpenAI-compatible SDK against Cerebras or DeepSeek via `LLM_BASE_URL` / `LLM_MODEL` | Anthropic API key; `claude -p` subprocess; local Ollama |

**Decision 4 + Decision 5 interact deliberately.** An auto-iterate loop optimising keyword coverage
has exactly one cheap way to raise its score: invent keywords. Decision 5 is what stops it. The
loop's score ceiling therefore becomes an honest measure of fit, and a low score is *information* —
it means the role genuinely wants things you haven't done yet.

---

## 4. Architecture

```
profile.yaml ─┐
              ├─→ tailor (LLM) ─→ resume.json ─→ ground ─→ score ─→ render ─→ verify ─→ out/
evidence.json ┤                        ↑            │         │
              │                        └────────────┴─────────┘
job_desc.txt ─┘                          retry with violations + gaps
```

### Pipeline stages

| Stage | Module | What it does |
|---|---|---|
| Parse JD | `jd.py` | JD text → structured requirements: hard skills, soft requirements, title, seniority, keyword set. Deterministic extraction + one LLM pass. |
| Tailor | `tailor.py` | LLM selects which evidence to surface and writes bullets. **Every bullet carries `source_ids`.** |
| Ground | `ground.py` | Hard gate. Each `source_id` must resolve; each tool/tech/metric named in a bullet must appear in the referenced source or in `profile.skills`; numbers must appear verbatim. Violations are fed back and the tailor retries. |
| Score | `score.py` | Transparent weighted proxy (below). Below threshold → feed gaps back and retry, up to `MAX_ITER`. |
| Render | `render.py` | `resume.json` → Jinja2 → HTML + CSS → Playwright Chromium → PDF. Single column, standard headings, embedded text, no tables/textboxes/graphics. |
| Verify | `verify.py` | Round-trip: extract text from the produced PDF with `pdfminer.six`, assert contact block, every section heading, and every bullet survive. **Build fails if it doesn't parse.** |
| Report | `report.py` | `report.md`: final score, score breakdown, matched keywords, missing keywords, and which gaps are missing *because you genuinely lack the experience*. |

### Score model

Deliberately transparent — no hidden magic, and printed as a breakdown, never a bare number.

| Component | Weight |
|---|---|
| Hard-skill coverage vs JD | 0.40 |
| Required qualifications addressed | 0.15 |
| Title / seniority alignment | 0.15 |
| Keyword presence *in context* (not stuffed) | 0.20 |
| Format checks passed | 0.10 |

---

## 5. Repo layout

```
resume-fill/
├── pyproject.toml            # uv
├── .env.example
├── PLAN.md
├── profile.yaml              # canonical career facts  (PII — see open question 6)
├── data/
│   ├── evidence.json         # blog-derived evidence corpus, cached
│   └── linkedin_export/      # unpacked LinkedIn data archive
├── templates/
│   ├── resume.html.j2
│   ├── resume.css
│   └── cover_letter.html.j2
├── out/
│   └── <company>-<role>-<date>/
│       ├── resume.pdf
│       ├── cover_letter.pdf
│       ├── resume.json       # the intermediate, kept for diffing runs
│       └── report.md
└── resume_fill/
    ├── cli.py                # command surface
    ├── config.py             # pydantic settings, mirrors infinance/config.py
    ├── llm.py                # OpenAI-compatible client
    ├── profile.py            # load + validate profile.yaml
    ├── ingest/
    │   ├── linkedin.py       # LinkedIn export CSVs → profile.yaml seed
    │   ├── resume_pdf.py     # existing résumé PDF → profile.yaml seed
    │   └── blog.py           # blog → evidence corpus
    ├── jd.py
    ├── tailor.py
    ├── ground.py
    ├── score.py
    ├── render.py
    ├── verify.py
    ├── report.py
    └── linkedin_draft.py     # blog → proposed profile copy + diff
```

Built as planned, plus five modules the plan implied but did not name:

| Module | Why it exists |
|---|---|
| `source.py` | The `Source` type and parent/child containment. Citing a job licenses that job's own highlights and nothing from another employer |
| `textutil.py` | One matcher. `ground`, `score` and `verify` all ask "does this string say that thing?" and must agree, or a bullet passes grounding and fails scoring on the same words |
| `lexicon.py` | What counts as a *claim*. "Improved throughput" is prose; "with Kafka" is checkable |
| `document.py` | `resume.json`, the cover letter and the LinkedIn draft, so `ground.py` can gate all three without importing the stages that produce them |
| `pipeline.py` | The loop, and `run()` for the three modes |
| `bootstrap.py`, `evidence.py`, `cover.py` | The `init` merge, the corpus reader, and the letter |

Plus three from the second round (§12), each of which exists because a question the tool was
answering implicitly deserved a module that could be read and argued with:

| Module | The question it answers |
|---|---|
| `ats.py` | Which formatting claims are checkable, and which are folklore. The docstring names what is deliberately *not* checked, which is the harder half |
| `letter_review.py` | Whether a cover letter is worth reading, as opposed to whether it is true — `ground.py` already owns the second |
| `meter.py` | What a run cost. Tokens and calls, never currency |

## 6. CLI surface

```bash
resume-fill init                          # bootstrap profile.yaml from LinkedIn export + résumé PDF
resume-fill blog sync                     # refresh the evidence corpus from the blog

resume-fill preview --jd jd.txt           # what the posting wants vs what the record has — free

resume-fill gen --jd jd.txt --resume      # mode 1: résumé only
resume-fill gen --jd jd.txt --cover       # mode 2: cover letter only
resume-fill gen --jd jd.txt --both        # mode 3: both  (default)

resume-fill linkedin draft                # proposed headline/About/bullets + diff vs current
resume-fill serve                         # the same generate loop, in a browser
resume-fill doctor                        # config, sources and the PDF toolchain
```

`--jd` takes a file path, an `https` URL, or `-` for stdin. `gen` also accepts `--out`,
`--max-iter`, `--threshold`, `--pages` and `--strict`; every one of them defaults to the
corresponding `.env` setting.

`preview` calls no model at all (§12f). It is the deterministic lexicon pass plus the
ceiling, both of which depend on the posting and the record rather than on anything a model
writes.

## 7. Config (`.env`)

```
LLM_API_KEY=
LLM_BASE_URL=https://api.cerebras.ai/v1     # or https://api.deepseek.com
LLM_MODEL=qwen-3-235b-a22b-instruct         # or deepseek-v4-flash

BLOG_URL=
SCORE_THRESHOLD=80
MAX_ITER=4
CEILING_SLACK=2.0          # stop this close to what the record can reach (§12c)
MIN_GAIN=1.5               # a rewrite gaining less than this is noise
```

---

## 8. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold | uv project, config, LLM client talking to Cerebras/DeepSeek |
| M1 | Profile bootstrap | `init` produces a `profile.yaml` you only have to lightly correct |
| M2 | Tailor + ground | `resume.json` generated, every bullet traceable, validator blocks fabrication |
| M3 | Render + verify | PDF out, round-trip parse assertion passing |
| M4 | Score + iterate | Score breakdown, gap report, auto-retry loop |
| M5 | Cover letter | Second template, three-mode flag wired |
| M6 | Blog + LinkedIn draft | Evidence corpus feeding tailoring; profile-copy diff |

M1–M4 are the tool. M5 is cheap once M2–M3 exist. M6 is the part you described first but depends on
everything else, so it lands last.

**All six are done**, one branch and one PR each, in that order. M5 was cheap exactly as
predicted. The estimate that was wrong was M1: seeding a profile from a résumé PDF is where most of
the heuristics live, because a PDF's text layer is not its layout.

---

## 9. Open questions — resolved

The grilling session stopped at these. Each was decided during the build, in the milestone that
first needed it.

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | **Blog URL** — blocking all of M6 | Not needed. `BLOG_URL` is config; ingestion autodetects | A blog only tells you which mechanism it supports by responding. `blog.discover()` tries a declared `<link rel=alternate>` feed, then conventional feed paths, then `sitemap.xml`, then landing-page links, and reports which route fired |
| 2 | **JD input** — file, stdin, or URL | All three | One function each. Picking one would have been the only wrong answer |
| 3 | **Résumé length** | `RESUME_MAX_PAGES=1`, configurable, `--pages` per run | Overflow is a named format failure fed back to the tailor, so the loop shortens rather than the user re-running. `FONT_PT` is the other lever; below ~9.5pt a second page is the better trade |
| 4 | **Cover letter parameters** | `COVER_LETTER_WORDS=300`, tone in config, addressee falls back to "Hiring Manager" | Nothing in a posting reliably names an addressee, and scraping a name off a company page is how a letter ends up addressed to someone who left. A convention beats a fake personalisation |
| 5 | **Loop tuning, and an honest-but-low ceiling** | `SCORE_THRESHOLD=80`, `MAX_ITER=4` kept. Below threshold **emits with a warning**; `STRICT_SCORE` / `--strict` makes it fail | The gate is what stopped the loop inflating the number, so a low ceiling is the *answer*, and `report.md` names the experience the role wants that you do not have. A failed **parse** check is always fatal — that is the one guarantee the tool makes |
| 6 | **`profile.yaml` and git** | Gitignored; `profile.example.yaml` is committed | It holds full contact details and employment history. The example doubles as the test fixture, which keeps it honest |
| 7 | **Profile variants** | Not built. `PROFILE_PATH` already points anywhere, and `profile.*.yaml` is gitignored | `PROFILE_PATH=profile.ml.yaml resume-fill gen ...` covers it with no new concept. A `--variant` flag would be a second way to say the same thing |
| 8 | **Output retention** | Keep everything; `out/` is gitignored | Runs are cheap, named `<company>-<role>-<date>`, and keeping `resume.json` is what makes two runs diffable. Nothing prunes on your behalf |

---

## 10. What the build turned up

Facts discovered by writing it, not by planning it. Each one changed the code.

| Finding | Consequence |
|---|---|
| **Chromium's flexbox reorders the PDF text layer.** A two-column entry header (`justify-content: space-between`) extracts with the right-hand column *after* the bullets — verified by rendering one and reading it back. A Word résumé with a right tab stop does the same. | The rendered résumé is strictly single column, dates inline. `resume_pdf.py` also had to learn to reattach an orphaned date line, since real résumés arrive this way |
| **Jinja autoescape silently breaks an inlined stylesheet.** `font-family: "Helvetica Neue"` becomes `&#34;Helvetica Neue&#34;`, which Chromium discards as invalid and falls back to serif — no error anywhere. | The stylesheet is wrapped in `Markup` at the single point it enters the context. Found by looking at the rendered page, not by a test failing |
| **Squashing punctuation out of both sides of a term match is far too eager.** `.NET` squashes to `net`, which is inside `Kub‑e‑r‑net‑es`. | `contains_term` builds separator-tolerant patterns from the term's *own* alphanumeric runs instead, and asserts boundaries only on edges that are alphanumeric (`C++` ends on punctuation, `.NET` starts on it) |
| **Every field on `ResumeDoc` has a default**, so an unrelated JSON object validated into an empty document — and grounding *passed* it, because there was nothing in it to be wrong. | `tailor()` rejects a document with no entries selected |
| **A skill tagged on one job's highlight is not a global claim.** Treating `profile.all_skills()` as the grounding allowance let a bullet about one job claim a tool tagged only on another. | `declared_skills()` (the curated block, assertable anywhere) is now distinct from `all_skills()` (everything, used for the skills-block subset check) |
| **A CamelCase company name is indistinguishable from a CamelCase product name.** | The cover letter passes an allowlist derived from the posting's own title and company; otherwise applying to DeepMind fails every draft |
| **A blog paragraph can be short and still be the best evidence you have.** A chunk-length minimum discarded "the old job took 51 minutes on a good night". | Filtering is per paragraph by word count, which drops navigation without touching prose |
| **PDF list markers are drawn, not written into the text layer.** | The résumé-PDF seeder classifies bullets by line length once the glyph is gone |

---

## 11. The web UI (W0–W3)

Added after the CLI was finished, from a second grilling session on 2026-07-28. Decisions:

| Decision | Chosen | Why |
|---|---|---|
| Deployment | **localhost only** | `profile.yaml` is full PII and every run spends your API key. Hosting it would mean accounts, other people's PII, and deciding who pays for the model |
| Scope | **the generate loop** | It is the thing you repeat. `init` runs once and exists to produce a file you correct in an editor |
| Stack | Preact + Vite + TS, Vite building into `resume_fill/webui` | Matches infinance; hatch `artifacts` ships the gitignored build output in the wheel |
| State | `out/` stays the only truth; each run also writes **`run.json`** | No database. `report.md` is prose for a person and must not become a parsing target |
| Progress | **stage-level**, polled ~1s | A run is 10–60s of silence per stage. Fine on a terminal, looks crashed in a browser |
| Concurrency | one at a time, 409 on a second | A `threading.Lock`. Chromium plus an LLM, on a laptop |
| JD input | **paste only** | No upload endpoint means no multipart, no PDF sniffing, no server-side fetch of a URL somebody typed |
| Cancel | cooperative, checked at stage boundaries | Killing the thread mid-render leaves a half-written PDF nothing can tell is corrupt |
| Binding | loopback; `AUTH_TOKEN` required for anything else | Copied from infinance. The failure mode is silent and the blast radius is your employment history |

**A thread, not an async task.** `render.py` uses Playwright's *sync* API, which raises inside a
running asyncio event loop. A `threading.Thread` has none — so the pipeline runs there unmodified,
and the lock is a `threading.Lock`. It has its own named test, because it would otherwise fail with
an unrelated-looking error.

**Cited source text is embedded in `run.json`, not referenced.** A citation is a receipt for a claim
on a document you may already have sent. Closing a gap means editing `profile.yaml`; if the audit
re-read the record it would silently start showing a source that no longer says what it said. It
would render, it would be wrong, and nothing would say so.

---

## 12. The loop was too expensive, and the documents were only checked for truth

A second round, after using it. Two complaints, and they turned out to have the same shape:
**the tool was strict about the wrong things and silent about the rest.**

### 12a. What a rejection cost

`ground.check()` answered "may this be rendered?" with yes or no, and no threw away the
whole document. One unsupportable token in one bullet cost the other fifteen, the render,
and an LLM call — and at `MAX_ITER=4`, three unlucky drafts produced no résumé at all.

| Decision | Chosen | Why |
|---|---|---|
| A failed draft | **repair, then re-check** | Cut out the parts that failed and put what is left through the *same* gate. Removal only: nothing is rewritten or substituted, and `.ok` means `check()` came back clean on the smaller document |
| A draft with nothing left | still rejected, still not rendered | An empty résumé is a failed run wearing a PDF |
| A repaired cover letter | floor of two paragraphs | Cutting one out of four removes a quarter of the letter; past a point the honest move is to write it again |
| What was cut | **printed** — `report.md`, `run.json`, the CLI, the run view | A résumé shorter than the model drafted is a question somebody will ask, and absorbing the difference silently is the one way repair could be dishonest |

**The gate did not move.** `tests/test_repair.py` exists to say so, and the old hard-block
tests still run against a fixture where every bullet is fabricated — the case repair
genuinely cannot help.

### 12b. What the gate rejected drafts *for*

Some of it was spelling. A bullet saying **Postgres** against a record saying **PostgreSQL**,
or **CI/CD** against a highlight saying *continuous integration*, is the same fact written
differently — and each rejection cost a full iteration to relitigate an alias.

Worse, it contradicted the tailor: rule 9 of that prompt asks the model to write in the
posting's vocabulary, and then the gate punished it for complying.

`supported_term()` now tries the literal spelling, the other names for the same concept
(`lexicon.EXPANSIONS`), the word a derived form was built from, and — against the cited
source only — the conjugations of the term itself. Nothing new may be claimed; every
accepted spelling still has to resolve to something written down. The rule for adding a pair
is that it must be interchangeable **in both directions** with no loss, which is why "ML"
for "machine learning" is in the table and "CV" for "computer vision" is deliberately not.

### 12c. The stopping rule was frequently unsatisfiable

A threshold of 80 against a record that tops out at 71.2 meant four tailor calls, four
Chromium launches and four PDF round trips to arrive at what the first attempt already knew
— then a report saying "below the threshold", which reads as a failure and is not one.

`score.ceiling()` computes the highest score a perfect selection from the record could get
against this posting, **before the first model call**, because it does not depend on what
the model does. (It reproduces `HONEST_CEILING = 71.2`, a constant that had been measured by
hand into the test suite.)

| Stopping rule | Meaning |
|---|---|
| `threshold` | the score reached what was asked for |
| `ceiling` | the score reached what this record can reach for this posting |
| `plateau` | the rewrite gained less than `MIN_GAIN` over the best so far |

A PDF that does not parse is still worth another attempt regardless of its score — that is
the one thing this tool actually promises.

**Stopping at the ceiling is honest rather than lazy, and Decision 5 is the reason.** The
missing points are unreachable precisely because the only cheap way to close them is to
invent the keyword, and the gate exists to stop that. If the loop could reach 80 there, it
would already be cheating. The ceiling is deliberately *optimistic* — it assumes every
keyword anywhere in the record could fit on one page — because that direction never stops
the loop early on the grounds that something was impossible when it was merely hard.

`--strict` changed meaning to match: it fails only when the threshold was **reachable** and
the run missed it. Failing a run for missing a number that was never available would be
scoring the candidate on experience nobody claimed they had.

### 12d. Machine-readability, checked instead of asserted

The `format` component was five hand-rolled booleans about bullet length. `ats.py` replaces
it with a rubric, at the same weight, and — more importantly — with a written rule for what
is allowed in it:

> a check must be about something a parser or a human reviewer demonstrably does with the
> document, not about a number somebody claims a machine assigns to it.

Which splits the list in two, and the split is the point. **Parsing** failures (dates a
parser cannot read, no email to key the record on, a heading it files under "other", a
layout that reorders the text layer) mean the document is invisible on the other side.
**Reading** failures (no figures, "responsible for", first-person pronouns) mean it is
weaker to a person — advisory, always, because putting style advice behind this tool's one
real guarantee would make that guarantee mean less by association.

Listed in the module docstring so nobody adds them back: keyword-density targets, "match
score" percentages, white-text injection, absolute length rules, and any claim that a font
or a file name affects ranking.

### 12e. The cover letter was only checked for truth

`ground.py` asks whether any of it is false. Nothing asked whether any of it was worth
reading — and a letter can pass the gate completely while opening *"I am writing to express
my interest in the Backend Engineer position"*, which is the most common first line in the
pile and the specific thing a reader is scanning for.

Three findings recur across 2024–26 recruiter surveys, and all three are checkable, which is
why `letter_review.py` is a module and not a longer prompt: a letter **is** read, often
before the résumé; the opening sentence is where it is lost; and readers report recognising
machine-written applications, naming a small stable vocabulary as the tell.

Blocking (a rewrite reliably fixes it, so the loop retries): a formulaic opening, "To Whom
It May Concern", a word count outside 150–420, fewer than three paragraphs, no figure and no
tool anywhere in it, nothing the posting asked for appearing at all.

Advisory: the machine-written vocabulary, praise aimed at the employer, every paragraph
opening on "I", quoting the advert back at the person who wrote it.

Deliberately not checked: tone, warmth, "passion" — anything needing an opinion about the
candidate rather than a fact about the text. A letter that fails nothing here can still be a
bad letter. That is a smaller claim than the module could have made, and a true one.

### 12f. Two things that were free and were not being given away

| Addition | Why |
|---|---|
| `resume-fill preview` and `POST /api/analyze` | The question people open the tool with is *"is this posting worth applying to, and what will it say I am missing?"* — and the two stages that answer it (the lexicon pass and the ceiling) have never needed a model. Running the whole loop to find out cost a minute and four calls for an answer that does not improve for having been paid for. A test asserts no model call happens, because "free" is the whole proposition and it is the kind of promise that quietly stops being true |
| `meter.py` | "Iterations: 3" is not a price, and the three stopping rules above are a trade between spending and quality. A trade nobody can see the price of is a trade nobody can tune. Tokens and calls, never currency: rates differ per provider and change without notice, and a stale multiplier printed to two decimal places would be worse than no number |

### 12g. What this round turned up

| Finding | Consequence |
|---|---|
| **The tailor prompt and the grounding gate were arguing.** Rule 9 asks for the posting's vocabulary; the gate rejected the draft for using it whenever the record spelled the same concept differently. | `lexicon.EXPANSIONS` and `ground.supported_term()`. Every pair in the table is one that cost a whole iteration to relearn |
| **Growing a tool name into a verb is far more dangerous than shrinking one.** `Spark` + `-ed` makes "sparked", which appears in ordinary prose; `Docker` + `-ised` does not. | The two derivation lists differ on purpose, and `-ed`/`-ing` are absent from the one that grows. There is a test named after "sparked a redesign" |
| **`HONEST_CEILING = 71.2` had been measured by hand and written into the test suite.** `score.ceiling()` computes it. | The number stopped being a magic constant, which is also the strongest evidence the ceiling is calculated correctly |
| **The honest draft sits exactly *at* the record's ceiling**, so it now ends the loop by itself — correct behaviour, and useless for testing iteration. | The loop-control tests use two deliberately-suboptimal drafts instead |
| **`tailor()` has had an `extra_rules` parameter since M2 and nothing ever passed one.** | `ats.TAILOR_RULES` goes into the *first* prompt. Every rule in it is something the first draft could simply have done, and a retry costs a model call |
| **The web UI's cover letter could be previewed and downloaded but not pasted**, which is how a cover letter is actually submitted most of the time. | A plain-text view and a copy button, with a `<textarea>` fallback — the clipboard API is not guaranteed on plain-HTTP localhost |
| **A stubbed `complete_json` is not a provider**, so the API tests meter zero calls. | `test_meter.py` owns the arithmetic; the API test asserts only that the field is exposed, and says why in its docstring |
