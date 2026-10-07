# Comparação dos tratamentos após o Whisper

Este experimento avalia três fluxos sobre a **mesma transcrição bruta**:

| Condição | Entrada do FormAgent | Tratamento |
|---|---|---|
| `raw` | Transcrição original | Nenhum |
| `rules` | Texto tratado | Regras locais de e-mail, telefone e data |
| `deepseek` | Objeto de valores aprovados | Extração estruturada pelo DeepSeek e validação local |

As três condições continuam usando FormAgent → cliente MCP → servidor MCP local
→ Playwright → navegador. O áudio é processado pelo Whisper local. O DeepSeek
recebe texto e inventário de campos, por API HTTP; esta etapa não recebe o áudio.

## Executar

Na raiz do projeto, com o ambiente instalado e `DEEPSEEK_API_KEY` no `.env`:

```bash
.venv/bin/python -m voice_form.evaluation \
  --cases reports/caso_perfeito/cases.csv \
  --mode pipeline --compare-treatments \
  --language pt --model small --attempts 3 \
  --output reports/comparacao-tratamentos
```

Para um piloto, use `--attempts 1`. Para acompanhar o navegador, prefixe o comando
com `HEADLESS=false`. Cada tentativa produz três execuções de formulário, além
de uma transcrição compartilhada. Há chamadas ao modelo de formulário nas três
condições; a terceira acrescenta uma chamada ao extrator.

Para executar a condição de extração DeepSeek com um áudio:

```bash
HEADLESS=false .venv/bin/python -m voice_form.cli \
  ../Dataset/caso_perfeito/samples/sample_02/audio.m4a \
  --language pt --model small --data-treatment deepseek --json
```

O perfil do agente de formulário mantém `MODEL_PROFILE`/`LLM_*`. O extrator sempre
usa o perfil `deepseek`, com sobrescritas `EXTRACTION_MODEL`,
`EXTRACTION_BASE_URL`, `EXTRACTION_TIMEOUT_SECONDS`, `EXTRACTION_TEMPERATURE` e
`EXTRACTION_API_KEY`. Na ausência dessas opções, usa o modelo/base do perfil,
timeout 60 segundos, temperatura 0 e `DEEPSEEK_API_KEY`. O modo thinking fica
desabilitado; não há retries automáticos. Não altere o modelo de formulário ao
trocar a condição, pois isso introduziria outro fator no experimento.

## Contrato da terceira condição

O extrator recebe somente a transcrição e o inventário inspecionado: referência,
rótulo, tipo, opções e restrições dos campos. Não recebe `expected_json`, texto de
referência nem valores atuais do DOM. Sua resposta tem este formato:

```json
{
  "fields": [
    {
      "field": "email",
      "value": "ana.silva@example.com",
      "source_text": "ana ponto silva arroba example ponto com",
      "status": "ready",
      "reason": null
    },
    {
      "field": "phone",
      "value": null,
      "source_text": "acho que termina em cinco",
      "status": "pending",
      "reason": "Telefone incompleto"
    }
  ]
}
```

O código exige chaves e tipos corretos, referências existentes e um trecho
literal da transcrição para cada campo. Valida e-mail, telefone brasileiro, data,
booleanos e opções existentes. Divergências com uma representação que as regras
locais conseguem verificar geram pendência; texto comum deve constar no trecho
de origem. Campos desabilitados, somente leitura ou repetidos ficam pendentes.
Na versão v2, o usuário do e-mail usa ASCII sem acentos, conforme a convenção
explicitamente escolhida para a POC. O trecho de origem precisa conter `@` ou
`arroba` explícito; um candidato válido não basta para inventar esse separador.

O FormAgent recebe somente os valores aprovados e os identificadores pendentes.
O host bloqueia qualquer `fill_field` que tente escrever outro campo ou valor
(`DATA_BLOCKED`) e verifica o plano aprovado no DOM final (`EXTRACTION_APPLY_ERROR`).
Pendências preservam os outros preenchimentos, mas impedem envio e sucesso
funcional da tentativa. JSON inválido, truncado ou vazio interrompe a condição
com `EXTRACTION_ERROR`; falha do provider é registrada e não recorre ao fluxo bruto.
O veto de envio presente na transcrição original continua valendo.

