# Python Form Agent and Audio Agent

Prova de conceito de um agente baseado em LLM para interpretar instruções em linguagem natural e preencher formulários web com segurança. A aplicação integra um provedor compatível com a API da OpenAI, MCP por `stdio` e Playwright.

## Requisitos

- Python 3.12 ou superior
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

## Audio Agent

O Audio Agent transcreve arquivos locais sem microfone e sem integração com MCP. Ele usa
`faster-whisper` por trás de uma abstração, permitindo comparar outros motores de STT no
futuro sem alterar o restante do fluxo.

Instale o extra de áudio:

```bash
python -m pip install -e '.[dev,audio]'
```

Coloque um arquivo `.wav`, `.mp3`, `.m4a` ou `.flac` em `samples/` e execute:

```bash
python -m audio_agent.cli samples/joao.wav --json
# ou
audio-agent-py samples/joao.wav --json
```

O padrão é o modelo `small` em CPU com `int8`. A primeira execução baixa o modelo e pode
demorar mais. Para um experimento reproduzível, informe explicitamente modelo, idioma e
parâmetros de geração:

```bash
audio-agent-py samples/joao.wav --model small --language pt --beam-size 5 --temperature 0
```

`faster-whisper` usa PyAV para decodificar os formatos suportados, então a instalação do
executável `ffmpeg` normalmente não é necessária. Instale-o apenas se precisar converter ou
inspecionar arquivos externamente:

```bash
# Fedora
sudo dnf install ffmpeg

# Debian/Ubuntu
sudo apt install ffmpeg
```

Áudios em `samples/` e `evaluation/audio/audios/` são ignorados pelo Git. O catálogo futuro
de avaliação fica em `evaluation/audio/cases.example.csv` e poderá servir para comparar
`reference_text` com `transcription.text` via WER.

### Fluxo integrado: áudio até o formulário

O Audio Agent e o Form Agent permanecem componentes independentes. Para testar o fluxo
completo, transcreva o áudio e use o texto retornado como instrução do Form Agent. Revise a
transcrição antes de preencher dados reais: reconhecimento de fala pode confundir nomes,
e-mails, telefones e datas.

O formulário só é enviado quando a instrução pede isso explicitamente. Em testes, acrescente
`Não envie nem submeta o formulário em hipótese alguma.` à instrução para garantir que somente
o preenchimento seja verificado.

O teste de integração MCP + Playwright verifica a conexão com o navegador, a inspeção dos
campos, o preenchimento e a leitura de volta de um valor:

```bash
pytest tests/integration/test_mcp_playwright.py -q
```

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

# Teste opcional que baixa/carrega um modelo local e usa samples/joao.wav
RUN_WHISPER_INTEGRATION=1 pytest -m whisper_integration

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
src/audio_agent/
├── agent.py              # Coordena validação e transcrição
├── preprocessing.py      # Validação não destrutiva dos arquivos
├── transcriber.py        # Contrato para motores STT intercambiáveis
├── engines/              # Adaptadores de motores, hoje faster-whisper
├── models.py             # Resultado, segmentos e parâmetros reproduzíveis
└── cli.py                # Interface de linha de comando
```

## Arquitetura

- `core` contém regras de negócio, contratos e tipos compartilhados; não depende de OpenAI, MCP ou Playwright.
- `adapters` implementa as integrações externas usadas pelos contratos do núcleo.
- `bootstrap.py` monta as dependências comuns à CLI e à avaliação.
- `mcp` e `cli.py` são interfaces de entrada; `evaluation` é um fluxo independente de execução e relatórios.

### Transporte MCP local

O agente inicia `form_agent.mcp.server` como subprocesso local e troca mensagens JSON-RPC 2.0
delimitadas por linha via `stdin` e `stdout`. O servidor implementa o handshake MCP, `tools/list`
e `tools/call`; as tools disponíveis são `inspect_form`, `fill_field`, `read_field` e
`click_button`.

Essa implementação não usa `mcp.client.stdio` nem `MCPServer.run(transport="stdio")`. No
Python 3.14, essa camada do SDK apresentou cancelamento do AnyIO entre tasks e bloqueio na
leitura do stdio. O transporte nativo preserva o protocolo MCP e evita essa incompatibilidade.

Erros esperados de configuração, autenticação, conexão e timeout são apresentados de forma amigável. Use `LOG_LEVEL=INFO` ou `LOG_LEVEL=DEBUG` quando precisar investigar uma falha inesperada.
