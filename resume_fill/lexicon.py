"""A curated list of technical terms, and the rule for spotting one that is not on it.

Two stages need it and they need it to agree:

  - jd.py, to pull hard skills out of a posting without an LLM round trip. Deterministic
    extraction is what lets the tool parse a JD with no API key configured at all.
  - ground.py, to decide which words in a bullet are *claims*. "Improved throughput" is
    prose; "with Kafka" is a claim about a tool you either used or did not.

A curated list beats "every capitalised word": a posting full of "Our Team Values
Ownership" would otherwise turn into a dozen fake skills, and a bullet mentioning a city
would be flagged as an unsupported technology.
"""

import re

# Grouped only so the list stays editable. Everything is matched the same way.
_TERMS: dict[str, list[str]] = {
    "languages": [
        "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go", "Golang", "Rust",
        "Ruby", "PHP", "Swift", "Kotlin", "Scala", "R", "MATLAB", "Perl", "Haskell", "Elixir",
        "Objective-C", "Dart", "Lua", "Julia", "Bash", "Shell", "PowerShell", "SQL", "PL/SQL",
        "T-SQL", "HTML", "CSS", "Sass", "SCSS", "Assembly", "VHDL", "Verilog", "Solidity", "COBOL",
        "Fortran", "Clojure", "F#", "Groovy", "Zig", "OCaml",
    ],
    "web": [
        "React", "React Native", "Next.js", "Vue", "Vue.js", "Nuxt", "Angular", "Svelte",
        "SvelteKit", "Node.js", "Express", "Deno", "Bun", "Django", "Flask", "FastAPI", "Rails",
        "Ruby on Rails", "Spring", "Spring Boot", "ASP.NET", ".NET", "Laravel", "Phoenix",
        "GraphQL", "REST", "gRPC", "WebSocket", "WebSockets", "tRPC", "Redux", "Tailwind",
        "Bootstrap", "jQuery", "Webpack", "Vite", "Babel", "HTMX", "Astro", "Remix",
    ],
    "data": [
        "PostgreSQL", "Postgres", "MySQL", "SQLite", "MariaDB", "Oracle", "SQL Server", "MongoDB",
        "DynamoDB", "Cassandra", "Redis", "Memcached", "Elasticsearch", "OpenSearch", "Neo4j",
        "InfluxDB", "ClickHouse", "DuckDB", "Snowflake", "BigQuery", "Redshift", "Databricks",
        "Hadoop", "Spark", "PySpark", "Hive", "Presto", "Trino", "Kafka", "RabbitMQ", "Pulsar",
        "Airflow", "dbt", "Dagster", "Prefect", "Flink", "Beam", "Kinesis", "Delta Lake", "Iceberg",
        "ETL", "ELT", "data warehouse", "data lake", "data pipeline", "OLAP", "OLTP",
    ],
    "ml": [
        "machine learning", "deep learning", "NLP", "computer vision", "reinforcement learning",
        "PyTorch", "TensorFlow", "Keras", "JAX", "scikit-learn", "sklearn", "XGBoost", "LightGBM",
        "CatBoost", "pandas", "NumPy", "SciPy", "Matplotlib", "Seaborn", "Plotly", "Polars",
        "Hugging Face", "Transformers", "LangChain", "LlamaIndex", "OpenAI", "LLM", "LLMs", "RAG",
        "MLOps", "MLflow", "Weights & Biases", "ONNX", "CUDA", "TensorRT", "vLLM", "embeddings",
        "fine-tuning", "prompt engineering", "A/B testing", "time series", "regression",
        "classification", "clustering", "feature engineering", "statistics", "Bayesian",
    ],
    "cloud": [
        "AWS", "Amazon Web Services", "Azure", "GCP", "Google Cloud", "EC2", "S3", "Lambda",
        "ECS", "EKS", "Fargate", "RDS", "CloudFront", "CloudWatch", "CloudFormation", "IAM",
        "SQS", "SNS", "API Gateway", "Route 53", "EMR", "Glue", "Athena", "SageMaker",
        "Cloud Run", "Cloud Functions", "GKE", "Pub/Sub", "Vercel", "Netlify", "Heroku",
        "DigitalOcean", "Cloudflare", "Firebase", "Supabase",
    ],
    "infra": [
        "Docker", "Kubernetes", "k8s", "Helm", "Terraform", "Pulumi", "Ansible", "Chef", "Puppet",
        "Vagrant", "Jenkins", "GitHub Actions", "GitLab CI", "CircleCI", "Travis CI", "ArgoCD",
        "CI/CD", "Nginx", "Apache", "HAProxy", "Envoy", "Istio", "Consul", "Vault", "Prometheus",
        "Grafana", "Datadog", "Splunk", "Sentry", "New Relic", "PagerDuty", "OpenTelemetry",
        "Linux", "Unix", "Ubuntu", "Debian", "CentOS", "macOS", "Windows", "systemd",
        "microservices", "serverless", "load balancing", "observability", "SRE", "infrastructure as code",
    ],
    "practice": [
        "Git", "GitHub", "GitLab", "Bitbucket", "Jira", "Confluence", "Agile", "Scrum", "Kanban",
        "TDD", "unit testing", "integration testing", "pytest", "JUnit", "Jest", "Vitest",
        "Cypress", "Playwright", "Selenium", "Mocha", "RSpec", "code review", "pair programming",
        "design patterns", "OOP", "functional programming", "concurrency", "asyncio", "async",
        "multithreading", "distributed systems", "system design", "API design", "caching",
        "algorithms", "data structures", "operating systems", "computer networks", "compilers",
        "cryptography", "security", "OAuth", "JWT", "SAML", "SSO", "penetration testing",
    ],
    "product": [
        "Figma", "Sketch", "Adobe XD", "Tableau", "Power BI", "Looker", "Excel", "Google Analytics",
        "Salesforce", "HubSpot", "Segment", "Amplitude", "Mixpanel", "Notion", "Airtable",
        "Stripe", "Twilio", "SEO", "accessibility", "WCAG", "UX research", "user research",
        "product roadmap", "stakeholder management", "technical writing",
    ],
}