Uma evidência literal e um formato válido **não provam correção semântica**.
Especialmente quando o parser local não reconhece a fala, a extração ainda pode
inferir um valor incorreto ou omitir um campo mencionado. O oráculo independente
continua sendo necessário. A terceira condição inclui tanto a extração quanto o
plano restrito de preenchimento; resultados melhores avaliam esse conjunto, não
isolam o efeito do modelo extrator.

## Controles e resultados

Para cada caso/tentativa, o executor transcreve uma vez e compartilha o mesmo
objeto imutável. Cada condição cria uma aplicação e uma sessão de navegador novas.
A ordem roda entre `raw/rules/deepseek`, `rules/deepseek/raw` e
`deepseek/raw/rules`, registrada por `pair_id` e `condition_order`.
Isso reduz efeito de posição, mas não elimina variabilidade do modelo ou da rede.
Formulários remotos podem ter estado persistente no servidor mesmo em sessões
novas; para o piloto, prefira o formulário local.

CSV e HTML apresentam métricas separadas com prefixos `raw.`, `rules.` e
`deepseek.`: sucesso funcional, precisão/recall/F1, valores errados, omitidos,
pendências, alterações extras e latência. As linhas incluem a condição,
transcrição original, instrução tratada, tempos, versão de extração e tokens
informados pelo provider. Tokens referem-se à extração concluída, não ao custo
total das chamadas de formulário ou de respostas que falharam.

WER/CER usam sempre a transcrição bruta, sendo iguais nas três condições do par.
`--email-hints` acrescenta contexto e vocabulário genéricos ao Whisper. Compare
essa condição STT em uma rodada separada; dentro dela, as três condições de
tratamento continuam compartilhando exatamente a mesma transcrição. O preset
não contém o e-mail esperado; pistas podem enviesar a saída e devem constar no
protocolo. Prompt/vocabulário são registrados no manifesto e no CSV.
`total_seconds` representa o tempo lógico do fluxo, incluindo o mesmo tempo STT
em cada condição; somar as três linhas conta o STT três vezes. Para comparar o
tratamento, use também `post_stt_seconds`. `extraction_seconds` inclui a inspeção
inicial do formulário e a chamada ao DeepSeek; não mede apenas a API. Inicialização
da infraestrutura anterior ao pipeline não está incluída nesses tempos.

Artefatos no diretório de saída:

- `stt-runs/<id>.jsonl`: transcrição compartilhada e manifesto STT.
- `runs/<id>.jsonl`: manifesto, par, ordem, extração, ferramentas e verificação.
- `tests/<id>/form_data.json`: transcrição, tratamento e estado observado.
- Relatórios HTML/CSV: métricas por condição e linhas das tentativas.

No catálogo atual `reports/caso_perfeito/cases.csv`, `reference_text` está vazio:
WER/CER ficam indefinidos até a referência ser revisada manualmente. Confira
também os oráculos: sample_02 não inclui os termos, enquanto sample_03 espera
aceitação dos termos. Solicitar envio, sozinho, não equivale a aceitar os termos.
Essas expectativas precisam corresponder ao áudio, sem serem ajustadas para
favorecer o resultado observado.

O experimento fica sem envio por padrão. Para autorizá-lo no lote, são necessários
`--allow-submission` e `submission_authorized=true` no caso, além das verificações.
O código 0 do lote indica relatório gerado; consulte as linhas PASS/FAIL para
avaliar o desempenho. Os testes automatizados usam STT/LLM simulados, com testes
de integração usando MCP/Playwright reais; eles não demonstram melhoria empírica
com o DeepSeek. O [piloto real do caso perfeito](caso-perfeito.md) passou com
`rules` e `deepseek` na amostra 01, sem demonstrar superioridade geral do extrator.

## Documentação do provider consultada

O formato JSON e o comportamento em respostas vazias/truncadas seguem o
[guia oficial JSON Output](https://api-docs.deepseek.com/guides/json_mode).
A configuração de thinking e os campos de uso seguem a
[referência oficial de Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion).
