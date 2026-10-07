import json

import pytest

from form_agent.config import load_agent_max_turns, load_browser_config, load_model_config
from form_agent.core.errors import ConfigurationError


@pytest.fixture
def profiles_file(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "defaultProfile": "test",
                "profiles": {
                    "test": {
                        "provider": "test-provider",
                        "model": "test-model",
                        "apiKeyEnv": "TEST_API_KEY",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_model_config(monkeypatch, profiles_file):
    monkeypatch.setenv("TEST_API_KEY", "secret-value")
    config = load_model_config(env_file=None, profiles_file=profiles_file)
    assert config.profile == "test"
    assert config.model == "test-model"
    assert config.api_key == "secret-value"


def test_rejects_placeholder_api_key(monkeypatch, profiles_file):
    monkeypatch.setenv("TEST_API_KEY", "coloque_sua_chave_aqui")
    with pytest.raises(ConfigurationError, match="Substitua o valor de exemplo"):
        load_model_config(env_file=None, profiles_file=profiles_file)


def test_rejects_unknown_profile(monkeypatch, profiles_file):
    monkeypatch.setenv("MODEL_PROFILE", "missing")
    with pytest.raises(ConfigurationError, match="Perfil de modelo desconhecido"):
        load_model_config(env_file=None, profiles_file=profiles_file)


def test_extraction_configuration_is_independent_of_form_model(monkeypatch, profiles_file):
    monkeypatch.setenv("TEST_API_KEY", "secret-value")
    monkeypatch.setenv("MODEL_PROFILE", "another-provider")
    monkeypatch.setenv("LLM_MODEL", "form-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://other.example")
    monkeypatch.setenv("EXTRACTION_MODEL", "extraction-model")
    config = load_model_config(
        env_file=None,
        profiles_file=profiles_file,
        profile_name="test",
        variable_prefix="EXTRACTION",
    )
    assert config.profile == "test"
    assert config.model == "extraction-model"
    assert config.base_url is None


def test_browser_and_agent_settings(monkeypatch):
    monkeypatch.setenv("HEADLESS", "não")
    monkeypatch.setenv("AGENT_MAX_TURNS", "5")
    assert load_browser_config(env_file=None).headless is False
    assert load_agent_max_turns(env_file=None) == 5


def test_rejects_invalid_boolean(monkeypatch):
    monkeypatch.setenv("HEADLESS", "talvez")
    with pytest.raises(ConfigurationError, match="HEADLESS"):
        load_browser_config(env_file=None)
