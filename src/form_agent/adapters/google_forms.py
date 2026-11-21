"""Inspect Google Forms questions, including their custom ARIA controls."""

from urllib.parse import urlsplit

from playwright.async_api import Locator, Page

from ..core.schemas import FormField, JsonObject


def is_google_form(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.hostname == "docs.google.com" and parsed.path.startswith("/forms/")


INSPECT_QUESTIONS = r"""items => {
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/\s*\*\s*$/, '').trim();
  const fields = [];
  for (const item of items) {
    const heading = item.querySelector('[role="heading"]');
    if (!heading || !heading.id) continue;
    const label = clean(heading.textContent);
    const required = Boolean(heading.querySelector('[aria-label="Pergunta obrigatória"]'));
    const base = {label, name: null, id: heading.id, required, disabled: false,
                  readonly: false, validation_message: ''};
    const checks = [...item.querySelectorAll('[role="checkbox"]')];
    if (checks.length) {
      const valid = !required || checks.some(c => c.getAttribute('aria-checked') === 'true');
      for (const control of checks) {
        fields.push({...base, id: control.id, label: label + ' / ' + clean(control.getAttribute('aria-label')),
          required: false, type: 'checkbox', role: 'checkbox', valid,
          disabled: control.getAttribute('aria-disabled') === 'true',
          value: control.getAttribute('aria-checked') === 'true'});
      }
      continue;
    }
    const group = item.querySelector('[role="radiogroup"], [role="listbox"]');
    if (group) {
      const role = group.getAttribute('role');
      const choices = [...group.querySelectorAll(role === 'radiogroup' ? '[role="radio"]' : '[role="option"]')];
      const selected = choices.find(c => c.getAttribute(role === 'radiogroup' ? 'aria-checked' : 'aria-selected') === 'true');
      const value = selected?.getAttribute('data-value') || '';
      const options = [...new Map(choices.map(c => {
        const value = c.getAttribute('data-value') || '';
        return [value, {label: clean(c.getAttribute('aria-label') || c.textContent), value}];
      })).values()].filter(o => o.value);
      fields.push({...base, type: 'select', role, options, value, valid: !required || Boolean(value),
        disabled: group.getAttribute('aria-disabled') === 'true'});
      continue;
    }
    const control = item.querySelector('input:not([type="hidden"]), textarea, select');
    if (!control) continue;
    const value = control.value;
    fields.push({...base, type: control.tagName === 'INPUT' ? control.type : control.tagName.toLowerCase(),
      role: 'textbox', value, disabled: control.disabled, readonly: Boolean(control.readOnly),
      valid: (!required || Boolean(value)) && (!control.willValidate || control.validity.valid),
      validation_message: control.validationMessage || ''});
  }
  return fields;
}"""


async def inspect_fields(scope: Page | Locator) -> list[JsonObject]:
    return await scope.locator('[role="listitem"]').evaluate_all(INSPECT_QUESTIONS)


def field_locator(scope: Page | Locator, meta: FormField) -> Locator:
    import json

    element = scope.locator(f"[id={json.dumps(meta.id)}]")
    if meta.type == "checkbox":
        return element
    question = element.locator('xpath=ancestor::*[@role="listitem"][1]')
    if meta.role == "radiogroup":
        return question.locator('[role="radiogroup"]')
    if meta.role == "listbox":
        return question.locator('[role="listbox"]')
    return question.locator('input:not([type="hidden"]), textarea, select')