TERMS: list[str] = sorted({t for group in _TERMS.values() for t in group}, key=len, reverse=True)
_BY_NORM: dict[str, str] = {t.casefold(): t for t in TERMS}

# Aliases that a job posting and a résumé spell differently. Normalising these is what
# stops "Postgres" in your bullet from reading as a gap against "PostgreSQL" in the JD.
ALIASES: dict[str, str] = {
    "golang": "Go", "postgres": "PostgreSQL", "k8s": "Kubernetes", "k8": "Kubernetes",
    "js": "JavaScript", "ts": "TypeScript", "node": "Node.js", "nodejs": "Node.js",
    "vuejs": "Vue", "reactjs": "React", "react.js": "React", "nextjs": "Next.js",
    "sklearn": "scikit-learn", "amazon web services": "AWS", "google cloud": "GCP",
    "google cloud platform": "GCP", "ruby on rails": "Rails", "llms": "LLM",
    "shell": "Bash", "torch": "PyTorch", "csharp": "C#", "cpp": "C++",
    "restful": "REST", "rest api": "REST", "rest apis": "REST", "postgressql": "PostgreSQL",
    "github actions": "GitHub Actions", "gh actions": "GitHub Actions",
    "huggingface": "Hugging Face", "objective c": "Objective-C", "dotnet": ".NET",
}

