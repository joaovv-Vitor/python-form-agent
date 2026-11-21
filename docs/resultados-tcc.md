# Resultados da avaliação técnica da VozForm

Os resultados descrevem testes automatizados pela CLI com cinco gravações, uma
por formulário do Google Forms. Cada condição repetiu três vezes a entrada de
cada caso. As execuções usaram sessões isoladas e nenhuma delas tentou enviar
uma resposta.

Em 18/11/2026, após conferência dos áudios, foram corrigidas duas referências
nominais no texto de referência e no gabarito. As tabelas mostram a pontuação
recalculada sobre as execuções originais, sob os mesmos critérios de comparação
por tipo de campo (`field-aware-v1`).

## Comparação dos modelos Whisper

Na primeira rodada, as quatro variantes processaram os mesmos áudios,
totalizando 60 execuções. O reconhecimento usou português, CPU/int8, busca em
feixe de tamanho 5, temperatura zero e nenhuma dica de vocabulário. O
tratamento por regras e o agente de preenchimento DeepSeek V4 Flash foram
mantidos em todas as condições. O tempo de transcrição inclui preparação e
inferência, com carregamento inicial do modelo excluído.

| Modelo | Sucesso completo | Acerto por campo | WER | STT médio (s) |
| --- | ---: | ---: | ---: | ---: |
| `base` | 0 de 15 | 76,02% | 20,80% | 1,79 |
| `small` | 3 de 15 | 80,70% | 15,04% | 4,06 |
| `medium` | 6 de 15 | 88,30% | 14,54% | 10,63 |
| `large-v3` | 8 de 15 | 91,23% | 13,28% | 19,04 |

O protocolo priorizou o sucesso completo para selecionar o modelo. O
`large-v3` foi selecionado para a rodada seguinte.

## Comparação dos tratamentos

As três condições receberam as mesmas 15 transcrições salvas do `large-v3`,
totalizando 45 preenchimentos com o agente DeepSeek V4 Flash. A WER de entrada
foi de 13,28% em todas as condições. O tempo pós-STT inclui tratamento, inspeção
e preenchimento.

| Tratamento | Sucesso completo | Acerto por campo | Pós-STT médio (s) |
| --- | ---: | ---: | ---: |
| Transcrição original (`raw`) | 7 de 15 | 93,57% | 14,58 |
| Normalização por regras (`rules`) | 6 de 15 | 88,89% | 12,28 |
| Extração estruturada (`deepseek`) | 3 de 15 | 87,72% | 13,05 |

A transcrição original completou uma tentativa a mais que as regras, enquanto
o tratamento por regras teve o menor tempo médio pós-STT. No formulário de
visita técnica, a transcrição original obteve 87,50% de acerto por campo, mas
o e-mail do responsável ficou em branco nas três tentativas.

## Alcance e reprodução

As 105 execuções tiveram zero falhas operacionais. O sucesso completo segue os
[critérios de avaliação](experimentos.md#definições-das-métricas), incluindo o
estado final do formulário e a condição de não envio. A amostra se limita às
cinco gravações e aos formulários selecionados. Usabilidade, correção
interativa e entrega de respostas ao site ficaram fora das baterias.

Para executar a comparação com seus próprios dados, prepare um catálogo a partir
do [modelo de avaliação](../evaluation/audio/README.md), usando áudios e
formulários sob seu controle. Com o ambiente instalado e o provedor configurado:

```bash
python -m voice_form.whisper_comparison \
  --cases evaluation/audio/cases.csv --attempts 3 --output reports/whisper
```

Se você já tem as transcrições no formato do
[comparador](../src/voice_form/treatment_comparison.py), com `index.json` e os
arquivos de cada caso e tentativa, use:

```bash
python -m voice_form.treatment_comparison \
  --cases evaluation/audio/cases.csv \
  --shared-transcriptions caminho/para/transcricoes \
  --attempts 3 --output reports/tratamentos
```

Para comparar tratamentos diretamente a partir de áudios, use o modo pareado
descrito no [guia do experimento](comparacao-tratamentos.md#executar). A reprodução
dos valores históricos depende dos áudios, catálogos e configurações originais,
mantidos com os registros locais.
