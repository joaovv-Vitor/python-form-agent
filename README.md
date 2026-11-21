# VozForm

Prova de conceito de TCC para preencher formulários web por voz. A VozForm
transcreve o áudio com Whisper, interpreta os valores e os associa aos campos do
formulário. O usuário pode conferir o preenchimento e solicitar correções por
texto ou por áudio.

| Interface | Uso |
| --- | --- |
| [Aplicação web](docs/web-v1.md) | Demonstração com quatro formulários integrados e suporte a URLs de formulários HTML compatíveis. O envio dos exemplos é simulado. |
| [Extensão para Chrome](docs/chrome-extension.md) | Preenchimento e revisão na aba selecionada. O usuário envia a resposta pelo botão do próprio site. |
| [Linha de comando](docs/guia-cli.md) | Transcrição isolada, preenchimento por texto ou áudio e avaliações em lote. |

## Executar localmente

A aplicação web requer Python 3.12+, Node.js 22.12+ (24 recomendado) e Chromium
do Playwright. Para preencher formulários, configure no servidor uma chave do
provedor de modelo de linguagem escolhido. A transcrição isolada roda localmente
sem a chave.

Na raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[audio,web]'
python -m playwright install chromium
cp .env.example .env
```

Informe a chave no `.env`. O perfil padrão usa `DEEPSEEK_API_KEY`. Os perfis
disponíveis estão em [model-profiles.json](model-profiles.json).

```bash
(cd frontend && npm ci && npm run build)
HF_HUB_CACHE=reports/model-cache form-web-py
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000) para testar o Cadastro com
um áudio fictício. O primeiro uso do Whisper pode baixar os pesos do modelo.
O endpoint `/api/health` verifica se o servidor responde.

Para usar o Chrome com o servidor em execução, compile a extensão:

```bash
(cd frontend && npm run build:extension)
```

Em `chrome://extensions`, ative o modo do desenvolvedor e carregue
`extension/dist` como extensão sem compactação. O [guia da extensão](docs/chrome-extension.md)
descreve a seleção da aba, a permissão do microfone e a revisão.

## Avaliação do TCC

As duas rodadas comparam quatro variantes do Whisper e três formas de tratar a
transcrição antes do preenchimento. As execuções automatizadas usaram cinco
gravações e foram realizadas pela CLI, com envio desabilitado.

- [Resultados agregados, recorte e comandos de reprodução](docs/resultados-tcc.md)
- [Método, critérios de pontuação e rastreabilidade](docs/experimentos.md)
- [Catálogos de exemplo e orientação para preparar os áudios](evaluation/audio/README.md)

As gravações e os registros detalhados ficam fora do controle de versão. Os
fluxos de preenchimento podem transmitir transcrições e dados dos campos ao
provedor configurado e gravá-los em relatórios locais. Use dados fictícios nos
testes públicos.

## Estrutura

| Diretório | Conteúdo |
| --- | --- |
| [src/audio_agent](src/audio_agent) | Preparação, transcrição e CLI de áudio |
| [src/form_agent](src/form_agent) | Agente de formulário, ferramentas, automação e avaliação textual |
| [src/voice_form](src/voice_form) | Integração entre transcrição e preenchimento e comparações experimentais |
| [src/web_api](src/web_api) | API, sessões e formulários de demonstração |
| [frontend](frontend) e [extension](extension) | Interface web e extensão para Chrome |
| [examples](examples) e [evaluation](evaluation) | Formulários e catálogos de exemplo |
| [tests](tests) | Testes Python e de integração |
| [docs](docs) e [deploy](deploy) | Guias, documentação técnica e configuração de implantação |

## Verificar o projeto

Instale as dependências de desenvolvimento no ambiente virtual e execute:

```bash
python -m pip install -e '.[dev]'
python -m pytest -m 'not integration'
ruff check src tests
ruff format --check src tests
mypy
(cd frontend && npm ci && npm test && npm run format:check)
```

Para os testes de integração, compile a aplicação web, instale Chromium e use
`python -m pytest`. Consulte a [referência de testes](docs/comandos.md#testes-e-qualidade)
para os pré-requisitos e a integração opcional com Whisper.

Mais detalhes no [índice de documentação](docs/README.md).