# Acronyms and the phrases they stand for.
#
# The tailor is *told* to write in the posting's vocabulary — that is rule 9 of its prompt,
# and it is the whole point of tailoring. Then the gate would reject it for doing so: a
# highlight recording "wired the test suite into the deploy pipeline on every push" cannot
# license the word "CI/CD", even though they are the same fact and the posting asked for the
# acronym. Every pair below is one that cost a whole iteration to relearn.
#
# The rule for adding one: the two spellings must be interchangeable *in both directions*
# with no loss. "ML" for "machine learning", yes. "CV" for "computer vision", no — a résumé
# is also a CV, and a gate that cannot tell them apart is not a gate.
EXPANSIONS: dict[str, tuple[str, ...]] = {
    "CI/CD": ("continuous integration", "continuous delivery", "continuous deployment"),
    "machine learning": ("ML",),
    "NLP": ("natural language processing",),
    "API": ("application programming interface",),
    "REST": ("representational state transfer", "RESTful"),
    "LLM": ("large language model", "large language models"),
    "SQL": ("structured query language",),
    "ETL": ("extract transform load",),
    "RAG": ("retrieval augmented generation", "retrieval-augmented generation"),
    "ORM": ("object relational mapping", "object-relational mapping"),
    "TDD": ("test driven development", "test-driven development"),
    "OOP": ("object oriented programming", "object-oriented programming"),
    "SRE": ("site reliability engineering",),
    "CDN": ("content delivery network",),
    "gRPC": ("google remote procedure call",),
    "IaC": ("infrastructure as code",),
    "CRUD": ("create read update delete",),
    "SPA": ("single page application", "single-page application"),
    "CV": (),  # deliberately empty: see the note above. Listed so nobody re-adds it.
}


def _equivalence_groups() -> dict[str, tuple[str, ...]]:
    """Every spelling of one concept, indexed by each of those spellings.

    Built once from ALIASES and EXPANSIONS rather than written out, so adding an alias in
    one place makes it usable from every direction.
    """
    groups: dict[str, list[str]] = {}

    def add(key: str, *names: str) -> None:
        bucket = groups.setdefault(key.casefold(), [])
        bucket.extend(n for n in names if n and n not in bucket)

    for alias, name in ALIASES.items():
        add(name, name, alias)
    for term, expansions in EXPANSIONS.items():
        add(canonical(term) or term, term, *expansions)

    index: dict[str, tuple[str, ...]] = {}
    for members in groups.values():
        frozen = tuple(dict.fromkeys(members))
        for member in frozen:
            index.setdefault(member.casefold(), frozen)
    return index


def equivalents(term: str) -> tuple[str, ...]:
    """Other ways of writing `term` that mean exactly the same thing.

    Empty for anything not in a group, which is most words. Callers treat this as "also
    accept these", never as "rewrite to these" — the résumé keeps whatever spelling the
    posting used.
    """
    key = (term or "").strip().casefold()
    if not key:
        return ()
    group = _EQUIVALENTS.get(key) or _EQUIVALENTS.get(canonical(term).casefold(), ())
    return tuple(name for name in group if name.casefold() != key)


# Derivations of a tool's name that are still that tool. "Dockerized the worker" is a claim
# about Docker; "containerised" is not a claim about anything. Only suffixes that build an
# adjective or a verb from a proper noun are listed — plurals are handled separately, and a
# bare "s"/"es" rule would let "Reds" license "Red".
_DERIVATIONS = ("ization", "isation", "izing", "ising", "ized", "ised", "ify", "ing", "ed")


def base_forms(term: str) -> tuple[str, ...]:
    """"Dockerized" -> ("Docker",). The name a derived word was built from, if any.

    Longest suffix first, and only the first match: stripping "ed" off "Dockerized" as well
    would produce "Dockeriz", which is not a word anybody wrote down.
    """
    for suffix in sorted(_DERIVATIONS, key=len, reverse=True):
        if len(term) > len(suffix) + 2 and term.casefold().endswith(suffix):
            return (term[: -len(suffix)],)
    return ()


# The same idea pointed the other way, and a much shorter list. A source note reading
# "Dockerised the worker" says Docker; the claim side is where the risk lives, because
# growing a tool name into a word is how "Spark" comes to be licensed by "sparked
# interest". Only the suffixes that build a verb out of a proper noun are here — "-ed" and
# "-ing" are not, and that is the whole reason this list differs from _DERIVATIONS.
_TOOL_VERBS = ("ized", "ised", "ization", "isation", "ify")


def derived_forms(term: str) -> tuple[str, ...]:
    """"Docker" -> ("Dockerized", "Dockerised", ...). Spellings of a source that would still
    be naming this tool. Multi-word terms and two-letter names are skipped: "Go" grows into
    far too much."""
    if not term or " " in term or len(term) < 3:
        return ()
    stem = term[:-1] if term.endswith("e") else term
    return tuple(dict.fromkeys(stem + suffix for suffix in _TOOL_VERBS))

