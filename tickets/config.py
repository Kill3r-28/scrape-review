"""GRIT programme subjects and SME assignment rules."""

from __future__ import annotations

# If org_assessment_title contains any of these (case-insensitive), ticket is GRIT.
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

# Map matched GRIT subject → SME display name. Non-GRIT stays Unassigned.
SME_BY_SUBJECT: dict[str, str] = {
    "Quantitative Reasoning": "Poojitha Pachava",
    "CS Fundamentals": "Saifullah",
    "UI Engineering": "Viharika",
    "Computational Thinking": "Varsha",
    "GenAI": "Unassigned",
    "Critical Thinking & Communication": "Namitha",
    "Server Side Engineering": "Saifullah",
    "SQL": "Varsha",
}

# Names admins can assign to tickets (dropdown).
ASSIGNABLE_SMES: tuple[str, ...] = (
    "Unassigned",
    "Poojitha Pachava",
    "Viharika",
    "Varsha",
    "Saifullah",
    "Namitha",
)

# Seed users: username → (display_name, role, default_password)
# role: admin | sme
SEED_USERS: tuple[dict[str, str], ...] = (
    {
        "username": "admin",
        "display_name": "Admin",
        "role": "admin",
        "password": "Admin@Grit2026!",
    },
    {
        "username": "poojitha",
        "display_name": "Poojitha Pachava",
        "role": "sme",
        "password": "Poojitha@Grit2026!",
    },
    {
        "username": "viharika",
        "display_name": "Viharika",
        "role": "sme",
        "password": "Viharika@Grit2026!",
    },
    {
        "username": "varsha",
        "display_name": "Varsha",
        "role": "sme",
        "password": "Varsha@Grit2026!",
    },
    {
        "username": "saifullah",
        "display_name": "Saifullah",
        "role": "sme",
        "password": "Saifullah@Grit2026!",
    },
    {
        "username": "namitha",
        "display_name": "Namitha",
        "role": "sme",
        "password": "Namitha@Grit2026!",
    },
)

PROGRAMME_GRIT = "GRIT"
PROGRAMME_NIAT_SKILL = "NIAT Skill Exams"
PROGRAMME_OTHER = "Other"

# Titles matching these (case-insensitive) map to NIAT Skill Exams when not GRIT.
NIAT_SKILL_TITLE_MARKERS: tuple[str, ...] = (
    "weekly assessment",
    "weekly skill assessment",
    "weekly skill main assessment",
)


STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RESOLVED = "resolved"

TICKET_STATUSES: tuple[str, ...] = (
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
)

ROLE_ADMIN = "admin"
ROLE_SME = "sme"

SESSION_COOKIE = "ticket_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14
