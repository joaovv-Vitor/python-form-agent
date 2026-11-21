"""Exercise Google Forms-style ARIA widgets without contacting Google."""

import pytest

from form_agent.adapters import google_forms
from form_agent.adapters.playwright_browser import BrowserController
from form_agent.config import BrowserConfig


@pytest.mark.integration
async def test_google_questions_dates_selections_and_checkbox_round_trip(tmp_path, monkeypatch):
    fixture = tmp_path / "form.html"
    fixture.write_text("""<!doctype html><html lang="pt"><body>
    <div role="listitem"><div role="heading" id="name">Nome <span aria-label="Pergunta obrigatória">*</span></div><input></div>
    <div role="listitem"><div role="heading" id="from">Data de retirada</div><input type="date" aria-label="Data"></div>
    <div role="listitem"><div role="heading" id="to">Data de devolução</div><input type="date" aria-label="Data"></div>
    <div role="listitem"><div role="heading" id="rating">Conteúdo</div><div role="radiogroup">
      <div role="radio" data-value="3" aria-label="3" aria-checked="false" onclick="this.setAttribute('aria-checked','true')">3</div>
      <div role="radio" data-value="4" aria-label="4" aria-checked="false" onclick="this.setAttribute('aria-checked','true')">4</div></div></div>
    <div role="listitem"><div role="heading" id="other">Metodologia</div><div role="radiogroup">
      <div role="radio" data-value="Manhã" aria-label="Manhã" aria-checked="false" onclick="this.setAttribute('aria-checked','true')">Manhã</div></div></div>
    <div role="listitem"><div role="heading" id="equipment">Equipamento</div><div role="listbox" aria-expanded="false">
      <div role="option" data-value="" aria-selected="true">Escolher</div>
      <div role="option" data-value="Projetor" aria-selected="false" onclick="this.parentElement.querySelectorAll('[role=option]').forEach(el=>el.setAttribute('aria-selected',String(el===this)))">Projetor</div></div></div>
    <div role="listitem"><div role="heading" id="accessories">Acessórios</div>
      <div id="hdmi" role="checkbox" aria-label="Cabo HDMI" aria-checked="false" onclick="setTimeout(()=>this.setAttribute('aria-checked',String(this.getAttribute('aria-checked')!=='true')),100)">Cabo HDMI</div>
      <div id="tripod" role="checkbox" aria-label="Tripé" aria-checked="false">Tripé</div></div>
    </body></html>""")
    controller = BrowserController(BrowserConfig(fixture.as_uri()))
    try:
        await controller.start()
        monkeypatch.setattr(google_forms, "is_google_form", lambda url: True)
        initial = await controller.inspect_form()
        assert len(initial.fields) == 8
        assert len({field.reference for field in initial.fields}) == 8
        assert not initial.fields[0].valid
        for label, value in [
            ("Nome", "Ana"),
            ("Data de retirada", "2026-11-20"),
            ("Data de devolução", "2026-11-23"),
            ("Conteúdo", "4"),
            ("Equipamento", "Projetor"),
            ("Acessórios / Cabo HDMI", "true"),
            ("Acessórios / Cabo HDMI", "true"),
        ]:
            result = await controller.fill_field(label, value)
            assert result["value"] == (True if value == "true" else value)
        assert (await controller.read_field("Metodologia"))["value"] == ""
        assert (await controller.fill_field("Metodologia", "Manhã"))["value"] == "Manhã"
        assert (await controller.read_field("Acessórios / Tripé"))["value"] is False
        assert (await controller.fill_field("Acessórios / Cabo HDMI", "false"))["value"] is False
        assert (await controller.click_button("Enviar"))["code"] == "SUBMISSION_BLOCKED"
    finally:
        await controller.close()
