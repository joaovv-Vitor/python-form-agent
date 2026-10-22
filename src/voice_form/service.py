"""Result coordination shared by terminal and web entry points."""

from dataclasses import replace

from .pipeline import PipelineResult
from .review import ReviewResult


def apply_review(result: PipelineResult, reviewed: ReviewResult) -> PipelineResult:
    return replace(
        result,
        form=reviewed.form,
        issues=reviewed.issues,
        initial_issues=result.initial_issues or result.issues,
        review_records=reviewed.records,
        review_seconds=reviewed.seconds,
        total_seconds=result.total_seconds + reviewed.seconds,
        post_stt_seconds=result.post_stt_seconds + reviewed.seconds,
    )


def submission_block(result: PipelineResult, denied: bool) -> str | None:
    if denied:
        return "Envio bloqueado pela instrução negativa."
    form = result.form
    if not form or not form.verification_complete or form.turn_limit_reached:
        return "Revisão incompleta ou estado não verificável."
    if any(issue.code != "SUBMISSION_BLOCKED" for issue in result.issues):
        return "Resolva as pendências antes de enviar."
    return None
