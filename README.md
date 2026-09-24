# Python Form Agent and Audio Agent

PoC acadêmica em Python para investigar reconhecimento de fala e preenchimento de
formulários web com um agente baseado em LLM. Mantém interfaces independentes para LLM,
STT e ferramentas, MCP local por stdio e Playwright encapsulado. O áudio pode ser usado
isoladamente ou composto com o Form Agent.

Consulte a [referência completa de comandos](docs/comandos.md) para instalação, execução,
avaliação do dataset, parâmetros do Whisper, testes e geração de relatórios.

## Instalação

Requer Python 3.12+, Chromium do Playwright e credenciais de um provider compatível para
os fluxos com LLM. A avaliação somente STT não requer credenciais nem navegador.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,audio]'
playwright install chromium
cp .env.example .env
```

Edite `.env` e selecione/configure o perfil em `model-profiles.json`. Não versione chaves.
O extra `audio` é opcional para quem só usa texto. O primeiro uso de um modelo Whisper
pode baixar pesos; registre e separe o tempo de carregamento das execuções seguintes.
Após atualizar este checkout, execute novamente `python -m pip install -e . --no-deps`
para instalar os novos entry points no venv existente.

## Uso por texto

```bash
form-agent-py
# equivalente:
python -m form_agent.cli
```

Digite, por exemplo: `Meu nome é Pessoa Alfa e moro em Quixadá, Ceará. Não envie.`
A CLI exibe os valores observados. Quando a instrução sugere envio, oferece uma confirmação
separada **depois** do preenchimento: é necessário digitar `ENVIAR`. Texto, transcrição e
LLM não concedem permissão por si mesmos. A negação continua sendo um veto conservador.

## Uso por áudio

Transcrição isolada, sem MCP/Playwright:

```bash
audio-agent-py samples/exemplo.wav --language pt --model small --json
python -m audio_agent.cli samples/exemplo.wav --language pt
```

Composição completa:

```bash
voice-form-agent-py samples/exemplo.wav --language pt --model small --json
# Com revisão humana e possibilidade de envio após preencher:
voice-form-agent-py samples/exemplo.wav --language pt --confirm-submit
# Equivalente por módulo:
python -m voice_form.cli samples/exemplo.wav --language pt
```

A transcrição original é encaminhada ao FormAgent. Falha STT ou texto vazio impedem o
preenchimento. Sem `--confirm-submit`, a CLI de voz não pede envio. Essa opção solicita
confirmação humana; não concede autorização ao LLM. `--json` e `--confirm-submit` são
mutuamente exclusivos. Recursos são fechados ao terminar a CLI de voz.

Ambos os comandos de áudio aceitam `--model`, `--language`, `--device cpu|cuda`,
`--compute-type`, `--beam-size`, `--temperature` e `--vad-filter`. Padrões: small, idioma
por detecção, CPU/int8, beam size 5, temperatura 0, VAD desativado. O adaptador usa PyAV
para decodificar WAV/MP3/MP4/M4A/FLAC; a preparação não aplica limpeza ou correção automática.

## Avaliação

Cada tentativa de formulário usa uma sessão nova. CSV/HTML e eventos JSONL são escritos
em `reports/` (ignorado pelo Git). Os comandos retornam 0 quando o lote termina e os
relatórios são gerados, mesmo com casos FAIL; 2 indica erro de configuração/execução do
comando. Consulte taxas e linhas, não apenas o código de saída do lote.

Texto, preservando o catálogo anterior:

```bash
form-evaluate-py --attempts 3
# Variáveis existentes continuam funcionando:
EVALUATION_ATTEMPTS=3 form-evaluate-py
# Casos autorizados a enviar no ambiente experimental controlado:
form-evaluate-py --attempts 3 --allow-submission
```

Três experimentos com o **mesmo catálogo de áudio**:

```bash
# A: somente reconhecimento de fala
# Após gravar os arquivos e revisar o catálogo:
audio-evaluate-py --cases evaluation/audio/cases.csv --language pt --model small

# B: texto de referência, sem executar STT
pipeline-evaluate-py --cases evaluation/audio/cases.csv --mode reference --attempts 3

