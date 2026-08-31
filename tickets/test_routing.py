"""Quick checks for topic-tag SME assignment + programmes."""

from tickets.routing import assign_sme, assign_sme_from_tags, route_ticket


def test_topic_assign():
    assert assign_sme_from_tags("TOPIC_QUANTITATIVE_MCQ") == "Poojitha Pachava"
    assert assign_sme_from_tags("TOPIC_LOGICAL_NIAT_ENTRANCE_MCQ") == "Poojitha Pachava"
    assert assign_sme_from_tags("TOPIC_VERBAL_ABILITY_MCQ") == "Mariyam"
    assert assign_sme_from_tags("TOPIC_HTML_CSS_MCQ") == "Viharika"
    assert assign_sme_from_tags("TOPIC_JS_CODING") == "Varsha"
    assert assign_sme_from_tags("TOPIC_SQL_CODING") == "Varsha"
    assert assign_sme_from_tags("TOPIC_CS_FUNDAMENTALS_MCQ") == "Saifullah"
    assert assign_sme_from_tags("TOPIC_GRIT_GENAI") == "Saifullah"
    assert assign_sme_from_tags("") == "Unassigned"


def test_title_helps_when_tags_weak():
    # No tags → Unassigned without title; with title rule fallback via assign_sme defaults
    assert assign_sme("UI Engineering - L1", "") == "Viharika"
    assert assign_sme("Random Exam", "") == "Unassigned"


def test_programme_still_from_title():
    assert route_ticket("CS Fundamentals - L1", "TOPIC_CS_FUNDAMENTALS_MCQ")["programme"] == "GRIT"
    assert route_ticket("Weekly Skill Assessment-7", "TOPIC_JS_CODING")["programme"] == "Intensive Offline"
    assert route_ticket("Weekly Assessment - 3", "")["programme"] == "NIAT Skill Exams"
