"""Ordered demonstration catalogue and per-session browser destinations."""

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from form_agent.adapters.url_policy import validate_web_url
from form_agent.config import BrowserConfig

from .config import asset


@dataclass(frozen=True)
class DemoForm:
    id: str
    name: str
    description: str
    filename: str

    @property
    def path(self) -> str:
        return f"/forms/{self.id}"

    def public(self, origin: str) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "url": urljoin(origin, self.path),
        }


DEMO_FORMS = (
    DemoForm("cadastro", "Cadastro", "Seu formulário original de cadastro.", "form.html"),
    DemoForm("contato", "Contato", "Assunto, mensagem e preferência de retorno.", "contact.html"),
    DemoForm(
        "inscricao", "Inscrição em evento", "Evento, modalidade e acessibilidade.", "event.html"
    ),
    DemoForm(
        "suporte", "Suporte técnico", "Produto, categoria e prioridade do chamado.", "support.html"
    ),
)


@dataclass(frozen=True)
class FormTarget:
    public_url: str
    name: str
    browser: BrowserConfig
    demo: bool


def resolve_target(
    url: str = "",
    *,
    origin: str = "",
    allowed_hosts: tuple[str, ...] = (),
) -> FormTarget:
    url = url.strip() or urljoin(origin, DEMO_FORMS[0].path)
    parsed = urlsplit(url)
    base = urlsplit(origin)
    same_origin = (parsed.scheme, parsed.netloc) == (base.scheme, base.netloc)
    if not parsed.scheme and not parsed.netloc:
        same_origin = True
    demo = next(
        (form for form in DEMO_FORMS if same_origin and parsed.path.rstrip("/") == form.path), None
    )
    if demo:
        if parsed.query or parsed.fragment:
            raise ValueError("Use a URL do exemplo sem parâmetros adicionais.")
        return FormTarget(
            urljoin(origin, demo.path),
            demo.name,
            BrowserConfig(asset(demo.filename).as_uri(), form_selector="form"),
            True,
        )
    parsed = validate_web_url(url, allowed_hosts)
    return FormTarget(
        url,
        f"Formulário de {parsed.hostname}",
        BrowserConfig(
            url, form_selector="form", restrict_network=True, allowed_hosts=allowed_hosts
        ),
        False,
    )