# C: áudio → STT → Form Agent → navegador
pipeline-evaluate-py --cases evaluation/audio/cases.csv --mode pipeline --language pt --attempts 3
```

Para um dataset externo com `metadata.csv` nas colunas
`id,speaker,file,category,transcription`, use o diretório diretamente. O nome-base em `file`
é associado à gravação encontrada mesmo que o catálogo declare WAV e o arquivo seja MP4.
Entradas ainda sem gravação são informadas e ignoradas:

```bash
audio-evaluate-py --dataset ../dataset --attempts 3 --language pt \
  --model small --device cpu --compute-type int8
```

Troque `--model` por `base`, `small` ou `medium`. Esse catálogo mede STT (WER, CER, latência
e RTF); os parâmetros do Whisper ficam registrados em cada linha e o modelo aparece no nome
do relatório. Para `reference`/`pipeline`, use `--cases` com o formato completo, incluindo
`expected_json`, pois a transcrição sozinha não define o estado esperado do formulário.

`--allow-submission` exige também `submission_authorized=true` no caso. A coluna
`submitted` é a expectativa do avaliador, independente da permissão. Sem a flag, casos
que esperam envio falham nessa dimensão de propósito. CLI e avaliação não inferem
permissão a partir de uma palavra reconhecida pelo STT.

O [catálogo de exemplo](evaluation/audio/cases.example.csv) contém **19 roteiros fictícios,
sem gravações**. Copie para `cases.csv`, grave/revise as referências e mantenha os áudios
em armazenamento autorizado. Arquivos ausentes geram STT_ERROR e não resultados fictícios.
A [proposta de dataset](evaluation/audio/README.md) explica coleta, privacidade e oráculos.

Métricas existentes: precision, recall, F1, pass rate, estabilidade, média/P95 de latência,
casos e tentativas. A extensão inclui sucesso funcional, mudanças extras, códigos de erro,
WER/CER, processamento STT, RTF e tempo do FormAgent/total. Relatórios cruzam WER zero/positivo
com sucesso/falha funcional. WER positivo não é automaticamente uma falha do pipeline.

A comparação funcional agora usa valores DOM exatos e verifica estados antes/depois;
resultados antigos não devem ser misturados sem reexecução. Veja as [definições e limites
das métricas](docs/experimentos.md), inclusive denominadores, silêncio e análise causal.

## Configuração

| Variável | Finalidade | Padrão |
|---|---|---|
| MODEL_PROFILE | Perfil de `model-profiles.json` | perfil padrão do arquivo |
| MODEL_PROFILES_FILE | Outro arquivo de perfis | `model-profiles.json` |
| LLM_API_KEY / chave do perfil | Credencial | obrigatória para LLM |
| LLM_MODEL | Sobrescreve modelo do perfil | perfil |
| LLM_BASE_URL | Endpoint compatível | perfil |
| LLM_TIMEOUT_SECONDS | Timeout do provider | 60 |
| LLM_TEMPERATURE | Temperatura opcional, quando suportada | omitida, padrão do provider |
| FORM_PROMPT_VERSION | Prompt empacotado | `form-agent-v2` |
| FORM_URL | Formulário de destino | exemplo local |
| HEADLESS | Navegador sem janela | true |
| BROWSER_TIMEOUT_MS | Timeout de automação | 30000 |
| BROWSER_EXECUTABLE_PATH | Chromium alternativo | vazio |
| SUBMISSION_SUCCESS_SELECTOR | Indicador DOM de envio confirmado | `[data-form-agent-submitted="true"]` |
| AGENT_MAX_TURNS | Limite de turnos LLM | 8 |
| EVALUATION_ATTEMPTS | Tentativas no executor textual | 3 |
| EVALUATION_CASES_FILE | Catálogo textual alternativo | `evaluation/cases.csv` |
| LOG_LEVEL | Logging operacional | WARNING |

O indicador de envio precisa de um contrato por formulário. Clique não prova envio, e um
indicador DOM não prova gravação no backend. Somente submit nativo é suportado. A política
protege as tools do host; scripts de páginas arbitrárias podem ter efeitos próprios ao
preencher. Use formulários controlados no experimento. [Modelo de ameaça e autorização](docs/experimentos.md).

## Rastreabilidade e reprodução

Cada execução salva os valores observados em `form_data.json`, em uma pasta com seu run ID:
`reports/manual/<run_id>/` para uso da CLI ou do áudio e `reports/tests/<run_id>/` para
avaliações. O arquivo inclui os campos alterados (`filled_fields`), o estado final dos
campos (`form_fields`), a instrução, a transcrição quando houver e, nas avaliações,
os dados esperados e obtidos. O caminho do JSONL correspondente fica em `trace_path`.
Se uma execução parar antes da inspeção final, os campos escritos com sucesso até esse
ponto ainda são registrados. O parâmetro `--output` das avaliações muda a pasta base;
`--trace-directory` da CLI de voz salva `manual/` ao lado da pasta de rastros escolhida.

Cada JSONL em `reports/runs/` tem run ID, sequência, timestamps UTC, eventos e manifesto.
Registra versão/hash do código e prompt, parâmetros, dependências, provider, configurações
STT, hashes do CSV/áudio/formulário local e resultados. A chave da API é excluída. Traces
contêm transcrições e valores; não versionar dados pessoais ou gravações sem o protocolo de coleta.

```bash
python -m pip freeze > reports/requirements-run.txt
```

Retenha também a versão exata do código e dos artefatos: hash e commit com árvore suja não
reconstroem arquivos. `FORM_PROMPT_VERSION=form-agent-v1` permite comparar o prompt anterior
sob as novas travas de execução. Retries do provider são explicitamente zero.

## Qualidade

```bash
pytest -m 'not integration'
pytest
ruff check .
ruff format --check .
mypy

