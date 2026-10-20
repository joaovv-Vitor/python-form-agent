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

`voice-form-agent-py` usa contexto automático do formulário por padrão: antes do
Whisper, inspeciona os campos visíveis via MCP/Playwright e gera `initial_prompt`
com rótulos e `hotwords` com dicas dos tipos, rótulos e opções de seleção. Não inclui
valores preenchidos nem texto de botões; ignora campos desabilitados, somente leitura,
senhas e arquivos. A geração considera até 20 campos, cinco opções por campo e
limita o prompt a 450 caracteres e o vocabulário a 200. Não exige LLM adicional.

```bash
# Contexto do formulário aplicado automaticamente:
voice-form-agent-py caminho/para/audio.wav --language pt
# Sem contexto automático, para comparação:
voice-form-agent-py caminho/para/audio.wav --language pt --no-form-context
```

Cada parâmetro manual (`--initial-prompt`, `--hotwords`) tem prioridade sobre seu
equivalente gerado. `--email-hints` define os dois parâmetros com o preset fixo,
dispensando a inspeção prévia. Se a inspeção falhar, o STT continua com as opções
originais e a falha é registrada. Falha STT ou texto vazio impedem o preenchimento,
embora o navegador possa já ter sido aberto para obter o contexto.

Os eventos `stt_context_started`, `stt_context_created`/`stt_context_failed` registram
a etapa. `audio_started.settings`, `transcription.settings` e `form_data.json`
(`stt_settings`) contêm os parâmetros efetivos; o manifesto inicial registra as
opções solicitadas e `auto_stt_context`. O tempo dessa inspeção entra no total,
sem alterar o tempo de inferência STT nem o de preenchimento.

Essa automação pertence à CLI de voz e a `AudioFormPipeline.run` (desativável com
`auto_context=False`). Avaliações em lote e comparação pareada mantêm o STT
explicitamente configurado, e `run_transcription` reutiliza a transcrição fornecida.
`audio-agent-py` opera sem navegador.

Para permitir esclarecimentos pelo terminal durante o fluxo:

```bash
voice-form-agent-py caminho/para/audio.mp4 --language pt --clarify
# Com extração e revisão de envio:
voice-form-agent-py caminho/para/audio.mp4 --language pt \
  --data-treatment deepseek --clarify --confirm-submit
```

`--clarify` solicita e-mails/telefones incompletos, conflitantes, inválidos ou
obrigatórios ausentes. Digite o valor completo, `PULAR` para manter a pendência
ou `ENCERRAR` para parar as perguntas. Há até duas tentativas por campo. Quando
houver mais de um campo possível, escolha primeiro o número ou identificador do
campo mostrado. Uma resposta inválida é explicada antes de uma nova tentativa.
O esclarecimento não autoriza envio e não pode ser combinado com `--json`.
Consulte o [protocolo de esclarecimento](esclarecimento-usuario.md).

Para rodar somente a configuração selecionada no caso perfeito:

```bash
HF_HUB_CACHE=reports/model-cache .venv/bin/python -m voice_form.cli \
  ../Dataset/caso_perfeito/samples/sample_01/audio.m4a \
  --model large-v3 --language pt --email-hints --data-treatment rules
```

Esse comando executa uma transcrição e um preenchimento, sem rodar o lote de
comparação. Continua usando o agente de formulário e o MCP local. As regras
tratam o e-mail, telefone e data; não há chamada adicional ao extrator DeepSeek.
O modelo do agente de formulário continua definido pelo `.env`. Para acompanhar
o navegador, acrescente `HEADLESS=false` antes de `.venv/bin/python`.

O caminho de áudio e o cache são locais e não versionados. Se o modelo não estiver
nesse cache, o primeiro uso o baixa. Consulte os
[resultados e requisitos do caso perfeito](caso-perfeito.md).

Executa áudio → Whisper → tratamento de dados → Form Agent → navegador:

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

O tratamento de e-mail, telefone e data é habilitado por padrão. O JSON conserva a
transcrição original e inclui `normalization`, com valores tratados e pendências.
Para comparar com o fluxo bruto:

