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
| There is **no ATS score an employer sees.** Greenhouse and Lever don't rank by keyword at all; they parse into fields for recruiter search. Taleo/iCIMS do keyword search. Jobscan-style "scores" are vendor heuristics. | The score in this tool is an explicitly-labelled *local proxy*, not a real-world metric. The guarantee that actually matters is parse survival. |
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

## 6. CLI surface

```bash
resume-fill init                          # bootstrap profile.yaml from LinkedIn export + résumé PDF
resume-fill blog sync                     # refresh the evidence corpus from the blog

resume-fill gen --jd jd.txt --resume      # mode 1: résumé only
resume-fill gen --jd jd.txt --cover       # mode 2: cover letter only
resume-fill gen --jd jd.txt --both        # mode 3: both  (default)

resume-fill linkedin draft                # proposed headline/About/bullets + diff vs current
resume-fill doctor                        # config, sources and the PDF toolchain
```

`--jd` takes a file path, an `https` URL, or `-` for stdin. `gen` also accepts `--out`,
`--max-iter`, `--threshold`, `--pages` and `--strict`; every one of them defaults to the
corresponding `.env` setting.

## 7. Config (`.env`)

```
LLM_API_KEY=
LLM_BASE_URL=https://api.cerebras.ai/v1     # or https://api.deepseek.com
LLM_MODEL=qwen-3-235b-a22b-instruct         # or deepseek-v4-flash

BLOG_URL=
SCORE_THRESHOLD=80
MAX_ITER=4
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
