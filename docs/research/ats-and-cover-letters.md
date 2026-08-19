# ATS parsing, résumé content, and cover letters

_A research brief for `resume-fill`. Compiled 2026-08-19._

Every non-obvious claim below carries a URL. Where a widely-repeated claim has no primary source,
it says so instead of repeating it. Where sources contradict each other, both are shown and the
contradiction is left standing rather than resolved by preference.

**Trust labels.**

| Label | Meaning |
|---|---|
| **primary** | Vendor developer/admin documentation, regulator, court filing, standards body, peer-reviewed paper |
| **vendor** | Vendor help centre, marketing, or press release — first-party but not technical documentation |
| **survey** | A named survey with a disclosed sample and fielding date |
| **interested** | A company that sells résumé or hiring services publishing research about résumés or hiring |
| **folklore** | Widely repeated; no primary source found |

---

## What this means for `resume-fill`

Ten changes, ordered by value. Each links to the section that justifies it.

1. **Correct the README and PLAN.md §2.** The claim "Greenhouse and Lever do not rank by keyword at
   all" was true when written and is **no longer true**. Greenhouse shipped **Talent Matching**
   (Real Talent, 16 Sep 2025) which scores résumés into Strong/Good/Partial/Limited and highlights
   "matched terms on this resume"; Lever shipped **Talent Fit** (26 Jun 2025) which ranks résumés
   against the JD with an LLM. Workday, Ashby and iCIMS all score too. **What survives intact is the
   sharper claim**: no vendor documents auto-rejection on résumé *content* — every documented
   automatic rejection fires on structured application-question answers. And Jobscan-style match
   scores still have no validated standing anywhere. See [A1](#a1), [A7](#a7).

2. **Add a "parse-hostile artefact" scan to `verify.py`.** The round-trip already asserts that text
   *survives*. It does not yet assert that the text is *clean*. Add assertions against Private Use
   Area codepoints, ligature presentation forms `U+FB00`–`U+FB06`, and letter-spacing artefacts —
   all three are documented parse-killers and all three are silent. Greenhouse names spaced-out
   letters as its **first** listed formatting failure. See [A2](#a2), [D-T0](#d-tier-0).

3. **Seed every skill into a dated bullet, not just the Skills block.** Textkernel, Sovren, RChilli
   and Affinda all attach `MonthsExperience` / `LastUsed` / `FoundIn` metadata to skills, derived
   from the work-history entry the skill was found in. A skill that appears *only* in a bare Skills
   list gets nulls for all of them and **fails a recruiter filter like "Python, 3+ years, used in
   the last 2 years"** even though the word is on the page. Textkernel's quality checker actively
   flags a standalone Skills section (code 112). Keep the block — humans skim it — but treat
   `profile.skills` entries that never surface in a bullet as a reportable gap. See [A5](#a5).

4. **Assert the contact block is in the first N characters of the extracted text.** Textkernel code
   **311** is a Major Issue for "a contact information section was found somewhere other than the
   top of the resume." `verify.py` currently checks the contact block *exists*; it should check
   *where*. Also assert exactly one email and one phone (codes 132/133). See [A4](#a4).

5. **Pin the date grammar and enforce it.** `Month YYYY – Month YYYY`, spaced en-dash `U+2013`,
   `Present` with a capital P, never numeric-only, never seasons, never stacked across two lines
   (Textkernel **418** is Fatal), no commas inside the date string. One real parser matches
   `Present` as a **case-sensitive literal**, and its month matcher rejects `Jan`/`Feb`/`Aug`/`Oct`
   but accepts `June`/`July`/`Sept` — spell months out. See [A3](#a3).

6. **Rewrite the cover-letter prompt around the words the evidence actually implicates.** The
   existing prompt already bans "I am writing to apply for" and subject lines — good, and
   independently corroborated by HBR and Cornell. Add the 407-word Kobak excess-style-word list as
   a *density* check rather than a blocklist (most of those words are ordinary English), plus the
   structural tells: `not only X but also Y`, `it's not X, it's Y`, trailing `-ing` participial
   clauses, em-dash density, and rule-of-three parallelism. See [C13](#c13), [D-CL](#d-cover-letter).

7. **Set the cover-letter word budget to 250–400 and the paragraph budget to 3–4.** Princeton says
   250–400. Anthropic's own live application form says "great answers are often 200-400 words".
   Yale says three to four paragraphs, with intro/close at 1–3 sentences and body at 3–5. The
   current `paragraph_budget()` (`words/75`, floor 3, ceiling 5) is close; tighten the ceiling to 4
   and set `COVER_LETTER_WORDS` default to 350. See [C12](#c12).

8. **Keep the score, keep the disclaimer, but change what it disclaims.** The honest 2026 statement
   is not "no ATS computes a score" — several do. It is: *the scores that exist are computed from
   the employer's own calibration, which you cannot see, and are documented as advisory input to a
   human. No third-party tool reproduces them.* The gap list remains the genuinely useful output.
   See [A6](#a6), [A7](#a7).

9. **Do not chase a quantification ratio you cannot justify.** No source — not one university
   career centre, not one study — specifies what fraction of bullets should carry a number. The
   universal phrasing is "quantify where you can". A ratio check is still worth *reporting* as a
   warning, but the threshold must be labelled as a house convention, not a finding. See [B9](#b9).

10. **Emit a DOCX alongside the PDF, eventually.** Vendors flatly contradict each other: Greenhouse
    says "Upload a PDF for best results"; Textkernel says "**If you want to minimize conversion
    problems, don't use PDF documents**" and flags "the document was PDF" as a Major Issue (code
    300); iCIMS says "Submit text-based documents, not PDFs". This is genuinely unsettled, and
    PDF-only is a real if modest risk. Not urgent — decision 6 in PLAN.md is defensible — but the
    justification should be "we accept a known contested risk", not "PDF is fine". See [A2](#a2).

**One thing to explicitly not do:** hidden text of any kind — white-on-white, 1pt, off-page, or
PDF-layer tricks. It is measurably detected in production, it is on the record as disqualifying,
and its effectiveness collapses toward zero as adoption rises. See [A6](#a6).

---

# Part A — résumé parsing and ranking

<a id="a1"></a>
## A1. What each ATS actually does with an uploaded résumé

**The headline, across all seven platforms: no vendor documents a feature that auto-rejects a
candidate based on the content of the résumé document.** Every documented automatic rejection fires
on **structured application/questionnaire answers**. AI résumé scoring is separately real and now
near-universal, but is documented as rank-and-surface-to-a-human.

The real mechanism of harm is not a robot reading your résumé and saying no. It is (a)
employer-configured knockout questions, (b) a recruiter bulk-rejecting a list **sorted by an AI
score**, and (c) a parse failure collapsing into a low score that is visually indistinguishable
from a genuinely weak candidate.

### Greenhouse

**Parsing.** "Greenhouse Recruiting scans an imported resume and auto-fills appropriate fields with
information it detects." Accepts `.doc .docx .pdf .rtf .txt` up to 100 MB — but **parses only up to
2.5 MB**. That gap is a trap: a 4 MB file uploads successfully and silently fails to parse. Full
parsing in 25+ languages.
[[formats]](https://support.greenhouse.io/hc/en-us/articles/360052218132-Supported-formats-for-resumes-cover-letters-and-other-candidate-uploads)
[[parse failure]](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse)
[[languages]](https://support.greenhouse.io/hc/en-us/articles/205019689-Resume-parsing-with-non-English-languages) — **primary**

**Auto-reject: yes, but only on application-question answers.** Greenhouse "application rules" are
"automatic actions applied to job post questions… triggered when an applicant's response to a
question fulfills the rule's conditions", and work only on Yes/No, single-select and multi-select
questions. "**You must first create a custom question on your application before you can create an
application rule.**" Résumé content cannot trigger a rule. This is what "knockout question" means
at Greenhouse.
[[rules]](https://support.greenhouse.io/hc/en-us/articles/203105595-Application-rules-overview)
[[auto-reject]](https://support.greenhouse.io/hc/en-us/articles/360000653472-Auto-reject) — **primary**

**Scoring: yes, since September 2025.** *Real Talent* launched 16 Sep 2025 and bundles Talent
Matching, Fraud Detection, Spam Blocklist and CLEAR identity verification.
[[press release]](https://www.prnewswire.com/news-releases/greenhouse-launches-new-tools-to-tame-chaotic-hiring-funnels-302556958.html) — **vendor**

*Talent Matching* is the résumé scorer. A recruiter builds a "calibration" — describes the role,
clicks Generate calibration, then adds skills and rates each one's importance. Greenhouse's own tip:
"Since the match score is spread across the selected skills, for clearer matches, we recommend
focusing on **4–6 key skills**." Five buckets: **Strong / Good / Partial / Limited / Needs manual
review**. The recruiter side panel shows "The candidate's resume, with **matched and similar
keywords highlighted** based on your calibration", plus counts like "Calibrated skills matched: 2
of 4" and "Matched terms on this resume: 4". So it is partly keyword-driven, with exact-match and
similar-match highlighting.
[[Talent Matching]](https://support.greenhouse.io/hc/en-us/articles/41396009937307-Talent-Matching) — **primary**

Greenhouse is unusually explicit about what it will not do:

> "Talent Matching is assistive AI, not automated-decision-making. **It does not automatically
> advance or reject candidates.**"
> — [Talent Matching](https://support.greenhouse.io/hc/en-us/articles/41396009937307-Talent-Matching)

> "**No. Talent Matching does not auto-reject or auto-advance any candidate.**"
> — [Talent Matching FAQ](https://support.greenhouse.io/hc/en-us/articles/41131886674075-Talent-Matching-FAQ)

**Two things a candidate should know.** First, "Needs manual review" is assigned when "Their resume
could not be processed by AI", the job has AI off, or the candidate opted out — so **a parse failure
at Greenhouse routes you to a human rather than sinking you**. Second, what the algorithm reads:

> "**The matching algorithm is only using data coming from the resume.** Greenhouse parses the
> resumes with ML models and extracts skills, job titles, years of experience, start/end dates of
> employment, and company names from employment history as structured data. **Currently, structured
> application form data is not included in this calculation.**"
> — [Data Processing FAQ](https://support.greenhouse.io/hc/en-us/articles/44504950876315-Talent-Matching-Data-Processing-FAQ) — **primary**

⚠️ **Greenhouse contradicts itself here.** The sample candidate-facing disclaimer in the main Talent
Matching article says "Talent Matching reviews your resume **and responses to application
questions**." Two primary docs, opposite claims. Take neither as settled.

Technology: "a series of fine-tuned LLM models, each one trained for a specific extraction task…
The system also uses third-party models such as OpenAI", under a DPA prohibiting training use.
Parsed résumés cached 30 days. "The system does not use names or any contact information for the
matching algorithm to avoid bias." Biased or soft-skill calibration terms are flagged and "in
extreme cases, they are blocked from saving the calibration."

**The honest caveat to the "never auto-rejects" line.** The Talent Matching table lets a recruiter
"Select multiple candidates to advance, **reject**, or leave feedback on them" — whereas classic
Greenhouse bulk review says "You will still need to individually review, move, or reject each
application."
[[bulk review]](https://support.greenhouse.io/hc/en-us/articles/115003558531-Review-applications-in-bulk) — **primary**
Real Talent introduced multi-select rejection on a list sorted by AI score. That, not autonomous
rejection, is how AI screening actually removes people at Greenhouse.

Greenhouse's policy page adds "**Greenhouse does not assign a single numerical score to rank
candidates**" and "AI and automation can inform, summarize and surface insight, but it is never the
final decision-maker."
[[AI principles]](https://www.greenhouse.com/ai-principles) — **vendor**

### Lever

**Documentation caveat:** `help.lever.co` renders only an error shell to fetchers. Quotes below came
from the search engine's index of those pages, corroborated across two independent queries — weaker
than a direct fetch.

**Parsing — verified directly from Lever's public API docs**
([hire.lever.co/developer/documentation](https://hire.lever.co/developer/documentation), **primary**):

> "**parsedData** — Object — The candidate's parsed resume, usually extracted from an attached
> PDF/Word document or online profile (LinkedIn, GitHub, AngelList, etc.)."

`positions` carries company name, location, job title, job summary, start and end date; `school`
carries school name, degree, field of study, summary, dates. Resume processing `status` is one of
`processing, processed, unsupported, error, null`.

**No AI score is exposed in Lever's public API.** The only `rank` field is pipeline-stage ordering,
and the docs state "Score fields are only available on feedback forms" — human interviewer ratings.
No `knockout`, `auto-reject` or `disqualify` terminology appears anywhere in the public API docs, so
**Lever's knockout capability is publicly undocumented** — unverified either way.

**Scoring: yes, since June 2025.** *Talent Fit* was announced 26 Jun 2025 as "the first step toward
our future AI Screening Companion" and "instantly ranks candidates against your job
requirements—giving you a shortlist of top matches, complete with transparent scoring and
explanations." Marketing shows percentage matches ("94% match") and tiers Strong Fit / Good Fit /
Review.
[[announcement]](https://www.lever.co/blog/levers-ai-innovations-are-here)
[[AI features]](https://www.lever.co/ai-features) — **vendor**

Per the help centre (search-index sourced, **vendor**, weaker):

> "Talent Fit uses **only the Job Description and the candidate's resume**… **No other data is
> included** from the candidate's application or other job details."
> "The candidate's resume is **anonymized**, and then compared to the job description by prompting a
> large language model… The LLM is instructed to act as a recruiter and evaluate a candidate
> **without regard to age, race, gender, or disability**."
> "Candidates are evaluated **automatically upon application**. Candidates are re-evaluated in the
> event that the Job Description is updated."
> — [Talent Fit AI Brief](https://help.lever.co/hc/en-us/articles/28081525270685-Talent-Fit-AI-Brief)

Auto-reject: the strongest fetchable statement is "**Recruiters always have the final say in
decision-making.**" Lever's "AI Rejection Email" feature *drafts* rejection feedback; it does not
make the decision. Governance claimed via IBM watsonx.governance. **No bias audit, no NYC LL144 or
EU AI Act statement found anywhere on lever.co.** Lever is the least-documented platform in this
brief.

### Workday Recruiting + HiredScore

**On upload.** Workday's parsing feature is "Autofill with Resume" (branded career sites) or "Quick
Apply" (unbranded). From the 3,263-page **Workday HCM Administrator Guide**
([PDF](https://doc.workday.com/content/dam/fmdita-outputs/pdfs/admin-guide/en-us/Admin-Guide-Human-Capital-Management.pdf), **primary**):

> "Resume parsing populates fields from a resume, and **Workday enables you to review the resume
> data**. Workday **doesn't auto-fill fields you configure as hidden or these fields: Languages,
> Skills**."
> "Resume parsing results **can vary based on resume format and order of words**. For best results,
> use resumes that **don't have images or image-based styles**."

That second sentence is one of very few pieces of primary-sourced résumé *formatting* guidance that
exists anywhere in ATS documentation. Skills are handled separately: candidates "can view and select
suggested skills" derived from the document, which they must accept.

**Parser vendor: not disclosed, and probably not Textkernel/Sovren.** Workday's
[subprocessor register](https://www.workday.com/content/dam/web/en-us/documents/legal/workday-subprocessors.pdf)
names **no** résumé-parsing vendor for Recruiting; the only parsing vendor ever listed was Daxtra for
Workday VNDLY, removed 2 Jan 2025. Textkernel's integrations page names SAP SuccessFactors, Oracle
Recruiting Cloud, Bullhorn and Salesforce — **not Workday**. Daxtra's partner page names iCIMS,
Oracle/Taleo and SAP SuccessFactors — **not Workday**. HiredScore described a "Deep Learning Global
Resume Parser" built in-house. So "Workday uses Textkernel/Sovren" is **folklore**, and the evidence
points against it.

**Base Workday Recruiting scores résumés even without HiredScore.** Three mechanisms, all in the
admin guide:

**(a) Candidate Skills Match — ML scoring.** "You can configure your tenant to review candidate job
applications and assign a **Skills Match Score** based on the similarity of skills between the job
application and job requisition… Recruiters might use this **machine learning-powered analysis**."
Scores: **Strong / Good / Fair / Low / Pending / Unable to Score**. "Workday assigns greater weight
to job applications with the required skills specified on the job requisition." Runs hourly, and
immediately on résumé attachment or requisition edit.

Explicit negative space: skills match "**doesn't consider**: How recently a candidate has acquired
relevant skills. How long a candidate used relevant skills. **Years of total work experience.**"

**The documented failure mode that matters most to a résumé generator:** "Workday can't calculate a
skills match score and displays **Low or Unable to Score** when: Either or both the job application
or job requisition are in **another language than English**… **The uploaded resume is in an
unsupported format**." A parse failure renders as "Low" — indistinguishable in the recruiter grid
from a genuinely weak candidate. This is the strongest single argument for the project's parse-gate.

Workday's liability posture: "**Customers are responsible** for understanding and complying with any
legal obligations arising from their use of Candidate Skills Match." There is a **Candidate Skills
Match Location Exclusion** setting — a compliance geofence, almost certainly built for NYC/Illinois.

**(b) Candidate Rating & Ranking — deterministic, employer-configured.** Not AI. Workday's own
worked example is the most vivid illustration in this brief of how ATS scoring encodes proxies:
Degrees weight 40, **Candidate City weight 60**; "PhD: 100 / M.S.: 90 / B.S.: 80"; "Atlanta: 100 /
Dublin: 80"; a B.S. holder in Atlanta scores `(100/100)×60 + (80/100)×40 = 92`.

**(c) Skills Cloud** — "a machine-learning-powered remote collection of skills." AI features are
gated on a tenant-level AI Data Contributions opt-in.

**Workday does ship auto-decline — but rules-based, not AI-based.** From the admin guide,
"Automatically Advance or Decline Candidates":

> "You can use condition rules to **automatically advance or decline candidates**: **When a candidate
> applies to a job.**… Create condition rules that determine whether a job application event should
> continue or end. Use information from the: Job application. Job profile. Job requisition.
> **Questionnaires completed when a candidate first applies.**"

⚠️ **Unresolved and consequential.** Skills Match Score is a reportable field *on the Job Application
business object*, and condition rules draw on "information from the job application." Workday's
documentation **neither permits nor prohibits** using Skills Match Score in an auto-decline rule.
Do not assert it either way.

**HiredScore** (acquired Feb 2024,
[announcement](https://newsroom.workday.com/2024-02-26-Workday-Announces-Intent-to-Acquire-HiredScore)).
The A/B/C/D Fit Score, from Workday's own docs
([HiredScore grades](https://doc.workday.com/hiredscore/en-us/workday-hiredscore/recruiter-productivity-/concept--hiredscore-grades.html), **primary**):

> "Workday HiredScore assigns candidates a grade in **Spotlight**… based on how well their **resumes
> match the skills and qualifications specified in the job description**… **A** — Candidate meets or
> exceeds the basic requirements. **B** — meets the basic requirements. **C** — meets some but not
> all. **D** — doesn't meet the basic requirements."

No grade is assigned when there is no résumé, an unsupported format, no job description, or a campus
requisition. Grades are **never curved** — "each candidate will receive a score of how they align to
the requirements that is independent of the pool." Recruiters can manually change a grade.

**August 2026: the grading algorithm was replaced with an LLM.** Per HiredScore release notes
(5 Aug 2026): "we enhance Workday HiredScore Spotlight by **replacing basic qualifications matching
and final grade assignment with a Large Language Model (LLM)-driven approach** that evaluates **each
screenable qualification individually** against the candidate's parsed resume… **Basic
qualifications determine whether a candidate is graded A/B or C/D.**" Rollout is opt-in and
reversible. **As of August 2026 different Workday customers — and different requisitions within one
customer — run materially different grading algorithms.** Any blanket statement about "how HiredScore
grades work" is tenant-dependent.

**Auto-reject: no.** The only automation recipe of that kind is **Candidate Fast Lane**, which
"provides the ability to **automatically advance** top-rated applicants." There is no auto-reject
recipe; rejection is a click. HiredScore's own archived position:

> "The model's output… **does not supplant human judgment**… Recruiters and hiring managers **always
> have complete discretion**… **HiredScore does not influence any decision making.**"
> — [archived hiredscore.com/nyc-legal-law](https://web.archive.org/web/20241001144018/https://www.hiredscore.com/nyc-legal-law)

That last clause is self-undermining: the entire product premise is prioritising recruiter attention.
Read it as LL144-era positioning, not a technical description.

⚠️ **Undocumented-risk behaviour worth knowing:** "HiredScore **calculates employment gaps** and time
in position" and displays them on the parsed résumé. Employment-gap surfacing has obvious
disparate-impact exposure and is **not covered by any published bias audit** — those measure grade
distribution only. This is precisely the mechanism the Harvard study identified.

### Ashby

**Auto-reject: application questions only.** "Auto-Reject allows you to reject candidates whose
application submissions match certain conditions automatically… The Rejection Condition [is] based on
application questions." Evaluated only at submission. Résumé content cannot trigger it.
[[auto-reject]](https://docs.ashbyhq.com/auto-reject-applications)
[[global rules]](https://docs.ashbyhq.com/global-application-questions-and-global-auto-reject-rules) — **primary**

**Parsing.** Résumé upload parses and fills only *missing* candidate fields; existing data wins.
Résumés must be ≤16 MB to be processed for full-text search and autofill (upload limit 50 MB).
[[candidate profile]](https://docs.ashbyhq.com/candidate-profile) — **primary**

**AI-Assisted Application Review.** "Ashby's AI assesses candidate resumes against each specific
criterion and returns an evaluation status… the candidate **meets, does not meet, or the AI was
undecided**." Rationale is shown; users can flag an evaluation as incorrect.
[[docs]](https://docs.ashbyhq.com/ai-assisted-application-review) — **primary**

⚠️ **A sharp marketing-vs-documentation contradiction, worth flagging because a widely-read blog
repeats the marketing side as fact.** Ashby's public AI page says "The AI **never 'ranks' or gives
numerical ratings** to applicants, a human must always be involved in decision-making"
([ashbyhq.com/ai](https://www.ashbyhq.com/ai), **vendor**). Ashby's own product documentation says:

> "you can also add an **AI job criteria met percentage** column to see the percentage of AI criteria
> each candidate met… **sort by this column to move the best fit candidates (highest percentage) to
> the top of your review queue and identify the lowest fit candidates (lowest percentage) at a
> glance**"
> — [AI-Assisted Application Review](https://docs.ashbyhq.com/ai-assisted-application-review) — **primary**

A sortable per-candidate percentage is a numerical rating and a ranking.

Ashby claims "PII is redacted from all resumes sent to AI models", no training on customer data, a
**FairNow** bias audit, and compliance with GDPR / NY Local Law 144 / SOC 2. **The FairNow report is
not published anywhere findable.** Separately, Warden AI publishes a public dashboard for an
**"Ashby — AI Interviewer"** (audited 4 Aug 2026, 48,600 interviews, LL144 methodology "Scoring") —
a product with **no page and no documentation on ashbyhq.com**.
[[trust.warden-ai.com/ashby]](https://trust.warden-ai.com/ashby) — **vendor**

### iCIMS

**Parser: Daxtra — not Textkernel/Sovren.** This corrects a widely repeated claim. iCIMS's own
sub-processor list (last modified 15 Dec 2025) names "**Daxtra Technologies, Ltd** — Purpose:
**Resume parsing, redaction, and searching capabilities**". Enumerating the full list, Daxtra is the
only parsing vendor named — and **no LLM vendor appears at all**, which makes the third-party claim
that iCIMS Copilot is "GPT-4-powered" unverified.
[[subprocessors]](https://www.icims.com/subprocessors/) — **primary**

The likely origin of the Textkernel error: an iCIMS blog *cites* Textkernel as a research source
while never claiming Textkernel is its parser.

**Scoring: yes — "Candidate Ranking."** From iCIMS's own blog, first-person about their product:

> "We engaged **BABL AI, Inc.** to perform an independent bias audit of the iCIMS '**Candidate
> Ranking**' algorithm per the requirements outlined in the new NYC local law."
> "The algorithm… assists recruiters with hiring decisions by **providing a ranked list of applicants
> against a position's requirements**."
> — [iCIMS blog](https://www.icims.com/blog/beyond-the-hype-the-essential-need-for-fair-and-compliant-ai-hiring/) — **vendor**

**The BABL AI audit itself is not published.** The finding exists only as a sentence in a blog post.

**iCIMS Copilot does not rank** — its five documented capabilities are interview-question generation,
JD optimisation, career-site SEO, translation, and a search-string assistant.
[[copilot]](https://www.icims.com/copilot/) — **vendor**

iCIMS's help centre is login-gated, so there is **no publicly readable iCIMS admin documentation**.
The best public evidence for screening behaviour is a customer training deck reproducing the actual
UI labels: "**Screening Question Score** and responses", "Bin C for those **disqualified off of
screening questions**", "Did Not Pass MQ/Level 1 Screening… **This will send an automatic email
declining the applicant**".
[[Larimer County deck, PDF]](https://www.larimer.org/sites/default/files/screeningcandidates.icims_.pdf) — **secondary**
**Whether iCIMS performs a hard submit-time auto-disqualification cannot be confirmed from primary
sources.**

iCIMS is also the source of the clearest vendor statement on keyword ranking and on white text — see
[A2](#a2) and [A6](#a6).

### Oracle Taleo

**Parsing: outsourced, unnamed, disclaimed.** From Oracle's own *Implementing Recruiting* 22D guide:

> "**Resume Parsing: Resume parsing is delivered using a third party partner service. The
> functionalities are delivered as-is. Customers needing additional or different resume parsing
> capabilities should explore partner services.**"
> — [PDF](https://docs.oracle.com/en/cloud/saas/taleo-enterprise/22d/otrcg/implementing-recruiting.pdf) — **primary**

Grepping both 22D guides for `textkernel|sovren|daxtra|hireability|resumix` returns **zero hits**.

⚠️ **"Taleo has notoriously bad parsing" is unsourced.** No Oracle statement, support note, or
credible measurement quantifies Taleo parse accuracy. The defensible substitute is Oracle's own
"delivered as-is… explore partner services".

**The most important finding here: Taleo scores questionnaire answers, not résumé text.** Stated
twice in Oracle's own words: "**It identifies top candidates based on their responses to the
competencies and questions in the Prescreening section** of the requisition file."

The ACE model ([*Using Recruiting* 22D](https://docs.oracle.com/en/cloud/saas/taleo-enterprise/22d/otfru/using-recruiting.pdf), **primary**):
**disqualification questions** — "Answers to the disqualification questions decide if candidates move
forward… or are **automatically disqualified**"; **Required** vs **Asset** competencies; **Weight**
as "an optional third level filter"; and a **Result %** threshold above which candidates become
"ACE candidates" (Oracle's suggested starting point: 75%). Three buckets: ACE / minimally qualified /
other.

**A documented employer-misconfiguration trap worth knowing:** "If a Bachelor's Degree is required,
you must mark that answer **and all answers greater than that answer** as required. **Otherwise, a
candidate that answers Master's degree won't be recorded as having met the requirement.**"

**Where résumé text matters: recruiter-initiated search only.** Taleo's conceptual/keyword search
indexes the pasted résumé, career objectives, education, work experience, text answers, and "**The
last three attachments per candidate**". And a sting: "**The conceptual search cannot retrieve
disqualified candidates because they are not indexed in the database.**" A knockout question makes
you invisible to sourcing too.

Neither Taleo guide mentions Local Law 144, AEDT, automated employment decisions, or bias audits
(grep-verified).

### SAP SuccessFactors Recruiting

**Parser: Textkernel — confirmed twice from SAP primary sources.**

> "**SAP SucessFactors uses the third-party software Textkernel to parse resume data.**"
> *(SAP's typo)* — [*Setting Up and Maintaining SAP SuccessFactors Recruiting*, release 2605, §21.1.6, PDF](https://help.sap.com/doc/ffb88b2705684ab0be068897766d72de/2605/en-US/SF_RCM_Admin.pdf) — **primary**

> "**Third party software Text kernel is used to parse resume data.**"
> — [SAP KBA 2081576](https://userapps.support.sap.com/sap/support/knowledge/en/2081576) — **primary**

**What parsing does:** "reads information from candidates' resumes and automatically enters it in the
corresponding candidate profile fields." SAP is refreshingly blunt: "**Resume parsing isn't always
100% accurate. This is a known limitation.**" and "**The creation of candidates through API does not
support parsing.**" 15 fields populated; 15 languages; accepts DOCX/PPT/TXT plus TIFF/JPG/BMP/GIF.
[[docs]](https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/282b8727ec494684b2ef8e26a75788b6.html) — **primary**

**SAP is the most explicit of all seven platforms about auto-disqualification — and it is
question-based:**

> "These pre-screen questions can be used to gather information, **score the applicants and
> automatically disqualify applicants** who meet certain criteria."
> "**Disqualifier**: … **If a question is selected as a disqualifier, applicants who don't provide a
> correct answer are automatically disqualified.**"
> "Determine the **Required Score** needed… **Rating Calculation per question = [Points per
> question/Total points] * 100**… If the applicant's total score falls below the Required Score
> threshold, **the applicant is automatically disqualified**."
> "**Applicants who fail the prescreen are automatically placed into the Auto-Disqualified status.**"
> — [§18.21](https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/bc8e6ee9269d4d6b878a047fd8b41119.html),
> [§18.24](https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/7fb8cc95f55e492d94376e39d229e2f6.html),
> [auto-disqualified](https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/9d005b9f377f4927815bd6fe670fa3ba.html) — **primary**

The Required Score is computed from **question answers only**, not résumé text.

**Where résumé text is scored: recruiter search, via Apache Solr.** "Number of stars = (criteria
matched / total criteria) * 5". And a concrete, primary-sourced formatting failure — one of very few
that exist:

> "**The system uses OCR to make all uploaded resumes searchable, including PDF documents.** The
> system can't search some resumes… For example, the system doesn't search Microsoft Word documents
> based on templates that store data in **Content Control boxes**."

**Newer AI (2024–2026): Skills Compatibility.** "**derived using AI by comparing skills in the
applicant's resume with those mentioned in the job description**", displayed as a **matched/total
count, not a percentage and not a ranking**. Precedence: computed from skills the candidate
*validated*; the résumé is the fallback. Job-side skills are AI-extracted using a "universal
taxonomy", not the customer's own library.

No mention of LL144, AEDT, or bias audits across a 79,040-line admin guide (grep-verified).

### Summary table

| Platform | Auto-**reject** at submit? | Trigger | Auto-**scores/ranks** the résumé? | Score name / scale |
|---|---|---|---|---|
| **Greenhouse** | Yes | **Application-question answers only.** Explicitly not résumé content | Yes (Real Talent, opt-in, since Sep 2025) | Talent Matching: Strong / Good / Partial / Limited / Needs manual review |
| **Lever** | **Publicly undocumented** | — | Yes (Talent Fit, since Jun 2025) | LLM vs anonymised résumé + JD; tiers + % match |
| **Workday Recruiting** | **Yes — Automatic Stage Routing**, rules-based | Job application, job profile, requisition, **questionnaires** | Yes | Candidate Skills Match: Strong / Good / Fair / Low / Pending / Unable to Score; plus deterministic Rating templates |
| **Workday HiredScore** | No auto-reject documented; auto-**advance** only (Fast Lane) | — | Yes | Spotlight **A / B / C / D** (LLM-driven since Aug 2026) |
| **Ashby** | Yes | **Application-form questions only** | Yes | Meets / Does not meet / Undecided, plus a **sortable "AI job criteria met percentage"** |
| **iCIMS** | Screening-question disqualification workflows; hard submit-time knockout **not publicly documented** | Screening questions / DNQ | Yes | "Screening Question Score"; **Candidate Ranking** |
| **Oracle Taleo** | **Yes — explicitly** "automatically disqualified" | **Disqualification questions only** | **No — not on résumé text.** ACE score is from question responses | Result %, ACE flag, Requirements/Assets Met X/Y |
| **SAP SuccessFactors** | **Yes — explicitly** "Auto-Disqualified" | Disqualifier questions **and** falling below Required Score % | **No — not for screening.** | Solr **Match Score** (5 stars) in recruiter *search*; AI **Skills Compatibility** count |

<a id="a2"></a>
## A2. Formatting choices that measurably break parsing

**The root cause of nearly everything below.** A PDF has no text structure:

> "a PDF file does not contain anything that resembles paragraphs, sentences or even words… When it
> comes to text, a PDF file is only aware of the characters and their placement."
> — [pdfminer.six](https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html) — **primary**

Words, reading order and section boundaries are *reconstructed by heuristics* from glyph
coordinates. A PDF generator does not emit a document; it emits a scatter plot of glyphs that a
parser must re-derive meaning from. This is why the round-trip check in `verify.py` is the right
guarantee.

### The primary-source lists

Two vendors publish concrete lists. They are the backbone of this section.

**Greenhouse, "Unsuccessful resume parse"** — verbatim causes
([source](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse), **primary**):

- "A resume with **spaces between the letters**. While it may appear cohesive to the naked eye, the
  parser won't recognize the separate letters as a single word and can't make sense of the data."
- "Resumes that include **graphics, photos, or word art**"
- "Resumes that are uploaded as an **image**, rather than a document (such as a .docx or .pdf)"
- "**Complex resumes with tables, headers, and footers**"
- "Resumes with the name and contact information in the **header, footer, or text box**"
- "Resumes that have a **columned layout**"
- "Resumes **without clear sections** and differing formats throughout each section"
- "**Company names that don't include identifying words** such as Inc., Co., LTD, or LLC."
- "Resumes with **incomplete job titles**. For example, *Sr. Account Exec* instead of *Senior Account
  Executive*"
- Plus: "Greenhouse Recruiting can't parse resumes larger than **2.5MB**", and a "fake data" heuristic
  that skips placeholder-looking names and company names.

The last two content items are the least-known and most actionable: **spell out job titles**, and
**include the legal suffix on company names**.

**Textkernel Resume Quality codes** — a complete, severity-banded, machine-checkable rule list from a
parser vendor
([source](https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/parser-output/), **primary**).
The full table is reproduced in [Part D](#d-appendix); the load-bearing entries:

| Code | Band | Verbatim |
|---|---|---|
| **433** | Fatal | "We detected that this document contained data in columnar format. We rearranged this data to be machine readable with greater accuracy. **It is a HUGE MISTAKE for candidates to represent data in columns rather than in a simple top-to-bottom, all-across-the-page format.**" |
| **418** | Fatal | "Dates ranges were found written **vertically on multiple lines**" |
| **419** | Fatal | "The Employment section did not provide **dates** for jobs" |
| **412 / 413 / 414** | Fatal | No sections found / no WORK HISTORY section / no EDUCATION section |
| **415 / 416** | Fatal | Work-history or education information found but the section boundary "had to be **calculated**" |
| **441** | Fatal | "neither an email address nor a phone number were found… A resume should include always include both." |
| **408** | Fatal | "the document was too long and was **truncated** prior to parsing" |
| **300** | Major | "**Indicates that the document was PDF.**" |
| **302** | Major | "the first and last name for the candidate was not found" |
| **311** | Major | "a contact information section was found somewhere **other than the top** of the resume" |
| **323 / 324 / 325** | Major | Multiple sections of the same type / section with no text / **section with no header** |
| **151** | Suggested | "any sections were found with the **header not on a separate line above the content**" |
| **112** | Suggested | "a **separate skills section** was found. **Skills should be included in the context of work history and education descriptions.**" |

Note code **300**: this parser flags *being a PDF at all* as a Major Issue, with no rationale given.

### Multi-column layouts — the best-evidenced failure

What happens mechanically: naive extractors emit glyphs in content-stream order or a crude
top-to-bottom sweep, interleaving columns line by line.

> "a screen reader may read the document from top to bottom, **across both columns, interpreting them
> as one column**" — [W3C WCAG 2.1 Technique PDF3](https://www.w3.org/WAI/WCAG21/Techniques/pdf/PDF3) — **primary** (same mechanism)

> "If a system were to use the basic left-to-right, top-down order rendering… that would generate a
> rendering where **the information from different sections of the CV is mixed together**… when
> automated systems try to extract structured information from an imperfect rendering, problems
> compound very quickly"
> — [Textkernel engineering blog](https://www.textkernel.com/learn-support/blog/improving-extraction-from-column-resumes/) — **primary**

Prevalence, measured twice independently: "at least **15%** of CV documents use a column layout"
(Textkernel, n > 12,000 random CVs); "approximately **20%** of resumes use non-linear, multi-column
layouts" ([Alibaba SmartResume, arXiv:2510.09722](https://arxiv.org/abs/2510.09722), **primary**).

⚠️ **But modern parsers do recover columns.** Textkernel's own fix improved column-separator
detection 60%→82% and "well rendered CVs increased from **62% to 90%**". Affinda advertises
"Two-column CVs, scans, photos, DOCX, PDF" as supported. So: **"ATS auto-rejects two-column résumés"
is folklore**; "columns are a Fatal-band quality flag and break older extractors" is primary-sourced.
Single column costs nothing and eliminates the whole failure class.

⚠️ Enhancv's widely-cited "73% of hired candidates used two columns" is **interested and
self-refuting** — the author concedes it is "a sample of people who got hired, not a controlled
experiment", and Enhancv sells two-column templates.

### Tables

> "tables are just **absolutely positioned text**. In the worst case, every single letter could be
> absolutely positioned. That makes it hard to tell where columns / rows are."
> — [pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) — **primary**

There is no "table" object in a PDF text layer; a table is a visual illusion produced by coordinates.
In DOCX, table content *is* present in `<w:tbl>` and traverses row-major — so a two-column
`Employer | Dates` row linearises fine, but a two-column *page layout* table interleaves the whole
document. Separately, `python-docx`'s `document.paragraphs` does not include table-cell paragraphs,
so naive extractors silently drop table content entirely.

Vendor and institutional consensus is unanimous against tables: Greenhouse (above), Daxtra ("Avoid
the use of headers and tables, as this can diminish the parsing accuracy rates",
[KB](https://portal.wearemercury.com/knowledgebase/article/KA-01555/en-us), **vendor**), and all
seven university career centres checked.

**The verified alternative:** Yale's and Penn's own shipped résumé templates were unzipped and
inspected — `<w:tbl>` count **zero**, with dates right-aligned via **tab stops**. CMU documents the
mechanism: "MS Word: Use Right Tab Stops… Press Tab once before your date to align it to the right."
**For a HTML/CSS renderer: the `Employer ……… Dates` row is a flex row, never a table.**

### Headers, footers, text boxes

DOCX headers/footers are **separate XML parts** (`word/header1.xml`), referenced only by relationship
ID — a naive extractor walking `document.xml` never sees them. Text boxes live in `<w:txbxContent>`
inside `<mc:AlternateContent>`, outside normal paragraph flow, and `python-docx` cannot reach them at
all.

Vendors that say so: Greenhouse ("name and contact information in the header, footer, or text box"),
HireAbility ("State your name and contact information on top of the resume and **not in a Word
header, footer or a text box**"), Daxtra ("slanted text, **text boxes or shapes** — these may be
misread or completely missed"), MIT, Berkeley, CMU, Columbia, Georgia Tech.

PDF headers/footers are just glyphs at a y-coordinate; they are not "dropped" so much as **repeated
on every page and injected mid-stream**, polluting the linearised text at page boundaries. *(No
vendor documents this specifically — inference from the pdfminer mechanism, labelled as such.)*
Moot for a one-page résumé, which is another quiet argument for the one-page budget.

### Graphics, logos, photos, icons

Greenhouse: graphics, photos, word art → parse failure, and high-quality images push the file past
the 2.5 MB parse limit. Workday: "use resumes that **don't have images or image-based styles**".
MIT is the only source naming icons: "Avoid use of graphics, **icons**, or images"
([MIT CAPD](https://capd.mit.edu/resources/make-your-resume-ats-friendly/), **secondary**).

**On envelope/phone icons beside contact details specifically — no vendor documents this.**
Mechanically, an icon is either (a) a vector drawing contributing **zero characters** — harmless but
useless — or (b) an **icon font** mapping to Private Use Area codepoints, which extracts as garbage
adjacent to your email. *(Inference from the ToUnicode mechanism below, labelled as such.)* Safe
rule: icons are decoration only, never the sole carrier of information, and never an icon font.

⚠️ Counter-nuance: Textkernel has an `OutputCandidateImage` option that *extracts* candidate photos.
Photos are not universally discarded — just useless for matching and a file-size risk.

### Bullet glyphs

**A critical asymmetry.** In DOCX, list bullets are **not text at all** — they are generated from
numbering definitions, so glyph choice is a non-issue but bullets may vanish on extraction. In PDF,
**the bullet is a real drawn glyph** that must round-trip through a ToUnicode CMap; Wingdings/Symbol
bullets map to PUA codepoints with no Unicode meaning.

The evidence that this matters is that the career centres violate their own advice. A codepoint
census of published guides:

| File | Bullet glyphs actually used |
|---|---|
| MIT Career Toolkit (2025/01) | `U+2022` ×87, **`U+F0D7` (Private Use Area)** ×22, `U+25CF` ×16 |
| MIT composite samples (2025/05) | `U+2022` ×223, **`U+2012 FIGURE DASH` as a bullet** ×20, **`U+261E ☞`** ×8 |
| Stanford résumé handout | **`U+00A7 §` ×65** vs 5 real `U+2022` |

MIT tells students to "use regular bullet points" while shipping PUA bullets. **Emit `U+2022` only.**

### Ligatures, letter-spacing, ToUnicode CMaps

**The highest-value technical section for a PDF generator.**

When a font maps `f`+`i` to a ligature glyph *and* maps `U+FB01` to the same glyph, subsetting
naturally emits the **presentation-form** mapping, and extraction yields `U+FB01` instead of `fi`:

> "If the font maps a sequence like <letter f, letter i> to a ligature glyph 'ﬁ', but also maps the
> single codepoint U+FB01 to that same glyph, it's not surprising that when generating a subset font…
> the natural mapping for cairo to provide is the one from the original font's 'cmap'; i.e. U+FB01."
> "all we have is a GlyphBuffer that contains glyph IDs and positions, but **no record of the actual
> text**"
> — [Mozilla Bug 1810914](https://bugzilla.mozilla.org/show_bug.cgi?id=1810914) — **primary**

Chromium has the same class of bug:
[issues.chromium.org/41432982](https://issues.chromium.org/issues/41432982), "When printing to PDF,
text with ligatures are not preserved in the PDF" — **primary**. The documented workaround is to
disable ligatures when printing. Consequence for this project: `efficient` extracts as
`e<U+FB03>cient`, and a skills matcher looking for `Certified` or `Workflow` misses.

Fixes, in priority order: **(1) disable discretionary ligatures** (`font-variant-ligatures: none`) —
highest value, zero cost; (2) emit correct ToUnicode CMaps mapping ligature glyphs to *character
sequences*; (3) use `/ActualText` to override extraction for a span.

**Letter-spacing is the other silent killer.** pdfminer inserts a space wherever the inter-glyph gap
exceeds its `word_margin` threshold — so a tracked-out heading becomes `S K I L L S` in the text
layer. This is Greenhouse's **first listed** formatting failure. **Never apply `letter-spacing`, and
especially not to section headings or the name.**

Missing or corrupt ToUnicode maps produce the same class of damage for accented characters, and
subset fonts only contain the glyphs used — so a late-added character can fall outside the subset.

**Fonts.** The converging list across MIT, Yale, Northwestern, Stanford, Daxtra: Arial, Calibri,
Cambria, Garamond, Georgia, Helvetica, Times New Roman. ⚠️ **Serif vs sans is not a parsing
question** — CMU says "preferably a Sans Serif font" while Berkeley/Yale/MIT/Stanford lead with Times
New Roman, and no source claims a parsing basis. Any embedded font with a correct ToUnicode CMap
extracts identically. Body size: **10–12pt, 10pt the universal floor**. Margins: **0.75" satisfies
every source simultaneously**.

### PDF vs DOCX — genuinely contested

| Position | Source | Quote |
|---|---|---|
| **PDF preferred** | Greenhouse | "Upload a **PDF** for best results." [[MyGreenhouse FAQ]](https://support.greenhouse.io/hc/en-us/articles/43418495049499-MyGreenhouse-FAQ-for-Candidates) — **vendor** |
| **Avoid PDF** | Textkernel/Sovren | "**If you want to minimize conversion problems, don't use PDF documents.** Many PDFs convert/parse fine; however, the reason for most of our 'this document did not parse correctly' bug reports is that the document is a corrupt PDF file." Also "PDF is a broken standard that often hides issues with the underlying text." [[getting started]](https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/getting-started/) — **primary** |
| **Word preferred** | iCIMS | "Submit text-based documents, not PDFs"; "MS Word is usually the best option… Images and PDFs are scannable, but they are generally more difficult for the system to read." [[blog]](https://www.icims.com/en-gb/blog/how-applicant-tracking-systems-work/) — **vendor** |
| **Either** | MIT CAPD | "it is usually fairly safe to use either a .doc/.docx or .pdf file type" — **secondary** |

⚠️ iCIMS contradicts *itself* in the same article, elsewhere saying "Today, most ATS vendors have
fixed these tricks and read PDFs and other file types accurately."

**Verdict: "always use .docx" is outdated folklore, and "PDF is always fine" is also unsupported.**
Do not state either side as settled. The one uncontested rule is that a PDF must **earn** it: real
text layer, correct reading order, correct ToUnicode, no text as outlines.
⚠️ Columbia still publishes the hard version ("Use/submit MS Word documents (not PDFs) since **all**
ATS systems can scan/read them") on a page that also recommends a product defunct since ~2016 —
treat as **stale**.

### Hyperlinks

**DOCX:** display text is in `<w:t>`; the URL lives in `document.xml.rels` keyed by `r:id`. Any
extractor walking `w:t` gets **"LinkedIn"** and loses the URL entirely.
[[python-docx]](https://python-docx.readthedocs.io/en/latest/dev/analysis/features/text/hyperlink.html) — **primary**

**PDF:** a link is an **annotation** (`/Annots` → `/Link` → `/A` → `/URI`), not content-stream text.
pypdf lists "Hyperlinks and Metadata" among *unclear objectives* for text extraction — `extract_text()`
does not emit URIs.

**So the anchor-text-only claim is mechanically correct**, even though the sources that assert it are
mostly SEO blogs. **Print the URL as visible text** (`linkedin.com/in/name`), optionally *also*
hyperlinked. Never hide a URL behind a word or an icon. This is a live risk for this project: the
round-trip check will pass on the anchor text while the URL is silently absent from the text layer.

### Special characters

This is the weakest-evidenced area. The only vendor statement is uninformative — Greenhouse's
"includes characters that aren't recognized by our text parsing technology". **Counter-evidence that
accents are fine:** Greenhouse offers full parsing in 25+ languages including Arabic, Chinese, Greek,
Hebrew, Japanese, Korean, Russian and Ukrainian; Textkernel parses 29. **Accented Latin characters
are unambiguously supported.** The real risk is not the character but the **ToUnicode round-trip** —
`é` breaks for exactly the same reason `fi` does.

⚠️ **"Avoid ampersands and slashes in job titles"** appears only in SEO blogs. **folklore.** No vendor
doc supports it. *(A defensible adjacent point, from a documented fact rather than a rule: Textkernel
skills are "usually 1-3 words", so `Node.js / Express / React` risks being n-grammed as
`Express / React`. Commas are unambiguous in every tokenizer. Inference, labelled.)*

### Image-only PDFs and OCR

Textkernel: `ovIsImage` — "The document is just an image file. You will need to **enable OCR**" —
which is a paid add-on, "limited to **10 pages** and will stop processing after **120 seconds**".
Greenhouse: images → failure. SmartRecruiters returns HTTP 400 `UNPARSABLE_RESUME` "when provided
resume cannot be parsed, e.g. an image"
([docs](https://developers.smartrecruiters.com/reference/candidatesresumeparse), **primary**).
Affinda exposes `isOcrd`/`ocrConfidence`, "only applicable for images or PDF documents **without a
text layer**".

**Critical:** a PDF *with* a text layer is read from the text layer; **embedded images are not OCR'd
on that path**. A skills graphic rendered as PNG inside an otherwise-text PDF is simply invisible.
Never rasterise text; never convert text to outlines.

**Size limits:** Greenhouse parses ≤ **2.5 MB**; Daxtra ≤ 8 MB; Ashby processes ≤ 16 MB for
search/autofill; Workday commonly 5 MB. **2.5 MB is the binding constraint.**

### The vendor-recommended self-test

> Open the PDF in Adobe Acrobat Reader, use **File > Save as Text**, then view the result in a text
> editor.
> — [Sovren/Bullhorn KB](https://kb.bullhorn.com/invenias/Content/Invenias/Topics/parsingTechnicalSpecificationsAndSovrenFAQ.htm) — **primary**

MIT independently recommends the same: save as `.txt` and check for "Missing text" or "**Text in the
wrong order**". **This is exactly what `verify.py` already automates** — the project's central
guarantee is the one both a parser vendor and a university career centre recommend by hand.

<a id="a3"></a>
## A3. Canonical section headings and the safest date format

### The parser-internal vocabulary

Textkernel/Sovren's `sectionType` enum — the normalised targets every heading is matched *to*
([source](https://developer.textkernel.com/tx-platform/v9/resume-parser/overview/parser-output/), **primary**):

```
ARTICLES, AVAILABILITY, BOOKS, CERTIFICATIONS, CONFERENCE_PAPERS, CONTACT_INFO,
EDUCATION, HOBBIES, IGNORE_DATA_AFTER, LANGUAGES, LICENSES, MILITARY, OBJECTIVE,
OTHER_PUBLICATIONS, PATENTS, PERSONAL_INTERESTS_AND_ACCOMPLISHMENTS,
PROFESSIONAL_AFFILIATIONS, QUALIFICATIONS_SUMMARY, REFERENCES, SECURITY_CLEARANCES,
SKILLS, SPEAKING, SUMMARY, TRAINING, WORK_HISTORY, WORK_STATUS
```

Each section records **the literal header text found**, or the value `"CALCULATED"` — "If there was
no text indicator and the location was calculated, then the value is 'CALCULATED'." **The parser
degrades to guessing boundaries when it cannot recognise your heading**, and separately flags that it
had to (Fatal codes 415/416). The worked examples in the same doc map `"Experience"` → `WORK HISTORY`,
`"Education"` → `EDUCATION`, `"Executive Summary"` → `SUMMARY`.

Affinda's parallel enum: `Achievements, AdditionalInformation, Education, Extracurriculars,
Organisations, Other, PersonalDetails, Projects, Publications, Referees, Skills, Summary, Training,
WorkExperience, Header, Footer` — **primary**.

### How heading detection actually works

A concrete open-source implementation (OpenResume, pdf.js-based —
[demo](https://www.open-resume.com/resume-parser), **primary**, source code):

- **Primary rule:** the line is **bold AND all-uppercase with at least one letter**.
- **Fallback:** ALL of — at most **2 words**; **only letters, spaces and ampersands**
  (`/^[A-Za-z\s&]+$/`); starts with a capital; contains a keyword.
- **Keywords:** primary `experience, education, project, skill`; secondary `job, course,
  extracurricular, objective, summary, award, honor`.

Testing the creative headings:

| Heading | Result |
|---|---|
| `WORK EXPERIENCE` (bold, caps) | **Passes** on the primary rule alone |
| `EXPERIENCE`, `EDUCATION`, `SKILLS`, `PROJECTS` (bold, caps) | **Pass** |
| `Professional Experience` | Passes the fallback (2 words, letters only, keyword) |
| `Relevant Coursework` | Passes (`course`) |
| `Selected Leadership & Research Impact` | **Fails** the fallback (>2 words) — survives only if bold + all-caps |
| `My Journey` | **Fails** — 2 words, letters only, but **no keyword** |
| `Where I've Made an Impact` | **Total failure** — 5 words, apostrophe, no keyword |

### The safe list — exact strings

Emit a standard heading token as the machine-legible anchor: **bold, ALL-CAPS, on its own line,
directly above its content, ≤ 2 words.** Let specificity live in *entry titles*, never in the
heading.

**Recommended, in preference order:**

```
EXPERIENCE            (or WORK EXPERIENCE / PROFESSIONAL EXPERIENCE)
EDUCATION
SKILLS                (or TECHNICAL SKILLS)
PROJECTS
CERTIFICATIONS
SUMMARY               (or PROFESSIONAL SUMMARY)
PUBLICATIONS
AWARDS                (or HONORS)
LANGUAGES
```

`resume-fill`'s existing `SECTION_TITLES` — Summary, Skills, Experience, Projects, Education,
Certifications — is already exactly on this list. The only change worth making is casing/weight
(bold + all-caps maximises the primary detection rule) and asserting **one section per type**
(Textkernel 323) and **heading on its own line** (151).

⚠️ **A genuine institutional disagreement.** Stanford's guide labels `Professional Experience`,
`Work Experience`, `Relevant Experience` as "**General Non-descriptive Headings**" (deprecated) and
prefers `Advising and Mentoring Experience`, `Community Leadership and Service`, etc.
[[PDF]](https://careered.stanford.edu/sites/g/files/sbiybj22801/files/media/file/developing_your_resume_handout.pdf) — **secondary**.
That guide is undated, has zero ATS content, uses numeric dates and `§` bullets — treat as
pre-ATS-era. Columbia, Berkeley and CMU all say the opposite ("Use **common names** for your section
headers").

### Date format

**`Present` with a capital P is the safest ongoing token, and here is the proof.** OpenResume's
source, verbatim:

```js
const hasPresent = (item: TextItem) => item.text.includes("Present");
```

**Case-sensitive literal match.** `Current`, `Now`, `Today` and lowercase `present` all fail.
⚠️ Textkernel recognises more — its `DocumentLastModified` field exists "so that the Parser knows how
to interpret dates in the document that are expressed as '**current**' or '**as of**' or similar" —
but `Present` is the only token both simple and sophisticated parsers recognise.

**Spell months out.** iCIMS states it directly: "spell out abbreviations for things like months and
years. For example, write '**August 2020**' instead of '**Aug. '20**.'" — **vendor**. And here is why,
from OpenResume's month matcher:

```js
MONTHS.some(month => item.text.includes(month) || item.text.includes(month.slice(0, 4)))
```

`month.slice(0,4)` yields `Janu, Febr, Marc, Apri, May, June, July, Augu, Sept, Octo, Nove, Dece`.
**The common three-letter abbreviations `Jan`, `Feb`, `Mar`, `Apr`, `Aug`, `Oct`, `Nov`, `Dec` do not
match.** Only `May`, `June`, `July`, `Sept` survive abbreviation.

**Commas inside dates are penalised** — OpenResume's `DATE_FEATURE_SETS` contains `[hasComma, -1]`.
So `January 5, 2020` and `Expected: May, 20XX` score worse.

**The best-reasoned institutional rule**, from CMU's 2026 guide (**secondary**):

> "Dates should be written as **Month Year** (May 2025; **Sept. 2023 – May 2024**). Abbreviating
> months is acceptable **when done consistently**. Listing dates as a season (e.g., Fall, Spring,
> Summer) is **not recommended**. **Avoid dates written with numerals only (1/2/2024).** Right
> Alignment of dates is encouraged."

Byte-verified from that PDF: `Sept. 2023 \xe2\x80\x93 May 2024` — **U+2013 EN DASH with a space on
each side**. Penn's templates independently converge on the same.

**Exact recommended strings:**

```
January 2023 – Present
January 2023 – March 2025
2023 – 2025                 (acceptable when only years are known)
```

- Separator: **` – `** — space, `U+2013`, space.
- Ongoing: **`Present`**, capital P, no other token.
- Never numeric-only (`01/2023`), never seasons (`Fall 2023`), never stacked across two lines
  (Textkernel **418**, Fatal), never a comma inside the string.
- Right-align via a flex row or tab stop, **never a table cell**.

⚠️ **En-dash vs hyphen: no vendor or ATS documentation addresses this at all.** SEO sources
contradict each other outright — one insists on *no* spaces around the en-dash, another insists on
spaces. **folklore, ignore.** The en-dash recommendation above rests on CMU/Penn convention, not on
any parsing evidence. OpenResume's date scorer does not look at the separator at all.

⚠️ **The career centres cannot agree and contradict themselves within single documents:** Harvard's
2025 samples show `May 2025–Aug 2025`, `Aug 20XX-present`, `June-July 20XX` and `Expected: May, 20XX`
in one guide; MIT prescribes "Present" then ships `2011-current` and lowercase `present` in its own
2025 samples; CMU's 2024 SCS samples use `August 20XX-May 20XX`, contradicting CMU's own 2026 rule;
Stanford uses `0/0000`, exactly what CMU forbids. **The absence of a real standard is itself the
finding** — which is why the rule should be "pick one grammar and be internally consistent", enforced
mechanically.

⚠️ Textkernel code **233** — "Do not put dates in your education section. Such dates are not relevant
and may be harmful" — is **career advice leaking into a technical API**, not a parsing capability.
Ignore it as a parsing claim.

<a id="a4"></a>
## A4. Contact block extraction

### How parsers find each field

Concrete heuristics from a real parser (OpenResume, **primary**):

| Field | Rule | What breaks it |
|---|---|---|
| Name | `/^[a-zA-Z\s\.]+$/`; **bold = +2**; **−4 each** for `@`, digits, comma, slash | Hyphens and apostrophes in names (`O'Brien`, `Smith-Jones`) fail the regex outright; a name on the same line as the email takes −4 |
| Email | `\S+@\S+\.\S+` | Robust |
| Phone | `\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}` | **US-only.** `+44 20 7946 0958` fails |
| Location | `[A-Z][a-zA-Z\s]+, [A-Z]{2}` | **US `City, ST` only.** `London, United Kingdom` fails |
| URL | `\S+\.[a-z]+/\S+` | Bare `linkedin.com/in/x` works; a hyperlinked word "LinkedIn" does not |

Sophisticated parsers do better on internationals — Textkernel outputs `InternationalCountryCode`,
`AreaCityCode`, `SubscriberNumber` and ISO 3166 country codes — but the naive tier is real and
US-centric.

### What breaks it, per vendor documentation

- **Greenhouse:** name/contact in "the header, footer, or text box"; graphics, photos, word art.
- **Textkernel 441** (Fatal): "neither an email address nor a phone number were found."
- **Textkernel 302** (Major): "the first and last name for the candidate was not found."
- **Textkernel 311** (Major): "a contact information section was found somewhere **other than the top**
  of the resume. Contact information should only be found at the top." → **a sidebar fails this.**
- **Textkernel 131/132/133**: multiple addresses / **multiple email addresses** / multiple phone
  numbers. "**Only one contact email address should be included in a resume.**"
- **Daxtra:** name is mandatory — "avoid shortening the Candidate's Name or anonymising the CV — this
  will cause the parser to fail"; at least one phone or email is mandatory.
- **Columbia**, an unusually specific and mechanically credible claim: "Do not put distinctions (e.g.,
  **PhD or CPA**) into your header, as ATS systems will pull that into your first name/last name box."
  — **secondary**, but consistent with OpenResume's letters-only name regex.

### Recommended shape

Contact block **first, in the document body**, plain text:

```
Firstname Lastname                                  ← own line, bold
email@example.com · +1 555 123 4567 · City, ST · linkedin.com/in/name · github.com/name
```

One email, one phone. City + state/country, **no street address** (Textkernel 213 wants one, but
121–124 and every career centre say omit it; the consensus lands on city/state). No credentials in
the name line. All URLs as visible text.

<a id="a5"></a>
## A5. Skills extraction and taxonomies

### The three public taxonomies, with corrected licensing

| Taxonomy | URL | Open? | Licence |
|---|---|---|---|
| **ESCO** (EU) | https://esco.ec.europa.eu/en/classification/skill_main | Free download, all formats, 28 languages | CC BY 4.0 by EC default policy — ⚠️ `/legal-notice` and `/use-esco/licensing` both **404**; inferred from [Commission Decision 2011/833/EU policy](https://commission.europa.eu/legal-notice_en). **Verify before shipping.** |
| **O*NET** (US DOL) | https://www.onetcenter.org/database.html | Free, no registration | ⚠️ **CC BY 4.0 — NOT public domain.** Attribution required |
| **Lightcast Open Skills** | https://lightcast.io/open-skills | Free to *browse*; **API is contract-based** | ⚠️ **No open licence** |

**ESCO:** 3,039 occupations and **13,939 skills**, v1.2.1 (10 Dec 2025), RDF/TTL/ODS/CSV/XML/JSON-LD.

**O*NET — two corrections to common belief.** (1) Not public domain: you must "credit the O*NET
Database and the U.S. Department of Labor… link to the license, and indicate where any changes were
made." (2) ⚠️ **O*NET "Skills" is not a skill vocabulary** — it is ~35 abstract descriptors rated per
occupation (Reading Comprehension, Active Listening, Writing…). **You will never match "React" or
"Kubernetes" against O*NET Skills.** The useful file is **Technology Skills** —
[32,681 rows](https://www.onetcenter.org/dictionary/30.0/excel/technology_skills.html) of named
products with UNSPSC codes and Hot Technology / In Demand flags.

⚠️ **"Lightcast Open Skills is open source" is outdated.** "Your use of the taxonomy is determined by
the **type of license you request**" / "**API access is now available on a contract basis**"
([FAQ](https://lightcast.io/open-skills/faqs), **primary**). This error is repeated even in Affinda's
own docs and SkillNER's README. ~33–34k skills, 3-tier hierarchy, refreshed every four weeks.

**Textkernel's proprietary taxonomy:** "more than **13,000 unique skills**, encompassing over
**250,000 skill synonyms** spanning 20+ languages", three layers (categories → language-independent
skill IDs → language-specific synonyms), skills "usually 1-3 words", synonyms updated fortnightly.
⚠️ **No documented ESCO mapping for skills** — *professions* map to
[O*NET and ISCO 2008](https://developer.textkernel.com/Parser/master/data_model/codes-reference/),
language skills to ISO 639-1. That is all the external alignment documented.

**SkillNER** (https://github.com/AnasAito/SkillNER) is MIT-licensed spaCy tooling, but its bundled
EMSI `SKILL_DB` is exactly what Lightcast's current FAQ contradicts. An ESCO-native alternative with
cleaner licensing: https://github.com/KonstantinosPetrakis/esco-skill-extractor.

⚠️ **Workday Skills Cloud, Eightfold, SeekOut and LinkedIn Skills Graph are all proprietary,
non-licensable, and their published skill counts are marketing.** ⚠️ "RChilli has 3 million skills"
is unverified and not found on any RChilli-controlled page.

### Skills are extracted from the whole document

Textkernel's config exposes **opt-out** toggles, all default-enabled (**primary**):

```
Coverage.FindSkillsInAchievements      Coverage.FindSkillsInCertifications
Coverage.FindSkillsInCoverLetter       Coverage.FindSkillsInEducationHistory
Coverage.FindSkillsInExecutiveSummary  Coverage.FindSkillsInLanguages
Coverage.FindSkillsInLicenses
```

`SKILLS` is 1 of 26 values in the `FoundIn.SectionType` enum. Affinda's spec records per-skill
`sources[].section`, `position` and `workExperienceId`. RChilli has an `Evidence` field: "the section
in the resume from where the skill is picked up."

**So: yes, parsers extract skills from experience bullets, summaries, education and certifications —
not only from a Skills section.** Note also `FindSkillsInCoverLetter` — at least one major parser
mines the cover letter for skills, which is a small point in favour of naming technologies there too.

### Does a dedicated Skills block help or hurt? — the counterintuitive primary finding

> **Code 112:** "Indicates if a **separate skills section** was found. **Skills should be included in
> the context of work history and education descriptions.**"
> — Textkernel Resume Quality, *Suggested Improvements* band — **primary**

**Why**, mechanically: every major parser attaches metadata to each extracted skill.

| Vendor | Fields |
|---|---|
| Textkernel CV Parser | `Skill`, `SkillCode`, `Level`, **`Years`**, **`LastUsed`** ("inferred from the work history"), **`FoundIn`** (list of work-history item IDs) |
| Tx Platform / Sovren | `@totalMonths`, `@lastUsed`, `@whereFound` (e.g. `"Found in WORK HISTORY; POS-1"`), `@existsInText` |
| RChilli | `Evidence`, `LastUsed`, `Experience in Months` |
| Affinda | `lastUsed`, `numberOfMonths`, `count`, `weighting` |

**A skill appearing only in a bare Skills list gets `MonthsExperience` = null and `LastUsed` = null.**
A recruiter filtering "Python, 3+ years, used in the last 2 years" — a standard query in Tx Platform,
Bullhorn and Daxtra — **will not match that candidate**, even though the word is on the page.

**Recommendation: do both.** Keep the Skills block (humans skim it; naive matchers hit it) *and* seed
the same canonical strings into dated experience bullets. Emitting a Skills section raises flag 112,
which is the **mildest** severity band — a worthwhile trade.

For `resume-fill` specifically: `profile.skills` is documented as the one place a tool may be claimed
without a bullet backing it. That licence is correct for *grounding*, but a skill that never reaches
a bullet is invisible to experience-based filtering. Treat "declared in `skills:` but never surfaced
in a bullet" as a reportable gap in `report.md`.

### Skills matrices, star bars, proficiency dots

⚠️ **No parser vendor documents behaviour on graphical rating widgets. Any confident claim is
folklore.** What *is* defensible from documented API contracts *(inference, labelled)*:

1. Extractors consume **text** — Textkernel's Extract Skills API takes a `Text` string (24,000-char
   limit); Lightcast returns byte offsets into that text. A filled circle contributes **zero
   characters**; only the adjacent label carries signal.
2. An image-rendered skills graphic inside a text-layer PDF is **never OCR'd** — completely lost.
3. Textual proficiency *is* modelled — Textkernel has a `Level` field — but accepted values are
   undocumented, so do not over-engineer.

**Never draw a rating. Write `Python (advanced, 6 yrs)`** — human-readable and inside the text layer.

### Separator style, and normalisation

⚠️ **Zero evidence, primary or secondary, on comma vs bullet vs one-per-line.** Every source ranking
these is a résumé-builder blog. **folklore.**

**Normalisation:** the mechanism is documented (250,000 synonyms → language-independent IDs, with
`RawText` + `BeginSpan`/`EndSpan` provenance; RChilli's worked example: "Microsoft Excel is the
formatted name of 'Excel'"), but **coverage is never published**. No document anywhere states that
`JS` resolves to JavaScript. Coverage is a per-vendor, fortnightly-moving target. **Write
`JavaScript (JS)`, `Amazon Web Services (AWS)`** — the parenthetical is free insurance and costs one
line.

### Academic evidence, with a framing caveat

⚠️ **Nearly all skill-extraction research evaluates on JOB POSTINGS, not résumés.** No public résumé
skill-extraction benchmark exists (privacy). Transfer is assumed, not measured.

- [SkillSpan, NAACL 2022](https://arxiv.org/abs/2204.12811) — the reference dataset; 14.5K sentences,
  12.5K annotated spans.
- [ESCOXLM-R, ACL 2023](https://arxiv.org/abs/2305.12092) — ESCO-pretrained, 27 languages, SOTA on
  6/9 datasets; **"performs better on short spans"**.
- [Rethinking Skill Extraction using LLMs, EACL 2024 workshop](https://arxiv.org/abs/2402.03832) —
  LLMs, "despite **not being on par** with traditional supervised models in terms of performance, can
  better handle syntactically complex skill mentions." **Do not assume an LLM-backed ATS rescues
  sloppy formatting.**
- [NNOSE, EACL 2024](https://arxiv.org/abs/2401.17092) — "up to **30% span-F1**" gaps on **infrequent**
  patterns. The long tail is fragile: niche technologies are the most likely to be missed, which is
  another argument for the redundant literal Skills block.
- [Layout-Aware Parsing Meets Efficient LLMs, arXiv:2510.09722](https://arxiv.org/abs/2510.09722) —
  ablation: removing the layout generator costs **−1.6% overall but −10.0% on long text**.

⚠️ **Do not cite arXiv:1910.03089** ("100% accuracy" résumé parsing with BERT) — that number reflects
template-uniform LinkedIn exports, not the method.

**Takeaway: explicit beats implicit, and short spans win.** The entire "implicit skill" research
programme exists because systems are bad at inferring "Kubernetes" from "orchestrated our container
fleet". **Write the literal skill name.**

<a id="a6"></a>
## A6. Keyword stuffing, white text, match-score tools, length, summaries

### Keyword stuffing — where the line actually falls

The clearest guidance is MIT's, and it draws the line on **truthfulness**, not density
([MIT CAPD, ATS-friendly resumes](https://capd.mit.edu/resources/make-your-resume-ats-friendly/), **secondary**):

> "Meaningfully use the keywords from the job postings; if you have done something that the job
> description mentions, think about how you might 'copy + paste + **personalize**' that information
> into your resume."
> "**Avoid spamming the ATS with keywords. You will still need to be able to account for everything
> indicated on your resume. Falsifying employment documents, including application materials, is
> both a legal and ethical breach and may result in dismissal from the search.**"
> "Avoid abbreviating relevant keywords as an ATS may not properly consider it."
> "Minimize the use of vague or ill-defined language such as '**various**,' '**multiple**,'
> '**several**,' or '**etc.**' as they might be masking some beneficial keywords you can use."

That last rule is genuinely useful and mechanically checkable: **vagueness is where keywords go to
die.** "various programming languages" should be "Python, Go, Rust".

Three consistent tests emerge across MIT, Columbia, Harvard and Ladders:
1. **Accountability** — can you defend every keyword in an interview? (This is exactly what
   `ground.py` enforces mechanically.)
2. **Context** — the keyword must sit inside a real accomplishment statement, not a keyword block.
3. **Voice** — the language must survive being rewritten in your own words.

**Ranking by keyword relevance is real; ranking by keyword *density* is not.** iCIMS: "Candidates who
include more relevant keywords… will pass through screening and be **ranked higher** than those who
include fewer keywords" — **vendor**. ⚠️ **No vendor anywhere documents a keyword-density metric.**
"Keyword density" is imported wholesale from SEO. **folklore.**

### White-text keyword injection — real, measured, and detected

**The load-bearing technical fact: text extraction ignores colour, so hidden text is extracted as
normal text.** An ATS vendor confirms the practice exists:

> "Some even went so far as to copy and paste job descriptions into their resumes and **turn the font
> white so it would register with the ATS but be invisible to human readers**."
> — [iCIMS](https://www.icims.com/en-gb/blog/how-applicant-tracking-systems-work/) — **vendor**

iCIMS then hedges — "Today, most ATS vendors have fixed these tricks" — **unelaborated and
ambiguous.**

**Prevalence, measured at scale:** ~**1% of résumés** contain hidden prompt injections, from ~200,000
real résumés at hireEZ ([USENIX Security 2026, arXiv:2605.28999](https://arxiv.org/abs/2605.28999),
Duke/ASU/Berkeley/UNC — **primary**). Time series: 0.6–0.8% (2019–2023) → peak ~1.5% (2024–25) →
~1.0% late 2025.

⚠️ **The most under-reported finding: more than 90% is NOT prompt injection.** "**more than 90% of
injected prompts do not use explicit instructions**" — it is **data injection**: fabricated skills,
fictitious work history, copied job-requirement text hidden in white or 1pt text. The authors'
conclusion: "detection systems that focus primarily on identifying explicit instruction patterns are
likely to be ineffective in practice."

Four documented concealment techniques, verbatim: colour-matching; "extremely small font sizes (e.g.,
1pt or smaller)"; positioning "outside the visible page boundaries"; and "**PDF layer structures to
include content that parsers extract but renderers do not display**."

**Detection is real but narrow.** hireEZ runs two production detectors from that work — **HCD**
(rules on font size / colour distance / ink density plus LLM verification; 86.1% precision, 1.35s)
and **VDA** (a vision-language model comparing **rendered page images against extracted text**; 92.7%
precision, 24.8s). PhantomLint is a research prototype
([arXiv:2508.17884](https://arxiv.org/abs/2508.17884)).

⚠️ **But the widely repeated claim that "ATS detect when font colour matches the background and flag
it" appears only in SEO blogs. No mainstream ATS documents an anti-hidden-text feature.** Greenhouse's
AI security page mentions prompt injection only as a **penetration-testing category for its own LLM
plumbing**, not as a candidate-fraud detector. **folklore — do not repeat.** Likewise "blacklisting":
exactly one documented anonymous rejection exists.

**It does work on LLM screeners — measurably.** [arXiv:2512.20164](https://arxiv.org/abs/2512.20164)
tested 12 model variants: Instruction Injection 8.1–92.3% attack success; **Invisible Experience
16.6–99.6%**; Job Manipulation 33.0–99.5%.
[arXiv:2606.27287](https://arxiv.org/abs/2606.27287) found even *visible* self-promotional text works
— up to 93.2% success with a 6.50 mean rank gain — **and the killer caveat: "Success rates drop
sharply, approaching zero once roughly 80% or more of résumés are injected."** A tragedy of the
commons with a short half-life.

The peer-review parallel is well documented: Nikkei found **17 preprints** from 14 institutions with
prompts hidden in "white text or extremely small font sizes"
([Nikkei Asia](https://asia.nikkei.com/business/technology/artificial-intelligence/positive-review-only-researchers-hide-ai-prompts-in-papers)),
and [arXiv:2508.20863](https://arxiv.org/abs/2508.20863) measured the effect: GPT-4o rating
**7.93 → 9.79**.

⚠️ **Greenhouse's survey claim that 41% of US job seekers "admit to using prompt injections" is 41×
higher than Greenhouse's own measured 1% across ~300M résumés.** Both numbers are Greenhouse's. The
measured figure is defensible; the survey figure is almost certainly a question-wording artefact, and
an ATS vendor selling fraud detection has an obvious interest in an inflated threat.

Recruiters on record: "Just because you tricked an AI to say I should interview you doesn't mean I
have to" (Mike Peditto, [Built In](https://builtin.com/articles/hidden-ai-prompts-in-resume)); the
NRWA: "**Never use white text on your resume for anything!**"

**For this project: never. The grounding gate already makes it structurally impossible to inject a
claim, which is the strongest possible version of this rule.**

### The finding that matters more than white text

> "The bias against human-written resumes is particularly substantial, with self-preference bias
> ranging from **67% to 82%** across major commercial and open-source models." … "Candidates using
> the same LLM as the evaluator are **23% to 60% more likely to be shortlisted** than equally
> qualified applicants submitting human-written resumes."
> — [*AI Self-preferencing in Algorithmic Hiring*, arXiv:2509.00462](https://arxiv.org/abs/2509.00462) — **primary**

If an LLM screens the résumé, having an LLM *write* it is a far larger, better-evidenced and entirely
legitimate advantage than hiding keywords. That is a striking validation of this project's basic
premise — with the caveat that it is a preprint measuring embedding/LLM rankers, not a named ATS.

⚠️ **Open question, explicitly:** no controlled study isolates layout/formatting effects on LLM
screeners. The best validity study ([arXiv:2602.18550](https://arxiv.org/abs/2602.18550)) uses
programmatically generated synthetic résumés, not formatted documents.

### "ATS automatically reject 75% of résumés"

**Verdict: no primary source supports it, and the standard debunking is also unsourced. Report both.**

**What the Harvard study actually says.** *Hidden Workers: Untapped Talent*, Fuller, Raman et al.,
Harvard Business School Project on Managing the Future of Work / Accenture, September 2021
([HBS page](https://www.hbs.edu/managing-the-future-of-work/research/hidden-workers-untapped-talent),
[PDF](https://www.hbs.edu/ris/Publication%20Files/hiddenworkers09032021_Fuller_white_paper_33a2047f-41dd-47b1-9a8d-bd08cf3bfa94.pdf)) — **primary**.
It contains **no claim that ATS reject 75% of résumés**. The only 75% nearby is adoption:

> "approximately two-thirds of all employers surveyed (63%) reported that they use an RMS… **In the
> U.S., the usage was most prevalent, with 75% of employers using these technologies**, compared to
> just over half in Germany (54%) and the U.K. (58%)."

The real numbers, verbatim:

| Finding | Exact text |
|---|---|
| Filtering prevalence | "more than 90% of employers used their RMS to initially filter or rank potential **middle-skills (94%)** and **high-skills (92%)** candidates" |
| Employment-gap filter | "**48% of employers filtered middle-skills candidates based on employment gaps of more than six months**" |
| Perceived elimination | "**78%** of the business leaders we interviewed estimated that **half or more of middle-skills candidates were eliminated by filtering**, and **80%** said that more than half of candidates for high-skilled positions were similarly disqualified" |
| Employers' own assessment | "**88%**—of employers believed that qualified **high-skills** candidates were vetted out of the process because they did not match the exact criteria… That number rose to **94%** in the case of **middle-skills** workers" |
| Hidden workers | "There are **27 million hidden workers** in the U.S. workforce. **63% are 'missing hours,' 33% are 'missing from the workforce,' and 4% are 'missing from work.'**" |

The mechanism passage worth quoting in full:

> "there are other, more subtle negative criteria, such as 'continuity of employment' or presence of
> long chronological gaps in a resume. **Almost half the companies surveyed weeded out resumes that
> present such a 'work gap.' If an applicant's work history has a gap of more than six months, the
> resume is automatically screened out by their RMS or ATS, based on that consideration alone**… A
> recruiter will never see that candidate's application, even though it might fill all of the
> employer's requirements."

**Three corrections this brief should make:**
1. ⚠️ **The 88% figure is not about keywords.** It is employers' belief that candidates were vetted
   out for not matching *the exact criteria in the job description*. Widely misquoted as "88%
   screened out due to keyword mismatch."
2. ⚠️ **27 million is a labour-market population estimate**, not a count of ATS rejections.
3. ⚠️ **"99% of Fortune 500 companies use an ATS" is not Harvard's research.** HBS footnote 79 cites
   it to a **vendor**: [Jobscan, 7 Nov 2019](https://www.jobscan.co/blog/99-percent-fortune-500-ats/).
   Jobscan's own updated methodology (manual review, data gathered 2 Jun 2025) now reports **97.8%**
   (489/500).

**Where 75% likely came from:** two independent corroborations that it is an *adoption* figure — HBS's
75% of US employers, and "75% of recruiters use some type of recruiting or applicant tracking system"
attributed to Capterra via [CIO](https://www.cio.com/article/284414/applicant-tracking-system.html).

⚠️ **The Preptel origin story is itself unsourced.** Many debunking articles trace the number to
Preptel, a résumé-optimisation vendor that shut down in August 2013 — but no source produces a
Preptel document, quote, or URL. The 2012 WSJ article usually invoked is paywalled and could not be
verified. **State that the figure has no traceable primary source, rather than asserting the Preptel
story as fact.**

**Counter-evidence from the field.** Enhancv interviewed **25 US recruiters** (Sep–Oct 2025) across
Workday, iCIMS, Lever, Greenhouse, Bullhorn, Phenom and LinkedIn Recruiter: **92% (23/25) said their
systems do NOT auto-reject** on formatting, content or design; **8% (2/25) do**, with configured
thresholds; **100% use knockout questions**, which route to human review
([source](https://enhancv.com/blog/does-ats-reject-resumes/) — **interested**, n=25, but it names
respondents and states a method, which the 75% claim never did). This is consistent with all seven
platforms' documentation in [A1](#a1).

### Match-score tools (Jobscan, Resume Worded, et al.)

**Bottom line: zero independent evidence that any match score correlates with interviews, offers, or
any real outcome. No peer-reviewed validation. No third-party audit. No published correlation study
by the vendors themselves.**

Jobscan's own explanation pages for Match Rate now **404**, and no vendor page making — or supporting
— an outcome claim could be located. Critical coverage exists but is **almost entirely SEO
review-blog content, much of it from competing tools**; no ERE / HBR / SHRM investigation of
match-score validity exists. **That cuts both ways: the criticism is as unsourced as the claims.**

Three structural conflicts worth stating plainly:
1. The vendors sell subscriptions, courses or coaching; the score is the funnel.
2. **The score is not produced by any real ATS.** Each algorithm is proprietary and undisclosed, and
   there is no ground truth to validate against — the platform scores in [A1](#a1) are computed from
   an employer's private calibration that no third-party tool can see.
3. The scores create a **measurable proxy for an unmeasurable goal** — precisely the condition under
   which Goodhart's law bites.

`resume-fill`'s own score is subject to exactly the same critique, which is why printing it as a
labelled breakdown rather than a bare number, and pairing it with a gap list, is the right design.
The one thing that materially distinguishes it: the grounding gate means the loop **cannot raise the
number by inventing** — so a ceiling is information rather than an artefact.

### Résumé length — one page vs two

**The only study that manipulated length: ResumeGo, 10 Nov 2018**
([source](https://www.resumego.net/research/one-or-two-page-resumes/), **interested**; trade coverage
[ERE](https://www.ere.net/articles/one-or-two-page-resumes-best),
[CNBC](https://www.cnbc.com/2018/12/19/resumego-hiring-managers-prefer-candidates-with-two-page-resumes.html)).

Method: **n = 482** professionals with recruitment experience; 15 Oct – 2 Nov (**the page omits the
year**; ERE supplies 2018); a hiring simulation with paired résumés for similar candidates;
one-pagers **350–500 words**, two-pagers **700–850 words**; **7,712 total selections**, 5,375 of them
two-page. Findings: two-page chosen **2.3×** as often overall (entry 1.4×, mid 2.6×, managerial
2.9×); scores 8.6 vs 7.1; time spent 4m05s vs 2m24s.

**Why it should not carry much weight:**
1. **The manipulation is confounded.** Two-pagers had roughly **twice the words**. The study compares
   *more information* against *less*, not the same information at two densities. "Recruiters prefer
   résumés with more content" is near-tautological in a low-stakes rating task.
2. **Preference ≠ outcome.** Nobody was hired.
3. **No statistical reporting at all** — no p-values, no confidence intervals, no per-condition Ns.
4. No preregistration, no raw data, no replication, no peer review.
5. **Direct conflict of interest**, undisclosed: ResumeGo sells résumé writing, and longer résumés are
   a more billable deliverable.
6. The page does not state the study year.
7. Its own time-spent numbers (2–4 minutes) quietly contradict the 6-second folklore the same
   industry sells.

**What survives:** it is the only length experiment that exists, and its weak signal is that
recruiters do not *punish* two pages — a much narrower claim than "two pages are 2.3× better."

**What the universities say** (all **secondary**, none cite evidence):

| Institution | Guidance |
|---|---|
| MIT CAPD | "Stick to one page, unless you have extensive experience or an advanced degree" / two pages at 10+ years |
| Yale OCS | Undergrads one page; master's 1–2; PhDs/postdocs 2–3 max |
| UC Berkeley | "For college students, we recommend a simple, one-page format" |
| Berkeley I School | 0–7 years → 1 page; 7+ → 2 max |
| Stanford GSB | "Maximum of two pages" |
| Columbia SPS | One page under ten years' experience, two above |
| Harvard MCS | **States no page limit** |
| Laszlo Bock | "One page of resume for every ten years of work experience" |

**The contradiction worth surfacing:** ResumeGo found two pages preferred **even for entry-level**
(1.4×); every university says students should use one page. Neither side has outcome data. The
universities have no conflict of interest but also no evidence; ResumeGo has a large conflict.
**Honest framing: the one-page rule is a strong, unanimous professional convention with no measured
support, and the single study that tested length is too compromised to overturn it.** `resume-fill`'s
one-page default is therefore well within convention — and defensible on a stronger ground, which is
that it eliminates the PDF header/footer failure class entirely.

### The "6 seconds" / "7.4 seconds" claim

- **2012, TheLadders:** eye-tracking, **30 recruiters over 10 weeks**, average **6.25 seconds** on the
  initial screen; 80% of that on six fields. Reported by
  [Forbes](https://www.forbes.com/sites/susanadams/2012/03/26/what-your-resume-is-up-against/) — which
  **flagged the conflict of interest at the time**: TheLadders sold résumé rewrites at $395.
- **2018, Ladders Inc.:** **7.4 seconds**. ⚠️ **The official press release states no sample size.** The
  universally-attached "n=30" for 2018 is inherited from the 2012 study by secondary writers.
  [[PRNewswire]](https://www.prnewswire.com/news-releases/ladders-updates-popular-recruiter-eye-tracking-study-with-new-key-insights-on-how-job-seekers-can-improve-their-resumes-300744217.html) — **interested**

**Does it support what people claim? No.** It measures the **initial keep/discard scan**, not total
review time. The 2012 study's own recruiters self-reported ~4+ minutes total; ResumeGo's simulation
measured 2m24s–4m05s.

The best critical treatment is [ERE, Gygax 2020](https://www.ere.net/articles/is-the-6-second-resume-scan-a-myth):
the 2018 report "does not specify the types of positions or lengths of resumes", never states "how
many recruiters were in the study", never names the eye-tracking hardware, and "is essentially a
how-to guide intended to help people make their resumes easier to read" — marketing collateral, not
research.

**Recommended framing:** recruiters make an initial keep/discard decision in roughly 6–8 seconds
(Ladders 2012/2018, n≈30, not peer-reviewed, vendor-funded, method never fully disclosed); résumés
that survive get minutes, not seconds. The *design* implications — front-load, bold headers, don't
bury the lede — are sound regardless, they are just not proven by these studies.

Usable-with-hedging findings from the 2018 release: high performers had simple designs, clearly
marked sections, **bold headers**, readable fonts, **bold job titles and bulleted accomplishments**,
and F/E-pattern reading flow; poor performers had cluttered layouts, little white space, **multiple
columns**, and long sentences. Keywords should be integrated **contextually rather than through
keyword stuffing**.

### Summary / objective paragraph

**No experimental evidence exists for or against.** This is the least-evidenced item in the brief and
the one where the folklore ("objectives are dead") is stated most confidently.

- **Harvard MCS, MIT CAPD, Yale OCS — do not address objective or summary statements at all** (verified
  across three MIT pages). That silence from three elite career centres is itself informative: they
  treat it as optional enough not to legislate.
- **Berkeley I School:** a "Professional Profile" is **optional** — "a short section (1–4 sentences)"
  serving as a "snapshot".
- **Stanford GSB:** "**Limit the summary to 4 lines** plus bullet points."
- **Columbia SPS:** avoid "generic words"; "challenge yourself to be authentic."
- **Cornell career blog (2016):** the objective "has been taken off most resumes recently and been
  replaced with a summary statement" — opinion, no data.
- **Ladders 2018** is the only empirical-ish signal *in favour*: high-performing résumés had "a
  detailed overview or mission statement, primarily located at the top of the first page" —
  correlational, vendor-run, no stated N, confounded with general layout quality.

**Verdict:** "objective is obsolete, use a summary" is **folklore**. The shift happened by fashion,
not measurement. The only concrete constraints from credible sources are **length**: ≤ 4 lines
(Stanford GSB) or 1–4 sentences (Berkeley). `resume-fill`'s `RESUME_SUMMARY` toggle is the right
design — the evidence does not justify making it mandatory or forbidden.

<a id="a7"></a>
## A7. How the AI rankers actually rank

Consolidating [A1](#a1), plus what the litigation and audits reveal.

| System | Inputs | Output | Documented decision role |
|---|---|---|---|
| **Greenhouse Talent Matching** | "**only… data coming from the resume**" per one doc; "resume **and responses to application questions**" per another ⚠️ | 5 buckets + matched-term counts + keyword highlighting | "does not auto-reject or auto-advance any candidate" |
| **Lever Talent Fit** | "**only the Job Description and the candidate's resume**"; résumé **anonymised** first; LLM prompted to act as a recruiter | Tiers + % match | "Recruiters always have the final say" |
| **Workday Candidate Skills Match** | Skills similarity between application and requisition; **explicitly ignores recency, duration and total years of experience** | Strong/Good/Fair/Low/Pending/Unable to Score | Advisory; but the score is a reportable field on the job-application object, and auto-decline rules read from that object ⚠️ |
| **Workday HiredScore Spotlight** | "how well their **resumes match the skills and qualifications specified in the job description**"; never curved | A/B/C/D | No auto-reject recipe exists; auto-**advance** does (Fast Lane) |
| **Ashby AI Review** | Résumé vs recruiter-defined criteria | Meets / Does not meet / Undecided **+ sortable % column** | Marketing says it never ranks; docs describe sorting by percentage ⚠️ |
| **iCIMS Candidate Ranking** | "**a ranked list of applicants against a position's requirements**" | Ranked list | Advisory |
| **Taleo ACE / SAP Required Score** | **Questionnaire answers only** | Result %, ACE flag / Auto-Disqualified | **These two genuinely auto-reject** |

**Three things a document generator can act on:**

1. **A parse failure is not neutral.** Workday renders it as **"Low"**, indistinguishable from a weak
   candidate. Greenhouse renders it as **"Needs manual review"**, which routes to a human.
   HiredScore assigns **no grade** for an unsupported format. **The downside of a parse failure is
   platform-dependent and at worst catastrophic** — which is the justification for making the
   round-trip a hard build failure rather than a warning.
2. **Recency and duration matter to some rankers and not others.** Workday CSM explicitly ignores
   them; Textkernel/Sovren/RChilli/Affinda all compute `LastUsed` and `MonthsExperience` from
   work-history context. This is the mechanism behind the skills-in-bullets recommendation in
   [A5](#a5).
3. **Calibration is invisible.** Greenhouse recommends recruiters pick "4–6 key skills" and spreads
   the score across them. You cannot see that list. **This is the strongest possible argument against
   any third-party "match score"** — including this project's — being treated as predictive.

### What the litigation established

**Mobley v. Workday**, N.D. Cal. No. 3:23-cv-00770-RFL (Judge Rita F. Lin). The July 2024 order
(Dkt. 80, 740 F. Supp. 3d 796) established a **legal rule, not a factual finding**:

> "**a third-party agent may be liable as an employer where the agent has been delegated functions
> traditionally exercised by an employer**."
> "Drawing an artificial distinction between software decisionmakers and human decisionmakers would
> potentially gut anti-discrimination laws in the modern era."
> — [order PDF](https://blogs.duanemorris.com/classactiondefense/wp-content/uploads/sites/56/2024/07/Mobley-v.-Workday-Order.pdf) — **primary**

The line the court drew — usually omitted from coverage — is that a **spreadsheet vendor** would not
be an agent, "**By contrast, Workday does qualify as an agent because its tools are alleged to perform
a traditional hiring function.**"

⚠️ **No court has ever found that Workday's tools auto-reject.** Four proofs: the July 2024 language
is expressly a Rule 12(b)(6) plausibility inference; in May 2025 the court assumed the opposite
arguendo ("**even if Workday is taken at its word that its AI recommendation system cannot
auto-reject an applicant**…"); the certified collective treats auto-rejection as only one of two
alternative routes; and the court's own approved notice says "**The Court has not made any findings
about whether Plaintiff's claims or Workday's denial of liability have any merit.**"

Workday's own interrogatory response, quoted by the court, is the most precise public description of
CSM that exists: "**CSM utilizes artificial intelligence to parse an employer's job posting and an
applicant's application and/or resume; extract skills… and determine the extent to which the
applicant's skills match the role.**"

Status as of mid-August 2026: **active litigation, no settlement, no merits ruling**; thousands of
opt-ins; a decertification motion pending. ⚠️ Claims that "a court ruled against Workday", that a
nationwide class was certified, or that a settlement exists are **false**.

### What the published bias audits actually contain

**Greenhouse/Warden AI** publishes a real, public monthly dashboard
([trust.warden-ai.com/greenhouse](https://trust.warden-ai.com/greenhouse)) — latest 30 Jul 2026,
sample 71,510, 15 dimensions all "Clear". But read the auditor's own disclaimer:

> "**Warden's independent data set of real candidate profiles was used to perform the audit, due to a
> lack of access to historical data.**"
> "This report reflects the system's behavior **under controlled test conditions**… **should not be
> interpreted as a formal certification or compliance determination**."
> "**Accordingly, this report should not be interpreted as evidence of full compliance with NYC Local
> Law 144.**"

**Workday/HiredScore** has three audits. The 2024 one (~945,000 applications) has a worst cell of
**impact ratio 0.8174** (Female / Two or more races) — passing by 0.017 — and **excluded Native
American and Native Hawaiian/PI candidates entirely** as "less than .2% of the total population". The
2026 Secretariat audit of Spotlight
([Workday responsible AI page](https://www.workday.com/en-us/legal/responsible-ai-and-bias-mitigation.html))
covers **N = 1,443** applications, at Workday itself, for the five highest-volume job profiles,
NYC-area, Sep 2025 – Feb 2026, with a lowest intersectional impact ratio of **0.84** — three orders
of magnitude smaller than the 2024 audit and not comparable to it. Its results table is published
**only as a PNG image**.

**iCIMS's BABL AI audit and Ashby's FairNow audit are not published** — only asserted. **Lever,
Oracle Taleo and SAP SuccessFactors publish nothing** (grep-verified for the latter two).

**The structural pattern worth naming:** both HiredScore and Workday publish LL144-formatted bias
audits while formally denying LL144 applies. HiredScore, archived: "**HiredScore does not believe
that its AI applications meet the definition of an AEDT**… Nonetheless, HiredScore routinely conducts
bias audits." Workday's 2026 page preserves the identical posture.

### Regulatory context, briefly

Relevant because it shapes what vendors will and will not build, and because it explains the
"assistive, never deciding" language quoted throughout [A1](#a1).

- **NYC Local Law 144** (effective 1 Jan 2023, **enforcement from 5 July 2023**). Its definition of
  "simplified output" is directly on point and **expressly carves out parsing**: it covers "a score…,
  tag or categorization (e.g., **categorizing a candidate's resume based on key words**…),
  recommendation…, or **ranking (e.g., arranging a list of candidates based on how well their cover
  letters match the job description)**. **It does not refer to the output from analytical tools that
  translate or transcribe existing text, e.g., convert a resume from a PDF**"
  ([DCWP final rules](https://rules.cityofnewyork.us/wp-content/uploads/2023/04/DCWP-NOA-for-Use-of-Automated-Employment-Decisionmaking-Tools-2.pdf)).
  **The duty is the employer's, not the vendor's** —
  [DCWP FAQ](https://www.nyc.gov/assets/dca/downloads/pdf/about/DCWP-AEDT-FAQ.pdf): "**The vendor that
  created the AEDT is not responsible for a bias audit of the tool.**"
  ⚠️ **Compliance is near-zero.** [FAccT 2024, arXiv:2406.01399](https://arxiv.org/abs/2406.01399):
  155 student investigators recorded 391 employers; **18 posted audit reports and 13 posted
  transparency notices** (4.6% / 3.3%) — with the authors' own "null compliance" caveat, since
  employers have discretion over scope. And the
  [NY State Comptroller audit, Report 2024-N-6, 2 Dec 2025](https://www.osc.ny.gov/state-agencies/audits/2025/12/02/enforcement-local-law-144-automated-employment-decision-tools):
  "Despite receiving **only two AEDT complaints**… DCWP did not investigate whether the complaint
  intake process worked", and where DCWP found one issue among 32 companies, the auditors "identified
  at least 17 instances of potential non-compliance."
- **EU AI Act (Reg. (EU) 2024/1689), Annex III point 4(a)** covers "AI systems intended to be used for
  the recruitment or selection of natural persons, in particular… **to analyse and filter job
  applications, and to evaluate candidates**". The Article 6(3) escape hatch is very likely
  unavailable, because a system "**shall always be considered to be high-risk where the AI system
  performs profiling**", and scoring candidates against job requirements is profiling on its face
  *(analysis from statutory text, not a regulator statement)*. ⚠️ **Dates moved:** Regulation (EU)
  2026/1744 (in force 27 Jul 2026) defers Annex III high-risk obligations to **2 December 2027**;
  Article 26 (deployer duties) moves with it, while **Article 86's right to explanation sits in
  Chapter IX and still runs off 2 August 2026**.
- **Illinois:** the AI Video Interview Act (820 ILCS 42, eff. 1 Jan 2020) requires pre-interview
  notice, an explanation of "how the artificial intelligence works and what general types of
  characteristics it uses", and consent. **HB 3773 / P.A. 103-0804, effective 1 January 2026**, makes
  it a civil-rights violation "**to use artificial intelligence that has the effect of subjecting
  employees to discrimination**… **or to use zip codes as a proxy**", and to fail to give notice —
  an **effects-based** standard.
- **Colorado:** SB 24-205 was delayed by SB 25B-004, then **repealed and reenacted by SB 26-189
  (signed 14 May 2026), effective 1 January 2027** ([coag.gov/ai](https://coag.gov/ai/)). Reported
  duties include a plain-language description of the technology's role in an adverse decision within
  **30 days** and a right to "meaningful human review and reconsideration". ⚠️ The enrolled statutory
  text could not be retrieved; those duties rest on official summaries.
- **California Civil Rights Council ADS regulations, effective 1 October 2025** — the new "agent"
  definition pulls third-party ATS vendors into "employer", and requires retention of
  automated-decision data for **four years**.
- **What definitely survives regardless:** Title VII disparate impact and the four-fifths rule,
  [29 C.F.R. § 1607.4(D)](https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XIV/part-1607/section-1607.4).
- ⚠️ **EEOC's AI technical-assistance documents appear withdrawn** — both the May 2022 ADA and May 2023
  Title VII documents, and `eeoc.gov/ai`, now return 404 following
  [EO 14179](https://www.govinfo.gov/content/pkg/FR-2025-01-31/html/2025-02172.htm) — but **no formal
  rescission instrument was located**, and eeoc.gov restructured its URLs, so the 404s are suggestive
  rather than conclusive.

---

# Part B — bullet and content quality

**Headline finding, stated up front because it governs everything below.** Essentially *none* of the
résumé-content advice in circulation — XYZ, CAR/STAR/PAR, "quantify every bullet", "lead with the
outcome", "1–2 lines per bullet", "3–4 bullets per role", "one page" — is backed by a controlled
experiment measuring hiring outcomes. It is **convergent expert convention**. The only rigorous
experimental literature randomises *credentials*, not *prose*.

That does not make the advice wrong. Convergence across a dozen independent career offices is real
information. It makes it **unfalsified convention**, which should be stated as such rather than
dressed up as evidence — especially by a tool that prints checks.

<a id="b8"></a>
## B8. Bullet structures

### The XYZ formula — primary source, and what actually backs it

The formula: **"Accomplished [X] as measured by [Y], by doing [Z]."**

Primary source: **Laszlo Bock, "My Personal Formula for a Winning Resume", LinkedIn Pulse,
29 September 2014** —
https://www.linkedin.com/pulse/20140929001534-24454816-my-personal-formula-for-a-better-resume
(LinkedIn 403s automated fetch; date and wording confirmed via
https://harbert.auburn.edu/blogs/school-of-accountancy/better-resume-formula.html, an Auburn business
school post that quotes it and cites the Bock article).

**Three corrections to the usual attribution:**

1. ⚠️ **It is not on any Google careers page and never was Google policy.** Google's official re:Work
   hiring guide "Review resumes"
   (https://rework.withgoogle.com/intl/en/guides/hiring-review-resumes) now returns **404** —
   Google's own hiring-research site no longer serves it.
2. Bock's **TIME** piece "The Biggest Mistakes I See on Resumes"
   (3 Dec 2014, https://time.com/3617063/biggest-mistakes-resumes-corrections/) covers length, typos
   and formatting and **contains no XYZ formula**.
3. The earlier TIME piece
   (21 Apr 2014, https://time.com/70430/this-is-googles-dead-simple-formula-for-a-perfect-resume/)
   is sourced to a *New York Times* interview and describes a **different** framing: "Here's the
   attribute I'm going to demonstrate; here's the story demonstrating it; here's how that story
   demonstrated that attribute." So the "Google formula" brand spans at least two distinct Bock
   formulations from 2014.

**Evidence behind XYZ: none.** It is one executive's personal heuristic, stated as such ("My
*Personal* Formula"). No A/B test, no callback data, no internal Google analysis. *Work Rules!* (2015)
argues at length for structured *interviewing* — it presents no résumé-bullet experiments.
**Verdict: folklore with a high-credibility author.** Plausible advice from someone who ran hiring at
scale is not the same as evidence. Note that Yale teaches the XYZ structure **without attributing it
to Google or Bock at all** — the attribution chain is looser than the internet implies.

### What the career centres actually recommend — and they do not agree

There is no dominant framework. Every school uses a different acronym, and **none cites evidence**.

| Institution | Framework | Exact wording | Source |
|---|---|---|---|
| MIT CAPD | **PAR** | "P: Describe the PROJECT, the context, task, or job. A: What ACTIVITY did you do? R: What was the RESULT or outcome?" | https://capd.mit.edu/resources/resumes-writing-about-your-skills/ |
| Yale OCS | **APR** | "[A] Choose an action verb + [P] Name a project you completed or problem you solved + [R] Describe the results you achieved, quantifying when possible" | https://ocs.yale.edu/resources/writing-impactful-resume-bullets/ |
| Yale OCS | **XYZ** (offered as an alternative, no preference stated) | "[X] Lead with the impact you delivered + [Y] Numerically measure what you accomplished + [Z] Detail specifically what you did" | same |
| Yale OCS (STEM) | **WHO** | "**What** did you do? **How** did you do it? What was the **Outcome**?" | https://ocs.yale.edu/resources/stemconnect-technical-resume-sample/ |
| Yale SOM | **SAR** (Situation–Action–Result) | image-only PDF | https://som.yale.edu/sites/default/files/2022-01/Yale%20SOM%20CDO%20Resume%20Writing%20Guide-1(1)(1).pdf |
| CMU CPDC | Verb + Context + Result | "Action Verb + Context (tell the what) + Result (Metrics, Outcome, and/or Impact)" | https://www.cmu.edu/career/documents/sample-resumes-cover-letters/graduate_student_resume_guide_24.pdf |
| UC Berkeley | "wow factor" | bullets "accomplishment driven"; "skills or tools used; how you completed the task; the result or impact" | https://www.ischool.berkeley.edu/careers/guides/resume |
| Harvard MCS | none named | principle is "Fact-based (quantify and qualify)"; lists "Not demonstrating results" as a top mistake | https://careerservices.fas.harvard.edu/resources/create-a-strong-resume/ |

Yale's before/after example is the most useful concrete artefact found:

- **Before:** "Worked with a student leadership committee to increase member participation"
- **After:** "Led a 5-person leadership team to increase student participation by 100% from 50 to 100
  members by creating a stronger social media presence"

⚠️ **STAR proper (Situation–Task–Action–Result) appears at these schools mainly as *interview*
guidance, not résumé guidance.** Treat "use STAR on your résumé" as a downstream corruption of
interview advice.

### Lead with the outcome vs lead with the verb — a live disagreement, no evidence either way

I looked specifically for a comparison and found none. What exists is a documented institutional
split:

- **Lead with the verb.** MIT: "Begin each bullet point statement or phrase with an action verb that
  points the reader to the skill you are trying to highlight"
  (https://capd.mit.edu/resources/resume-action-verbs/). Penn: "begin each bullet point with a strong
  active verb" (https://careerservices.upenn.edu/resources/career-services-resume-action-verbs/).
  Columbia and Cornell agree.
- **Lead with the interesting thing.** **Stanford GSB:** "**Make the most interesting fact at the
  beginning of the bullet; it will entice the reader to read the rest.**"
  (https://www.gsb.stanford.edu/alumni/career-resources/job-search/resumes)
- **Yale offers both, side by side, with no stated preference.**

Weak indirect support for front-loading: Ladders 2018 reports recruiters scan in **F- and E-patterns**
favouring "bold job titles and bulleted accomplishments" — which implies the left edge of a line gets
read, but does **not** test verb-first vs outcome-first. *(An inference, labelled as one.)*

**This matters for `resume-fill` specifically:** `TAILOR_RULES` item 10 instructs the model to "Lead
every bullet with the verb for what was done", which takes a side in a disagreement where Stanford GSB
is on the other side and nobody has data. See [D.1.c](#d-crosscheck).

### Evidence ledger

| Claim | Status |
|---|---|
| XYZ improves outcomes | **folklore** (credible author, no data) |
| CAR / PAR / STAR / APR / SAR / WHO improve outcomes | **folklore** — universal convention, zero cited evidence at any of ~8 institutions checked |
| Lead with outcome > lead with verb | **folklore, and contested in print** |
| Accomplishments beat duties | **folklore with strong convergence.** Weak supporting signal from NACE: employers say they scan for *evidence* of problem-solving and teamwork, which duty-lists do not provide |
| Employers' résumé preferences are measurable at all | **evidence** — Kessler, Low & Sullivan, "Incentivized Resume Rating", *American Economic Review* 2019, 109(11):3713–44 (https://www.aeaweb.org/articles?id=10.1257/aer.20181714, free PDF https://hrlr.msu.edu/_assets/images/IRR_kesslerlowsullivan.pdf). ⚠️ **It randomises credentials, not bullet phrasing, and cannot be cited to support any formatting advice.** |

<a id="b9"></a>
## B9. Quantification

### Is there a study showing quantified bullets perform better?

**No. None exists.** Not a randomised field experiment, not an A/B test, not a peer-reviewed study.
This is the largest gap in the brief between how confidently the advice is stated and what supports
it. What gets cited instead:

- **Ladders 2012 / 2018 eye-tracking** — do not test quantification. See [A6](#a6).
- **ResumeGo** — tests length and cover letters, not quantification.
- **Cultivated Culture, "We Analyzed 125,000+ Resumes"** (https://cultivatedculture.com/resume-statistics/)
  — n = **125,484 résumé scans** through the vendor's own free tool. **36% of résumés contained zero
  metrics; only 26% contained five or more.** The authors explicitly state the data is "**not
  scientifically gathered or reviewed**". The sample is self-selected users of a résumé-fixing tool —
  i.e. people who already suspect their résumé is bad. ⚠️ **Crucially this is a *prevalence*
  statistic, not an *outcome* statistic.** It shows most résumés lack numbers. It says nothing about
  whether adding numbers gets more interviews. Read the other way: **zero-metric résumés are normal,
  and plenty of those people get hired.**

⚠️ **"Quantified resumes are 3.2× more likely to get callbacks — Resume Research Institute" is
fabricated or untraceable — do not use.** No such organisation, no methodology, no publication. Same
for "increases interview rates by up to 40%" and "34% of hiring managers pass over resumes with few
measurable results."

### What fraction of bullets should carry a number?

**No credible source specifies a fraction.** Every high-trust source says some version of "quantify
when possible", which is deliberately non-numeric:

- **MIT:** "Quantify if you can. If you gave a presentation, include how many people attended. If you
  raised or managed money, say how much." Three named levers: financial performance, percentage
  improvements, and scale of work (size of department, event, budget, dataset).
- **Yale:** "QUANTIFY the result and impact in terms of % improvement or % increase"
- **Stanford GSB:** "Be as quantitative as possible: revenue growth, money saved, market share
  growth"; include "size and scope, revenue or budget managed, and number of people on your team"
- **UC Berkeley:** "Quantify your results if possible" (https://career.berkeley.edu/prepare-for-success/resumes/)
- **Cornell:** "Quantify whenever possible (number of employees you supervised, dollar amount of
  sales volume increase…)"

⚠️ **Anyone who states "70% of your bullets need a number" is inventing it.** The honest framing for a
tool is: *no evidence supports a target ratio; the convention is "quantify wherever a real number
exists, and never invent one".*

A ratio check is still worth **reporting**, for a reason that is specific to this project and does not
depend on any external evidence: because `ground.py` forbids invention, a low quantification share is
a **selection** signal — either the tailor picked the wrong highlights, or the record itself has no
numbers in it. Both are actionable, and the second is exactly the kind of gap `report.md` exists to
surface. That is a defensible justification for the check; "studies show quantified bullets perform
better" is not, because there are none.

### What happens with zero numbers?

**No evidence of a penalty exists.** Nobody has measured it. The only indirect signal is **NACE Job
Outlook 2025** (https://www.naceweb.org/research/reports/job-outlook/2025): **n = 237 employer
respondents** (162 NACE members = **19.2%** response rate among eligible members, plus 75
non-members), fielded **5 Aug – 16 Sep 2024**. **~90%** seek evidence of **problem-solving**; **~80%**
**teamwork**; ≥70% written communication, initiative, work ethic, technical skills. This is a
*stated-preference* survey, not behaviour, with a 19.2% response rate — and **NACE never says "use
numbers."**

<a id="b10"></a>
## B10. Action verbs, pronouns, tense, length

### Action-verb lists (all primary institutional sources)

| Source | URL |
|---|---|
| MIT CAPD | https://capd.mit.edu/resources/resume-action-verbs/ (~200 verbs, 10 categories) |
| Harvard MCS | https://careerservices.fas.harvard.edu/resources/create-a-strong-resume/ |
| UC Berkeley HR | https://hrweb.berkeley.edu/sites/default/files/attachments/action-verbs.pdf |
| Columbia CCE | https://www.careereducation.columbia.edu/resources/200-action-verbs-spice-your-resume |
| Stanford | https://careered.stanford.edu/sites/g/files/sbiybj22801/files/media/file/action-verbs-pg-22.pdf |
| Penn | https://careerservices.upenn.edu/resources/career-services-resume-action-verbs/ |

⚠️ These lists are near-identical across schools and appear to descend from a common ancestor — the
categories match almost verb-for-verb. **Nobody has tested whether verb choice affects outcomes.**

### First-person pronouns — the most unanimous item in the brief

- **MIT:** "Avoid the use of first-person pronouns, i.e. I, me, mine, myself"
  (https://capd.mit.edu/resources/resume-checklist/); "Resumes don't require complete sentences and
  you should avoid using the first person (I, me, my)"
- **Yale OCS:** "**Do not use pronouns.**" (https://ocs.yale.edu/resources/resume-formatting/)
- **Harvard MCS:** under DON'T — "Use personal pronouns (such as **I or We**)"
- **Cornell:** "Avoid the first person (I, me, my)"

Harvard is the source that explicitly extends this to **We**, which is what licenses including
`we/our/us` in a pronoun check. Still: **no study.** It is a genre convention.

### Tense

- **MIT:** "Past tense verbs for previous roles, present tense verbs for current roles."
- **Yale OCS:** past experiences "use past tense (e.g. conducted or developed)"; current experiences
  "use present simple tense (e.g. create) – **do not use present continuous tense** (e.g. creating)."

Yale's present-simple-not-present-continuous rule is the most precise tense guidance found anywhere
and is directly encodable. ⚠️ Harvard, Berkeley, Columbia and Stanford GSB **state no tense rule** on
the pages checked — so the "universal rule" is really MIT and Yale being explicit while others are
silent.

### Bullet length — the unit everyone uses is *lines*, not characters

| Source | Guidance |
|---|---|
| Yale OCS | "no more than 1-2 lines" |
| MIT CAPD | "keeping each statement to 1-2 lines" |
| Stanford GSB | "3-4 bullet points of no more than 2 lines each" |
| Berkeley I School | "bulleted and in easy to read, shorter sentences (1 or 2 lines only)" |
| CMU CPDC | "Try to write one phrase per line when possible, but no more than two lines per bullet point"; "use consistent punctuation for bullets (bullet points do not require periods)" |

⚠️ **Nobody publishes a word or character count.** The unit is *lines*, which is font- and
margin-dependent. Converting: at MIT's stated 10–12pt with 0.5–1.0in margins on US Letter, one line
is roughly **95–115 characters**, so two lines is roughly **190–230 characters**. **That conversion is
arithmetic, not published guidance** — any character threshold in code is a house constant derived
from a line count, and should say so.

⚠️ The one word-count claim in circulation — TalentWorks' "475–600 word sweet spot doubles
interviews" — traces to a **defunct site** with no retrievable analysis. **Not verified; do not use.**

### Bullets per role

- **Yale OCS:** "no more than 3-4 bullets" per experience — but Yale's STEM page says "In general,
  provide **3-5 bullets** for each experience". **Yale contradicts itself across two of its own
  pages**, which is a useful signal about how precise this "rule" really is.
- **Stanford GSB:** "For each job, use 3-4 bullet points"
- **MIT, Harvard, Berkeley, Columbia:** do not specify a count.

**Converged range: 3–5, most commonly 3–4.**

### Other format numbers

- **MIT:** margins "between 0.5 and 1.0 inches"; font "between 10 pt and 12 pt"; Arial / Calibri /
  Times New Roman; bold and italics fine, **avoid underlining**.
- **Yale:** body 10–12pt; name header 12–14pt.
- **Berkeley:** "10-11 point font size and between .5-inch to one-inch margins".
- **Bock (TIME):** at least 10pt, half-inch margins, contact info on every page, **save as PDF**.
- **Berkeley:** "avoid using headers, footers, text boxes, tables, colors, pictures, or graphics."

**Binding intersection across all sources: 10pt floor, 0.75in margins, no underlining.**

---

# Part C — cover letters

<a id="c11"></a>
## C11. Are cover letters read?

**The honest summary: the surveys saying yes are almost all funded by companies that sell cover
letters, most were fielded before the generative-AI flood, the highest-trust employer survey does not
measure cover letters at all, and named employers are visibly dropping the requirement.** All four
facts belong together; quoting only the first is how this topic goes wrong.

### The best real-behaviour evidence is good — and five years stale

**ResumeGo, "Cover Letters: Just How Important Are They?"**
(https://www.resumego.net/research/cover-letters/) — **interested**.

- **Field experiment: 7,287 fictitious applications**, 15 Jul 2019 – 10 Jan 2020, to real postings on
  ZipRecruiter / Glassdoor / Indeed. Three arms. Callbacks within 30 days.
- **Absolute callback rates: no cover letter 10.7% · generic 12.5% · job-specific 16.4%** — a **+53%**
  relative lift for tailored over none, **+17%** for generic over none.
- **Survey component: 236 recruiters/hiring managers.** 87% read them · 65% say they materially
  influence interview/hire decisions · **24% regularly reject solely on a poor cover letter** · 81%
  value tailored over generic · 78% say generic-vs-tailored is easy to spot · 26% penalise omitting
  an "optional" cover letter.
- **Time spent — the most design-relevant number in this brief: 32% spend 0–10 seconds · 52% spend
  10s–1min · 16% spend 1–5min · 0% over 5 minutes. 84% spend under a minute.**

**Assessment.** Methodologically this is the strongest thing in ResumeGo's portfolio — a real field
experiment with a real behavioural outcome, far better than their one-vs-two-page simulation. ⚠️ But
the author is ResumeGo's CEO, the company sells cover-letter writing, there is **no per-arm N, no
randomisation procedure, no confidence intervals, no significance test and no preregistration**, the
page carries an internal date inconsistency (dated Jan 2019, field window running into Jan 2020) —
**and it was fielded before ChatGPT existed**, which is close to disqualifying for the 2024–2026
question.

### The "83% / 94% / 60%" numbers are one 2023 survey wearing a 2026 hat

**Resume Genius cover-letter statistics**
(https://resumegenius.com/blog/cover-letter-help/cover-letter-statistics) — **interested**.
**625 U.S. hiring managers, Pollfish, fielded 2023**, page relabelled "for 2026" and updated January
2026. Reports: 83% always/frequently read · **45% read the cover letter *before* the résumé** · 94%
say they influence interview decisions · 72% expect one even when "optional" · 36% spend <30s ·
requirement by employer size 60% overall / 72% medium / 69% large / **49% small** · ~400 words ideal
· PDF preferred · intro is the highest-impact section (41%).

⚠️ **Trust: low.** Pollfish is mobile-app river sampling with self-identified "hiring managers", not a
verified employer panel, and the funder sells cover letters.

⚠️ **The corporate structure matters: Resume Genius and CV Genius are both owned and operated by
Sonaga Tech Limited** (stated in both `/about` footers). So the "US" and "UK/Ireland" surveys are the
same company, same vendor, **same N of 625** — one conflicted source, not two. The CV Genius wave
(**625 UK/Ireland hiring managers, Pollfish, fielded 22 April 2024**,
https://cvgenius.com/blog/career-advice/cv-and-cover-letter-trends-survey) reports only **49% expect a
cover letter** and 57% find them influential. **The same company's two surveys give 60% and 49%** — a
useful demonstration of how soft these numbers are.

### The highest-trust employer survey barely mentions cover letters

- **NACE Job Outlook 2026** (published Nov 2025, fielded **7 Aug – 22 Sep 2025**): the phrase "cover
  letter" appears **once**, at 50.0% of 108 respondents naming "create a skills-based resume and/or
  cover letter" as a top way students demonstrate skills — **ranked 5th of 8**, below interview prep
  (88.9%) and experiential learning (74.1%). **Zero mentions of AI, generative AI or ChatGPT in the
  entire report.**
- **NACE Job Outlook 2025** (n=237, 19.2% member response rate, fielded Aug–Sep 2024): **zero**
  mentions of cover letters, zero of AI.

**The finding is the absence.** The most methodologically sound employer survey in US campus
recruiting does not consider the cover letter worth measuring.

### Employers dropping cover letters — on the record

*Business Insider*, "RIP cover letters", Ana Altchek, 1 Jun 2026. Named executives: **Bonnie Dilber
(Zapier)** — "All cover letters look the same with AI"; **Marie Christine Padberg (McKinsey)** —
"They're long gone. No more cover letter"; **Scott McGuckin (Cisco)**; **Brian Myerholtz (BCG)** —
stopped requiring nearly a decade ago; **Erin Scruggs (LinkedIn)**; **Paul Farnsworth (Dice)**.

⚠️ **The caveat the headline hides:** McKinsey, BCG and Cisco dropped cover letters *before*
generative AI. **The decline predates the flood; AI accelerated an existing trend.**

### Direct measurement from live application forms

Sampling first-listed jobs across 22 Greenhouse job boards:

- **Present and REQUIRED:** Airbnb (1 of 22).
- **Present, optional:** Stripe, Databricks, Instacart, Robinhood, GitLab, Brex, Coinbase, Reddit,
  Dropbox, Asana, Affirm, Discord, Cloudflare, MongoDB, Twilio, Samsara, Scale AI.
- **Absent entirely:** Figma, Lyft, Anthropic, Datadog.

**And the replacement pattern is real:**

- **Anthropic** — no cover-letter field; **résumé itself optional**; a **required** free-text
  `Why Anthropic?` — "*(We value this response highly - great answers are often 200-400 words.)*";
  plus a **required** AI-policy attestation.
- **Figma** — no cover-letter field; **required** "Please share 3-4 sentences on why you want to join
  Figma."
- **Instacart** — cover-letter field plus a **required** STAR behavioural prompt, "this should take no
  more than 5 minutes to complete."
- **Lyft** — field removed, nothing replacing it.

**Implication for `resume-fill`:** the artefact increasingly being asked for is a **200–400 word
structured answer to a specific question**, not a letter. A future mode emitting that shape — same
grounding gate, same citations, no salutation, no signoff — would track where hiring is actually
going better than the letter does.

### Application volume, with caveats

- **LinkedIn: ~11,000 applications/minute, +45% YoY** — sourced to *NYT*, "Employers Are Buried in
  A.I.-Generated Résumés", 23 Jun 2025. ⚠️ **LinkedIn has never published this as research** — its
  Economic Graph and *Future of Recruiting 2025* report (1,271 recruiting professionals, 23 countries,
  fielded Sep 2024) contain no application-volume data. Treat as a vendor press quote.
- **Greenhouse: 28 → 95 applications per job, 2021→2025**
  (https://www.greenhouse.com/blog/hiring-pipeline-overload), customer ATS data, **no N**.
  ⚠️ **Greenhouse's own earlier figure was 228 applications per posting in Feb 2024.** 228 (2024) vs
  95 (2025) is not reconcilable as published — **do not present as one time series.**
- ⚠️ **Indeed Hiring Lab publishes no application-volume data at all** — a common misattribution.

### The one causal study that matters

**Cui, Dias & Ye, "Signaling in the Age of AI: Evidence from Cover Letters"**
(https://arxiv.org/abs/2509.25054) — **primary**, though a working paper.

- **N = 5,499,707 cover letters** from **264,082 unique bidders** across **106,714 jobs** on
  Freelancer.com, 19 Jan – 15 Sep 2023. DiD sample 2,511,592 bids from 17,759 workers.
- Natural experiment: Freelancer launched an "AI Bid Writer" on **19 April 2023**, staged by
  membership tier — which separates the tool from GPT-4's 14 Mar 2023 release.
- **Tool access raised callback probability 0.43pp (ITT); usage raised it 3.56pp — a 51% lift on the
  7.02% baseline.**
- ⚠️ **But the correlation between cover-letter tailoring and callbacks fell 51%, and the correlation
  with actual offers fell 79%.** Employers shifted weight to work history and platform rankings.
- **Time spent editing the AI draft was positively correlated with hiring success.**
- Funded by the Cowles Foundation, Yale; data provided by Freelancer.com. ⚠️ A **gig platform**, not
  corporate hiring — external validity unproven.

Pair with the pre-flood counterfactual: **Wiles, Munyikwa & Horton, NBER w30886 → *Management
Science* 2025** (https://www.nber.org/papers/w30886), ~500,000 jobseekers — algorithmic writing
assistance produced **+8% hires with no drop in employer satisfaction**.

**The thesis: writing assistance helps while it is scarce and destroys the signal once it is
universal.** For this project that is an argument to lean on the parts that do not decay — verifiable
specifics traceable to a record — rather than on polish.

<a id="c12"></a>
## C12. Structure

### Length — a real consensus at 250–400 words

| Source | Guidance |
|---|---|
| **Princeton** | "Keep it to no longer than one page, approximately **250-400 words**." (https://careerdevelopment.princeton.edu/cover-letter-guide/basic-principles-cover-letter-writing) |
| **Anthropic's live application form** | "great answers are often **200-400 words**" |
| **Harvard FAS careerservices blog**, 10 Aug 2026 | "One page, three to four paragraphs. Aim for **250 to 400 words**." ⚠️ authored by **WayUp**, syndicated career media, not Harvard research |
| **MIT CAPD** | "no longer than one page with a font size between 10-12 points" (https://capd.mit.edu/resources/how-to-write-an-effective-cover-letter/) |
| **HBR** | "Much of the advice out there says to keep it under a page. But both Glickman and Lees say **even shorter is better**… brief enough that someone can read it at a glance." |
| Resume Genius | ~400 words (**interested**) |

**Consensus: 250–400 words, one page maximum, shorter is safer.** That an employer's own
required-field spec independently lands in the same band as Princeton's is the strongest corroboration
available. Cross-check against the timing data: at 84% of readers spending under a minute, 400 words
is already at the ceiling of what gets read.

⚠️ **No source states a minimum.** Any lower bound in code is a house floor.

### Paragraph count and what goes where

- **Yale OCS** is the most specific source found: "**three to four paragraphs**"; "The introductory
  and concluding paragraphs should be **between one and three sentences**, and the body paragraphs
  should be **between three and five sentences**." Plus: "Start each paragraph with a topic sentence
  that highlights one of your skills that relates to the position."
  (https://ocs.yale.edu/channels/cover-letters-correspondence/)
- **UNC:** "3 to 5 paragraphs… a more persuasive document", structured **ATTENTION / INTEREST / FIT /
  FOLLOW-UP** (https://careers.unc.edu/resource/writing-effective-cover-letters/)
- **MIT CAPD:** intro (1) + body (2–3) + closing (1). Body: "Cite a couple of examples from your
  experience that support your ability to be successful in the position."
- **Princeton's three questions:** who are you and what are you applying for · what value can you add
  · why this particular opportunity.

**3–4 is the consensus; 3–5 is the union of the sources.**

### Opening lines — the clichés are named explicitly

This is well-evidenced, which is unusual for this topic.

- **HBR**, verbatim: "People typically write themselves into the letter with '**I'm applying for X job
  that I saw in Y place**.' **That's a waste**," says John Lees. "**Start with the punch line** — why
  this job is exciting to you and what you bring to the table," says Jodi Glickman. Also: "Stay away
  from common platitudes"; "Humor can often fall flat or sound self-regarding"; "don't go overboard
  with the flattery."
- **Cornell:** "Jumping out of the gate in the first paragraph of a cover letter with your **value**,
  not '**I'm excited to apply for this position…**'"
  (https://gradcareers.cornell.edu/spotlights/resume-and-cover-letter-takeaways/)
- **Harvard/WayUp blog:** avoid "**I am writing to express my interest in…**"
- **Princeton's Weak→Better→Best ladder**
  (https://careerdevelopment.princeton.edu/cover-letter-guide/weak-better-best-sample-sentences) is
  the most concrete artefact in this section:
  - **Weak:** "I am a junior sociology major seeking a summer journalism internship."
  - **Better:** "I am interested in using my writing skills this summer in your journalism
    internship. As a junior sociology major, I have had the opportunity to develop my writing
    skills…"
  - **Best:** "I am an avid reader of *People & Places Magazine* and was inspired to launch a travel
    blog [link] after my semester abroad. With an interest in creative writing and a global focus, I
    am excited to apply for the creative writing internship at your publication."

⚠️ **Tension worth flagging: Princeton's own "Best" example contains "I am excited to apply for" —
the exact phrase Cornell tells you to cut.** Universities disagree here. HBR and the AI-tells
literature both side with Cornell, which is why blocking that opener is defensible — but it is a
choice between sources, not a settled rule, and a checker should say so.

### Middle

- **Yale:** "Use keywords from the position description in your cover letter."
- **Berkeley:** "Connect your experiences and qualifications with the desired qualifications";
  "Demonstrate your knowledge of the position AND the company." (https://career.berkeley.edu/cover-letters/)
- **Cornell:** "Take your cues from the market and address what the job postings ask for";
  **quantify accomplishments**; adopt "a solutions focus, not just what you did."
- **HBR:** "provide evidence of the things that set you apart."
- **Harvard/WayUp:** "Grew a student org's Instagram following from 200 to 1,400 in one semester"
  beats "Managed social media content."
- **Empirical backing, with an expiry date:** textual alignment with the job post *did* predict
  callbacks pre-AI (Cui et al.) — and its predictive power then **collapsed 51%**. Mirroring is
  correct advice that is losing potency.

### Closing

Princeton's ladder again:
- **Weak:** "This internship would be a great opportunity to improve my writing skills. Please feel
  free to call me if you'd like more information." *(candidate-centred; no appreciation)*
- **Better:** "Thank you for your time and consideration. I hope to hear from you soon." *(note this
  is the middle rung, not the target)*
- **Best:** "I am excited about the journalism internship and am confident you will find my background
  a strong match for your organization. I look forward to speaking with you soon about the role and
  my qualifications."

⚠️ **Purdue OWL still advises announcing a follow-up phone call — that advice reads dated** and
conflicts with modern ATS-mediated processes where no number is available.

### What makes a letter fail

⚠️ **Honest finding: the survey evidence here is thin and almost entirely vendor-funded.** The
strongest items:

- **Generic/template is the top killer.** ResumeGo: 81% value tailored significantly more; 78% say it
  is easy to tell. **Princeton names the specific failure mode:** "Employers can tell when a letter
  reads like a generic template. **They will notice if their name has simply been swapped in.**"
- **Repeating the résumé.** Princeton: "A cover letter is more than a resume in paragraph form."
  HBR: "don't rehash your résumé."
- **Candidate-centred framing.** Cornell leads its list with taking "the employer's perspective… not
  yours (as in, 'I think this position is great for me because I can learn…')."
- **Typos.** Berkeley requires "NO grammar/spelling errors."
  ⚠️ The widely-quoted "nearly half instantly reject for typos" and Zety's "81% of recruiters have
  rejected a candidate based on cover letter details" **could not be verified** — Zety blocks
  automated access and sells résumés. **Do not cite.**

⚠️ **Gap to state plainly: there is no high-trust, non-conflicted survey quantifying cover-letter
rejection reasons.** Everything circulating traces to résumé-sellers.

<a id="c13"></a>
## C13. What reads as AI-generated

### The empirical word list

**Kobak, González-Márquez, Horvát & Lause, "Delving into LLM-assisted writing in biomedical
publications through excess vocabulary", *Science Advances* 11(27):eadt3813, 2 Jul 2025.**
Preprint https://arxiv.org/abs/2406.07016 · data
https://github.com/berenslab/chatgpt-excess-words — **primary**.

Method: >15M PubMed abstracts 2010–2024, using the excess-word method borrowed from excess-mortality
studies. Findings: **at least 13.5% of 2024 abstracts LLM-processed**, up to 30–40% in some
subcorpora; **900 unique excess words** annotated across 2013–24; excess words jumped to **454 in
2024**; of the **379 excess style words in 2024, 66% were verbs and 14% adjectives**, where prior
years' excess words were mostly content nouns. Headline markers: **delves (r=28.0), underscores
(r=13.8), showcasing (r=10.7)**; by frequency gap **potential, findings, crucial**.

The paper's own illustration of the register, from a real 2023 abstract:

> "By **meticulously** **delving** into the **intricate** web connecting […] and […], this
> **comprehensive** chapter takes a deep dive into their involvement as **significant** risk factors
> for […]."

**The machine-readable artefact is `results/excess_words.csv` in that repo** — 900 words, each
annotated `content` / `style` with a part of speech. **407 are style words.** Raw 2024-vs-2022
frequency ratios computed directly from the released count matrix *(my arithmetic — a different
estimator from the paper's counterfactual extrapolation, hence delves 47.8× here vs r=28.0
published)*:

| Word | 2022 | 2024 | ratio |
|---|---|---|---|
| delves | 0.007% | 0.357% | **47.8×** |
| delved | 0.004% | 0.071% | 18.5× |
| showcasing | 0.017% | 0.229% | 13.8× |
| underscores | 0.104% | 1.439% | 13.8× |
| meticulously | 0.016% | 0.166% | 10.5× |
| intricate | 0.134% | 0.992% | 7.4× |
| garnered | 0.060% | 0.365% | 6.1× |
| tapestry | 0.001% | 0.006% | 5.5× |
| realm | 0.045% | 0.226% | 5.0× |
| leveraging | 0.193% | 0.749% | 3.9× |
| seamlessly | 0.024% | 0.076% | 3.2× |
| pivotal | 0.565% | 1.730% | 3.1× |
| crucial | 2.962% | 7.060% | 2.4× |

⚠️ **Three caveats that matter enormously for turning this into code.**

1. **Most of the 407 style words are ordinary English.** The list includes `across`, `based`, `both`,
   `this`, `were`, `while`, `within`, `however`, `including`, `research`, `role`, `their`, `using`.
   **A naive blocklist over the full list would reject normal prose.** Only the low-base-rate,
   high-ratio tail is usable.
2. **The corpus is biomedical abstracts and it transfers only partially to cover letters.** Measured
   in the same data: `thrilled` **0.00×**, `passionate` **0.80×**, `excited` **1.04×**, `moreover`
   0.97×, `proven` 0.95×, `resonate` 1.15× — **no excess at all**, because they are cover-letter
   register, not academic register. **"I am thrilled to apply" is a template tell, but it is not
   evidenced by this paper.** Do not overclaim.
3. Conversely: of 100 stereotypical cover-letter buzzwords tested against the list, **95 appear among
   Kobak's style words** — the overlap is real, it just runs in one direction.

**The high-signal subset** — distinctive and low-base-rate, therefore usable as a density signal:

```
delve delves delved delving   intricate intricately intricacies   meticulous meticulously
showcase showcases showcasing showcased   underscore underscores underscoring underscored
pivotal   realm realms   tapestry   garner garnered garnering   seamless seamlessly
multifaceted   nuanced   groundbreaking   unparalleled   transformative   invaluable
commendable   noteworthy   formidable   renowned   bolster bolstered bolstering
harness harnesses harnessing   leverage leveraging leverages   elevate elevates elevating
foster fosters fostering   unveil unveils unveiling   illuminate illuminates illuminating
elucidate elucidates elucidating   encompass encompasses encompassing
navigate the complexities   testament to   interplay   landscape   paving the way
ever-evolving   in today's fast-paced
```

**Second corpus, non-academic text.** Liang et al., "The widespread adoption of large language
model-assisted writing across society" (https://arxiv.org/abs/2502.09747 → *Patterns*, Cell Press) —
687,241 consumer complaints, 537,413 corporate press releases, **304.3M job postings**, 15,919 UN
press releases, Jan 2022 – Sep 2024. By late 2024: ~18% of consumer complaints, up to 24% of corporate
press releases, ~10% of small-firm job postings LLM-assisted. Growth **plateaued in 2024**. Its top
LLM-preferred words — **pivotal, intricate, showcasing, realm** — independently match Kobak's.

### Structural tells

The most concrete, actively maintained catalogue is **Wikipedia's "Signs of AI writing"**
(https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) — created 4 Dec 2023, still edited
Aug 2026. ⚠️ **It is a WikiProject advice page, not policy and not peer-reviewed** — but it is written
by editors doing this adversarially at scale, and its vocabulary list independently overlaps Kobak
heavily. Its catalogue:

- **Negative parallelism:** "**Not only X, but also Y**" · "**It's not X, it's Y**" · "X rather than Y"
- **Rule of three:** adjective-adjective-adjective, phrase-phrase-and-phrase
- **Significance inflation:** *stands/serves as, is a testament to, crucial/pivotal/vital role,
  underscores importance, reflects broader, setting the stage*
- **Trailing "-ing" participial clauses** bolted onto sentence ends — *highlighting, underscoring,
  emphasizing, ensuring, reflecting, fostering, encompassing, enhancing*
- **Avoidance of "is/are"** in favour of *serves as, stands as, marks, functions as, represents,
  boasts, features*
- **Promotional register:** *boasts a, vibrant, rich, profound, nestled, in the heart of,
  groundbreaking, renowned, diverse array*
- **Vague attribution:** *Industry reports, Observers have cited, Experts argue, Some critics argue*
- **Em-dash overuse**, curly quotes, overuse of boldface, title-case headings, emoji as formatting

**A .edu source names the em-dash directly.** MIT CAPD's "Using AI for cover letters"
(https://capd.mit.edu/resources/using-ai-for-cover-letters/) warns that recruiters recognise AI
through "**the use of dashes as punctuation marks**…a formulaic cover letter, and **over polished
writing that lacks a human touch**", and that AI "can hallucinate facts" and "make statements about
your capabilities with **no tangible evidence**." That last point is exactly what `ground.py` prevents
structurally — worth noting as external validation of the design.

### The skeptical core: hiring managers cannot actually detect AI text

**This is the most important counterweight in the brief, and the best-evidenced part of it.**

**Jakesch, Hancock & Naaman, "Human heuristics for AI-generated language are flawed", *PNAS* 120(11),
Mar 2023** (https://arxiv.org/abs/2206.07271) — **primary**.

- **N = 4,600 participants, 7,600 self-presentations, six experiments**, across professional,
  hospitality and dating contexts. The professional condition is the closest published analogue to a
  cover letter.
- **Accuracy: 50–52%. Chance is 50%.** Professional context with incentives **51.6%**; with immediate
  feedback **51.2%**.
- Judgements were **not random** — Fleiss' κ = 0.07, p<0.0001 — meaning participants **shared flawed
  heuristics**.
- **Which heuristics were wrong:** grammatical errors were rated 5% more AI-like but were **15%
  *less* likely to be AI**; long words and rare bigrams were rated AI-like but were mostly **human**;
  first-person speech was rated human but predicted nothing. Only *nonsensical* (+23%) and
  *repetitive* (+47%) content genuinely indicated AI.
- An automated classifier reached **58.8%** — barely better.

**Milička et al. 2025** (https://arxiv.org/abs/2505.01877), 254 participants, GPT-4o vs human texts,
**side-by-side pairs** — an *easier* task than judging one document alone: **no-feedback group
55.4%** (95% CI 52.0–58.7), feedback group 65.1%. The killer detail: without feedback, "participants
made the most errors **precisely when they were most certain** (even below the chance level of 0.5)."

**Synthesis, and it should be stated wherever this project cites AI detection:** every recruiter
statistic of the form "X% of us can spot AI" measures **confidence, not accuracy**. The measurement
literature puts naïve humans at chance and trained humans at 55–65% on an easier task than the real
one. ⚠️ **No study anywhere has measured recruiters' actual accuracy on real application materials.**
That is a genuine research gap.

⚠️ **And an employer running cover letters through an AI detector is running a tool with documented
disparate impact:** Liang et al., "GPT detectors are biased against non-native English writers",
*Patterns* 2023 — detectors systematically misclassify non-native English writing as AI.

**What this does and does not change.** It does **not** make cliché-avoidance pointless: the
structural tells above are also just *bad writing*, and cutting them improves a letter for a reader
who never thinks about AI at all. It **does** mean the justification should be "these phrases are
empty and every other letter has them", not "recruiters will detect the model". The second claim is
not supported.

### Recruiter AI surveys — all conflicted

- **TopResume**, https://topresume.com/career-advice/ai-in-hiring-survey — **600 U.S. hiring managers,
  Pollfish, fielded 15–16 May 2025**, funded by TopResume, *which sells human-written résumés and
  therefore profits from the finding*. 19.6% would reject for AI-generated material · 52% say AI
  proofreading/drafting is acceptable · 25% say cover letters specifically should stay AI-free ·
  33.5% claim they can spot AI in under 20 seconds. ⚠️ The generational split is a tell that this
  measures confidence: **Gen Z claims the *lowest* detection ability (19.8%)** vs Gen X/Millennials
  ~34.7%.
- **CV Genius**, 625 UK/IE hiring managers, fielded 22 Apr 2024: **80% view AI-generated content
  negatively; 57% less likely to hire or consider it a dealbreaker.** Conflicted (Sonaga Tech).
- **Greenhouse**, ~Nov 2025, N=4,136 (2,900 job seekers + 1,236 recruiters/HMs): 91% of recruiters
  have spotted candidate deception; 41% of job seekers admit prompt-injection attempts. ⚠️ No fielding
  dates, no vendor disclosed, and Greenhouse sells fraud detection. See A6 for why the 41% is almost
  certainly a question-wording artefact.
- **Robert Half**, 10 Mar 2026, >2,000 US hiring managers, fielded Nov 2025: **67% say AI-generated
  applications have slowed hiring**; 38% run more interviews per candidate; **32% rewrote job
  descriptions to deter generic AI answers**. Staffing-firm COI — the workload numbers are
  defensible; the "employers need staffing firms" numbers are marketing.

⚠️ **Untraceable, do not use:** "2026 TopResume survey of 800+ hiring managers, 67% can identify AI
cover letters" and "2026 Indeed survey: 61% spend under 30 seconds on AI-generated cover letters."
An audit of `coverlettercopilot.ai` — an AI cover-letter vendor, so a reverse conflict of interest —
found **12 specific-sounding statistics with zero source links and no bibliography**. These numbers
are laundering.

### The model employer policy

**Anthropic's candidate AI guidance**, last updated 10 Jul 2025
(https://www.anthropic.com/candidate-ai-guidance), which its application form makes a **required
attestation**:

- Application materials: "**Please create your first draft yourself, then use Claude to refine it.**"
- Encouraged: "Help me think of ways to quantify the impact of the platform migration that I led."
- Not allowed: "Write my answers to the application questions…"
- Live interviews: "This is all you–no AI assistance."
- Principle: "**Be yourself. Use AI to refine your ideas, not replace them.**"

The cleanest dated first-party policy available, and it **aligns precisely with Cui et al.'s finding
that editing time correlates with success**. It is also a fair statement of what a tool like
`resume-fill` should aim to be: the ideas and the facts come from the record; the model arranges them.

<a id="c14"></a>
## C14. Addressee when nobody is named

Near-total consensus on **"Dear Hiring Manager"**, with one outlier.

| Source | Position |
|---|---|
| **MIT CAPD** | "address it directly to the hiring manager, using their name. **If you are not sure who to address the letter to, write 'Dear Hiring Manager.'**" |
| **Yale OCS** | "If you cannot find a name, consider using '**Dear Hiring Manager**.'" |
| **UC Berkeley** | "Dear Hiring Manager" when unknown |
| **UNC** | "Dear Human Resources Director," or "Dear Hiring Manager." — **explicitly advises against "To Whom It May Concern"** |
| **Harvard/WayUp blog** | "**Dear Hiring Team**" works fine |
| **Purdue OWL** (©2026) | ⚠️ **Outlier:** "Dear Hiring Professionals:" or "Dear Selection Committee:". Also: if you find a name but not the gender, use the full name — "Dear Amy Kincaid:" |
| **HBR** | "**always address your letter to someone directly.** With social media, it's often possible to find the name of a hiring manager" (Glickman) |
| **Resume Genius** (interested) | "Dear Hiring Manager" is the most-preferred generic — **but addressing by name ranked the *least* important customisation element** |

**Bottom line: "Dear Hiring Manager" is the safe default. No source recommends "To Whom It May
Concern", and UNC explicitly forbids it.** "Dear [Team] Team" is endorsed only by the Harvard-hosted
syndicated post.

⚠️ **A real tension:** HBR says always find a name; Resume Genius's own data says the name matters
least. Given that 84% of readers spend under a minute, the salutation is unlikely to be where the
decision is made. **This validates `resume-fill`'s existing decision** (PLAN.md open question 4) to
use a configured fallback rather than scrape a name — "guessing a person's name from a company page is
how a letter ends up addressed to someone who left" is the correct reasoning, and no source
contradicts it.

## C-extra. Do ATS parse cover letters at all?

**This is the thinnest area in the brief and should be flagged as such.**

**What is established from vendor APIs and docs:**

- **Greenhouse** models the cover letter as **one question exposing two fields — `cover_letter`
  (`input_file`) and `cover_letter_text` (`textarea`)** — attachment *or* inline text, same slot.
  Verified across ~50 live application forms.
- **Lever's and Ashby's public posting APIs expose no cover-letter concept at all** in job data.
- **Textkernel has a `Coverage.FindSkillsInCoverLetter` toggle, default enabled** — so at least one
  major parser **does** mine cover letters for skills. This is the strongest single piece of evidence
  that cover-letter text enters a structured record.
- **NYC DCWP's rules contemplate it:** their example of a ranking AEDT is "arranging a list of
  candidates based on **how well their cover letters match the job description**" — a regulator
  describing a practice, not a vendor documenting a product.

⚠️ **What could NOT be verified and should not be asserted:** whether any named ATS parses, indexes,
keyword-searches, scores or auto-rejects on cover-letter content. **No primary vendor documentation
exists either way.** The widespread claim that ATS keyword-screen cover letters is
**unsubstantiated** — and the pages pushing that framing tend to sell "ATS checkers".

**Format guidance that is sourced:** PDF preferred (Resume Genius, **interested**); when applying by
email, "include the cover letter in the text of your email and attach the resume" (UNC); match the
résumé's header, font and margins (Berkeley); "the files should start with your last name, not the
name of the company" (Cornell); one page, 10–12pt (MIT).

**Practical implication:** because the letter is at least as likely to be **pasted into a textarea**
as parsed, the round-trip check in `verify_letter` is doing real work — and its existing docstring
("more often pasted into a textarea than parsed by an ATS, which makes clean extraction matter more,
not less") is correct, with the Textkernel toggle now supporting the other half.

---

# Part D — the actionable checklist

**The rule for adding a check.** `ats.py`'s docstring already states it well: a check must be about
something a parser or a human reviewer **demonstrably does with the document**, not about a number
somebody claims a machine assigns to it. This section keeps that rule and adds a second one: **every
check should be able to name what backs it, and checks backed by convention rather than evidence
should say so in their own comment.** A tool that prints "3 of 12 ATS checks failed" is making an
implicit evidentiary claim, and the ones that are house conventions should not free-ride on the ones
that are Textkernel Fatal codes.

<a id="d-crosscheck"></a>
## D.1 Cross-check against the implemented rubric

Read against `resume_fill/ats.py` and `resume_fill/letter_review.py` as they stand.

### D.1.a Rules the code implements that the sources DO support

| Implementation | What backs it | Strength |
|---|---|---|
| `check_single_column` — bans `<table>`, floats, `column-count`, `<img>`, `<svg>` | Greenhouse lists "Complex resumes with tables, headers, and footers" and "Resumes that have a columned layout" as parse-failure causes; Textkernel **433 is Fatal** ("a HUGE MISTAKE… columns"); Workday "use resumes that don't have images or image-based styles"; Daxtra, MIT, Berkeley, CMU, Columbia, Georgia Tech all agree; column layouts measured at 15% (Textkernel, n>12,000) and ~20% (arXiv:2510.09722) of real CVs | **Strong.** The best-evidenced formatting rule in the brief. Note the project's own measurement (extraction reorders a two-column entry header) is *additional* evidence, not a substitute |
| `check_sections` — must have a work-history section | Textkernel **413 is Fatal**: "a WORK HISTORY section was not found"; **412** Fatal: "no sections were found" | **Strong**, primary |
| `check_headings` — headings must be from a known set | Textkernel records "the exact text that was used to identify the beginning of the section", falling back to `"CALCULATED"` and raising Fatal **415/416** when it must guess; OpenResume's detector requires a keyword from `experience/education/project/skill/...` | **Strong** in principle; see D.1.c for the specific set |
| `check_dates` — every entry needs a parseable range | Textkernel **419** Fatal ("The Employment section did not provide dates for jobs"), **224/225** (jobs without start/end dates), **418** Fatal (dates stacked vertically) | **Strong**, primary |
| `DATE_RANGE` requires `Present` capital-P for ongoing | OpenResume matches `item.text.includes("Present")` — **case-sensitive literal**. `Current`, `Now`, lowercase `present` all fail | **Strong**, and unusually concrete |
| `DATE_RANGE` accepts `-`, `–`, `—` interchangeably | Correct by omission: **no vendor documents a separator preference**, and the SEO sources contradict each other. Being agnostic is the evidenced position | **Correct precisely because it does not take a side** |
| `check_contact` — email is blocking, phone/location advisory | Textkernel **441 is Fatal** ("neither an email address nor a phone number were found. A resume should include always include both"); **211/212/213** are Data Issues; Daxtra requires at least one of phone/email | **Strong.** The split (email blocking, phone advisory) is a defensible reading, though Textkernel treats the *pair* as the Fatal condition |
| `check_first_person` including `we/our/us` | MIT ×3 pages, Yale ("Do not use pronouns"), Cornell — and **Harvard explicitly names "I or We"**, which is what licenses the plural | **Unanimous convention, zero studies.** See D.1.c for the honest phrasing |
| `verify.py` round-trip: extract text from the produced PDF and assert on it | **Sovren/Bullhorn recommend exactly this by hand** ("File > Save as Text, then view the result in a text editor"); MIT independently recommends the same, checking for "Missing text" or "Text in the wrong order" | **Strong.** The project automates the test two independent sources recommend manually |
| Page budget as a hard failure | Weakest of the strong set — but Textkernel **408** is Fatal for a truncated over-long document, and one page eliminates the PDF header/footer failure class entirely | **Defensible**, better justified by mechanism than by the "one page" convention |
| `DEAD_OPENINGS` — blocks "I am writing to", "I am excited to apply", "As a passionate", "Re:", "Subject:" | HBR/John Lees: writing yourself in with "I'm applying for X job that I saw in Y place" is "**a waste**"; Glickman: "Start with the punch line"; Cornell: "not 'I'm excited to apply for this position…'"; Harvard/WayUp: avoid "I am writing to express my interest in…" | **Good** — three independent high-trust sources. ⚠️ But see C12: **Princeton's own "Best" example contains "I am excited to apply for"**. The code takes the better-supported side of a genuine disagreement; the comment should say that rather than imply unanimity |
| `DEAD_ADDRESSEES` — blocks "To Whom It May Concern", "Dear Sir or Madam" | UNC explicitly advises against "To Whom It May Concern"; **no source in the brief recommends it**; MIT/Yale/Berkeley all prescribe "Dear Hiring Manager" | **Strong** |
| `addressee_for()` uses a configured fallback rather than scraping a name | MIT: "If you are not sure who to address the letter to, write 'Dear Hiring Manager.'" Resume Genius's own data ranks addressing-by-name the **least** important customisation element | **Strong.** PLAN.md open question 4 was resolved correctly |
| `check_specifics` — a letter must carry figures or ≥2 named technologies | Cornell ("quantify accomplishments"); HBR ("provide evidence of the things that set you apart"); Harvard/WayUp's before/after; Princeton ("Employers can tell when a letter reads like a generic template") | **Good as a proxy for specificity**, though no source states this exact test |
| `check_not_the_advert` — verbatim echo of the posting | Princeton ("they will notice if their name has simply been swapped in"); HBR ("don't rehash"); MIT (complement, don't repeat) | **Good**, correctly advisory |
| `check_answers_the_posting` | Yale ("Use keywords from the position description"); Berkeley ("Connect your experiences… with the desired qualifications"); Cornell ("address what the job postings ask for"); and Cui et al. measured that JD alignment *did* predict callbacks pre-2023 | **Good**, with an expiry note: Cui et al. found that correlation **fell 51%** post-AI |
| Ban on keyword density targets, "match score" percentages, white-text injection, and font/filename claims (stated in the docstring's "deliberately absent" list) | Every one of these is confirmed folklore or fraud by the brief. White text specifically: measured at ~1% prevalence, two production detectors, recruiters on record treating it as disqualifying, and effectiveness collapsing "approaching zero once roughly 80% or more of résumés are injected" | **The most defensible paragraph in either module.** Keep verbatim |

### D.1.b Rules the sources support that the code does NOT implement

Ordered by value. Most are cheap, and several are pure text assertions over the string `verify.py`
already extracts.

**Against the extracted PDF text (add to `verify.py` or a new parse-artefact check):**

| # | Check | Source | Severity |
|---|---|---|---|
| 1 | **No Private Use Area codepoints** (`U+E000–U+F8FF`, `U+F0000+`) in extracted text | Icon fonts and Wingdings bullets map to PUA with no Unicode meaning. MIT's own guides ship `U+F0D7` bullets — this failure is common enough that a career centre commits it | **hard** |
| 2 | **No ligature presentation forms** `U+FB00–U+FB06` | [Chromium 41432982](https://issues.chromium.org/issues/41432982) — "When printing to PDF, text with ligatures are not preserved"; [Mozilla 1810914](https://bugzilla.mozilla.org/show_bug.cgi?id=1810914) explains the subsetting mechanism. `efficient` → `e<U+FB03>cient` silently breaks skill matching | **hard** |
| 3 | **No letter-spacing artefact** — no run of ≥3 consecutive single-character tokens | **Greenhouse's first listed formatting failure**: "A resume with spaces between the letters… the parser won't recognize the separate letters as a single word" | **hard** |
| 4 | **Contact block within the first ~N characters** of the extracted text | Textkernel **311** (Major): "a contact information section was found somewhere other than the top of the resume. Contact information should only be found at the top" | **hard** |
| 5 | **Exactly one email and one phone** in the rendered document | Textkernel **132/133**: "Only one contact email address should be included in a resume" | warn |
| 6 | **Reading order** — the order in which bullets/headings appear in the extracted text matches document order | This is the *direct* assertion that `check_single_column`'s CSS heuristic only approximates. The project already has both strings; comparing their sequence is nearly free | **hard** |
| 7 | **File size ≤ 2.5 MB** | Greenhouse: "Greenhouse Recruiting can't parse resumes larger than 2.5MB" — and uploads are allowed to 100 MB, so the failure is silent | **hard** |
| 8 | **Every URL appears as visible text**, not only as an anchor | pypdf lists hyperlinks among *unclear objectives* for extraction; `extract_text()` does not emit URIs. **The current round-trip passes on anchor text while the URL is absent from the text layer** | **hard** |
| 9 | **Section heading on its own line**, directly above its content | Textkernel **151**: "sections were found with the header not on a separate line above the content" | warn |
| 10 | **One section per type**; no empty section | Textkernel **323** (multiple sections of same type), **324** (section with no text) | warn |

**Content checks (add to `ats.py`):**

| # | Check | Source | Severity |
|---|---|---|---|
| 11 | **Job titles spelled out** — flag `Sr.`, `Jr.`, `Mgr`, `Eng.`, `Dir.`, `VP` without expansion | Greenhouse, verbatim: "Resumes with incomplete job titles. For example, *Sr. Account Exec* instead of *Senior Account Executive*" | warn |
| 12 | **Company names carry a legal suffix** where the profile has one | Greenhouse: "Company names that don't include identifying words such as Inc., Co., LTD, or LLC" | warn |
| 13 | **Every `profile.skills` entry also appears in at least one dated bullet** | Textkernel/Sovren/RChilli/Affinda all derive `LastUsed` and `MonthsExperience` from the work-history entry a skill was found in. A skill only in the Skills block gets nulls and **fails a "Python, 3+ years, used in last 2 years" recruiter filter**. Textkernel **112** flags a standalone skills section | warn — and it belongs in `report.md`'s gap list, which is the project's best existing surface for it |
| 14 | **Acronyms expanded on first use** — `JavaScript (JS)`, `Amazon Web Services (AWS)` | MIT: "Avoid abbreviating relevant keywords as an ATS may not properly consider it." Textkernel documents 250,000 synonyms but **publishes no coverage**, so the parenthetical is free insurance | warn |
| 15 | **No vague quantity words** — `various`, `multiple`, `several`, `numerous`, `etc.`, `a variety of` | MIT, verbatim: "Minimize the use of vague or ill-defined language such as 'various,' 'multiple,' 'several,' or 'etc.' as they might be masking some beneficial keywords you can use." **The most mechanically checkable content rule in the brief, and currently unimplemented** | warn |
| 16 | **Tense** — present *simple* for current roles, past for previous; flag present continuous | Yale: current experiences "use present simple tense (e.g. create) – **do not use present continuous tense** (e.g. creating)"; MIT states the past/present split | warn |
| 17 | **3–5 bullets per entry** | Yale (3–4, and 3–5 on its STEM page — it contradicts itself), Stanford GSB (3–4) | warn, and label the self-contradiction |

**Cover letter (`letter_review.py`):**

| # | Check | Source | Severity |
|---|---|---|---|
| 18 | **Structural AI tells** — `not only X but also Y`, `it's not X, it's Y`, trailing `-ing` participial clauses (`, underscoring…`), em-dash density, rule-of-three parallelism | Wikipedia *Signs of AI writing* (editor consensus, actively maintained, **not peer-reviewed**); **MIT CAPD names the em-dash directly**: recruiters recognise AI through "the use of dashes as punctuation marks" | advisory |
| 19 | **Kobak excess-style-word *density*** rather than a phrase blocklist | Kobak et al., *Science Advances* 2025 — 407 annotated style words, machine-readable at `results/excess_words.csv`. Must be a **density metric over the low-base-rate tail**, never a blocklist over the full list (which contains `across`, `both`, `this`, `were`) | advisory |
| 20 | **Company name present, and no other company name present** | Princeton: "They will notice if their name has simply been swapped in." The wrong-company-name failure is named repeatedly and is trivially checkable given `jd.company` | **blocking** — this is the one letter defect that is unambiguously fatal and currently unchecked |
| 21 | **No street address / DOB / marital status / passport / driving licence** anywhere in the résumé | Textkernel **121–124** ("Do not include this level of personal information in a resume"), **141/142** (never include a street address for a job or school) | warn |

### D.1.c Rules the code implements that the sources do NOT actually support

**This is the list the project asked for, and the one that matters most given its stated position
that most published ATS rules are folklore.**

---

**1. `ats.py` module docstring — factually out of date, and it is the load-bearing claim.**

> "Greenhouse and Lever parse a résumé into fields for recruiter search and do not rank by keyword at
> all"

⚠️ **No longer true.** Greenhouse shipped **Talent Matching** (16 Sep 2025) — five match buckets, with
the recruiter panel showing "matched and similar keywords highlighted" and "Matched terms on this
resume: 4". Lever shipped **Talent Fit** (26 Jun 2025) — LLM ranking of the résumé against the JD.
Both are documented in [A1](#a1) from vendor primary sources.

Also imprecise: "Workday and SuccessFactors run their own matching over what their parser extracted".
Workday does (Candidate Skills Match). **SuccessFactors' screening score is computed from questionnaire
answers only** — its résumé-side matching is Solr relevance in recruiter *search* plus a Skills
Compatibility **count**, and its auto-disqualification never touches résumé text.

**What the comment should honestly say:** *Several ATS now score a résumé against an employer-authored
calibration and present the result to a recruiter — Greenhouse Talent Matching, Lever Talent Fit,
Workday Candidate Skills Match and HiredScore Spotlight, Ashby's criteria percentage, iCIMS Candidate
Ranking. None of them is reproducible from outside, because the calibration is private; and none of
them auto-rejects on résumé content — every documented automatic rejection in every one of these
platforms fires on structured application-question answers. What they all share is the parser, and
that is still the only place a formatting decision has a demonstrable effect.* That is a **stronger**
claim than the current one and it survives the 2025 product releases.

---

**2. `MIN_QUANTIFIED = 0.4` — house convention, correctly labelled, inconsistent with the prompt.**

The code comment is already honest ("Not a hard number anybody publishes"). The research confirms it
completely: **no university career centre, no study, no vendor specifies a fraction.** Every credible
source says "quantify when possible". The only prevalence datum is Cultivated Culture's finding that
**36% of résumés contain zero metrics** — from a self-selected sample the authors say is "not
scientifically gathered or reviewed", and which measures prevalence, not outcomes.

⚠️ **Two inconsistencies to fix:** `TAILOR_RULES` item 11 tells the model "**Roughly half** the bullets
should state one" while the check fires at **0.4**. Neither number is sourced, and they disagree.

**Verdict: defensible house convention. Keep it, advisory, one number.** Honest comment: *No source
specifies a target ratio — every career centre says "quantify where you can" and stops. This threshold
is a house convention chosen so that unquantified bullets read as the exception; it is not a finding,
and a résumé below it is not defective. It is here because it surfaces a selection problem the grounding
gate guarantees is fixable without invention.*

---

**3. `MAX_BULLET_CHARS = 240` — derived arithmetic, not published guidance.**

Every source measures bullets in **lines**, never characters: Yale "no more than 1-2 lines", MIT "1-2
lines", Stanford GSB "no more than 2 lines each", Berkeley "1 or 2 lines only", CMU "no more than two
lines per bullet point". **Unanimous — and not one of them gives a character or word count.**

Independent arithmetic at 10–12pt with 0.5–1.0in margins on US Letter puts one line at roughly 95–115
characters, so two lines is roughly **190–230**. 240 is slightly generous but the right order of
magnitude.

**Verdict: defensible house convention, and the code comment already derives it correctly.** The one
change worth making is to say the *convention* is unanimous while the *number* is local: *Career
centres are unanimous that a bullet should not exceed two lines and unanimous in never stating a
character count. 240 is this template's two-line equivalent at 10.5pt on Letter with 0.5in margins —
re-derive it if the template's type changes.*

---

**4. `STANDARD_HEADINGS` — the safe list is broader than any single parser's.**

Two concrete problems.

- ⚠️ **`"employment history"` fails the one open-source detector that could be inspected.** OpenResume's
  fallback requires a keyword from `experience, education, project, skill` (primary) or `job, course,
  extracurricular, objective, summary, award, honor` (secondary). **"Employment History" contains
  none of them.** It survives only via the primary rule — bold AND all-caps. Same for
  `"core skills"`… which does contain `skill`, so it passes; but **`"certifications and licenses"` is
  three words and fails the ≤2-word fallback outright**.
- ⚠️ **`"projects"` has no equivalent in Textkernel's `sectionType` enum at all.** That enum has
  `ARTICLES, AVAILABILITY, BOOKS, CERTIFICATIONS, CONFERENCE_PAPERS, CONTACT_INFO, EDUCATION, …,
  SKILLS, SPEAKING, SUMMARY, TRAINING, WORK_HISTORY, WORK_STATUS` — **no PROJECTS**. Affinda's enum
  *does* have `Projects`. So a Projects section is well-supported by one major parser and unmapped by
  another. That is worth knowing and is not a reason to drop the section — but it is a reason not to
  put load-bearing content there when an Experience entry would do.

**Verdict: keep the set — it is right that these are conventional headings — but the mitigation is
rendering, not vocabulary.** Bold + ALL-CAPS satisfies OpenResume's *primary* rule and makes the
word-count and keyword fallbacks irrelevant. Honest comment: *These are the conventional headings.
Recognition is not guaranteed by the wording alone — one open-source parser accepts any bold all-caps
line and otherwise requires ≤2 words containing a known keyword, which "Employment History" and
"Certifications and Licenses" fail. Rendering headings bold and uppercase is what makes the set safe,
not the set itself.*

---

**5. `DATE_RANGE` mandates three-letter month abbreviations — and this is the one place the code may
be actively counterproductive.**

The regex is `(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}`, which **requires** the
abbreviated form and **rejects** `January 2023`.

⚠️ **iCIMS says the opposite, explicitly:** "spell out abbreviations for things like months and years.
For example, write '**August 2020**' instead of '**Aug. '20**.'"

⚠️ **And OpenResume's month matcher rejects most three-letter abbreviations.** It tests
`item.text.includes(month) || item.text.includes(month.slice(0, 4))` over full month names —
`slice(0,4)` yields `Janu, Febr, Marc, Apri, May, June, July, Augu, Sept, Octo, Nove, Dece`. So
`Jan`, `Feb`, `Mar`, `Apr`, `Aug`, `Oct`, `Nov`, `Dec` **do not match**, and neither does `Sep`
(it needs `Sept`). Of the twelve abbreviations the regex mandates, **only `May`, `Jun`→`June` and
`Jul`→`July` partially survive**, and `Sep` fails where `Sept` would pass.

CMU's rule — the best-reasoned institutional one — is "**Month Year**… Abbreviating months is
acceptable **when done consistently**", i.e. abbreviation is *tolerated*, not preferred.

**Verdict: not supported, and worth changing.** The regex should **accept both forms and prefer full
month names**, e.g. `(?:January|February|…|December|Jan|Feb|…|Sept|Sep|…)`. Note `Sept` before `Sep`
in the alternation. This is the single highest-value correction in this section because it is a
one-line change that removes a documented parser failure the code currently *requires*.

The rest of `DATE_RANGE` is well-supported: `Present` capital-P is exactly right, and separator
agnosticism is correct.

---

**6. `WEAK_OPENERS` — convention, and the *prompt* takes a side the evidence does not.**

The check itself is well-designed: it blocks **filler** openers (`Responsible for`, `Tasked with`,
`Helped with`, `Worked on`, `Part of a team`) without requiring a verb first. That is compatible with
both camps and nothing in the research contradicts it. The accomplishments-not-duties principle is
universal convention — MIT, Harvard ("Not demonstrating results" is a listed top mistake), Yale,
Berkeley, CMU — with **zero cited evidence at any of them**.

⚠️ **But `TAILOR_RULES` item 10 says "Lead every bullet with the verb for what was done"**, and that is
a live disagreement: **Stanford GSB says "Make the most interesting fact at the beginning of the
bullet; it will entice the reader to read the rest"**, and Yale prints the verb-first and outcome-first
templates side by side with no stated preference. MIT, Penn, Columbia and Cornell say verb-first.
**Nobody has data either way.**

**Verdict: keep the check (it only blocks filler); soften the prompt.** Honest comment on
`WEAK_OPENERS`: *Every career office says a bullet should show an accomplishment rather than a duty,
and none of them cites evidence for it. This blocks the openers that describe a job advert rather
than a person. It deliberately does not require a verb first: whether to lead with the verb or with
the outcome is a live disagreement — Stanford GSB says lead with the most interesting fact, MIT and
Penn say lead with the verb, and nobody has tested it.*

---

**7. `FIRST_PERSON` — unanimous convention, no study.**

MIT (three pages), Yale ("Do not use pronouns"), Harvard (explicitly "I or We"), Cornell. **This is
the most unanimous item in the entire brief** and Harvard is what licenses including `we/our/us`.
**And there is not a single study.**

**Verdict: keep, evidenced as convention.** The current comment — "one of the few pieces of guidance
every university career office states the same way" — is already accurate and honest. It should just
not be read as implying an effect was measured. Add: *No study has tested it; it is a genre convention
that every career office states identically.*

---

**8. `letter_review.py` docstring — all three of its stated premises overstate the evidence.**

> "Recruiter surveys through 2025–26 agree on three things with unusual consistency"

⚠️ **Premise 1 — "A letter is read, often before the résumé".** The 87%-read figure is **ResumeGo,
fielded Jul 2019 – Jan 2020, pre-ChatGPT, from a company that sells cover letters**. The
"45% read it before the résumé" figure is **Resume Genius, Pollfish, n=625, fielded 2023, relabelled
"2026"**, from **Sonaga Tech**, which also owns CV Genius — whose own 2024 wave puts the requirement
rate at **49% against Resume Genius's 60%**. Meanwhile **NACE, the highest-trust employer survey,
does not measure cover letters at all** (one mention in 2026, zero in 2025), and *Business Insider*
(1 Jun 2026) has named executives at McKinsey, BCG, Cisco, Zapier and LinkedIn dropping them — several
**before** generative AI. In a 22-board sample of live Greenhouse forms, the cover letter was
**required exactly once and absent entirely at four employers**.
**"Unusual consistency" is not what the record shows.** What the record shows is: vendor-funded
surveys say yes, the non-conflicted survey does not ask, and employers are visibly dropping it.

⚠️ **Premise 2 — "The opening sentence is where it is lost".** This one is **well-supported** — HBR
(Lees, Glickman), Cornell and Harvard/WayUp all name it independently. Keep it. Only caveat: Princeton
prints "I am excited to apply for" in its own *Best* example, so it is a strong majority, not
unanimity.

⚠️ **Premise 3 — "Readers report recognising AI-written applications, and report reacting badly."**
The *reporting* is real (TopResume 19.6% would reject, 33.5% claim sub-20-second detection; CV Genius
80% negative). **But the detection literature says they cannot.** *PNAS* 120(11) 2023, **n = 4,600
participants across six experiments**, found accuracy of **50–52%** — chance — including **51.6% in
the professional self-presentation condition with incentives**; an automated classifier managed
58.8%. Milička et al. 2025 found **55.4%** on the *easier* side-by-side task, and that participants
"made the most errors precisely when they were most certain". **No study has ever measured recruiters'
accuracy on real application materials.**

Note also that the sentence "The tells they name are… a small, stable vocabulary" implies surveys
publish word lists. ⚠️ **No survey found publishes one.** The concrete lists come from Kobak
(biomedical abstracts), Wikipedia's AI-cleanup page (not peer-reviewed, not policy) and MIT CAPD
(which names the em-dash).

**Verdict: keep the module — the checks are good writing hygiene — but re-found premise 3.** Honest
version: *Readers report recognising AI-written applications and report reacting badly. What they
cannot actually do is detect it: the only controlled measurements put humans at 50–52% — chance — on
exactly this task, and most confident when most wrong. So these checks are not here because a reader
will catch the model. They are here because the phrases are empty, unverifiable, and in every other
letter in the pile, which makes them worth cutting for a reader who has never thought about AI at
all.*

---

**9. `AI_TELLS` — the list conflates two different things, and its sourcing claim is wrong.**

The comment says these are "repeatedly named in 2025-26 hiring surveys". ⚠️ **No survey publishes a
word list.** Checking the entries against the one empirical corpus (Kobak, 15M abstracts):

- **Genuinely measured LLM-excess vocabulary:** `delve` (47.8× raw), `tapestry` (5.5×), and — present
  only inside longer phrases — `leveraging` (3.9×), `seamlessly` (3.2×). `testament to` maps to the
  measured *significance-inflation* pattern.
- ⚠️ **Business clichés, not AI tells — they predate LLMs by decades:** `synergy`, `synergies`,
  `game-changer`, `hit the ground running`, `think outside the box`, `wear many hats`,
  `a proven track record of success`, `cutting-edge solutions`, `wealth of experience`. Worth cutting
  from a letter, but for a completely different reason, and citing "AI tells" for them is not
  supportable.
- ⚠️ **Actively contradicted by the data:** the register the list is reaching for includes words the
  Kobak corpus shows **no excess** for — `thrilled` **0.00×**, `passionate` 0.80×, `excited` 1.04×,
  `proven` 0.95×, `resonate` 1.15×. They are cover-letter register, not LLM register. `resonates
  deeply` is in the list on no evidence.
- **Missing, and empirically the strongest signals:** `underscores` (13.8×), `showcasing` (13.8×),
  `meticulous(ly)` (10.5×), `intricate` (7.4×), `garnered` (6.1×), `realm` (5.0×), `pivotal` (3.1×),
  `multifaceted`, `nuanced`, `groundbreaking`, `unparalleled`, `transformative`, `invaluable`,
  `commendable`, `noteworthy`.

**Verdict: keep the mechanism, split the list, fix the comment.** Two tuples with two different
justifications — `LLM_EXCESS` (cite Kobak; the high-ratio, low-base-rate tail) and `BUSINESS_CLICHE`
(cite nothing but candour: they are empty and universal). ⚠️ **And do not expand `LLM_EXCESS` to the
full 407-word style list** — it contains `across`, `both`, `this`, `were`, `while`, `including`,
`research`, `using`. The code's existing instinct here is right and should be stated as the reason:
*Kept short and specific on purpose: the published excess-vocabulary list is 407 words and most of
them are ordinary English, so a long list would catch normal prose.*

---

**10. `FLATTERY` — supported in substance, mis-sourced in the comment.**

The substance is right: **HBR says "don't go overboard with the flattery"**, Cornell says take the
employer's perspective rather than your own, and Wikipedia's AI-writing catalogue names exactly this
*promotional register* (`renowned`, `vibrant`, `boasts a`, `diverse array`) as a machine tell — so
`renowned`, `esteemed` and `prestigious` sit in **both** categories. But ⚠️ **no source measures that
flattery costs a candidate anything**, and the comment's "every other letter in the pile contains it"
is an assertion nobody has counted.

**Verdict: keep, advisory, and drop the unmeasured prevalence claim.** Honest comment: *Praise aimed
at the employer is unverifiable and spends words on the reader's own organisation. HBR's advice is
"don't go overboard with the flattery"; nobody has measured what it costs. Several of these words —
renowned, esteemed, prestigious — are separately catalogued as promotional register typical of
machine-written text.*

---

**11. `MIN_WORDS = 150` / `MAX_WORDS = 420` — the floor is unsupported; the band is wider than the
consensus.**

The consensus is tight and independently corroborated: **Princeton 250–400**, **Anthropic's own
required application field 200–400**, **Harvard/WayUp 250–400**, Resume Genius ~400. **HBR goes
further: "even shorter is better… brief enough that someone can read it at a glance."** And the
timing data (84% of readers under a minute) puts 400 at the ceiling of what is read.

⚠️ **Nothing supports a 150-word floor.** No source states a minimum at all. The code's rationale
("Under about 180 words a letter has not said anything a résumé did not" — note the comment says 180
while the constant is 150) is a reasonable intuition, unsourced, and internally inconsistent.

**Verdict: defensible as a *check* band — you only want to flag clear problems — but it should not be
presented as the target.** Two numbers, honestly distinguished: the **target** the prompt asks for
(250–400, cite Princeton and Anthropic) and the **band** the check tolerates. Fix the 150/180
mismatch. Honest comment: *Princeton says 250–400 words and Anthropic's own application form says
200–400; HBR says shorter still. No source states a minimum, so the lower bound here is a house
floor for "has this said anything", not a finding.*

---

**12. `MIN_PARAGRAPHS = 3` / `MAX_PARAGRAPHS = 5` — the ceiling is one above the best source.**

**Yale is the most specific source found and says "three to four paragraphs"**, with intro and close
at 1–3 sentences and body paragraphs at 3–5 sentences. UNC says 3–5. MIT's structure (1 intro + 2–3
body + 1 close) yields 4–5. So 3–5 is the union of the sources rather than the consensus; **3–4 is
the consensus**.

**Verdict: mild house convention, keep or tighten to 4.** `cover.py`'s `paragraph_budget()`
(`words/75`, floor 3, ceiling 5) should have its ceiling moved to 4 to match Yale, which also brings
it in line with a 250–400 word target. Yale's sentence-count rule is additionally checkable and
currently unimplemented.

---

**13. `check_i_openings` threshold of 0.75 — pure house heuristic.**

⚠️ **No source anywhere states a limit on paragraphs beginning "I".** The closest adjacent evidence is
Wikipedia's catalogue of structural monotony as a machine tell, which is not the same claim.
**Correctly advisory.** Honest comment: *Nobody publishes a threshold for this; it is a house
heuristic for a rhythm that reads as a list of assertions.* Keep — it costs nothing and the check is
advisory — but do not let it sit in a list implying the same footing as Textkernel's Fatal codes.

---

**14. `check_single_column` bans `display: flex` — more conservative than the evidence, in the safe
direction.**

⚠️ Worth noting because **a flex row is the CSS equivalent of the right-tab-stop construct that CMU
explicitly recommends** for `Employer ……… Dates`, and inspecting Yale's and Penn's own DOCX templates
confirms they use tab stops rather than tables for exactly this. No vendor documents flex at all —
CSS is invisible to the PDF; only the resulting glyph coordinates matter.

**Verdict: defensible, and the project's own measurement is the right justification.** The check's
comment already says "Measured, not assumed", which is the correct standing. The refinement worth
noting: **the direct check is rule #6 in D.1.b — assert extracted order matches document order.** That
tests the thing that actually matters, and would let a safe single-line flex row through while still
catching a genuine two-column layout.

---

**15. `check_answers_the_posting` is blocking, and can fail honestly.**

Not unsupported — the substance is well-backed. But note the interaction: it is `kind="blocking"`
(the default) and fires when **none** of the posting's terms appear. Given the grounding gate, a
record that genuinely cannot answer any of a posting's requirements will produce a letter that
legitimately contains none of them, and the loop will burn iterations on something no rewrite can
fix. The check's own `fix` text acknowledges this ("that is the report's gap list and not something
to write around") — which suggests it should be advisory, with the gap list as the real output.

---

## D.2 The prioritised rule list

Severity convention, matching the code: **hard** = fails the build (`kind="parsing"` /
`kind="blocking"`); **warn** = reported and fed to the rewrite loop, never fails a build.

<a id="d-tier-0"></a>
### Tier 0 — hard failures: the document is not machine-readable

| Rule | Check | Why | Source |
|---|---|---|---|
| T0.1 | Every heading, bullet, the name, email and phone survive PDF→text extraction | If it is not in the text layer, no system sees it | Sovren "Save as Text" self-test; MIT; *implemented* |
| T0.2 | Extracted reading order == document order | A two-column layout reorders silently; this is the direct test | Textkernel 433 (Fatal); W3C PDF3; *missing* |
| T0.3 | No `U+E000–U+F8FF` / `U+F0000+` (PUA) in extracted text | Icon fonts and Wingdings bullets extract as meaningless codepoints | Mechanism; MIT's own guides ship `U+F0D7`; *missing* |
| T0.4 | No `U+FB00–U+FB06` ligature presentation forms | `efficient` → `e<U+FB03>cient` breaks matching | Chromium 41432982; Mozilla 1810914; *missing* |
| T0.5 | No run of ≥3 consecutive single-character tokens | Letter-spacing destroys word boundaries | **Greenhouse's first listed failure**; *missing* |
| T0.6 | Contact block within the first ~N chars of extracted text | Contact info must be at the top | Textkernel 311; *partially — presence checked, position not* |
| T0.7 | Email present | The parsed record has no key without it | Textkernel 441 (Fatal); *implemented* |
| T0.8 | At least one work-history section, with a recognised heading | Parser files unrecognised sections under "other" | Textkernel 412/413 (Fatal); *implemented* |
| T0.9 | Every entry has a parseable `Month YYYY – Month YYYY \| Present` range, on one line | Undated jobs are a Fatal quality code | Textkernel 419, 418, 224/225; *implemented, but see D.1.c #5* |
| T0.10 | Single column; no `<table>`, float, `column-count`, `<img>`, `<svg>` | The best-evidenced formatting rule | Greenhouse; Textkernel 433; Workday; *implemented* |
| T0.11 | Text layer only — no rasterised text, no text-as-outlines | Embedded images are not OCR'd on the text-layer path | Textkernel `ovIsImage`; Greenhouse; SmartRecruiters `UNPARSABLE_RESUME`; *implicitly covered by T0.1* |
| T0.12 | File ≤ 2.5 MB | Greenhouse silently fails to parse above it while accepting the upload | Greenhouse; *missing* |
| T0.13 | Every URL present as visible text | `extract_text()` does not emit `/URI` annotations | pypdf; *missing — and the current round-trip passes on anchor text* |
| T0.14 | Page count ≤ budget | Truncation is Fatal; one page removes the header/footer class | Textkernel 408; *implemented* |
| T0.15 | Every claim traces to `profile.yaml` or the corpus | Fabrication | MIT ("You will still need to be able to account for everything"); *implemented in `ground.py`* |
| T0.16 | No hidden text: no near-background colour, no font < 6pt, nothing outside the page box | Detected in production; disqualifying; collapses to zero effectiveness at scale | arXiv:2605.28999; recruiters on record; *structurally prevented by `ground.py`, not asserted* |

### Tier 1 — warnings: the document is machine-readable but weaker

| Rule | Check | Source | Status |
|---|---|---|---|
| T1.1 | Every bullet ≤ 2 rendered lines (~240 chars for this template) | Yale, MIT, Stanford GSB, Berkeley, CMU — unanimous on *lines*, silent on characters | *implemented*; relabel as derived |
| T1.2 | ≥ 40% of bullets contain a quantity | **No source specifies a ratio.** House convention | *implemented*; align prompt to the same number |
| T1.3 | No bullet opens on `Responsible for` / `Worked on` / `Helped with` / `Part of a team` | Universal convention, no evidence | *implemented* |
| T1.4 | No first-person pronouns incl. `we/our/us` | MIT, Yale, Harvard ("I or We"), Cornell — unanimous, no study | *implemented* |
| T1.5 | 3–5 bullets per entry | Yale (3–4, and 3–5 elsewhere — self-contradictory), Stanford GSB (3–4) | *missing* |
| T1.6 | Past tense for past roles; present **simple** for current; flag present continuous | Yale (the most precise tense rule found), MIT | *missing* |
| T1.7 | No vague quantity words: `various`, `multiple`, `several`, `numerous`, `etc.` | **MIT, verbatim** | *missing — highest-value unimplemented content check* |
| T1.8 | Acronyms expanded on first use | MIT ("avoid abbreviating relevant keywords"); Textkernel publishes no synonym coverage | *missing* |
| T1.9 | Job titles spelled out (`Senior`, not `Sr.`) | **Greenhouse, verbatim** | *missing* |
| T1.10 | Company names carry `Inc.` / `Ltd` / `LLC` where the record has one | **Greenhouse, verbatim** | *missing* |
| T1.11 | Every declared skill also appears in ≥1 dated bullet | Textkernel 112 + the `LastUsed`/`MonthsExperience` mechanism across four parsers | *missing — belongs in the gap list* |
| T1.12 | Exactly one email, one phone; phone and location present | Textkernel 132/133, 211/212/213 | *partially implemented* |
| T1.13 | No street address, DOB, marital status, passport, licence number | Textkernel 121–124, 141/142 | *missing* |
| T1.14 | Heading on its own line; one section per type; no empty section | Textkernel 151, 323, 324 | *missing* |
| T1.15 | Bullets use `U+2022` only | Mechanism (PUA/ToUnicode); MIT and Stanford both violate this in their own guides | *not applicable — template-controlled, but worth asserting* |

<a id="d-cover-letter"></a>
### Cover letter rules

| Rule | Check | Severity | Source | Status |
|---|---|---|---|---|
| CL.1 | Opening sentence does not match `/^(I am writing\|I'?m writing\|I am (excited\|thrilled\|delighted\|pleased\|eager) to (apply\|submit\|express)\|I would like to apply\|Please accept\|As a (passionate\|dedicated\|highly motivated\|results.driven\|detail.oriented)\|Re\s*:\|Subject\s*:\|Application for)/i` | blocking | HBR (Lees, Glickman), Cornell, Harvard/WayUp — ⚠️ Princeton dissents | *implemented* |
| CL.2 | Addressee is not `To Whom It May Concern` / `Dear Sir or Madam` | blocking | UNC explicitly; nothing recommends it | *implemented* |
| CL.3 | The company's name appears; **no other company name appears** | blocking | Princeton: "They will notice if their name has simply been swapped in" | ***missing — the most valuable unimplemented letter check*** |
| CL.4 | Word count in band; target 250–400 | blocking | Princeton, Anthropic's own form, Harvard/WayUp; HBR says shorter | *implemented at 150–420; retarget* |
| CL.5 | 3–4 paragraphs | blocking | Yale ("three to four paragraphs") | *implemented at 3–5* |
| CL.6 | Intro/close 1–3 sentences; body paragraphs 3–5 sentences | warn | Yale, the most specific structural source found | *missing* |
| CL.7 | Carries figures or ≥2 named technologies | blocking | Cornell, HBR, Harvard/WayUp — proxy, not a stated test | *implemented* |
| CL.8 | Answers the posting | **advisory** (see D.1.c #15) | Yale, Berkeley, Cornell; Cui et al. measured the effect **and its 51% decay** | *implemented as blocking* |
| CL.9 | Does not restate the advert verbatim | advisory | Princeton, HBR, MIT | *implemented* |
| CL.10 | LLM-excess vocabulary **density**, from Kobak's high-ratio tail | advisory | Kobak et al., *Science Advances* 2025 + released CSV | *partially — list needs splitting and correcting* |
| CL.11 | Business clichés (`synergy`, `game-changer`, `hit the ground running`, `wear many hats`) | advisory | No source; candour — they are empty and universal | *implemented, mislabelled as AI tells* |
| CL.12 | Structural tells: `not only X but also Y`, `it's not X, it's Y`, trailing `-ing` participles, em-dash density, rule-of-three | advisory | Wikipedia *Signs of AI writing* (not peer-reviewed); **MIT CAPD names the em-dash** | *missing* |
| CL.13 | No flattery aimed at the employer | advisory | HBR ("don't go overboard"); several terms double as promotional register | *implemented* |
| CL.14 | < 75% of paragraphs open on "I" | advisory | **No source** — house heuristic | *implemented* |
| CL.15 | Round-trip: addressee and every paragraph survive extraction | blocking | Textkernel mines cover letters for skills (`FindSkillsInCoverLetter`, default on); and letters are as often pasted into a textarea | *implemented* |
| CL.16 | Every claim traces to the record | blocking | MIT: AI "can make statements about your capabilities with no tangible evidence" | *implemented in `ground.py`* |

## D.3 Rules to keep NOT implementing

`ats.py`'s "deliberately absent" paragraph is the most defensible in either module. The research
supports every item and adds a few:

- **Keyword density targets.** ⚠️ No vendor documents a density metric anywhere. iCIMS documents
  ranking by keyword *relevance*; "density" is imported wholesale from SEO. **folklore.**
- **"ATS match score" percentages as a prediction.** No independent evidence any third-party score
  correlates with any outcome; no peer review, no audit, no vendor correlation study. And the real
  platform scores are computed against a **private employer calibration** — Greenhouse recommends
  recruiters pick 4–6 skills — which no external tool can see.
- **White text / hidden keywords / prompt injection.** Fraud; ~1% measured prevalence; two production
  detectors; recruiters on record; and effectiveness "approaching zero once roughly 80% or more of
  résumés are injected."
- **Résumé length rules stated as absolutes.** The only study that manipulated length is confounded
  (two-pagers had twice the words), reports no statistics, and is vendor-funded; the universities are
  unanimous the other way and cite nothing.
- **Font or filename affecting ranking.** ⚠️ **Serif vs sans is not a parsing question** — any embedded
  font with a correct ToUnicode CMap extracts identically, and the career centres split.
- **New: en-dash vs hyphen in dates.** ⚠️ No vendor documentation exists; SEO sources contradict each
  other; the one inspectable parser ignores the separator entirely. The current regex's agnosticism
  is correct.
- **New: skills-section separator style** (comma vs bullet vs one-per-line). ⚠️ Zero evidence, primary
  or secondary.
- **New: "avoid ampersands and slashes in job titles."** ⚠️ SEO blogs only.
- **New: "tagged PDF fixes ATS parsing."** ⚠️ Tagging demonstrably fixes *screen-reader* reading order
  (W3C PDF3), but **no evidence any résumé parser reads the PDF structure tree** — pdfminer, pypdf and
  pdf.js all use coordinate heuristics. Tag for accessibility; do not claim a parsing benefit.
- **New: an AI-detector score.** ⚠️ Detectors run at ~58.8% on this task and are **documented as biased
  against non-native English writers** (Liang et al., *Patterns* 2023). Computing one would import a
  known disparate-impact instrument into the tool.

<a id="d-appendix"></a>
## D appendix — Textkernel Resume Quality codes, verbatim

The most useful single artefact found: a parser vendor publishing its own machine-checkable rule list,
severity-banded. Source:
https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/parser-output/

**Fatal (400–499)** — 408 document too long and truncated · 411 time limit exceeded · 412 no sections
found · 413 no WORK HISTORY section · 414 no EDUCATION section · 415 work history had to be calculated
as a section · 416 education had to be calculated · 417 CV-style document with nonstandard headers,
only the first work-history section parsed · **418 date ranges written vertically on multiple lines** ·
**419 employment section provided no dates** · **433 columnar data ("a HUGE MISTAKE")** · **441 neither
email nor phone found**.

**Major (300–399)** — **300 the document was PDF** · 301 the document was Apple Pages · 302 candidate
first/last name not found · 303 sections longer than work history and education combined · **311
contact information not at the top** · 312 oversized publications section · 323 multiple sections of
the same type · 324 section with no text · **325 section with no header** · 331 more than 30 jobs.

**Data issues (200–299)** — 211 no email · 212 no phone · 213 no street address · 221 job without
title · 222 job without company · 223 duplicate current employer · **224 job without start date** ·
**225 job without end date** · 226 no job within the past year of the document's last-modified date ·
227 very old work history · 231 degree without a name · 232 degree without a school · 233 dates in the
education section.

**Suggested (100–199)** — 111 references section present · **112 separate skills section present
("Skills should be included in the context of work history and education descriptions")** · 113
publications section · 121–124 driving licence / passport / marital status / date of birth · 131–133
multiple addresses / emails / phone numbers · 141/142 street address for an employer or school ·
**151 section header not on a separate line above its content** · 161 high school listed alongside
higher education.

⚠️ **Read three of these as vendor opinion rather than parsing capability:** 233 ("Do not put dates in
your education section"), 227 ("No one cares"), and 112's normative half. They are career advice
leaking into a technical API. The *structural* halves — a section exists, a header is on its own line,
dates are present and horizontal — are the parsing claims.

---

# Sources

Grouped by kind. ⚠️ marks a source that is cited in this brief **as an example of a weak or
unverifiable claim**, not as support for one.

## ATS vendor documentation (primary)

**Greenhouse**
- Unsuccessful resume parse — https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse
- Why didn't the candidate's resume import correctly? — https://support.greenhouse.io/hc/en-us/articles/200721684-Why-didn-t-the-candidate-s-resume-import-correctly
- Supported formats for resumes, cover letters and other uploads — https://support.greenhouse.io/hc/en-us/articles/360052218132-Supported-formats-for-resumes-cover-letters-and-other-candidate-uploads
- Resume parsing with non-English languages — https://support.greenhouse.io/hc/en-us/articles/205019689-Resume-parsing-with-non-English-languages
- MyGreenhouse FAQ for Candidates ("Upload a PDF for best results") — https://support.greenhouse.io/hc/en-us/articles/43418495049499-MyGreenhouse-FAQ-for-Candidates
- Application rules overview — https://support.greenhouse.io/hc/en-us/articles/203105595-Application-rules-overview
- Auto-reject — https://support.greenhouse.io/hc/en-us/articles/360000653472-Auto-reject
- Talent Matching — https://support.greenhouse.io/hc/en-us/articles/41396009937307-Talent-Matching
- Talent Matching FAQ — https://support.greenhouse.io/hc/en-us/articles/41131886674075-Talent-Matching-FAQ
- Talent Matching Data Processing FAQ — https://support.greenhouse.io/hc/en-us/articles/44504950876315-Talent-Matching-Data-Processing-FAQ
- Real Talent overview — https://support.greenhouse.io/hc/en-us/articles/45127324799003-Real-Talent-overview
- Review applications in bulk — https://support.greenhouse.io/hc/en-us/articles/115003558531-Review-applications-in-bulk
- Search resumes for keywords — https://support.greenhouse.io/hc/en-us/articles/115004600186-Search-resumes-for-keywords
- Greenhouse AI principles — https://www.greenhouse.com/ai-principles
- Greenhouse AI recruiting — https://www.greenhouse.com/ai-recruiting
- Real Talent launch press release, 16 Sep 2025 — https://www.prnewswire.com/news-releases/greenhouse-launches-new-tools-to-tame-chaotic-hiring-funnels-302556958.html
- Hiring pipeline overload (applications per job) — https://www.greenhouse.com/blog/hiring-pipeline-overload

**Lever**
- Public API documentation (`parsedData`, `positions`, `school`) — https://hire.lever.co/developer/documentation
- Lever's AI innovations are here (Talent Fit, 26 Jun 2025) — https://www.lever.co/blog/levers-ai-innovations-are-here
- AI features — https://www.lever.co/ai-features
- AI-powered screening — https://www.lever.co/solutions/ai-powered-screening
- Talent Fit AI Brief ⚠️ *(help centre unfetchable; quotes via search index)* — https://help.lever.co/hc/en-us/articles/28081525270685-Talent-Fit-AI-Brief

**Workday / HiredScore**
- HCM Administrator Guide, 3,263pp PDF (resume parsing, Candidate Skills Match, Candidate Rating & Ranking, Automatic Stage Routing) — https://doc.workday.com/content/dam/fmdita-outputs/pdfs/admin-guide/en-us/Admin-Guide-Human-Capital-Management.pdf
- HiredScore grades explained (A/B/C/D) — https://doc.workday.com/hiredscore/en-us/workday-hiredscore/recruiter-productivity-/concept--hiredscore-grades.html
- Responsible AI and bias mitigation (Secretariat Spotlight audit, Mar 2026) — https://www.workday.com/en-us/legal/responsible-ai-and-bias-mitigation.html
- Subprocessor list — https://www.workday.com/content/dam/web/en-us/documents/legal/workday-subprocessors.pdf
- HiredScore acquisition announcement, 26 Feb 2024 — https://newsroom.workday.com/2024-02-26-Workday-Announces-Intent-to-Acquire-HiredScore
- HiredScore AI for Recruiting datasheet — https://www.workday.com/content/dam/web/za/documents/datasheets/hiredscore-ai-recruiting.pdf
- How Workday builds AI ("Our AI does not make employment decisions, automatically reject candidates…") — https://blog.workday.com/en-us/how-workday-builds-ai-puts-people-first.html
- HiredScore's archived NYC LL144 position — https://web.archive.org/web/20241001144018/https://www.hiredscore.com/nyc-legal-law

**Ashby**
- AI-Assisted Application Review (the sortable "AI job criteria met percentage") — https://docs.ashbyhq.com/ai-assisted-application-review
- Auto-Reject applications — https://docs.ashbyhq.com/auto-reject-applications
- Global application questions and global auto-reject rules — https://docs.ashbyhq.com/global-application-questions-and-global-auto-reject-rules
- Candidate profile (resume parsing, size limits) — https://docs.ashbyhq.com/candidate-profile
- Ashby AI page ("never 'ranks' or gives numerical ratings") ⚠️ *contradicts the docs above* — https://www.ashbyhq.com/ai
- AI-Assisted Application Review in practice — https://www.ashbyhq.com/blog/recruiting/ai-assisted-application-review-in-practice
- `candidate.uploadResume` API — https://developers.ashbyhq.com/reference/candidateuploadresume
- Warden AI trust dashboard, "Ashby — AI Interviewer" *(a product with no page on ashbyhq.com)* — https://trust.warden-ai.com/ashby

**iCIMS**
- Sub-processor list (**Daxtra** for resume parsing) — https://www.icims.com/subprocessors/
- How applicant tracking systems work (white text; PDF vs Word; keyword ranking) — https://www.icims.com/en-gb/blog/how-applicant-tracking-systems-work/
- Beyond the hype: fair and compliant AI hiring (BABL AI audit of "Candidate Ranking") — https://www.icims.com/blog/beyond-the-hype-the-essential-need-for-fair-and-compliant-ai-hiring/
- iCIMS Copilot — https://www.icims.com/copilot/
- Larimer County iCIMS screening training deck *(customer material reproducing the UI)* — https://www.larimer.org/sites/default/files/screeningcandidates.icims_.pdf

**Oracle Taleo**
- Implementing Recruiting 22D ("Resume parsing is delivered using a third party partner service… as-is") — https://docs.oracle.com/en/cloud/saas/taleo-enterprise/22d/otrcg/implementing-recruiting.pdf
- Using Recruiting 22D (ACE prescreening, disqualification questions, Result %) — https://docs.oracle.com/en/cloud/saas/taleo-enterprise/22d/otfru/using-recruiting.pdf
- Oracle Recruiting Cloud, conditional questions — https://docs.oracle.com/en/cloud/saas/talent-management/faimh/ask-a-question-to-a-candidate-based-on-an-answer.html

**SAP SuccessFactors**
- Setting Up and Maintaining Recruiting, release 2605 PDF ("uses the third-party software Textkernel to parse resume data") — https://help.sap.com/doc/ffb88b2705684ab0be068897766d72de/2605/en-US/SF_RCM_Admin.pdf
- KBA 2081576 (Textkernel; the 15 parsed fields) — https://userapps.support.sap.com/sap/support/knowledge/en/2081576
- Resume parsing setup ("isn't always 100% accurate. This is a known limitation") — https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/282b8727ec494684b2ef8e26a75788b6.html
- Pre-screening questions — https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/bc8e6ee9269d4d6b878a047fd8b41119.html
- Required Score and disqualifiers — https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/7fb8cc95f55e492d94376e39d229e2f6.html
- Auto-Disqualified status — https://help.sap.com/docs/SAP_SUCCESSFACTORS_RECRUITING/8477193265ea4172a1dda118505ca631/9d005b9f377f4927815bd6fe670fa3ba.html
- SAP AI ethics — https://www.sap.com/products/artificial-intelligence/ai-ethics.html

**SmartRecruiters**
- Resume parse API (`UNPARSABLE_RESUME`) — https://developers.smartrecruiters.com/reference/candidatesresumeparse

## Résumé parser vendors (primary)

**Textkernel / Sovren / Tx Platform**
- **Resume Quality codes — the full severity-banded rule table** — https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/parser-output/
- Parser output, `sectionType` enum and skills provenance — https://developer.textkernel.com/tx-platform/v9/resume-parser/overview/parser-output/
- Getting started ("don't use PDF documents"; "PDF is a broken standard") — https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/getting-started/
- Technical specifications — https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/specs/
- FAQ (DocumentLastModified and the interpretation of "current") — https://developer.textkernel.com/tx-platform/v10/faq/
- Supported file formats (70+ formats; OCR add-on) — https://developer.textkernel.com/TKPlatform/master/file-formats/
- Parser documentation index — https://developer.textkernel.com/Parser/master/
- Codes reference (professions → O*NET and ISCO 2008) — https://developer.textkernel.com/Parser/master/data_model/codes-reference/
- Improving extraction from column resumes (15% prevalence; 62%→90%) — https://www.textkernel.com/learn-support/blog/improving-extraction-from-column-resumes/
- Parser product page — https://www.textkernel.com/products-solutions/parser/
- Sovren/Bullhorn KB — the "File > Save as Text" self-test — https://kb.bullhorn.com/invenias/Content/Invenias/Topics/parsingTechnicalSpecificationsAndSovrenFAQ.htm
- Bullhorn: Textkernel resume parsing — https://kb.bullhorn.com/bh4sf/Content/BH4SF/LP/resumeParsing.htm

**Others**
- Affinda resume parser (two-column CVs; `isOcrd`/`ocrConfidence`; Lightcast default) — https://www.affinda.com/resume-parser/
- Daxtra CV formatting guidance (headers, tables, text boxes, fonts) — https://portal.wearemercury.com/knowledgebase/article/KA-01555/en-us
- OpenResume parser (inspectable heading, date, name and contact heuristics) — https://www.open-resume.com/resume-parser

## PDF and document-format mechanics (primary)

- pdfminer.six — "a PDF file does not contain anything that resembles paragraphs, sentences or even words" — https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html
- pypdf text extraction — tables are "absolutely positioned text"; hyperlinks an unclear objective — https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- Chromium issue 41432982 — ligatures not preserved when printing to PDF — https://issues.chromium.org/issues/41432982
- Mozilla bug 1810914 — ToUnicode/ligature subsetting mechanism — https://bugzilla.mozilla.org/show_bug.cgi?id=1810914
- Prince XML forum — ToUnicode CMap overlap breaking extraction — https://www.princexml.com/forum/topic/4959/some-exported-pdfs-have-issues-with-tounicode-cmap
- CTAN `cmap` package — makes pdfLaTeX output searchable and copyable — https://ctan.org/pkg/cmap
- W3C WCAG 2.1 Technique PDF3 — multi-column reading order — https://www.w3.org/WAI/WCAG21/Techniques/pdf/PDF3
- python-docx: headers/footers as separate parts — https://python-docx.readthedocs.io/en/latest/dev/analysis/features/header.html
- python-docx: hyperlink URL in `document.xml.rels` — https://python-docx.readthedocs.io/en/latest/dev/analysis/features/text/hyperlink.html
- python-docx: table traversal is row-major — https://python-docx.readthedocs.io/en/latest/api/table.html
- python-docx: list bullets come from numbering definitions, not text — https://python-docx.readthedocs.io/en/latest/dev/analysis/features/numbering.html
- python-docx issue 1123 — `document.paragraphs` excludes table cells — https://github.com/python-openxml/python-docx/issues/1123
- python-docx issue 413 — text boxes unreachable — https://github.com/python-openxml/python-docx/issues/413

## Skills taxonomies (primary)

- ESCO skills classification — https://esco.ec.europa.eu/en/classification/skill_main
- European Commission legal notice (the CC BY 4.0 default policy ESCO's licence is inferred from) — https://commission.europa.eu/legal-notice_en
- O*NET database (CC BY 4.0, **not** public domain) — https://www.onetcenter.org/database.html
- O*NET Technology Skills file (32,681 rows) — https://www.onetcenter.org/dictionary/30.0/excel/technology_skills.html
- Lightcast Open Skills — https://lightcast.io/open-skills
- Lightcast Open Skills FAQ ("API access is now available on a contract basis") — https://lightcast.io/open-skills/faqs
- Lightcast Open Skills taxonomy blog — https://lightcast.io/resources/blog/open-skills-taxonomy
- SkillNER (MIT-licensed; bundles the old EMSI DB) — https://github.com/AnasAito/SkillNER
- ESCO skill extractor — https://github.com/KonstantinosPetrakis/esco-skill-extractor

## Academic and peer-reviewed

- Kobak, González-Márquez, Horvát & Lause, "Delving into LLM-assisted writing in biomedical publications through excess vocabulary", *Science Advances* 11(27):eadt3813 (2025) — https://www.science.org/doi/10.1126/sciadv.adt3813 · preprint https://arxiv.org/abs/2406.07016 · **data and the 900-word annotated list** https://github.com/berenslab/chatgpt-excess-words
- Jakesch, Hancock & Naaman, "Human heuristics for AI-generated language are flawed", *PNAS* 120(11) (2023) — https://arxiv.org/abs/2206.07271
- Milička et al., human detection of GPT-4o text (2025) — https://arxiv.org/abs/2505.01877
- Liang et al., "The widespread adoption of large language model-assisted writing across society", *Patterns* — https://arxiv.org/abs/2502.09747
- Kessler, Low & Sullivan, "Incentivized Resume Rating", *American Economic Review* 109(11) (2019) — https://www.aeaweb.org/articles?id=10.1257/aer.20181714 · PDF https://hrlr.msu.edu/_assets/images/IRR_kesslerlowsullivan.pdf · NBER WP 25800 https://www.nber.org/papers/w25800
- Cui, Dias & Ye, "Signaling in the Age of AI: Evidence from Cover Letters" (2025) — https://arxiv.org/abs/2509.25054
- Wiles, Munyikwa & Horton, algorithmic writing assistance, NBER w30886 → *Management Science* 2025 — https://www.nber.org/papers/w30886
- Wilson & Caliskan, "Gender, Race, and Intersectional Bias in Resume Screening via Language Model Retrieval", AAAI/ACM AIES 2024 — https://arxiv.org/abs/2407.20371 · UW release https://www.washington.edu/news/2024/10/31/ai-bias-resume-screening-race-gender/
- "AI Self-preferencing in Algorithmic Hiring" — https://arxiv.org/abs/2509.00462
- Hidden prompt injection in ~200K real résumés, USENIX Security 2026 — https://arxiv.org/abs/2605.28999
- PhantomLint (hidden-text detection) — https://arxiv.org/abs/2508.17884
- Prompt injection against LLM résumé screeners — https://arxiv.org/abs/2512.20164
- Self-promotional injection and its collapse at scale — https://arxiv.org/abs/2606.27287
- Hidden prompts in peer review, measured — https://arxiv.org/abs/2508.20863 · survey https://arxiv.org/abs/2507.06185
- Wright et al., "Null Compliance: NYC Local Law 144 and the Challenges of Algorithm Accountability", ACM FAccT 2024 — https://arxiv.org/abs/2406.01399
- SkillSpan, NAACL 2022 — https://arxiv.org/abs/2204.12811
- Kompetencer, LREC 2022 — https://arxiv.org/abs/2205.01381
- ESCOXLM-R, ACL 2023 — https://arxiv.org/abs/2305.12092
- Rethinking Skill Extraction using LLMs, EACL 2024 workshop — https://arxiv.org/abs/2402.03832
- NNOSE, EACL 2024 — https://arxiv.org/abs/2401.17092
- Entity Linking in the Job Market Domain, EACL 2024 Findings — https://arxiv.org/abs/2401.17979
- Layout-Aware Parsing Meets Efficient LLMs (Alibaba SmartResume) — https://arxiv.org/abs/2510.09722
- ⚠️ arXiv:1910.03089 — "100% accuracy" résumé parsing; **do not cite**, the number reflects template-uniform LinkedIn exports

## Research reports and employer surveys

- Fuller, Raman et al., *Hidden Workers: Untapped Talent*, HBS Project on Managing the Future of Work / Accenture, Sept 2021 — https://www.hbs.edu/managing-the-future-of-work/research/hidden-workers-untapped-talent · PDF https://www.hbs.edu/ris/Publication%20Files/hiddenworkers09032021_Fuller_white_paper_33a2047f-41dd-47b1-9a8d-bd08cf3bfa94.pdf · HKS overview https://www.hks.harvard.edu/centers/mrcbg/programs/growthpolicy/look-inside-hidden-workers-untapped-talent-joseph-fuller
- NACE Job Outlook 2025 (n=237, 19.2% member response rate) — https://www.naceweb.org/research/reports/job-outlook/2025
- NACE Job Outlook 2026 — https://www.naceweb.org/research/reports/job-outlook/2026
- NACE, what employers look for when reviewing résumés — https://www.naceweb.org/talent-acquisition/candidate-selection/what-are-employers-looking-for-when-reviewing-college-students-resumes
- ERE — "Is the 6-Second Resume Scan a Myth?" (Gygax, 2020) — https://www.ere.net/articles/is-the-6-second-resume-scan-a-myth
- ERE — one-page vs two-page résumés — https://www.ere.net/articles/one-or-two-page-resumes-best
- Forbes (Adams, 2012) on the TheLadders study, including its conflict of interest — https://www.forbes.com/sites/susanadams/2012/03/26/what-your-resume-is-up-against/
- Ladders 2018 eye-tracking press release ⚠️ *no sample size stated* — https://www.prnewswire.com/news-releases/ladders-updates-popular-recruiter-eye-tracking-study-with-new-key-insights-on-how-job-seekers-can-improve-their-resumes-300744217.html · study PDF https://www.theladders.com/static/images/basicSite/pdfs/TheLadders-EyeTracking-StudyC2.pdf · HR Dive https://www.hrdive.com/news/eye-tracking-study-shows-recruiters-look-at-resumes-for-7-seconds/541582/
- CIO — 75% of recruiters use an ATS (Capterra), i.e. an **adoption** figure — https://www.cio.com/article/284414/applicant-tracking-system.html
- HiringThing — "It's simply not true that ATS systems auto-reject" *(vendor blog)* — https://blog.hiringthing.com/applicant-tracking-system-myths
- Built In — recruiters on hidden AI prompts in résumés — https://builtin.com/articles/hidden-ai-prompts-in-resume
- Nikkei Asia — hidden prompts in 17 preprints — https://asia.nikkei.com/business/technology/artificial-intelligence/positive-review-only-researchers-hide-ai-prompts-in-papers
- Anthropic candidate AI guidance (10 Jul 2025) — https://www.anthropic.com/candidate-ai-guidance
- Wikipedia, *Signs of AI writing* ⚠️ *WikiProject advice page, not policy, not peer-reviewed* — https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing

### Interested sources (companies selling résumé or hiring services)

- ResumeGo, cover letter field experiment (7,287 applications) — https://www.resumego.net/research/cover-letters/
- ResumeGo, one vs two page résumés (n=482) — https://www.resumego.net/research/one-or-two-page-resumes/ · CNBC coverage https://www.cnbc.com/2018/12/19/resumego-hiring-managers-prefer-candidates-with-two-page-resumes.html
- ResumeGo, LinkedIn profile field experiment (24,570 résumés) — https://www.resumego.net/research/linkedin-interview-chances/
- Cultivated Culture, résumé statistics (n=125,484; "not scientifically gathered or reviewed") — https://cultivatedculture.com/resume-statistics/
- Resume Genius cover-letter statistics ⚠️ *Pollfish, n=625, fielded 2023, relabelled 2026; Sonaga Tech* — https://resumegenius.com/blog/cover-letter-help/cover-letter-statistics
- CV Genius CV and cover letter trends ⚠️ *same parent company, n=625, fielded Apr 2024* — https://cvgenius.com/blog/career-advice/cv-and-cover-letter-trends-survey
- TopResume AI-in-hiring survey ⚠️ *Pollfish, n=600, fielded May 2025; sells human-written résumés* — https://topresume.com/career-advice/ai-in-hiring-survey
- Enhancv, "Does ATS reject resumes?" (25 named recruiters, Sep–Oct 2025) — https://enhancv.com/blog/does-ats-reject-resumes/
- Enhancv on ATS résumé parsing ⚠️ *the "73% used two columns" claim, which the author concedes is not a controlled experiment* — https://enhancv.com/blog/ats-resume-parsing/
- Jobscan, "99% of Fortune 500 companies use ATS" ⚠️ *the actual source of a statistic usually attributed to Harvard; Jobscan's own 2025 update says 97.8%* — https://www.jobscan.co/blog/99-percent-fortune-500-ats/

## University career services

- **MIT CAPD** — Resumes https://capd.mit.edu/resources/resumes/ · Résumé checklist https://capd.mit.edu/resources/resume-checklist/ · Writing about your skills (PAR) https://capd.mit.edu/resources/resumes-writing-about-your-skills/ · Career toolkit https://capd.mit.edu/resources/career-toolkit-crafting-an-effective-resume/ · Action verbs https://capd.mit.edu/resources/resume-action-verbs/ · **Make your resume ATS-friendly** https://capd.mit.edu/resources/make-your-resume-ats-friendly/ · How to write an effective cover letter https://capd.mit.edu/resources/how-to-write-an-effective-cover-letter/ · **Using AI for cover letters** https://capd.mit.edu/resources/using-ai-for-cover-letters/
- **Yale OCS** — Writing impactful résumé bullets https://ocs.yale.edu/resources/writing-impactful-resume-bullets/ · Résumé formatting and common errors https://ocs.yale.edu/resources/resume-formatting/ · STEMConnect technical résumé sample https://ocs.yale.edu/resources/stemconnect-technical-resume-sample/ · Cover letters and correspondence https://ocs.yale.edu/channels/cover-letters-correspondence/ · Yale SOM résumé guide https://som.yale.edu/sites/default/files/2022-01/Yale%20SOM%20CDO%20Resume%20Writing%20Guide-1(1)(1).pdf
- **Harvard** — Create a strong résumé https://careerservices.fas.harvard.edu/resources/create-a-strong-resume/ · Résumés and cover letters guide https://careerservices.fas.harvard.edu/resources/harvard-college-guide-to-resumes-cover-letters/ · AI for résumés and cover letters https://careerservices.fas.harvard.edu/ai-resumes-and-cover-letters/
- **Princeton** — Basic principles of cover letter writing https://careerdevelopment.princeton.edu/cover-letter-guide/basic-principles-cover-letter-writing · **Weak / Better / Best sample sentences** https://careerdevelopment.princeton.edu/cover-letter-guide/weak-better-best-sample-sentences
- **UC Berkeley** — Résumés https://career.berkeley.edu/prepare-for-success/resumes/ · Cover letters https://career.berkeley.edu/cover-letters/ · I School résumé guide https://www.ischool.berkeley.edu/careers/guides/resume · Action verb list (PDF) https://hrweb.berkeley.edu/sites/default/files/attachments/action-verbs.pdf
- **Stanford** — GSB résumés and cover letters https://www.gsb.stanford.edu/alumni/career-resources/job-search/resumes · Developing your résumé handout https://careered.stanford.edu/sites/g/files/sbiybj22801/files/media/file/developing_your_resume_handout.pdf · Action verbs https://careered.stanford.edu/sites/g/files/sbiybj22801/files/media/file/action-verbs-pg-22.pdf
- **CMU** — Graduate student résumé guide https://www.cmu.edu/career/documents/sample-resumes-cover-letters/graduate_student_resume_guide_24.pdf · SCS résumé guide https://www.cmu.edu/career/documents/resources-by-college/scs-resume-guide-2020.pdf
- **Columbia** — Optimizing your résumé for ATS ⚠️ *undated; recommends a defunct product; publishes the 90%/75% statistics uncited* https://www.careereducation.columbia.edu/resources/optimizing-your-resume-applicant-tracking-systems · Résumés with impact https://www.careereducation.columbia.edu/resources/resumes-impact-creating-strong-bullet-points · 200+ action verbs https://www.careereducation.columbia.edu/resources/200-action-verbs-spice-your-resume · SPS Career Design Lab https://sps.columbia.edu/students/career-design-lab/career-journey-resources/resume
- **Cornell** — Create a résumé or cover letter https://career.cornell.edu/channels/create-a-resume-cover-letter/ · **Résumé and cover letter takeaways** https://gradcareers.cornell.edu/spotlights/resume-and-cover-letter-takeaways/ · The summary statement https://hecec.human.cornell.edu/2016/10/25/the-summary-statement-for-resumes-linkedin-and-more/
- **UNC** — Writing effective cover letters https://careers.unc.edu/resource/writing-effective-cover-letters/
- **Penn** — Résumé action verbs https://careerservices.upenn.edu/resources/career-services-resume-action-verbs/ · Résumé channel https://careerservices.upenn.edu/channels/resume/

## Law, regulation and litigation

- NYC Local Law 144 — DCWP page and the 5 July 2023 enforcement date — https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page
- DCWP final rules, 6 RCNY §§ 5-300–5-304 (the "simplified output" definition, which carves out PDF conversion) — https://rules.cityofnewyork.us/wp-content/uploads/2023/04/DCWP-NOA-for-Use-of-Automated-Employment-Decisionmaking-Tools-2.pdf
- DCWP AEDT FAQ ("The vendor that created the AEDT is not responsible for a bias audit") — https://www.nyc.gov/assets/dca/downloads/pdf/about/DCWP-AEDT-FAQ.pdf
- NY State Comptroller audit of DCWP enforcement, Report 2024-N-6 (2 Dec 2025) — https://www.osc.ny.gov/state-agencies/audits/2025/12/02/enforcement-local-law-144-automated-employment-decision-tools
- EU AI Act, Regulation (EU) 2024/1689 — https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689 · Annex III https://artificialintelligenceact.eu/annex/3/ · Article 6 https://artificialintelligenceact.eu/article/6/
- GDPR Art. 4(4), the definition of profiling — https://gdpr-info.eu/art-4-gdpr/
- Regulation (EU) 2026/1744, the Digital Omnibus deferring Annex III high-risk to 2 Dec 2027 — https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202601744
- Illinois AI Video Interview Act, 820 ILCS 42 — https://www.ilga.gov/Legislation/ILCS/Articles?ActID=4015&ChapterID=68
- Illinois HB 3773 / P.A. 103-0804, effective 1 Jan 2026 — https://www.ilga.gov/Legislation/PublicActs/View/103-0804
- Colorado SB 24-205 — https://leg.colorado.gov/bills/sb24-205 · SB 25B-004 (delay) https://leg.colorado.gov/bills/sb25b-004 · SB 26-189 (repeal and reenactment, eff. 1 Jan 2027) https://leg.colorado.gov/bills/sb26-189 · Colorado AG https://coag.gov/ai/
- California Civil Rights Council ADS regulations, effective 1 Oct 2025 — https://calcivilrights.ca.gov/2025/06/30/civil-rights-council-secures-approval-for-regulations-to-protect-against-employment-discrimination-related-to-artificial-intelligence/
- Texas TRAIGA (HB 149), effective 1 Jan 2026 — https://capitol.texas.gov/tlodocs/89R/billtext/html/HB00149F.htm
- Maryland HB 1202 (2020) — https://mgaleg.maryland.gov/mgawebsite/Legislation/Details/hb1202?ys=2020RS
- Uniform Guidelines on Employee Selection Procedures, 29 C.F.R. § 1607.4(D) — the four-fifths rule — https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XIV/part-1607/section-1607.4
- Executive Order 14179 (23 Jan 2025) — https://www.govinfo.gov/content/pkg/FR-2025-01-31/html/2025-02172.htm
- *Mobley v. Workday*, N.D. Cal. No. 3:23-cv-00770-RFL, order of 12 July 2024 — https://blogs.duanemorris.com/classactiondefense/wp-content/uploads/sites/56/2024/07/Mobley-v.-Workday-Order.pdf
- EEOC amicus brief in *Mobley* — https://www.eeoc.gov/litigation/briefs/mobley-v-workday-inc
- Warden AI trust dashboard, Greenhouse — https://trust.warden-ai.com/greenhouse

## Sources that could not be verified, and claims to avoid

Recorded so that nobody re-derives them later and assumes they were checked.

| Claim | Status |
|---|---|
| "ATS automatically reject 75% of résumés" | ⚠️ **No primary source.** Corresponds to *adoption* figures (HBS: 75% of US employers use an RMS; Capterra via CIO: 75% of recruiters use an ATS). **And the standard Preptel-2012 debunking is itself unsourced** — no Preptel document, quote or URL exists in any source found. The 2012 WSJ article usually invoked is paywalled and could not be read. |
| "Harvard: 88% screened out due to keyword mismatch" | ⚠️ **Misquote.** HBS says 88% of employers *believed* qualified high-skills candidates were vetted out for not matching *the exact criteria in the job description*. |
| "ATS exclude 27 million people" | ⚠️ **Conflation.** 27M is HBS's estimate of the US hidden-worker *population*, not a rejection count. |
| "99% of Fortune 500 use an ATS" | ⚠️ Vendor research (Jobscan), not Harvard; Jobscan's own 2025 update says **97.8%**. |
| "ATS detect white text by comparing font colour to background" | ⚠️ **Only hireEZ has a confirmed production detector.** No mainstream ATS documents such a feature. |
| "ATS rank by keyword density" | ⚠️ Ranking by keyword *relevance* is vendor-documented; **density** is imported from SEO and documented nowhere. |
| "Workday uses Textkernel/Sovren" | ⚠️ **Unverified, and the evidence points against it** — no parsing vendor in Workday's subprocessor register; Textkernel's and Daxtra's partner pages both omit Workday. |
| "iCIMS uses Textkernel/Sovren" | ⚠️ **Contradicted by iCIMS's own sub-processor disclosure: Daxtra.** |
| "iCIMS Copilot is GPT-4-powered" | ⚠️ Unverified; **no LLM vendor appears on iCIMS's sub-processor list at all.** |
| "Taleo has notoriously bad parsing" | ⚠️ Unsourced. No Oracle figure or credible measurement exists. |
| "Workday autofill has a 34% error rate" | ⚠️ SEO blog only; no study; no Workday accuracy figure exists publicly. |
| "A court ruled against Workday / found its AI auto-rejects" | ⚠️ **False.** Zero merits findings; the court expressly assumed the opposite arguendo. |
| "En-dash vs hyphen matters for dates" | ⚠️ No vendor documentation; SEO sources contradict each other. |
| "Avoid ampersands and slashes in job titles" | ⚠️ SEO blogs only. |
| "Commas parse better than bullets in a skills list" (or the reverse) | ⚠️ Zero evidence, primary or secondary. |
| "Star-rating bars confuse the ATS" | ⚠️ No vendor documents graphical rating widgets. The defensible version is mechanical: a drawn bar contributes zero characters, so the rating is simply invisible. |
| "Tagged PDF fixes ATS parsing" | ⚠️ Tagging demonstrably fixes *screen-reader* order (W3C PDF3), but **no evidence any résumé parser reads the PDF structure tree.** |
| "O*NET is public domain" | ⚠️ **False** — CC BY 4.0, attribution required. |
| "Lightcast Open Skills is open source" | ⚠️ **Outdated** — contract-based API access. Repeated even in Affinda's docs and SkillNER's README. |
| "Textkernel maps skills to ESCO" | ⚠️ Not documented. Professions map to O*NET and ISCO only. |
| "2026 TopResume survey: 67% can identify AI cover letters"; "2026 Indeed survey: 61% spend under 30 seconds" | ⚠️ **Untraceable.** Surfaced only on an AI-cover-letter vendor's site carrying 12 specific-sounding statistics with no sources. |
| Zety: "81% of recruiters have rejected a candidate based on cover letter details" | ⚠️ Could not be verified; Zety blocks automated access and sells résumés. |
| TalentWorks: "475–600 word résumé sweet spot doubles interviews" | ⚠️ Site defunct; original analysis unretrievable. |
| Greenhouse: "41% of job seekers admit to using prompt injections" | ⚠️ **41× higher than Greenhouse's own measured ~1%** across ~300M résumés. Both figures are Greenhouse's. |
| Greenhouse applications-per-job: 228 (Feb 2024) vs 95 (2025) | ⚠️ **Not reconcilable as published.** Do not present as one time series. |
| "LinkedIn receives 11,000 applications per minute" | ⚠️ A press quote to the *NYT*; LinkedIn has never published it as research. |
| Indeed Hiring Lab application-volume data | ⚠️ **Does not exist** — a common misattribution. |

## Open questions worth revisiting

1. **Can Workday's Skills Match Score feed an Automatic Stage Routing rule to auto-decline?** The
   score is a reportable field on the job-application object, and condition rules read from that
   object. 3,263 pages of admin guide neither permit nor prohibit it. This is the highest-value
   unresolved question in the platform layer.
2. **Does any named ATS parse, index or score cover-letter content?** No primary documentation exists
   either way. Textkernel's `FindSkillsInCoverLetter` toggle is the only hard evidence that the text
   enters a structured record at all.
3. **No controlled study isolates layout or formatting effects on LLM screeners.** The best validity
   study uses synthetic résumés with no formatting. Since LLMs see extracted text, layout should be
   invisible to them *except* through what extraction mangles — but that is inference, not
   measurement.
4. **No study has measured recruiters' actual accuracy at detecting AI-written application
   materials.** Every published figure measures self-reported confidence, which the general
   literature says is unfounded.
5. **Lever publishes almost nothing** — no fetchable help centre, no bias audit, no LL144 or EU AI Act
   statement, no knockout documentation.
6. **ESCO's licence page 404s.** CC BY 4.0 is inferred from Commission-wide policy. Verify before
   shipping ESCO data in a product.