# Teste caro opcional (não faz parte do ciclo rápido):
RUN_WHISPER_INTEGRATION=1 WHISPER_TEST_AUDIO=samples/exemplo.wav pytest -m whisper_integration
```

A suíte comum não chama LLM real nem baixa Whisper. Integrações usam Chromium local;
um teste compõe STT/LLM simulados com MCP/Playwright reais. No sandbox desta sessão,
Chromium e o despertar de `asyncio.to_thread` exigiram executar os testes fora da restrição.
Essa limitação de ambiente não foi contornada com alterações no código ou mocks adicionais.

## Estrutura e documentação

```text
src/audio_agent/          # validação, contrato STT, modelos, adaptador e CLI
src/form_agent/core/      # agente, políticas, contratos, resultados, eventos
src/form_agent/adapters/  # OpenAI compatível, cliente MCP e BrowserController
src/form_agent/mcp/       # servidor local JSON-RPC, tools e controle de autorização
src/form_agent/prompts/   # prompts versionados e empacotados
src/form_agent/evaluation/ # casos, scoring, métricas, relatórios e executor textual
src/form_agent/experiments.py # manifesto e escritor JSONL local
src/voice_form/           # composição, CLI e avaliação A/B/C
examples/                # formulário base e fixture adversarial nativa
```

- [Auditoria inicial e plano incremental](docs/auditoria-inicial.md)
- [Arquitetura, agência, métricas e metodologia](docs/experimentos.md)
- [Referência completa de comandos](docs/comandos.md)
- [43 cenários de formulário e 20 condições de áudio](docs/cenarios-adversariais.md)
- [Dataset proposto e protocolo de coleta](evaluation/audio/README.md)
- [Auditoria final e validação](docs/auditoria-final.md)

O transporte MCP próprio foi preservado: subprocesso e JSON-RPC por linhas, com locks,
timeout, drenagem de stderr, validação de envelopes e fechamento controlado. A incompatibilidade
anterior de SDK/AnyIO em Python 3.14 não exige substituir as outras camadas.

A nomenclatura das classes e do projeto foi mantida. Conceitualmente, esta implementação
é melhor descrita como agente de formulário composto com um pipeline STT; a alegação de
sistema multiagente requer uma fundamentação adicional, discutida na documentação.
