# Caso perfeito: configuração selecionada no piloto

Atualizado em 7 de outubro de 2026. A configuração escolhida para demonstrar a
POC é **sample_01 + Whisper large-v3 + orientação de e-mail + regras locais**.
Ela preencheu todos os sete campos esperados nas duas execuções observadas. A
condição com extração DeepSeek também passou, acrescentando uma chamada ao provider.

## Executar somente essa configuração

Na raiz do projeto:

```bash
HF_HUB_CACHE=reports/model-cache .venv/bin/python -m voice_form.cli \
  ../Dataset/caso_perfeito/samples/sample_01/audio.m4a \
  --model large-v3 --language pt --email-hints --data-treatment rules
```

O comando executa um único áudio e preenche o formulário uma vez. Não executa o
catálogo nem as outras condições. O fluxo é áudio → Whisper → regras locais →
agente de formulário → MCP local → Playwright → navegador. O agente de formulário
continua usando o modelo configurado no `.env`; não há extração DeepSeek adicional.

Requisitos: ambiente instalado com suporte a áudio, credencial do agente de
formulário no `.env`, Chromium e gravação no caminho indicado. O áudio e o cache
em `reports/model-cache` são locais e não versionados. Ajuste o caminho do dataset
se necessário; `Dataset` corresponde ao nome usado neste ambiente. O modelo é
baixado no primeiro uso se ainda não estiver no cache.

Para ver o navegador, adicione `HEADLESS=false` antes de `.venv/bin/python`. Para
receber JSON, acrescente `--json`. Para revisão e eventual envio, use
`--confirm-submit`; essa opção exige confirmação humana separada e não pode ser
combinada com `--json`. O comando acima não solicita envio.

Parâmetros utilizados:

| Parâmetro | Valor |
|---|---|
| Modelo STT | `large-v3` |
| Idioma | `pt` |
| Dispositivo / quantização | CPU / `int8` |
| Beam size / temperatura | 5 / 0 |
| VAD | desativado |
| Orientação STT | `--email-hints` |
| Tratamento | `rules`, versão `spoken-data-pt-BR-v2` |
| Formulário | exemplo local, salvo se `FORM_URL` for sobrescrito |

## Por que o e-mail passou a funcionar

Sem orientação, o large-v3 produziu `joão.pedro.gmail.com`: o separador entre
usuário e domínio se perdeu. Regras e extrator não podem inserir um `@` sem
evidência. A orientação combinada recuperou `joão.pedro arroba gmail.com` na
amostra 01 e `joao.pedro arroba gmail.com` na amostra 02.

`--email-hints` fornece ao Whisper um exemplo genérico `contato@example.com` e
vocabulário de separadores/domínios; não fornece o endereço esperado. Por
convenção explícita da POC, a regra v2 remove acentos da parte do usuário quando
há `@` ou `arroba` explícito. Assim, a representação vira `joao.pedro@gmail.com`.
O nome pessoal permanece `João Pedro Almeida`, e a transcrição original é preservada.

Domínios não são substituídos por aproximação: `jimeio.com` não vira `gmail.com`.
Separadores ausentes continuam pendentes. A convenção de usuário ASCII é uma
decisão deste experimento, não uma garantia de correção de qualquer endereço.
Veja as [regras e limites completos](tratamento-dados-falados.md).

## Resultado observado

Na amostra 01, com o mesmo STT orientado, foram observadas duas rodadas completas:

| Condição | Tentativas que passaram | Tempo médio após STT |
|---|---:|---:|
| `raw` | 0/2 | 15,96 s |
| `rules` | 2/2 | 7,08 s |
| `deepseek` | 2/2 | 8,40 s |

O fluxo bruto preservou o acento no e-mail e o telefone sem a máscara esperada.
Regras e extração produziram os sete valores esperados, sem pendências ou códigos
de erro. Para esta demonstração, as regras foram escolhidas pelo mesmo sucesso
observado, menor tempo após STT e ausência da chamada adicional de extração.
Amostra pequena e latência variável do provider impedem afirmar superioridade geral.

Os resultados foram obtidos em execuções reais com Whisper, modelo remoto, MCP e
navegador. Os relatórios locais usados nesta análise estão em
`reports/comparacao-email-hints/`, nos arquivos:

- `python-evaluation-report_comparison_2026-10-07_17-29-06-013416.csv`
- `python-evaluation-report_comparison_2026-10-07_17-32-19-633316.csv`

Os horários dos nomes são UTC. Os rastros JSONL relacionam as condições por
`pair_id`, preservam a transcrição e identificam versões/hash, ordem, parâmetros
e estado final. Relatórios e gravações não entram no repositório.

## Limites e pendências do catálogo

`reference_text` está vazio no catálogo local; WER/CER são indefinidos. Esses
resultados mostram preenchimento comparado ao oráculo, não uma taxa de erro STT.

Na amostra 02, regras e extração preencheram o e-mail correto, mas a transcrição
inclui aceitação dos termos e o oráculo omite esse campo. O preenchimento é
contabilizado como alteração extra. A amostra 03 transcreve somente um pedido de
envio, enquanto o oráculo exige aceitação dos termos. Revise os áudios e as
expectativas antes de usar o catálogo para uma conclusão sobre desempenho.

As duas rodadas não são uma amostra independente de falantes e não demonstram
generalização. A orientação pode enviesar transcrição; mantenha-a identificada
como condição STT. Primeira carga/download deve ser separada ao comparar latência.
Para ampliar o experimento, use o [protocolo de comparação](comparacao-tratamentos.md).

## Verificação de software

A versão foi verificada com 198 testes aprovados e 1 teste opcional de Whisper
ignorado, além de Ruff e mypy. Testes de fluxo usam STT/LLM simulados; as
integrações exercitam MCP e Chromium reais. A evidência de preenchimento deste
piloto vem das execuções reais descritas acima, não do número de testes.
