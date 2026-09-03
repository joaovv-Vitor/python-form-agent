# Form Agent PoC — Python

Implementação Python independente com DeepSeek/OpenAI-compatible, MCP por stdio, Playwright, avaliação por CSV e relatórios datados.

```bash
cd python-version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
playwright install chromium
cp .env.example .env
```

Adicione sua chave no `.env`. Execute a CLI com `python -m python_poc.cli`, os testes com `pytest -q` e a avaliação com `EVALUATION_ATTEMPTS=3 python -m python_poc.evaluation`.