# A token that is technical on its face even though nobody curated it: an ALLCAPS acronym,
# a CamelCase product name, a version-tagged tool (Python3, H100, GPT-4), a dotted or
# suffixed package (foo.js, C++). Used by ground.py so a bullet cannot smuggle in
# "deployed on Kubermatic" just because the lexicon has not heard of it.
_LOOKS_TECHNICAL = re.compile(
    r"""^(?:
        [A-Z]{2,}[0-9]*            # ATS, GPU, S3AR
      | [A-Z][a-z]+[A-Z][A-Za-z]*  # CamelCase
      | [A-Za-z]+[0-9]+[A-Za-z0-9]*  # H100, Python3, EC2
      | [A-Za-z]+\+\+              # C++
      | [A-Za-z]+\#                # C#
      | [A-Za-z]{2,}\.(?:js|py|net|io|ai|sh)  # Node.js, Next.js
    )$""",
    re.VERBOSE,
)

# Words that pass _LOOKS_TECHNICAL but are not claims about tooling.
_NOT_A_TOOL = {
    "I", "A", "AN", "THE", "AND", "OR", "TO", "OF", "IN", "ON", "AT", "BY", "FOR", "US", "USA",
    "UK", "EU", "NY", "NYC", "CA", "SF", "LA", "TX", "WA", "DC", "MA", "IL", "PhD", "BS", "BA",
    "MS", "MBA", "GPA", "CV", "OK", "TODO", "AM", "PM", "EST", "PST", "UTC", "Q1", "Q2", "Q3",
    "Q4", "H1", "H2", "FY", "CEO", "CTO", "VP", "HR", "COVID", "ID", "OS", "PC", "IT", "QA",
}

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9.+#/&'-]*")


def canonical(term: str) -> str:
    """Fold spelling variants onto one name so coverage is measured on meaning."""
    key = (term or "").strip().casefold().rstrip(".")
    return ALIASES.get(key) or _BY_NORM.get(key) or (term or "").strip()


# Built after canonical() because it uses it. Module-level so the grouping is computed once.
_EQUIVALENTS: dict[str, tuple[str, ...]] = _equivalence_groups()


def find_terms(text: str) -> list[str]:
    """Every lexicon term present in `text`, canonicalised, in first-appearance order.

    Matched against the raw text with the same word-boundary rule ground.py uses, so a
    posting asking for "R" does not match every "or" in the paragraph.
    """
    from .textutil import contains_term

    found: list[str] = []
    seen: set[str] = set()
    for term in TERMS:  # longest first, so "Spring Boot" wins over "Spring"
        if contains_term(text, term):
            name = canonical(term)
            if name.casefold() not in seen:
                seen.add(name.casefold())
                found.append(name)
    return found


def technical_tokens(text: str) -> list[str]:
    """Words in `text` that assert a specific technology, whether curated or not.

    This is the set ground.py demands support for. Everything else in a bullet — verbs,
    outcomes, ordinary nouns — is phrasing, and phrasing is the tailor's job.
    """
    from .textutil import squash

    out: list[str] = []
    # Keyed on the squashed spelling so a bullet writing "CICD" is not reported separately
    # from the "CI/CD" the lexicon already matched — that would be one violation for a
    # term the source does contain.
    seen: set[str] = set()

    for term in find_terms(text):
        if squash(term) not in seen:
            seen.add(squash(term))
            out.append(term)

    for raw in _TOKEN.findall(text or ""):
        # Strip the possessive: "DeepMind's platform" names DeepMind, and leaving the "'s"
        # on makes the token fail the shape test and slip through unchecked. (Curated terms
        # are unaffected — contains_term already treats the apostrophe as a boundary.)
        token = re.sub(r"['’]s$", "", raw.strip(".,;:"))
        if not token or token in _NOT_A_TOOL or squash(token) in seen:
            continue
        if _LOOKS_TECHNICAL.match(token):
            seen.add(squash(token))
            out.append(token)
    return out
