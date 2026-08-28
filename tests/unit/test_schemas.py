import pytest
from pydantic import ValidationError

from orchestration.schemas import (
    PackageRef,
    PRDiffInput,
    TriageResult,
    TriageIntent,
    SynthesisOutput,
    SynthesisRiskLevel,
)


def test_package_ref_rejects_unknown_ecosystem():
    with pytest.raises(ValidationError):
        PackageRef(name="left-pad", ecosystem="go")  # "go" not in allowed Literal


def test_triage_result_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        TriageResult(
            intent=TriageIntent.NEW_DEPENDENCY,
            confidence=1.5,  # > 1.0, should fail ge/le constraint
            reasoning="bad confidence",
        )


def test_triage_result_rejects_invalid_intent_string():
    with pytest.raises(ValidationError):
        TriageResult(
            intent="totally_made_up_intent",
            confidence=0.5,
            reasoning="bad intent",
        )


def test_synthesis_output_requires_risk_level():
    with pytest.raises(ValidationError):
        SynthesisOutput(recommendation="missing risk_level entirely")


def test_synthesis_output_unable_to_assess_path_is_valid_shape():
    # This is the low-confidence refusal path — confirm it's a valid,
    # non-crashing shape, not an exception.
    result = SynthesisOutput(
        risk_level=SynthesisRiskLevel.UNABLE_TO_ASSESS,
        recommendation="Cannot assess: ecosystem not supported",
        unable_to_assess=True,
        unable_to_assess_reason="unsupported ecosystem: go",
    )
    assert result.unable_to_assess is True
    assert result.risk_level == SynthesisRiskLevel.UNABLE_TO_ASSESS


def test_pr_diff_input_requires_repo_fields():
    with pytest.raises(ValidationError):
        PRDiffInput(diff_text="some diff")  # missing repo_owner, repo_name