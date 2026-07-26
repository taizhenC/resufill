import json

import pytest
from conftest import needs_chromium
from test_cover import LETTER
from test_pipeline import FABRICATED, HONEST

from resume_fill.cli import main


@pytest.fixture
def wired(monkeypatch, tmp_path, example_profile):
    """A fully configured run: profile on disk, credentials present, model scripted."""
    from resume_fill import cli
    from resume_fill.config import Settings
    from resume_fill.profile import dump_profile

    profile_path = tmp_path / "profile.yaml"
    dump_profile(example_profile, profile_path)
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text(
        "Backend Engineer, Data Platform\n\nAbout Northwind\n\n"
        "Basic Qualifications\n- Production Python\n- Strong PostgreSQL\n- Kubernetes in production\n",
        encoding="utf-8",
    )

    cfg = Settings(
        LLM_API_KEY="test", LLM_BASE_URL="https://example.invalid", LLM_MODEL="test-model",
        PROFILE_PATH=profile_path, OUT_DIR=tmp_path / "out", EVIDENCE_PATH=tmp_path / "none.json",
        SCORE_THRESHOLD=70, MAX_ITER=3,
    )
    monkeypatch.setattr("resume_fill.config.settings", cfg)

    responses: list[dict] = []
    letters: list[dict] = [LETTER]

    def fake_complete_json(system, user, **kwargs):
        """Three different prompts reach the model in one run — route by what each asks for
        rather than by call order, so a test can script one document without having to know
        how many times the others are called."""
        if "Extract the requirements" in user:
            return {}
        if "Write a cover letter" in user:
            return letters[min(len(letters) - 1, 0)] if len(letters) == 1 else letters.pop(0)
        return responses[min(len(responses) - 1, 0)] if len(responses) == 1 else responses.pop(0)

    monkeypatch.setattr("resume_fill.llm.complete_json", fake_complete_json)
    assert cli  # imported for the monkeypatched module path to resolve
    return {
        "jd": str(jd_path), "cfg": cfg, "responses": responses, "letters": letters,
        "tmp_path": tmp_path,
    }


@needs_chromium
def test_gen_writes_the_pdf_the_json_and_the_report(wired, capsys):
    wired["responses"].append(HONEST)
    code = main(["gen", "--jd", wired["jd"], "--out", str(wired["tmp_path"] / "run"), "--resume"])

    assert code == 0
    run = wired["tmp_path"] / "run"
    assert (run / "resume.pdf").exists()
    assert (run / "report.md").exists()
    assert json.loads((run / "resume.json").read_text(encoding="utf-8"))["experience"]

    printed = capsys.readouterr().out
    assert "Backend Engineer, Data Platform | Northwind" in printed
    assert "every heading and bullet survived" in printed
    assert "Hard-skill coverage vs JD" in printed
    # The gap is stated on the terminal, not buried in the report.
    assert "not in your record, deliberately left out: Kubernetes" in printed


@needs_chromium
def test_gen_exits_nonzero_when_nothing_could_be_grounded(wired, capsys):
    wired["responses"].append(FABRICATED)
    code = main(["gen", "--jd", wired["jd"], "--out", str(wired["tmp_path"] / "run"),
                 "--resume", "--max-iter", "1"])

    assert code == 1
    assert not (wired["tmp_path"] / "run" / "resume.pdf").exists()
    printed = capsys.readouterr().out
    assert "the grounding gate rejected every résumé attempt" in printed
    assert "unsupported_term" in printed


# ------------------------------------------------------------ the modes ----


@needs_chromium
def test_both_is_the_default_and_writes_two_pdfs(wired, capsys):
    wired["responses"].append(HONEST)
    run = wired["tmp_path"] / "run"
    assert main(["gen", "--jd", wired["jd"], "--out", str(run), "--threshold", "70"]) == 0

    assert (run / "resume.pdf").exists()
    assert (run / "cover_letter.pdf").exists()
    assert (run / "cover_letter.json").exists()
    printed = capsys.readouterr().out
    assert "mode:    both" in printed
    assert "addressed to Hiring Manager" in printed

    # One report covers the run, not one per document.
    report = (run / "report.md").read_text(encoding="utf-8")
    assert "## Score" in report
    assert "# Cover letter" in report


@needs_chromium
def test_cover_only_writes_no_resume(wired, capsys):
    run = wired["tmp_path"] / "run"
    assert main(["gen", "--jd", wired["jd"], "--out", str(run), "--cover"]) == 0

    assert (run / "cover_letter.pdf").exists()
    assert not (run / "resume.pdf").exists()
    report = (run / "report.md").read_text(encoding="utf-8")
    assert "## Score" not in report
    assert "# Cover letter" in report


def test_the_modes_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit):
        main(["gen", "--jd", "x", "--resume", "--cover"])


@needs_chromium
def test_a_fabricated_cover_letter_fails_the_run(wired, capsys):
    """Same gate as the résumé: the letter claims Kubernetes, which is nowhere in the
    record, so no PDF is written and the run fails."""
    wired["responses"].append(HONEST)
    wired["letters"][:] = [
        {
            "addressee": "Hiring Manager",
            "paragraphs": [
                {"text": "I have run production Kubernetes clusters for three years.",
                 "source_ids": ["exp-northwind-backend.h1"]}
            ],
        }
    ]
    run = wired["tmp_path"] / "run"
    code = main(["gen", "--jd", wired["jd"], "--out", str(run), "--cover", "--max-iter", "1"])

    assert code == 1
    assert not (run / "cover_letter.pdf").exists()
    printed = capsys.readouterr().out
    assert "the grounding gate rejected every cover letter" in printed
    assert "Kubernetes" in printed


@needs_chromium
def test_an_honest_low_score_warns_but_succeeds(wired, capsys):
    """PLAN.md open question 5, resolved: the gate stopped the loop inflating the number,
    so a low ceiling is the answer, not a failure."""
    wired["responses"].append(HONEST)
    code = main(["gen", "--jd", wired["jd"], "--out", str(wired["tmp_path"] / "run"),
                 "--resume", "--threshold", "99", "--max-iter", "1"])

    assert code == 0
    printed = capsys.readouterr().out
    assert "below the threshold" in printed
    assert "Nothing was invented to close it" in printed


@needs_chromium
def test_strict_turns_a_low_score_into_a_failure(wired, capsys):
    wired["responses"].append(HONEST)
    code = main(["gen", "--jd", wired["jd"], "--out", str(wired["tmp_path"] / "run"),
                 "--resume", "--threshold", "99", "--max-iter", "1", "--strict"])

    assert code == 1
    assert "STRICT_SCORE is on" in capsys.readouterr().out


def test_gen_without_credentials_says_what_to_set(monkeypatch, tmp_path, capsys):
    from resume_fill.config import Settings

    monkeypatch.setattr("resume_fill.config.settings", Settings(LLM_API_KEY=""))
    assert main(["gen", "--jd", str(tmp_path / "jd.txt")]) == 1
    assert ".env" in capsys.readouterr().out


def test_gen_without_a_profile_says_to_run_init(monkeypatch, tmp_path, capsys):
    from resume_fill.config import Settings

    jd_path = tmp_path / "jd.txt"
    jd_path.write_text("Engineer", encoding="utf-8")
    monkeypatch.setattr(
        "resume_fill.config.settings",
        Settings(LLM_API_KEY="k", LLM_BASE_URL="u", LLM_MODEL="m", PROFILE_PATH=tmp_path / "nope.yaml"),
    )
    assert main(["gen", "--jd", str(jd_path)]) == 1
    assert "resume-fill init" in capsys.readouterr().out
