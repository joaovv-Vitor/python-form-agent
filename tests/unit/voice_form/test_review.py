import json
from dataclasses import replace

import pytest

from audio_agent.agent import AudioAgent
from audio_agent.models import EngineTranscription, TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.core.errors import ModelCommunicationError, ToolClientError
from form_agent.core.schemas import (
    AgentResult,
    FilledField,
    FormField,
    FormInspection,
    FormOption,
    RunIssue,
    ToolCall,
)
from form_agent.experiments import RunTrace
from voice_form.clarification import ClarificationSession
from voice_form.interaction import ReviewInput
from voice_form.normalization import normalize_spoken_data
from voice_form.review import ReviewSession


def field(ref, kind="text", value="", **kwargs):
    return FormField(ref, ref, ref, kind, "textbox", value=value, **kwargs)


def correction(ref, value, source=None):
    return ToolCall(
        "change", "fill_field", {"field": ref, "value": value, "source_text": source or value}
    )


class Tools:
    def __init__(self, *fields):
        self.inspection = FormInspection("file:///form", tuple(fields))
        self.calls = []
        self.side_effect = False
        self.reject_native = False
        self.error_after_write = False

    async def inspect_form(self):
        return self.inspection

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        assert name == "fill_field"
        self.inspection = replace(
            self.inspection,
            fields=tuple(
                replace(f, value=arguments["value"], valid=not self.reject_native)
                if f.reference == arguments["field"]
                else replace(f, value="efeito colateral")
                if self.side_effect
                else f
                for f in self.inspection.fields
            ),
        )
        self.reject_native = False
        if self.error_after_write:
            raise ToolClientError("timeout após escrita", "TIMEOUT")
        return {"success": True, "field_ref": arguments["field"], "value": arguments["value"]}


class Model:
    def __init__(self, *batches):
        self.batches = iter(batches)
        self.requests = []

    def create_session(self, instruction, inspection, tools):
        self.requests.append((instruction, inspection, tools))
        return self

    async def next(self, completed):
        value = next(self.batches)
        if isinstance(value, Exception):
            raise value
        return value


class Speech:
    def __init__(self, text=""):
        self.text, self.calls = text, []

    def transcribe(self, audio, settings):
        self.calls.append((audio, settings))
        return EngineTranscription("scripted", "1", self.text, "pt", 1.0, 2.0, ())


def initial(tools, **kwargs):
    return AgentResult(
        "Inicial",
        tools.inspection,
        tuple(
            FilledField(f.label, f.value, f.reference) for f in tools.inspection.fields if f.value
        ),
        False,
        False,
        final_inspection=tools.inspection,
        **kwargs,
    )


def session(tools, model, *answers, speech=None, events=lambda *_: None):
    iterator = iter(answers)
    prompts, notices = [], []

    async def ask(question):
        prompts.append(question)
        answer = next(iterator)
        if isinstance(answer, Exception):
            raise answer
        return answer

    speech = speech or Speech()
    review = ReviewSession(
        tools,
        model,
        AudioAgent(AudioPreprocessor(), speech),
        TranscriptionSettings(),
        ask=ask,
        notify=notices.append,
        events=events,
    )
    return review, prompts, notices


async def test_multiple_corrections_preserve_other_fields_and_submission_remains_external():
    tools = Tools(
        field("name", value="Ana"),
        field("phone", "tel", "(85) 99912-3456"),
        field("city", value="Fortaleza"),
    )
    model = Model(
        [correction("phone", "85988881234")],
        [correction("city", "Quixadá")],
    )
    review, _, notices = session(
        tools,
        model,
        "Meu telefone está errado, o correto é 85988881234",
        "Na verdade moro em Quixadá",
        "MOSTRAR",
        "ENVIAR",
        "CONCLUIR",
    )
    result = await review.run(initial(tools), ())
    assert result.completed and result.issues == ()
    assert [r.field for r in result.records] == ["phone", "city"]
    assert result.records[0].previous == "(85) 99912-3456"
    assert {f.reference: f.value for f in result.form.final_inspection.fields} == {
        "name": "Ana",
        "phone": "(85) 98888-1234",
        "city": "Quixadá",
    }
    assert not result.form.submission_authorized and not result.form.submission_attempted
    assert {t.name for t in model.requests[0][2]} == {"fill_field", "ask_clarification"}
    assert all(name == "fill_field" for name, _ in tools.calls)
    assert any("Nome" not in n and "name [name]: Ana" in n for n in notices)


