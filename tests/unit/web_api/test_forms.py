import socket
from unittest.mock import AsyncMock

import pytest

from form_agent.adapters.url_policy import validate_network_url, validate_web_url
from web_api.config import asset
from web_api.forms import DEMO_FORMS, resolve_target


def test_original_form_is_first_and_unchanged():
    from form_agent.config import PROJECT_ROOT

    assert DEMO_FORMS[0].id == "cadastro"
    assert resolve_target().browser.url == asset("form.html").as_uri()
    assert (
        asset("form.html").read_bytes()
        == (PROJECT_ROOT / "examples/test-form/index.html").read_bytes()
    )


@pytest.mark.parametrize("demo", DEMO_FORMS)
def test_catalogue_url_resolves_to_the_matching_packaged_form(demo):
    target = resolve_target(f"https://vozform.example{demo.path}", origin="https://vozform.example")
    assert target.demo and target.name == demo.name
    assert target.browser.url == asset(demo.filename).as_uri()
    assert target.browser.form_selector == "form"
    assert asset(demo.filename).is_file()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,test",
        "ftp://example.com",
        "http://localhost/form",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.1/",
        "http://[::1]/",
        "https://user:password@example.com/",
        "https://example.com:99999/",
        "https://example.com\\@127.0.0.1/",
        "https://exa mple.com/",
    ],
)
def test_custom_destination_rejects_invalid_schemes_credentials_and_local_networks(url):
    with pytest.raises(ValueError):
        resolve_target(url, origin="https://vozform.example")


def test_external_form_preserves_url_without_enabling_simulated_submission():
    url = "https://example.com/contact?language=pt"
    target = resolve_target(url)
    assert target.public_url == target.browser.url == url
    assert not target.demo and target.browser.restrict_network


def test_operator_can_enable_a_controlled_local_host():
    target = resolve_target("http://localhost:8080/form", allowed_hosts=("localhost",))
    assert not target.demo and target.browser.allowed_hosts == ("localhost",)


async def test_dns_resolution_cannot_turn_public_hostname_into_private_destination(monkeypatch):
    import asyncio

    loop = asyncio.get_running_loop()
    resolver = AsyncMock(
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    )
    monkeypatch.setattr(loop, "getaddrinfo", resolver)
    with pytest.raises(ValueError, match="rede não habilitada"):
        await validate_network_url("https://example.com/form")


async def test_public_dns_addresses_are_accepted(monkeypatch):
    import asyncio

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            ]
        ),
    )
    await validate_network_url("https://example.com/form")
    assert validate_web_url("https://example.com/form").hostname == "example.com"
