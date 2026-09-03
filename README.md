# Python Form Agent

Prova de conceito de um agente baseado em LLM para interpretar instruções em linguagem natural e preencher formulários web com segurança. A aplicação integra um provedor compatível com a API da OpenAI, MCP por `stdio` e Playwright.

## Requisitos

- Python 3.11 ou superior
- Uma chave válida da DeepSeek ou OpenAI
- Chromium instalado pelo Playwright

## Instalação

```bash
git clone git@github.com:joaovv-Vitor/python-form-agent.git
cd python-form-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
playwright install chromium
cp .env.example .env
```

Edite apenas o arquivo `.env` e substitua o valor de exemplo pela sua chave. Nunca adicione credenciais ao `.env.example` ou ao Git.

## Configuração

As principais variáveis disponíveis são:

| Variável | Finalidade | Padrão |
| --- | --- | --- |
| `MODEL_PROFILE` | Perfil definido em `model-profiles.json` | `deepseek` |
| `DEEPSEEK_API_KEY` | Chave usada pelo perfil DeepSeek | obrigatória |
| `LLM_MODEL` | Sobrescreve o modelo do perfil | valor do perfil |
| `LLM_BASE_URL` | Endpoint compatível com OpenAI | valor do perfil |
| `LLM_TIMEOUT_SECONDS` | Timeout das chamadas ao modelo | `60` |
| `FORM_URL` | Formulário que será aberto | formulário local de teste |
| `HEADLESS` | Executa o navegador sem interface | `true` |
| `BROWSER_TIMEOUT_MS` | Timeout do Playwright | `30000` |
| `BROWSER_EXECUTABLE_PATH` | Caminho opcional para outro Chromium | vazio |
| `AGENT_MAX_TURNS` | Limite de ciclos de tools por instrução | `8` |
| `LOG_LEVEL` | Nível dos logs internos | `WARNING` |

## Uso

Com o ambiente virtual ativado:

```bash
form-agent-py
```

Exemplo de instrução sem envio:

```text
Meu nome é João, nasci em 02/11/2002 e moro em Juazeiro do Norte, Ceará.
```

O agente só pode clicar no botão de envio quando a instrução atual pedir isso explicitamente. Expressões como “não envie” bloqueiam o envio mesmo que o modelo solicite a tool.

## Avaliação

Os casos ficam em `evaluation/cases.csv`. Para executar três tentativas por caso:

```bash
EVALUATION_ATTEMPTS=3 form-evaluate-py
```

Os relatórios CSV e HTML são gerados em `reports/`, que não é versionado.

## Qualidade

```bash
# Testes rápidos, sem abrir um navegador real
pytest -m 'not integration'

# Suíte completa
pytest

# Lint e formatação
ruff check .
ruff format --check .

# Análise de tipos
mypy src/form_agent
```

## Estrutura

```text
src/form_agent/
├── core/                 # Domínio: agente, contratos, schemas e erros
├── adapters/             # Integrações OpenAI, MCP e Playwright
├── mcp/server.py         # Tools MCP do navegador
├── evaluation/           # Runner, casos, métricas e relatórios
├── bootstrap.py          # Composição das dependências da aplicação
├── cli.py                # Interface interativa
└── config.py             # Leitura e validação das configurações
tests/
├── unit/                 # Testes rápidos, sem navegador real
└── integration/          # Testes MCP + Playwright
examples/test-form/       # Formulário local usado por padrão
```

## Arquitetura

- `core` contém regras de negócio, contratos e tipos compartilhados; não depende de OpenAI, MCP ou Playwright.
- `adapters` implementa as integrações externas usadas pelos contratos do núcleo.
- `bootstrap.py` monta as dependências comuns à CLI e à avaliação.
- `mcp` e `cli.py` são interfaces de entrada; `evaluation` é um fluxo independente de execução e relatórios.

Erros esperados de configuração, autenticação, conexão e timeout são apresentados de forma amigável. Use `LOG_LEVEL=INFO` ou `LOG_LEVEL=DEBUG` quando precisar investigar uma falha inesperada.