async def test_ambiguous_request_and_short_reply_keep_only_pending_context():
    tools = Tools(field("city", value="Fortaleza"))
    model = Model(
        [ToolCall("ask", "ask_clarification", {"question": "Qual é a cidade correta?"})],
        [correction("city", "Quixadá")],
    )
    review, prompts, _ = session(
        tools, model, "Minha cidade está errada", "CONCLUIR", "Quixadá", "CONCLUIR"
    )
    result = await review.run(initial(tools), ())
    assert result.completed and len(tools.calls) == 1
    assert "Qual é a cidade correta?" in prompts[1]
    assert "Minha cidade está errada" in model.requests[1][0]
    assert "Resposta: Quixadá" in model.requests[1][0]


async def test_new_request_cannot_reuse_value_from_a_previous_successful_correction():
    tools = Tools(field("city", value="Fortaleza"), field("name", value="Ana"))
    model = Model([correction("city", "Quixadá")], [correction("name", "Quixadá")])
    review, _, _ = session(tools, model, "Cidade Quixadá", "Meu nome está errado", "CONCLUIR")
    result = await review.run(initial(tools), ())
    assert [r.status for r in result.records] == ["applied", "rejected"]
    assert len(tools.calls) == 1
    assert "Cidade Quixadá" not in model.requests[1][0]


@pytest.mark.parametrize(
    "calls",
    [
        [ToolCall("send", "click_button", {"button": "Enviar"})],
        [correction("city", "Quixadá"), correction("name", "Ana")],
        [correction("unknown", "Quixadá")],
        [correction("city", "Inventado", "Inventado")],
        [correction("phone", "85999999999", "85 99912-3456")],
        [correction("phone", "9999")],
    ],
)
async def test_invalid_or_ungrounded_proposals_never_reach_browser(calls):
    tools = Tools(
        field("city", value="Fortaleza"),
        field("name", value="Ana"),
        field("phone", "tel", "(85) 98888-1234"),
    )
    snapshot = tools.inspection
    review, _, _ = session(
        tools, Model(calls), "Corrija para Quixadá; telefone 85 99912-3456 ou 9999", "CONCLUIR"
    )
    result = await review.run(initial(tools), ())
    assert not tools.calls and tools.inspection == snapshot
    assert result.records[0].status == "rejected"


async def test_unrelated_pending_issues_are_preserved_after_fixing_a_phone():
    tools = Tools(field("phone", "tel"), field("email", "email"))
    normalization = normalize_spoken_data("E-mail: incompleto. Telefone: incompleto.")
    unrelated = RunIssue("DATA_BLOCKED", "tool", "Outro problema")
    review, _, _ = session(
        tools, Model([correction("phone", "85999123456")]), "Telefone 85999123456", "CONCLUIR"
    )
    result = await review.run(
        initial(tools), (*normalization.issues, unrelated), normalization=normalization
    )
    assert result.issues == (normalization.issues[0], unrelated)
    assert all(f.status == "pending" for f in normalization.fields)


async def test_native_rejection_remains_pending_until_a_new_correction_is_verified():
    tools = Tools(field("phone", "tel", "", required=True))
    tools.reject_native = True
    model = Model([correction("phone", "85999123456")], [correction("phone", "85988881234")])
    review, _, notices = session(
        tools, model, "Telefone 85999123456", "PENDENCIAS", "Telefone 85988881234", "CONCLUIR"
    )
    result = await review.run(initial(tools), ())
    assert result.issues == ()
    assert [record.status for record in result.records] == ["pending", "applied"]
    assert any("phone: campo obrigatório vazio ou inválido" in text for text in notices)


async def test_selected_required_radio_group_does_not_leave_unchecked_sibling_pending():
    tools = Tools(
        replace(field("online", "radio", True, required=True, valid=True), name="mode"),
        replace(field("presencial", "radio", False, required=True, valid=True), name="mode"),
    )
    review, _, _ = session(tools, Model(), "CONCLUIR")
    result = await review.run(initial(tools), ())
    assert result.completed and result.issues == ()


