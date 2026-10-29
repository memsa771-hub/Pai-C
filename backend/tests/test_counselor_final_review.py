"""Final review regressions: research budgets are counted per key (the Vault version path research read)."""
from unittest.mock import patch
from app.config import config
from app.plugins._shared.budget import bounded_research, spend
from scripts.counselor_eval_support import StudentSession


def test_budget_resets_per_budget_key():
    with StudentSession() as student, patch.object(config,'PAI_RESEARCH_MAX_CALLS_PER_STUDENT',1):
        def attempt(version):
            with bounded_research(queries=5,fetches=5,seconds=30,workspace_id=student.workspace_id,
                 budget_key=version):
                return spend('web.search')
        assert attempt('first') is None
        assert attempt('first')=='research_student_budget_exceeded'
        assert attempt('second') is None
        assert attempt('first')=='research_student_budget_exceeded'
