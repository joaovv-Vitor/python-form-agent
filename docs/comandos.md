# Referência de comandos

Execute os comandos a partir da raiz do projeto. Antes de qualquer execução, ative o
ambiente virtual:

```bash
source .venv/bin/activate
```

## Instalação e atualização do ambiente

Criação completa do ambiente:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,audio]'
playwright install chromium
cp .env.example .env
```

Depois, edite `.env` e informe a chave do provider selecionado. Para reinstalar somente os
entry points após atualizar o código:

```bash
python -m pip install -e . --no-deps
```

Para conferir as dependências instaladas:

```bash
python -m pip check
python -m pip freeze
```

## Agente de formulário por texto

Inicia a interface interativa:

```bash
form-agent-py
```

Comando equivalente pelo módulo Python:

```bash
python -m form_agent.cli
```

Digite uma instrução em português e pressione Enter. Use `sair` para encerrar. Quando houver
pedido de envio, a CLI solicita uma confirmação separada e só aceita a palavra `ENVIAR`.

Exemplo de instrução:

```text
Meu nome é Pessoa Alfa e moro em Quixadá, Ceará. Não envie.
```

## Transcrição de um áudio

Transcreve WAV, MP3, MP4, M4A ou FLAC sem abrir navegador ou chamar o LLM:

```bash
audio-agent-py caminho/para/audio.mp4 \
  --language pt \
  --model small \
  --device cpu \
  --compute-type int8
```

Comando equivalente pelo módulo Python:

```bash
python -m audio_agent.cli caminho/para/audio.mp4 --language pt --model small
```

Para receber a resposta estruturada em JSON:

```bash
audio-agent-py caminho/para/audio.mp4 --language pt --model small --json
```

Para exibir logs detalhados:

```bash
audio-agent-py caminho/para/audio.mp4 --language pt --model small --verbose
```

## Preenchimento de formulário por áudio

Executa áudio → Whisper → Form Agent → navegador:

```bash
voice-form-agent-py caminho/para/audio.mp4 \
  --language pt \
  --model small \
  --device cpu \
  --compute-type int8
```

Comando equivalente pelo módulo Python:

```bash
python -m voice_form.cli caminho/para/audio.mp4 --language pt --model small
```

Para produzir JSON:

```bash
voice-form-agent-py caminho/para/audio.mp4 --language pt --model small --json
```

Para solicitar confirmação humana antes de um possível envio:

```bash
voice-form-agent-py caminho/para/audio.mp4 \
  --language pt \
  --model small \
  --confirm-submit
```

`--json` e `--confirm-submit` não podem ser usados juntos. Para escolher onde os traces serão
gravados:

```bash
voice-form-agent-py caminho/para/audio.mp4 \
  --trace-directory reports/runs \
  --language pt \
  --model small
```

## Opções do Whisper

`audio-agent-py`, `voice-form-agent-py`, `audio-evaluate-py` e `pipeline-evaluate-py`
aceitam as opções abaixo.

| Opção | Padrão | Finalidade |
|---|---:|---|
| `--model MODEL` | `small` | Modelo Whisper ou caminho/ID compatível com faster-whisper. |
| `--language LANGUAGE` | detecção automática | Idioma esperado, por exemplo `pt`. |
| `--device cpu\|cuda` | `cpu` | Dispositivo usado na inferência. |
| `--compute-type TYPE` | `int8` | Quantização, como `int8` em CPU ou `float16` em CUDA. |
| `--beam-size N` | `5` | Quantidade de hipóteses mantidas durante a decodificação. |
| `--temperature VALUE` | `0.0` | Temperatura da decodificação. |
| `--vad-filter` | desativado | Remove trechos classificados como silêncio antes da transcrição. |

No Mac M1 Pro, use `--device cpu --compute-type int8`. O projeto não oferece `mps` como
dispositivo. Os modelos são baixados automaticamente e ficam no cache local.

Comandos recomendados para comparar os três modelos instalados:

```bash
audio-agent-py caminho/para/audio.mp4 --language pt --model base --device cpu --compute-type int8
audio-agent-py caminho/para/audio.mp4 --language pt --model small --device cpu --compute-type int8
audio-agent-py caminho/para/audio.mp4 --language pt --model medium --device cpu --compute-type int8
```

- `base`: referência rápida, com menor custo de processamento.
- `small`: configuração principal recomendada para o projeto.
- `medium`: maior prioridade para precisão, com execução mais lenta.

## Avaliação do Form Agent por texto

Executa cada caso de `evaluation/cases.csv` três vezes:

```bash
form-evaluate-py --attempts 3
```

Escolha outro catálogo ou diretório de saída:

```bash
form-evaluate-py \
  --cases caminho/para/cases.csv \
  --attempts 3 \
  --output reports
