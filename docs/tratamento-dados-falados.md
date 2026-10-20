# Tratamento de dados falados

O fluxo de voz passa a ser áudio → STT → tratamento de dados → FormAgent → navegador.
A etapa `spoken-data-pt-BR-v3` é local e determinística: não chama outro LLM, não
consulta `expected_json` e não corrige cidades, nomes pessoais, domínios ou dígitos.
Por convenção explícita deste experimento, o usuário do e-mail usa ASCII sem acentos.
A transcrição original permanece intacta no resultado e nos rastros.

## Regras suportadas

Só são tratados valores explicitamente anunciados com `é`, `:` ou `=`. Rótulos:
`e-mail`/`email`, `telefone`/`celular`/`whatsapp`, `data de nascimento`/`nascimento`/`data`.
Trechos não reconhecidos seguem para o agente como antes. O idioma dessas regras é
português brasileiro, independentemente do idioma selecionado para o STT.

| Entrada | Valor tratado |
|---|---|
| Meu e-mail é ana ponto silva arroba example ponto com | `ana.silva@example.com` |
| Meu e-mail é joão.pedro arroba gmail.com | `joao.pedro@gmail.com` |
| Meu e-mail é joão.pedro, arroba, gmail, ponto, com | `joao.pedro@gmail.com` |
| E-mail: ana mais teste arroba example ponto com | `ana+teste@example.com` |
| Telefone: 85 999123456 | `(85) 99912-3456` |
| Telefone: oitenta e cinco nove nove nove um dois três quatro cinco seis | `(85) 99912-3456` |
| Telefone: DDD oito cinco nove nove nove um dois três quatro cinco meia | `(85) 99912-3456` |
| Telefone: 85 34567890 | `(85) 3456-7890` |
| Celular: +55 85 999123456 | `+55 (85) 99912-3456` |
| Nascimento: quinze de março de 2001 | `2001-03-15` |
| Data: 03/04/2001 | `2001-04-03` (dia/mês/ano) |

**E-mail:** palavras separadas `arroba`, `ponto`, `hífen`/`traço`,
`underscore`/`sublinhado` e `mais` viram separadores entre componentes. O domínio fica
em minúsculas; a caixa do usuário é preservada. Endereços já escritos e compactos
não têm palavras do usuário reinterpretadas. A validação é um subconjunto ASCII
conservador e não confirma que o endereço exista ou corresponda à intenção da pessoa.
Um domínio escrito como `jimeio.com` não vira `gmail.com`.

V2 aceita vírgulas de pausa ao redor de separadores falados. Remove marcas de
acento somente da parte do usuário quando houver `@` ou `arroba` explícito,
registrando `email_local_remove_accents`. Nomes pessoais permanecem com seus acentos.
Esta é uma convenção da POC para endereços ASCII, não uma afirmação de que e-mails
internacionalizados não possam existir. `joão.pedro.gmail.com` continua pendente:
remover acento não recupera um separador que não foi transcrito. Domínios com
acentos não são reinterpretados nem convertidos por aproximação.

**Telefone (v3):** a conversão de números por extenso usa
[`text2num`](https://github.com/allo-media/text2num) em português, inclusive grupos
como `oitenta e cinco` e sequências de dígitos. Uma adaptação local interpreta
`meia` como `seis` somente no trecho do telefone. O texto integral não passa pela
biblioteca; nomes, e-mails, datas e comandos continuam nas suas regras próprias.

São exigidos 10 ou 11 dígitos incluindo DDD, opcionalmente precedidos por
`55`/`+55`. A validação e a máscara usam
[`phonenumbers`](https://github.com/daviddrysdale/python-phonenumbers), com região
brasileira. Além do comprimento, o número precisa corresponder a um padrão válido
de DDD e numeração nos metadados da biblioteca. Isso não comprova existência,
atividade ou titularidade da linha. Um número de 11 dígitos começando com `55`
é tratado como DDD 55; o código do país só é separado quando há 12 ou 13 dígitos.

Resíduos de palavras, ramais, expressões decimais (`ponto`/`vírgula`), alternativas
e repetições como `três noves` ficam pendentes. Outros códigos internacionais e
prefixos de operadora/tronco não são interpretados. Nenhum dígito é inventado ou
removido para fazer o tamanho caber: o valor reconhecido e a máscara são conferidos
contra a sequência informada, impedindo correção silenciosa pelo parser.

O histórico registra `phone_text2num_pt`, `phone_meia_as_six` quando aplicável e
`phone_phonenumbers_br`. A transcrição e o trecho originais permanecem intactos.
As dependências são instaladas com `python -m pip install -e .`; a conversão e a
validação rodam localmente. A regra compartilhada também é usada na conferência
de valores da extração e nas respostas de `--clarify`.

**Data:** são aceitos ISO, dia/mês/ano com quatro dígitos no ano e dia numérico ou
por extenso seguido do mês em português e ano numérico. Datas impossíveis,
incompletas e anos com dois dígitos ficam pendentes. Anos por extenso e datas
relativas, como `amanhã`, não são interpretados.

## Pendências e evidência

Valores inválidos, separadores aglutinados (`anaarrobajimeio.com`) ou repetições
conflitantes geram `DATA_PENDING`, com estágio `normalization`. Correções entre
valores repetidos ainda exigem revisão; esta versão não escolhe qual prevalece.

O trecho incerto é substituído por `[PENDENTE: tipo; não preencher]` na instrução
encaminhada ao agente. O texto original, a posição do trecho, as regras aplicadas,
o valor normalizado e o motivo da pendência ficam no resultado JSON, no evento
`data_normalized` e em `form_data.json` sob `data_normalization`.
O marcador orienta o agente; não é uma política independente de bloqueio de tools
por campo. Envio automático e confirmação de envio na CLI são bloqueados enquanto
houver pendências. A CLI retorna 2 nesse caso e pode preencher os outros dados.

## Comparação experimental

O tratamento é habilitado por padrão em `voice-form-agent-py` e no modo `pipeline`
da avaliação. Os modos `stt` e `reference` e a CLI de texto não recebem tratamento.

```bash
voice-form-agent-py samples/exemplo.wav --language pt --json
voice-form-agent-py samples/exemplo.wav --language pt --json --no-normalize-data

pipeline-evaluate-py --cases reports/caso_perfeito/cases.csv --mode pipeline \
  --language pt --attempts 3 --output reports/pipeline-tratado
pipeline-evaluate-py --cases reports/caso_perfeito/cases.csv --mode pipeline \
  --language pt --attempts 3 --no-normalize-data --output reports/pipeline-bruto
```

Use o mesmo catálogo revisado, áudios, parâmetros e modelo nas duas condições.
Não misture resultados antigos com tratados sem identificar a condição.
A v3 amplia a conversão de telefones e exige um padrão de numeração válido; os
resultados anteriores da v2 continuam descrevendo a regra usada naquela rodada.
O manifesto registra `data_normalization_version`; CSV/HTML incluem
`normalized_instruction`, `data_normalization_version` e `normalization_seconds`.
WER/CER continuam calculados sobre o texto original do STT, nunca sobre o tratado.
Uma pendência torna o resultado integrado FAIL, mesmo quando os demais campos
coincidem com o esperado. O tempo total inclui tratamento e o tempo do FormAgent
continua medido separadamente.
