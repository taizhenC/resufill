# resume-fill — Plan

A local CLI that turns a canonical record of your career into a job-specific résumé and cover
letter, and drafts LinkedIn profile copy from your blog.

Status: **design agreed, not yet implemented.** Produced from a `/grill-me` session on 2026-07-25.

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

## 6. CLI surface

```bash
resume-fill init                          # bootstrap profile.yaml from LinkedIn export + résumé PDF
resume-fill blog sync                     # refresh the evidence corpus from the blog

resume-fill gen --jd jd.txt --resume      # mode 1: résumé only
resume-fill gen --jd jd.txt --cover       # mode 2: cover letter only
resume-fill gen --jd jd.txt --both        # mode 3: both  (default)

resume-fill linkedin draft                # proposed headline/About/bullets + diff vs current
```

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

---

## 9. Open questions

Not yet decided — the grilling session stopped here.

1. **Blog URL.** Blocking all of M6. Once known, ingestion mechanics (RSS vs sitemap vs HTML scrape,
   date/tag extraction) get determined by inspection rather than by asking.
2. **JD input method.** File path, stdin paste, or scrape from a posting URL?
3. **Résumé length.** Hard one-page cap, or allow two pages when the evidence justifies it?
4. **Cover letter parameters.** Target length, tone, and what to do when the addressee is unknown.
5. **Loop tuning.** Confirm `SCORE_THRESHOLD=80` and `MAX_ITER=4`, and decide what happens when the
   ceiling is honest-but-low — fail, or emit with a warning?
6. **`profile.yaml` and git.** It holds full contact details and employment history. Commit it, or
   gitignore it and keep only `profile.example.yaml`?
7. **Profile variants.** One `profile.yaml`, or separate emphases (e.g. SWE vs ML) selected per run?
8. **Output retention.** Keep every run in `out/` forever, or prune?
