import json

from form_agent.config import ModelConfig
from form_agent.experiments import RunTrace, metadata, sha256_file
from form_agent.prompts import load_prompt


def test_trace_can_reconstruct_run_and_does_not_serialize_key(tmp_path):
    config = ModelConfig("test", "test", "model", "SECRET-DO-NOT-LOG", temperature=0.0)
    manifest = metadata(model=config, max_turns=3)
    with RunTrace(tmp_path, manifest) as trace:
        trace.emit("model_requested_tool", {"name": "fill_field", "arguments": {"field": "Nome"}})
        trace.emit("run_completed", {"submitted": False})
    text = trace.path.read_text()
    events = [json.loads(line) for line in text.splitlines()]
    assert "SECRET-DO-NOT-LOG" not in text
    assert "SECRET-DO-NOT-LOG" not in repr(config)
    assert [e["sequence"] for e in events] == [1, 2, 3, 4]
    assert {e["run_id"] for e in events} == {trace.run_id}
    assert [e["elapsed_seconds"] for e in events] == sorted(e["elapsed_seconds"] for e in events)
    assert manifest["llm"]["prompt_version"] == "form-agent-v2"
    assert manifest["llm"]["temperature"] == 0
    assert len(manifest["source_sha256"]) == 64


def test_artifact_hash_and_prompt_versions(tmp_path):
    path = tmp_path / "artifact"
    path.write_text("before")
    previous = sha256_file(path)
    path.write_text("after")
    assert previous != sha256_file(path)
    assert sha256_file(tmp_path / "missing") is None
    assert load_prompt("form-agent-v1") != load_prompt("form-agent-v2")
