from types import SimpleNamespace

from app.agents.resume_tailor import _build_prompt, evidence_text
from app.models.opportunity import OpportunityRequirements

BASE = "Jane Doe\nSkills: Django\n• Built a Django app"

IMPLIES = "SKILLS THE RESUME IMPLIES (add to Technical Skills): "
CONFIRMED = "SKILLS THE CANDIDATE CONFIRMED (add to Technical Skills): "
ABSENT = "Skills the resume does NOT show — never add these: "


def _line(prompt: str, prefix: str):
    matches = [l for l in prompt.split("\n") if l.startswith(prefix)]
    assert len(matches) <= 1
    return matches[0] if matches else None


def _prompt(requirements, skill_gap=None, confirmed_skills=None, base=BASE):
    return _build_prompt(base, "Backend Developer", "Co", requirements, skill_gap, None, confirmed_skills)


def test_implied_line_lists_only_skills_the_resume_implies_but_does_not_state():
    reqs = OpportunityRequirements(required_skills=["Python", "Django", "Kubernetes"])
    prompt = _prompt(reqs)
    assert _line(prompt, IMPLIES) == IMPLIES + "Python"


def test_no_implied_line_when_nothing_is_implied():
    reqs = OpportunityRequirements(required_skills=["Django", "Kubernetes"])
    prompt = _prompt(reqs)
    assert "SKILLS THE RESUME IMPLIES" not in prompt
    assert "SKILLS THE CANDIDATE CONFIRMED" not in prompt


def test_confirmed_line_has_posting_and_extra_confirmed_skills_without_duplicates():
    reqs = OpportunityRequirements(required_skills=["Python", "Django", "Kubernetes"])
    prompt = _prompt(reqs, confirmed_skills=["Kubernetes", "Docker"])
    assert _line(prompt, CONFIRMED) == CONFIRMED + "Kubernetes, Docker"
    assert _line(prompt, IMPLIES) == IMPLIES + "Python"


def test_confirmed_skill_not_in_posting_is_still_listed():
    reqs = OpportunityRequirements(required_skills=["Django"])
    prompt = _prompt(reqs, confirmed_skills=["Docker"])
    assert _line(prompt, CONFIRMED) == CONFIRMED + "Docker"


def test_absent_skills_exclude_confirmed_ones():
    reqs = OpportunityRequirements(required_skills=["Django"])
    gap = SimpleNamespace(matched=["Django"], missing=["Kubernetes", "Haskell"], weak=[])
    prompt = _prompt(reqs, skill_gap=gap, confirmed_skills=["Kubernetes"])
    assert _line(prompt, ABSENT) == ABSENT + "Haskell"


def test_absent_skills_say_none_when_all_missing_are_confirmed():
    reqs = OpportunityRequirements(required_skills=["Django"])
    gap = SimpleNamespace(matched=["Django"], missing=["Kubernetes"], weak=[])
    prompt = _prompt(reqs, skill_gap=gap, confirmed_skills=["Kubernetes"])
    assert _line(prompt, ABSENT) == ABSENT + "none"


class _FalsyStr(str):
    def __bool__(self):
        return False


def test_blank_or_falsy_posting_skills_are_ignored():
    reqs = SimpleNamespace(required_skills=[_FalsyStr("Python")], preferred_skills=[], raw_eligibility_text=None)
    prompt = _prompt(reqs)
    assert "SKILLS THE RESUME IMPLIES" not in prompt

    reqs = SimpleNamespace(required_skills=["  ", "Python"], preferred_skills=[], raw_eligibility_text=None)
    prompt = _prompt(reqs)
    assert _line(prompt, IMPLIES) == IMPLIES + "Python"


def test_evidence_text_skips_blank_confirmed_skills():
    assert evidence_text("Resume", None) == "Resume"
    assert evidence_text("Resume", ["   "]) == "Resume"
    assert evidence_text("Resume", ["  ", "", " Go "]) == "Resume\n\nAdditional skills (confirmed by candidate): Go"
