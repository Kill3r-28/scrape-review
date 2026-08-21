"""Quick checks for GRIT / NIAT title routing."""

from tickets.routing import is_niat_skill_exam, match_grit_subject, route_ticket


def test_grit_matches():
    assert match_grit_subject("CS Fundamentals - L1") == "CS Fundamentals"
    assert match_grit_subject("Quantitative Reasoning - L2") == "Quantitative Reasoning"
    assert match_grit_subject("Critical Thinking & Communication - L1") == (
        "Critical Thinking & Communication"
    )
    assert match_grit_subject("Weekly Skill Assessment-7") is None


def test_niat_skill_exam():
    assert is_niat_skill_exam("Weekly Assessment - 3")
    assert is_niat_skill_exam("Weekly Skill Assessment-7")
    assert is_niat_skill_exam("Java Weekly Skill Main Assessment 3")
    assert not is_niat_skill_exam("Frontend Developer")


def test_route_sets_programme():
    routed = route_ticket("SQL - L1")
    assert routed["programme"] == "GRIT"
    assert routed["subject"] == "SQL"
    assert routed["sme_name"] == "Varsha"

    niat = route_ticket("Weekly Assessment - 3")
    assert niat["programme"] == "NIAT Skill Exams"
    assert niat["sme_name"] == "Unassigned"

    other = route_ticket("Frontend Developer")
    assert other["programme"] == "Other"
    assert other["subject"] == ""
