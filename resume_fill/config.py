"""Settings, mirroring infinance/config.py: one pydantic-settings object, one .env,
paths resolved relative to the checkout when run from one and to the platform user-data
dir when installed as a tool."""

from pathlib import Path

import platformdirs
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
BASE_DIR = PACKAGE_DIR.parent

# Repo checkout (developer flow): profile, evidence and output stay inside the repo.
# Installed package (uv tool install): site-packages is ephemeral, so state goes to the
# platform user-data dir instead.
IS_REPO_CHECKOUT = (BASE_DIR / "pyproject.toml").exists()
DATA_HOME = (
    BASE_DIR if IS_REPO_CHECKOUT else Path(platformdirs.user_data_dir("resume-fill", appauthor=False))
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DATA_HOME / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM (any OpenAI-compatible endpoint) ---------------------------------
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.cerebras.ai/v1"
    LLM_MODEL: str = "qwen-3-235b-a22b-instruct"
    LLM_TIMEOUT_SEC: float = 180.0
    # Tailoring is a selection-and-phrasing job over fixed evidence, not a creative one.
    # Low temperature keeps reruns comparable, which is what makes resume.json diffable.
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 6000

    # --- Sources --------------------------------------------------------------
    PROFILE_PATH: Path = DATA_HOME / "profile.yaml"
    EVIDENCE_PATH: Path = DATA_HOME / "data" / "evidence.json"
    LINKEDIN_EXPORT_DIR: Path = DATA_HOME / "data" / "linkedin_export"
    OUT_DIR: Path = DATA_HOME / "out"
    # Jinja looks here first, then falls back to the templates shipped in the package,
    # so a checkout can override one template without vendoring all of them.
    TEMPLATES_DIR: Path = DATA_HOME / "templates"

    BLOG_URL: str = ""
    BLOG_MAX_POSTS: int = 100
    BLOG_USER_AGENT: str = "resume-fill/0.1 (+personal résumé tooling)"

    # `linkedin draft` shape. LinkedIn truncates the About section at ~2,600 characters and
    # collapses it after the third line, so the opening paragraph does the work.
    LINKEDIN_ABOUT_PARAGRAPHS: int = 3
    LINKEDIN_ABOUT_WORDS: int = 180

    # --- Loop -----------------------------------------------------------------
    # The score is a local proxy (PLAN.md §2): no employer computes it. The threshold is
    # a stopping rule for the loop, not a quality bar anyone else will apply.
    SCORE_THRESHOLD: float = 80.0
    MAX_ITER: int = 4
    # The threshold is an aspiration; the *ceiling* is what this record can actually reach
    # against this posting (score.ceiling). A posting wanting three technologies the record
    # has never touched caps the score before a word is written, and ground.py guarantees no
    # rewrite can lift it. Iterating towards an unreachable number is how a run spends four
    # LLM calls to arrive at the answer the first one already gave.
    #
    # So the loop also stops within this much of the ceiling...
    CEILING_SLACK: float = 2.0
    # ...and when an iteration stops buying anything. A rewrite that gains less than this is
    # noise: the feedback pushes on gaps, and past a point pushing only trades one keyword
    # for another.
    MIN_GAIN: float = 1.5
    # A low ceiling that ground.py refused to inflate is *information* — the role wants
    # things you have not done. Default is to emit anyway and say so in report.md.
    STRICT_SCORE: bool = False

    # --- Document shape -------------------------------------------------------
    RESUME_MAX_PAGES: int = 1
    # Off by default. A summary restates what the bullets below already prove, and it is the
    # one block on the page with no citation of its own — the space buys more where it is
    # spent on a job or a project. Set true to get one back.
    RESUME_SUMMARY: bool = False
    # A cover letter that runs to two pages does not get read; the budget is the point.
    COVER_LETTER_MAX_PAGES: int = 1
    COVER_LETTER_WORDS: int = 300
    COVER_LETTER_TONE: str = "direct and specific; no filler, no flattery, no restating the job ad"
    # Used when the posting names no addressee (PLAN.md open question 4).
    COVER_LETTER_FALLBACK_ADDRESSEE: str = "Hiring Manager"
    # --- Local web UI (`resume-fill serve`) -----------------------------------
    HOST: str = "127.0.0.1"
    PORT: int = 8765
    # Required before binding anything but loopback. This server reads profile.yaml and
    # spends the configured API key on request, so exposing it without one is not a
    # configuration choice — see main.check_bind_security.
    AUTH_TOKEN: str = ""

    PAGE_FORMAT: str = "Letter"
    PAGE_MARGIN_IN: float = 0.5
    # The one honest lever for fitting a page. Below about 9.5pt a résumé stops being
    # comfortable to read, which is a worse outcome than a second page.
    FONT_PT: float = 10.5

    @property
    def template_dirs(self) -> list[Path]:
        """User overrides first, packaged defaults second."""
        return [self.TEMPLATES_DIR, PACKAGE_DIR / "templates"]

    @property
    def llm_configured(self) -> bool:
        return bool(self.LLM_API_KEY and self.LLM_BASE_URL and self.LLM_MODEL)


settings = Settings()
