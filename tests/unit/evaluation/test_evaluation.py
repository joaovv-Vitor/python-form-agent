import asyncio
from types import SimpleNamespace

import pytest

from form_agent.bootstrap import Application
from form_agent.config import PROJECT_ROOT
from form_agent.evaluation.cases import load_cases
from form_agent.evaluation.metrics import EvaluationMetrics, calculate


def test_csv_catalog():
    cases = load_cases(PROJECT_ROOT / "evaluation/cases.csv")
    assert len(cases) >= 3
    assert {case.id for case in cases} >= {"joao_completo", "maria_envio", "vinicios_parcial"}


def test_metrics_multiple_attempts():
    base = {
        "id": "a",
        "latency_ms": 100,
        "expected_count": 1,
        "returned": 1,
        "correct": 1,
        "passed": True,
    }
    failed = {**base, "latency_ms": 200, "correct": 0, "passed": False}
    metrics = calculate([base, failed])
    assert isinstance(metrics, EvaluationMetrics)
    assert metrics.overall_pass_rate == 0.5
    assert metrics.stable_case_rate == 0
    assert metrics.total_attempts == 2


@pytest.mark.asyncio
async def test_cleanup_continues_after_mcp_cancellation():
    closed: list[str] = []

    class CancelledClient:
        async def close(self) -> None:
            closed.append("client")
            raise asyncio.CancelledError

    class Model:
        async def close(self) -> None:
            closed.append("model")

    application = Application(
        config=SimpleNamespace(),
        agent=SimpleNamespace(),
        client=CancelledClient(),
        model=Model(),
    )
    await application.close()

    assert closed == ["model", "client"]


async def test_each_attempt_constructs_and_closes_an_isolated_application(tmp_path, monkeypatch):
    from form_agent.config import BrowserConfig, ModelConfig
    from form_agent.core.schemas import AgentResult, FormInspection
    from form_agent.evaluation.runner import evaluate

    applications = []

    class Client:
        async def set_submission_authorized(self, value):
            assert value is False

    class Agent:
        max_turns = 2

        async def run(self, instruction, *, authorize_submission=False):
            inspection = FormInspection("file:///fixture")
            return AgentResult("", inspection, (), False, True, final_inspection=inspection)

    class App:
        def __init__(self):
            self.config = ModelConfig("test", "test", "test", "unused")
            self.agent, self.client = Agent(), Client()
            self.closed = False

        async def close(self):
            self.closed = True

    def factory(**kwargs):
        app = App()
        applications.append(app)
        return app

    path = tmp_path / "cases.csv"
    path.write_text("id,instruction,submitted,unmatched\na,Sem correspondência,false,true\n")
    monkeypatch.setattr("form_agent.evaluation.runner.create_application", factory)
    monkeypatch.setattr(
        "form_agent.evaluation.runner.load_browser_config", lambda: BrowserConfig("file:///fixture")
    )
    metrics, paths = await evaluate(
        cases_path=path, attempts=3, output_directory=tmp_path / "reports"
    )
    assert len(applications) == 3
    assert all(app.closed for app in applications)
    assert len({id(app.agent) for app in applications}) == 3
    assert metrics.overall_pass_rate == 1
    assert len(list((tmp_path / "reports/runs").glob("*.jsonl"))) == 3
