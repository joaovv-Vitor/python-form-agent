from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence

from playwright.async_api import Browser, Locator, Page, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ..config import BrowserConfig, load_browser_config
from ..core.errors import AmbiguousElementError, BrowserControllerError, ElementNotFoundError
from ..core.schemas import FormButton, FormField, FormInspection, JsonObject

FIELD_INSPECTION_SCRIPT = r"""els => els.map(control => {
  const labels = control.labels
    ? [...control.labels].map(label => label.textContent?.trim()).filter(Boolean)
    : [];
  const root = control.getRootNode();
  const indirectLabel = (control.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map(id => root.getElementById?.(id)?.textContent?.trim()).filter(Boolean).join(' ');
  const tag = control.tagName.toLowerCase();
  const type = tag === 'input' ? control.type : tag;
  return {
    label: indirectLabel || control.getAttribute('aria-label') || labels[0] || control.placeholder || control.name || control.id || '(sem rótulo)',
    name: control.name || null,
    id: control.id || null,
    type,
    role: control.getAttribute('role') || (type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : tag === 'select' ? 'combobox' : 'textbox'),
    placeholder: control.placeholder || null,
    required: control.required,
    disabled: control.matches(':disabled'),
    readonly: Boolean(control.readOnly),
    value: ['checkbox', 'radio'].includes(type) ? control.checked : control.value,
    valid: control.willValidate ? control.validity.valid : null,
    validation_message: control.validationMessage || '',
    ...(tag === 'select' ? {options: [...control.options].map(option => ({label: option.text.trim(), value: option.value}))} : {})
  };
})"""

BUTTON_INSPECTION_SCRIPT = """els => els.map(button => ({
  label: button.getAttribute('aria-label') || button.textContent?.trim() || button.value || button.name || button.id || '(sem rótulo)',
  name: button.name || null,
  id: button.id || null,
  type: button.type || 'button',
  role: 'button',
  disabled: button.disabled
}))"""


def normalize(value: str) -> str:
    return (
        "".join(
            character
            for character in unicodedata.normalize("NFD", value)
            if unicodedata.category(character) != "Mn"
        )
        .strip()
        .lower()
    )