```bash
voice-form-agent-py caminho/para/audio.mp4 --language pt --json --no-normalize-data
```

Consulte as [regras e limites](tratamento-dados-falados.md). `DATA_PENDING` retorna
código 2 e impede envio; os demais campos podem ser preenchidos.

Para usar extração estruturada pelo DeepSeek, com validação local antes do MCP:

```bash
python -m voice_form.cli caminho/para/audio.m4a \
  --language pt --model small --data-treatment deepseek --json
```

`--data-treatment raw|rules|deepseek` seleciona uma condição; `--no-normalize-data`
é um alias de `raw`. A extração usa `DEEPSEEK_API_KEY` e as opções `EXTRACTION_*`,
independentes de `LLM_*`. O JSON inclui `extraction`, com a resposta original,
valores candidatos, valores validados, trechos de origem e pendências.

Para comparar todas as condições com uma única transcrição por caso/tentativa:

```bash
python -m voice_form.evaluation --cases reports/caso_perfeito/cases.csv \
  --mode pipeline --compare-treatments --language pt --model small \
  --attempts 3 --output reports/comparacao-tratamentos
```

O [protocolo de comparação](comparacao-tratamentos.md) explica as métricas e os
controles. `--compare-treatments` exige um catálogo com `expected_json`; não pode
ser combinado com `--dataset` ou `--data-treatment`.

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
| `--email-hints` | desativado | Contexto e vocabulário genéricos para preservar separadores de e-mail no Whisper. |
| `--initial-prompt TEXT` | ausente | Contexto personalizado; não pode ser combinado com `--email-hints`. |
| `--hotwords TEXT` | ausente | Vocabulário personalizado; substitui o vocabulário do preset quando informado. |

Para investigar e-mails que perderam o `@`, repita o caso perfeito com orientação
de transcrição, usando o modelo já baixado no projeto:

```bash
HF_HUB_CACHE=reports/model-cache python -m voice_form.evaluation \
  --cases reports/caso_perfeito/cases.csv --compare-treatments \
  --model large-v3 --language pt --email-hints \
  --output reports/comparacao-email-hints
```

O preset não contém o endereço esperado e não consulta o oráculo. Ele orienta o
Whisper com um exemplo `contato@example.com` e vocabulário de separadores/domínios.
As orientações alteram a condição STT: registre essa rodada separadamente. O
prompt e as palavras são registrados no manifesto, no JSON e nas colunas
`stt_initial_prompt`/`stt_hotwords` do CSV. A orientação pode ajudar, mas não garante
o e-mail: separadores ausentes e grafias inválidas continuam pendentes.

No Mac M1 Pro, use `--device cpu --compute-type int8`. O projeto não oferece `mps` como
dispositivo. Os modelos são baixados automaticamente e ficam no cache local.

Comandos para comparar configurações STT:

```bash
audio-agent-py caminho/para/audio.mp4 --language pt --model base --device cpu --compute-type int8
audio-agent-py caminho/para/audio.mp4 --language pt --model small --device cpu --compute-type int8
audio-agent-py caminho/para/audio.mp4 --language pt --model medium --device cpu --compute-type int8
audio-agent-py caminho/para/audio.mp4 --language pt --model large-v3 --device cpu --compute-type int8 --email-hints
```

- `base`: referência rápida, com menor custo de processamento.
- `small`: configuração padrão, útil como linha de base rápida.
- `medium`: maior prioridade para precisão, com execução mais lenta.
- `large-v3` com `--email-hints`: configuração selecionada para o piloto do caso perfeito.

O último comando também muda as orientações de transcrição. Para isolar o efeito
do tamanho do modelo, mantenha `--email-hints` igual nas configurações comparadas.

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

Modo C, áudio → Whisper → tratamento de dados → Form Agent → navegador:

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

Acrescente `--no-normalize-data` ao modo `pipeline` para executar a condição bruta,
salvando cada condição em uma pasta `--output` diferente. WER/CER usam sempre a
transcrição original; os modos `stt` e `reference` não recebem tratamento.

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