@pytest.mark.parametrize("value,required,valid", [("invalido", False, False), ("", True, True)])
async def test_review_resolves_skipped_clarification_after_verified_correction(
    value, required, valid
):
    tools = Tools(field("email", "email", value, required=required, valid=valid))

    async def skip(_):
        return "PULAR"

    clarified = await ClarificationSession(skip, notify=lambda _: None).run(
        tools, initial(tools), ()
    )
    assert clarified.issues[0].stage == "clarification"
    review, _, _ = session(
        tools,
        Model([correction("email", "ana@example.com")]),
        "Corrija meu e-mail para ana@example.com",
        "CONCLUIR",
    )
    result = await review.run(clarified.form, clarified.issues)
    assert result.completed and result.issues == ()
    assert result.records[0].status == "applied"
    assert result.form.final_inspection.fields[0].value == "ana@example.com"


async def test_resolving_clarification_keeps_other_fields_pending():
    tools = Tools(
        field("email", "email", "", required=True),
        field("backupEmail", "email", "", required=True),
    )

    async def skip(_):
        return "PULAR"

    clarified = await ClarificationSession(skip, notify=lambda _: None).run(
        tools, initial(tools), ()
    )
    review, _, _ = session(
        tools,
        Model([correction("email", "ana@example.com")]),
        "Corrija meu e-mail para ana@example.com",
        "CONCLUIR",
    )
    result = await review.run(clarified.form, clarified.issues)
    assert len(result.issues) == 1
    assert result.issues[0].message.startswith("backupEmail:")


@pytest.mark.parametrize("failure", ["side_effect", "timeout_after_write"])
async def test_uncertain_mutation_stops_session_without_retry(failure):
    tools = Tools(field("city", value="Fortaleza"), field("name", value="Ana"))
    tools.side_effect = failure == "side_effect"
    tools.error_after_write = failure == "timeout_after_write"
    review, prompts, _ = session(tools, Model([correction("city", "Quixadá")]), "Cidade Quixadá")
    result = await review.run(initial(tools), ())
    assert len(tools.calls) == len(prompts) == 1
    assert not result.completed and not result.form.verification_complete
    assert result.records[0].status == "failed"
    assert result.issues[0].stage == "review"
    assert result.form.final_inspection == tools.inspection


async def test_state_change_while_waiting_for_user_blocks_correction():
    tools = Tools(field("city", value="Fortaleza"))
    form = initial(tools)

    async def ask(_):
        tools.inspection = replace(tools.inspection, url="file:///another")
        return "Cidade Quixadá"

    review = ReviewSession(
        tools,
        Model(),
        AudioAgent(AudioPreprocessor(), Speech()),
        TranscriptionSettings(),
        ask=ask,
        notify=lambda _: None,
    )
    result = await review.run(form, ())
    assert not tools.calls and not result.form.verification_complete


async def test_provider_error_leaves_browser_unchanged_and_user_can_exit():
    tools = Tools(field("city", value="Fortaleza"))
    snapshot = tools.inspection
    review, _, _ = session(
        tools, Model(ModelCommunicationError("offline")), "Cidade Quixadá", EOFError()
    )
    result = await review.run(initial(tools), ())
    assert not tools.calls and tools.inspection == snapshot
    assert result.form.verification_complete and not result.completed
    assert result.records[0].status == "rejected"


async def test_web_text_cannot_open_a_server_file_or_execute_terminal_commands():
    tools = Tools(field("city", value="Fortaleza"))
    speech = Speech()
    model = Model([], [])
    review, _, _ = session(
        tools,
        model,
        ReviewInput("text", "AUDIO /private/audio.wav"),
        ReviewInput("text", "CONCLUIR"),
        ReviewInput("close"),
        speech=speech,
    )
    result = await review.run(initial(tools), ())
    assert not speech.calls and not tools.calls and not result.completed
    assert len(model.requests) == 2