class BrowserController:
    def __init__(self, config: BrowserConfig | None = None) -> None:
        self.config = config or load_browser_config()
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.submission_authorized = False

    async def start(self) -> Page:
        if self.page is not None:
            return self.page
        try:
            self.playwright = await async_playwright().start()
            if self.config.executable_path:
                self.browser = await self.playwright.chromium.launch(
                    headless=self.config.headless,
                    executable_path=self.config.executable_path,
                )
            else:
                self.browser = await self.playwright.chromium.launch(headless=self.config.headless)
            self.page = await self.browser.new_page()
            self.page.set_default_timeout(self.config.timeout_ms)
            await self.page.goto(self.config.url, wait_until="domcontentloaded")
            return self.page
        except Exception as exc:
            await self.close()
            raise BrowserControllerError(
                f"Não foi possível abrir o formulário em {self.config.url}."
            ) from exc

    async def close(self) -> None:
        browser, playwright = self.browser, self.playwright
        self.browser = None
        self.page = None
        self.playwright = None
        try:
            if browser is not None:
                await browser.close()
        finally:
            if playwright is not None:
                await playwright.stop()

    async def inspect_form(self) -> FormInspection:
        page = await self.start()
        raw_fields = await page.locator(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="image"]):visible, select:visible, textarea:visible'
        ).evaluate_all(FIELD_INSPECTION_SCRIPT)
        raw_buttons = await page.locator(
            'button:visible, input[type="submit"]:visible, input[type="button"]:visible'
        ).evaluate_all(BUTTON_INSPECTION_SCRIPT)
        return FormInspection.from_mapping(
            {"url": page.url, "fields": raw_fields, "buttons": raw_buttons}
        )

    @staticmethod
    def _best(
        query: str,
        elements: Sequence[FormField | FormButton],
    ) -> FormField | FormButton:
        wanted = normalize(query)
        if not wanted:
            raise ElementNotFoundError("A referência ao elemento não pode ser vazia.")
        scored: list[tuple[int, FormField | FormButton]] = []
        for element in elements:
            values = [
                normalize(value)
                for value in (
                    element.label,
                    element.name,
                    element.id,
                    getattr(element, "placeholder", None),
                )
                if value
            ]
            score = (
                3
                if wanted in values
                else 1
                if len(wanted) >= 3 and any(wanted in value for value in values if len(value) >= 3)
                else 0
            )
            if score:
                scored.append((score, element))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            raise ElementNotFoundError(f"Elemento não encontrado semanticamente: {query}")
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            raise AmbiguousElementError(f"Referência ambígua: {query}")
        return scored[0][1]

    async def _field(self, field: str) -> tuple[FormField, Locator]:
        inspection = await self.inspect_form()
        meta = self._best(field, inspection.fields)
        if not isinstance(meta, FormField):
            raise ElementNotFoundError(f"Campo não encontrado: {field}")
        if meta.disabled:
            raise BrowserControllerError(f"O campo está desabilitado: {meta.label}")
        page = await self.start()
        locator = page.get_by_label(meta.label, exact=True).filter(visible=True)
        if await locator.count() != 1 and meta.name:
            locator = page.locator(f"[name={json.dumps(meta.name)}]").filter(visible=True)
        if await locator.count() != 1 and meta.id:
            locator = page.locator(f"[id={json.dumps(meta.id)}]").filter(visible=True)
        if await locator.count() != 1 and meta.placeholder:
            locator = page.get_by_placeholder(meta.placeholder, exact=True).filter(visible=True)
        if await locator.count() != 1:
            raise AmbiguousElementError(f"Campo não localizado unicamente: {field}")
        return meta, locator

    async def fill_field(self, field: str, value: str) -> JsonObject:
        meta, locator = await self._field(field)
        if meta.readonly:
            raise BrowserControllerError(f"O campo é somente leitura: {meta.label}")
        if meta.type in ("checkbox", "radio"):
            if normalize(value) not in {
                "true",
                "sim",
                "yes",
                "1",
                "aceito",
                "marcar",
                "false",
                "nao",
                "no",
                "0",
            }:
                raise ValueError("Checkbox/radio requer valor booleano explícito")
            checked = normalize(value) in ("true", "sim", "yes", "1", "aceito", "marcar")
            await locator.set_checked(checked)
        elif meta.type == "select":
            wanted = normalize(value)
            option = next(
                (
                    item
                    for item in meta.options
                    if wanted in {normalize(item.label), normalize(item.value)}
                ),
                None,
            )
            if option is None:
                raise ElementNotFoundError(f"Opção não encontrada em {meta.label}: {value}")
            await locator.select_option(value=option.value)
        else:
            await locator.fill(value)
        return await self.read_field(meta.reference)

    async def read_field(self, field: str) -> JsonObject:
        meta, locator = await self._field(field)
        value = (
            await locator.is_checked()
            if meta.type in ("checkbox", "radio")
            else await locator.input_value()
        )
        return {
            "success": True,
            "field": meta.label,
            "field_ref": meta.reference,
            "value": value,
            "valid": meta.valid,
            "validation_message": meta.validation_message,
        }

    async def click_button(self, button: str) -> JsonObject:
        if not self.submission_authorized:
            return {
                "success": False,
                "code": "SUBMISSION_BLOCKED",
                "error": "Autorização externa necessária",
            }
        inspection = await self.inspect_form()
        meta = self._best(button, inspection.buttons)
        if not isinstance(meta, FormButton):
            raise ElementNotFoundError(f"Botão não encontrado: {button}")
        if meta.type != "submit":
            return {
                "success": False,
                "code": "SUBMISSION_BLOCKED",
                "error": "Somente botões submit nativos são autorizados",
            }
        if meta.disabled:
            raise BrowserControllerError(f"O botão está desabilitado: {meta.label}")
        page = await self.start()
        locator = page.get_by_role("button", name=meta.label, exact=True)
        if await locator.count() != 1:
            raise AmbiguousElementError(f"Botão não localizado unicamente: {button}")
        valid = await locator.evaluate(
            "button => button.form && [...button.form.elements].every(el => !el.willValidate || el.validity.valid)"
        )
        if not valid:
            return {
                "success": False,
                "code": "VALIDATION_ERROR",
                "error": "O formulário contém campos inválidos",
            }
        success = page.locator(self.config.submission_success_selector)
        if await success.count() and await success.first.is_visible():
            return {
                "success": False,
                "code": "SUBMISSION_ERROR",
                "error": "O indicador de envio já estava presente; não é evidência de novo envio",
            }
        # Consume permission before the side effect: uncertain outcomes must not be retried.
        self.submission_authorized = False
        try:
            await locator.click()
            await success.wait_for(state="visible")
        except PlaywrightTimeoutError:
            return {
                "success": False,
                "code": "SUBMISSION_ERROR",
                "error": "Envio sem confirmação observável (timeout)",
                "submission_attempted": True,
                "submitted": False,
            }
        except Exception:
            return {
                "success": False,
                "code": "SUBMISSION_ERROR",
                "error": "Falha durante o clique; resultado incerto",
                "submission_attempted": True,
                "submitted": False,
            }
        return {
            "success": True,
            "button": meta.label,
            "submission_attempted": True,
            "submitted": True,
        }
