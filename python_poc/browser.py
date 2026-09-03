from __future__ import annotations

import os
import unicodedata
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Locator, Page, Playwright, async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn").strip().lower()


class BrowserController:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def start(self) -> Page:
        if self.page:
            return self.page
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=os.getenv("HEADLESS", "true").lower() != "false")
        self.page = await self.browser.new_page()
        url = os.getenv("FORM_URL") or (PROJECT_ROOT / "test-form/index.html").as_uri()
        await self.page.goto(url)
        return self.page

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = self.page = self.playwright = None

    async def inspect_form(self) -> dict[str, Any]:
        page = await self.start()
        fields = await page.locator("input, select, textarea").evaluate_all("""els => els.map(c => {
          const labels = c.labels ? [...c.labels].map(x => x.textContent?.trim()).filter(Boolean) : [];
          const tag = c.tagName.toLowerCase(); const type = tag === 'input' ? c.type : tag;
          return {label: labels[0] || c.getAttribute('aria-label') || c.placeholder || c.name || c.id || '(sem rótulo)',
            name: c.name || null, id: c.id || null, type,
            role: c.getAttribute('role') || (type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : tag === 'select' ? 'combobox' : 'textbox'),
            placeholder: c.placeholder || null, required: c.required, disabled: c.disabled,
            ...(tag === 'select' ? {options: [...c.options].map(o => ({label:o.text.trim(), value:o.value}))} : {})};
        })""")
        buttons = await page.locator('button, input[type="submit"], input[type="button"]').evaluate_all("""els => els.map(b => ({
          label: b.getAttribute('aria-label') || b.textContent?.trim() || b.value || b.name || b.id || '(sem rótulo)',
          name:b.name || null, id:b.id || null, type:b.type || 'button', role:'button', disabled:b.disabled}))""")
        return {"url": page.url, "fields": fields, "buttons": buttons}

    @staticmethod
    def _best(query: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
        wanted = normalize(query)
        scored = []
        for element in elements:
            values = [normalize(str(element[k])) for k in ("label", "name", "id", "placeholder") if element.get(k)]
            score = 3 if wanted in values else 1 if any(wanted in value or value in wanted for value in values) else 0
            if score:
                scored.append((score, element))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            raise ValueError(f"Elemento não encontrado semanticamente: {query}")
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            raise ValueError(f"Referência ambígua: {query}")
        return scored[0][1]

    async def _field(self, field: str) -> tuple[dict[str, Any], Locator]:
        inspection = await self.inspect_form()
        meta = self._best(field, inspection["fields"])
        page = await self.start()
        locator = page.get_by_label(meta["label"], exact=True)
        if await locator.count() != 1 and meta.get("name"):
            locator = page.locator(f'[name="{meta["name"]}"]')
        if await locator.count() != 1 and meta.get("id"):
            locator = page.locator(f'[id="{meta["id"]}"]')
        if await locator.count() != 1:
            raise ValueError(f"Campo não localizado unicamente: {field}")
        return meta, locator

    async def fill_field(self, field: str, value: str) -> dict[str, Any]:
        meta, locator = await self._field(field)
        if meta["type"] in ("checkbox", "radio"):
            checked = normalize(value) in ("true", "sim", "yes", "1", "aceito", "marcar")
            await locator.set_checked(checked)
        elif meta["type"] == "select":
            try:
                await locator.select_option(label=value)
            except Exception:
                await locator.select_option(value=value)
        else:
            await locator.fill(value)
        return {"success": True, "field": meta["label"], "value": value}

    async def read_field(self, field: str) -> dict[str, Any]:
        meta, locator = await self._field(field)
        value = await locator.is_checked() if meta["type"] in ("checkbox", "radio") else await locator.input_value()
        return {"success": True, "field": meta["label"], "value": value}

    async def click_button(self, button: str) -> dict[str, Any]:
        inspection = await self.inspect_form()
        meta = self._best(button, inspection["buttons"])
        page = await self.start()
        locator = page.get_by_role("button", name=meta["label"], exact=True)
        await locator.click()
        return {"success": True, "button": meta["label"]}