```

Também é possível definir as tentativas por variável de ambiente:

```bash
EVALUATION_ATTEMPTS=3 form-evaluate-py
```

Para os casos controlados que esperam submissão:

```bash
form-evaluate-py --attempts 3 --allow-submission
```

Além da flag, o caso precisa ter `submission_authorized=true` no catálogo.

## Avaliação STT com o dataset externo

O diretório deve conter `metadata.csv` com estas colunas:

```text
id,speaker,file,category,transcription
```

Executa cada áudio disponível três vezes usando `small`:

```bash
audio-evaluate-py \
  --dataset ../dataset \
  --attempts 3 \
  --language pt \
  --model small \
  --device cpu \
  --compute-type int8
```

O comando associa o nome-base informado no CSV ao arquivo gravado. Assim, uma entrada como
`spk02_01_common.wav` pode usar a gravação `spk02_01_common.mp4`. Entradas do catálogo ainda
sem gravação são contabilizadas na tela e ignoradas na avaliação.

Comparação entre os três modelos:

```bash
audio-evaluate-py --dataset ../dataset --attempts 3 --language pt --model base --device cpu --compute-type int8
audio-evaluate-py --dataset ../dataset --attempts 3 --language pt --model small --device cpu --compute-type int8
audio-evaluate-py --dataset ../dataset --attempts 3 --language pt --model medium --device cpu --compute-type int8
```

Com detecção de silêncio habilitada:

```bash
audio-evaluate-py \
  --dataset ../dataset \
  --attempts 3 \
  --language pt \
  --model small \
  --device cpu \
  --compute-type int8 \
  --vad-filter
```

Para escolher o diretório dos relatórios:

```bash
audio-evaluate-py \
  --dataset ../dataset \
  --attempts 3 \
  --language pt \
  --model small \
  --output reports/small
```

Essa execução mede reconhecimento de fala: WER, CER, tempo de STT, latência e RTF. A
configuração do Whisper aparece em cada linha e o modelo faz parte do nome do relatório.

O dataset atual não possui `expected_json`, portanto não contém o oráculo necessário para
avaliar o preenchimento do formulário. Para os modos `reference` e `pipeline`, use o catálogo
completo descrito na próxima seção.

## Avaliação com catálogo completo de áudio

O catálogo de `--cases` contém áudio, texto de referência, formulário e `expected_json`.

Modo A, somente reconhecimento de fala:

```bash
audio-evaluate-py \
  --cases evaluation/audio/cases.csv \
  --attempts 3 \
  --language pt \
  --model small
```

Modo B, texto humano de referência → Form Agent, sem executar Whisper:

```bash
pipeline-evaluate-py \
  --cases evaluation/audio/cases.csv \
  --mode reference \
  --attempts 3
```

Modo C, áudio → Whisper → Form Agent → navegador:

```bash
pipeline-evaluate-py \
  --cases evaluation/audio/cases.csv \
  --mode pipeline \
  --attempts 3 \
  --language pt \
  --model small \
  --device cpu \
  --compute-type int8
```

Para permitir submissões previstas pelo catálogo:

```bash
pipeline-evaluate-py \
  --cases evaluation/audio/cases.csv \
  --mode pipeline \
  --attempts 3 \
  --language pt \
  --model small \
  --allow-submission
```

## Relatórios e códigos de saída

As avaliações escrevem:

- relatório HTML em `reports/python-evaluation-report_*.html`;
- planilha CSV em `reports/python-evaluation-report_*.csv`;
- eventos JSONL por tentativa em `reports/runs/`.

O código de saída `0` indica que o lote terminou e os relatórios foram escritos. Casos com
`FAIL` não alteram esse código. O código `2` indica erro de configuração ou execução do
comando, e `130` indica interrupção pelo teclado.

Para arquivar as versões das dependências junto de uma rodada:

```bash
python -m pip freeze > reports/requirements-run.txt
```

## Testes e qualidade

Testes rápidos, sem integrações externas:

```bash
pytest -m 'not integration'
```

Suíte completa, incluindo integrações locais com Chromium:

```bash
playwright install chromium
pytest
```

Executar um arquivo ou teste específico:

```bash
pytest tests/unit/evaluation/test_audio_evaluation.py
pytest tests/unit/evaluation/test_audio_evaluation.py::test_stt_report_records_transcription_settings
```

Teste real opcional do Whisper:

```bash
RUN_WHISPER_INTEGRATION=1 \
WHISPER_TEST_AUDIO=../dataset/speaker_02/spk02_01_common.mp4 \
pytest -m whisper_integration
```

Lint, formatação e tipos:

```bash
ruff check .
ruff format --check .
mypy
```

Para aplicar automaticamente a formatação:

```bash
ruff format .
```

## Ajuda dos comandos

As CLIs com argumentos exibem a referência instalada com `--help`:

```bash
audio-agent-py --help
voice-form-agent-py --help
form-evaluate-py --help
audio-evaluate-py --help
pipeline-evaluate-py --help
```

`form-agent-py` é interativo e não possui opções de linha de comando.