async def test_audio_correction_is_transcribed_separately_and_original_evidence_is_preserved(
    tmp_path,
):
    tools = Tools(field("phone", "tel", "(85) 98888-1234"), field("name", value="Ana"))
    text = "Corrija meu telefone para oitenta e cinco nove nove nove um dois três quatro cinco seis"
    source = "oitenta e cinco nove nove nove um dois três quatro cinco seis"
    speech = Speech(text)
    path = tmp_path / "correcao com espacos.wav"
    path.write_bytes(b"simulated decoder")
    with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
        trace.emit("audio_transcribed", {"text": "Áudio inicial"})
        trace.emit("form_inspected", tools.inspection.to_dict())
        review, _, _ = session(
            tools,
            Model([correction("phone", "85999123456", source)]),
            f'AUDIO "{path}"',
            "CONCLUIR",
            speech=speech,
            events=trace.emit,
        )
        result = await review.run(initial(tools), ())
    assert result.records[0].audio_file == str(path)
    assert result.records[0].text == text
    assert "phone" in speech.calls[0][1].initial_prompt
    data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
    assert data["transcription"] == "Áudio inicial"
    assert data["review_transcriptions"][0]["text"] == text
    assert data["review_records"][0]["value"] == "(85) 99912-3456"
    assert data["form_fields"]["name"] == "Ana"
    assert data["filled_fields"] == {"phone": "(85) 99912-3456"}


@pytest.mark.parametrize(
    "changes",
    [
        {"verification_complete": False},
        {"submission_attempted": True},
        {"turn_limit_reached": True},
    ],
)
async def test_uncertain_or_submitted_run_does_not_open_review(changes):
    tools = Tools(field("city", value="Fortaleza"))
    review, prompts, _ = session(tools, Model())
    result = await review.run(initial(tools, **changes), ())
    assert not prompts and not result.completed and not tools.calls


async def test_submission_veto_in_correction_is_preserved():
    tools = Tools(field("city", value="Fortaleza"))
    review, _, _ = session(
        tools,
        Model([correction("city", "Quixadá")]),
        "Não envie. Corrija cidade para Quixadá",
        "CONCLUIR",
    )
    result = await review.run(initial(tools), ())
    assert result.completed and result.submission_denied


@pytest.mark.parametrize(
    "target,value,source",
    [
        (field("birthDate", "date", "2001-03-15"), "2002-04-20", "vinte de abril de 2002"),
        (
            field(
                "state",
                "select",
                "PB",
                options=(FormOption("Ceará", "CE"), FormOption("Paraíba", "PB")),
            ),
            "CE",
            "Ceará",
        ),
    ],
)
async def test_date_and_select_corrections_validate_evidence_and_write_native_values(
    target, value, source
):
    tools = Tools(target, field("name", value="Ana"))
    review, _, _ = session(
        tools,
        Model([correction(target.reference, value, source)]),
        f"Corrija {target.reference} para {source}",
        "CONCLUIR",
    )
    result = await review.run(initial(tools), ())
    assert result.records[0].status == "applied"
    assert result.records[0].value == value
    assert result.form.final_inspection.fields[1].value == "Ana"


@pytest.mark.parametrize(
    "target",
    [field("city", readonly=True), field("city", disabled=True), field("city", "password")],
)
async def test_ineligible_fields_are_rejected_before_writing(target):
    tools = Tools(target)
    review, _, _ = session(
        tools, Model([correction("city", "Quixadá")]), "Cidade Quixadá", "CONCLUIR"
    )
    result = await review.run(initial(tools), ())
    assert not tools.calls and result.records[0].status == "rejected"


async def test_source_must_be_literal_user_input_rather_than_prompt_scaffolding():
    tools = Tools(field("city", value="Fortaleza"))
    model = Model(
        [ToolCall("ask", "ask_clarification", {"question": "Qual cidade?"})],
        [correction("city", "Quixadá", "Resposta: Quixadá")],
    )
    review, _, _ = session(tools, model, "Corrija a cidade", "Quixadá", "CONCLUIR")
    result = await review.run(initial(tools), ())
    assert not tools.calls and result.records[0].status == "rejected"


async def test_interruption_keeps_last_observed_correction_and_marks_snapshot_unverified(tmp_path):
    tools = Tools(field("city", value="Fortaleza"))
    with pytest.raises(RuntimeError, match="interrompido"):
        with RunTrace(tmp_path / "runs", {}, data_directory=tmp_path / "manual") as trace:
            trace.emit("form_inspected", tools.inspection.to_dict())
            review, _, _ = session(
                tools,
                Model([correction("city", "Quixadá")]),
                "Cidade Quixadá",
                RuntimeError("interrompido"),
                events=trace.emit,
            )
            await review.run(initial(tools), ())
    data = json.loads((tmp_path / "manual" / trace.run_id / "form_data.json").read_text())
    assert data["form_fields"]["city"] == "Quixadá"
    assert data["filled_fields"] == {"city": "Quixadá"}
    assert data["verification_complete"] is False
