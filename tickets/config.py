"""SME roster, topic→SME assignment, programmes, and agent config."""

from __future__ import annotations

# --- SME roster (display names) ---
SME_POOJITHA = "Poojitha Pachava"
SME_MARIYAM = "Mariyam"
SME_VIHARIKA = "Viharika"
SME_VARSHA = "Varsha"
SME_SAIFULLAH = "Saifullah"
SME_UNASSIGNED = "Unassigned"
SME_NOT_MINE = "Not mine"

ASSIGNABLE_SMES: tuple[str, ...] = (
    SME_UNASSIGNED,
    SME_POOJITHA,
    SME_MARIYAM,
    SME_VIHARIKA,
    SME_VARSHA,
    SME_SAIFULLAH,
)

# Shown in admin filters / reassignment (includes Not mine queue label).
ADMIN_SME_FILTERS: tuple[str, ...] = ASSIGNABLE_SMES + (SME_NOT_MINE,)

RULE_TYPE_TOPIC = "topic"
RULE_TYPE_ASSESSMENT = "assessment_title"

# Fill real addresses later; nudge skips empty emails and logs instead.
SME_EMAILS: dict[str, str] = {
    SME_POOJITHA: "",
    SME_MARIYAM: "",
    SME_VIHARIKA: "",
    SME_VARSHA: "",
    SME_SAIFULLAH: "",
}

# Topic-tag substrings (matched against TOPIC_* tags, case-insensitive).
# First matching bucket wins (order matters).
TOPIC_SME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        SME_POOJITHA,
        ("QUANTITATIVE", "LOGICAL", "APTITUDE"),
    ),
    (
        SME_MARIYAM,
        ("VERBAL",),
    ),
    (
        SME_VIHARIKA,
        ("HTML", "CSS", "REACT", "WEB_", "FRONTEND", "NODE"),
    ),
    (
        SME_VARSHA,
        ("DSA", "SQL", "CODING", "PYTHON", "CPP", "IDE_CODING"),
    ),
    (
        SME_SAIFULLAH,
        ("CS_FUNDAMENTAL",),
    ),
)

SEED_USERS: tuple[dict[str, str], ...] = (
    {
        "username": "admin",
        "display_name": "Admin",
        "role": "admin",
        "password": "Admin@Grit2026!",
    },
    {
        "username": "poojitha",
        "display_name": SME_POOJITHA,
        "role": "sme",
        "password": "Poojitha@Grit2026!",
    },
    {
        "username": "mariyam",
        "display_name": SME_MARIYAM,
        "role": "sme",
        "password": "Mariyam@Grit2026!",
    },
    {
        "username": "viharika",
        "display_name": SME_VIHARIKA,
        "role": "sme",
        "password": "Viharika@Grit2026!",
    },
    {
        "username": "varsha",
        "display_name": SME_VARSHA,
        "role": "sme",
        "password": "Varsha@Grit2026!",
    },
    {
        "username": "saifullah",
        "display_name": SME_SAIFULLAH,
        "role": "sme",
        "password": "Saifullah@Grit2026!",
    },
)

PROGRAMME_GRIT = "GRIT"
PROGRAMME_NIAT_SKILL = "NIAT Skill Exams"
PROGRAMME_INTENSIVE_OFFLINE = "Intensive Offline"
PROGRAMME_OTHER = "Other"

GRIT_SUBJECTS: tuple[str, ...] = (
    "Quantitative Reasoning",
    "CS Fundamentals",
    "UI Engineering",
    "Computational Thinking",
    "GenAI",
    "Critical Thinking & Communication",
    "Server Side Engineering",
    "SQL",
)

INTENSIVE_OFFLINE_TITLE_MARKERS: tuple[str, ...] = (
    "weekly skill assessment",
    "weekly skill main assessment",
)

NIAT_SKILL_TITLE_MARKERS: tuple[str, ...] = (
    "weekly assessment",
)

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"

CRITICALITY_CRITICAL = "Critical"
CRITICALITY_MODERATE = "Moderate"
CRITICALITY_TRIVIAL = "Trivial"
CRITICALITY_LABELS: tuple[str, ...] = (
    CRITICALITY_CRITICAL,
    CRITICALITY_MODERATE,
    CRITICALITY_TRIVIAL,
)

TICKET_STATUSES: tuple[str, ...] = (
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
)

ROLE_ADMIN = "admin"
ROLE_SME = "sme"

SESSION_COOKIE = "ticket_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14

# OpenRouter for WhatsApp draft generation only (not MCQ triage).
DEFAULT_DRAFT_MODEL = "deepseek/deepseek-chat-v3.1"
