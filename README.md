# resume-fill

A local CLI that turns a canonical record of your career into a job-specific résumé and cover
letter, and drafts LinkedIn profile copy from your blog.

**Nothing it writes is invented.** Every bullet carries the id of the source it came from, and a
validator rejects the document if a claim cannot be traced back to `profile.yaml` or the evidence
corpus. Keywords the job description wants but your record cannot support are reported as **gaps**,
never quietly inserted.

See [PLAN.md](PLAN.md) for the design, the decisions, and what building it turned up.

## Install

```bash
uv sync
uv run playwright install chromium   # the PDF renderer; this machine has no Word/LaTeX/pandoc
cp .env.example .env                 # then fill in LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
uv run resume-fill doctor
```

Any OpenAI-compatible endpoint works. Cerebras and DeepSeek are both a two-line `.env` swap.
`doctor` actually launches Chromium and imports pdfminer rather than checking that the wheels are
installed, because a missing browser is the failure you want to find before a deadline.

## Use

```bash
# 1. Build the record. Reads a LinkedIn data export for the skeleton (employers, titles, dates)
#    and an existing résumé PDF for the bullets and the contact block.
resume-fill init --linkedin-export data/linkedin_export --resume-pdf old-resume.pdf

# 2. Optional: add an evidence layer from your blog. Feeds/sitemaps are autodetected.
resume-fill blog sync

# 3. Generate. --jd takes a file, an https URL, or - for stdin.
resume-fill gen --jd jd.txt              # résumé + cover letter (default)
resume-fill gen --jd jd.txt --resume     # résumé only
resume-fill gen --jd jd.txt --cover      # cover letter only
cat posting.txt | resume-fill gen --jd -

# 4. Optional: proposed LinkedIn copy, as a diff. You paste it.
resume-fill linkedin draft --export data/linkedin_export
```

## Or in a browser

```bash
cd frontend && npm ci && npm run build && cd ..
resume-fill serve
```

Opens `http://127.0.0.1:8765`. Same pipeline, same `out/` directory, same `profile.yaml` — the
server is a thin JSON API over the library the CLI already uses, so a run started in either
place is indistinguishable afterwards.

It covers the generate loop only: paste a posting, pick a mode, watch each stage as it happens,
then read the score breakdown and gap list with the PDFs rendered inline. `init`, `blog sync` and
`linkedin draft` stay on the command line — they run once, and `init` exists to produce a file you
then correct by hand in an editor.

The one thing the browser does that a terminal cannot: **audit the résumé claim by claim**. Every
bullet expands to the source text that licensed it, snapshotted at generation time, so editing
`profile.yaml` later cannot quietly change what a résumé you already sent appears to stand on.

It binds to loopback and refuses to start on any other address unless `AUTH_TOKEN` is set — this
server reads your contact details and employment history, and every run spends your API key.

Output lands in `out/<company>-<role>-<date>/`:

| File | What it is |
|---|---|
| `resume.pdf`, `cover_letter.pdf` | The documents |
| `resume.json` | The intermediate — kept so two runs can be diffed |
| `report.md` | Score breakdown, gap list, and a citation for every bullet |
| `resume.html` | What was handed to Chromium, for when a bullet fails the parse check |

## `profile.yaml` is the point

It is the source of truth, and it is the only part that needs a human. `init` seeds it and prints
everything it had to guess; correct those once, by hand. It is gitignored — it holds your contact
details and employment history — and [`profile.example.yaml`](profile.example.yaml) is the
committed shape.

Every entry and every highlight has an id. Those ids are what a tailored bullet cites, which is
what makes the fabrication gate possible at all.

The `skills:` block is the one place a tool may be claimed without a bullet backing it. Keep it to
things you would defend in an interview.

## About the score

The number in `report.md` is a **local proxy**, not a metric any employer computes. Greenhouse and
Lever do not rank by keyword at all; Taleo and iCIMS do recruiter-side keyword search. It is a
stopping rule for the rewrite loop, printed as a weighted breakdown and never as a bare number.

Because the validator blocks invention, the loop **cannot raise its score by making things up**. A
low ceiling is therefore information: the role genuinely wants things you have not done yet, and
`report.md` says which. It separates two kinds of gap that mean very different things:

- **in your record but not on this résumé** — a tailoring miss, fixable by editing the record;
- **not in your record at all** — a fact about you, which no rewrite closes.

A score below the threshold is a warning, not a failure (`--strict` changes that). A PDF that fails
its **parse** check is always a failure — every build extracts the text back out of the file it
just produced and asserts the contact block, every section heading and every bullet survived the
round trip. That is the guarantee that actually matters.

## LinkedIn

Draft-and-paste, by design. LinkedIn has no public write API for profile fields, and automating the
live account violates the User Agreement §8.2 — on the exact profile you are trying to polish.
`linkedin draft` prints the proposed copy and a diff; you paste it in. The module has no LinkedIn
client, no session and no credentials, and a test asserts that against its source.

## Development

```bash
uv run pytest        # 207 tests
uv run ruff check .
```

The PDF tests render real files with the same Chromium the tool ships with and parse them back —
a PDF's text layer is not its markup, and that gap is what the verifier exists to police. They skip
cleanly if `playwright install chromium` has not been run.
