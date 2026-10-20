# Revisão e correções na mesma sessão

`--review` mantém o navegador aberto após o preenchimento inicial, permitindo
consultar os dados, acrescentar informações ou corrigir um campo por vez. A entrada
inicial continua sendo um arquivo de áudio. Durante a revisão, as novas instruções
podem ser digitadas ou transcritas de outro arquivo com `AUDIO caminho/do/arquivo`.

## Caso perfeito

Na raiz do projeto:

```bash
HF_HUB_CACHE=reports/model-cache .venv/bin/python -m voice_form.cli \
  ../Dataset/caso_perfeito/samples/sample_01/audio.m4a \
  --model large-v3 --language pt --data-treatment rules --review
```

Para observar o navegador, adicione `HEADLESS=false` antes de `HF_HUB_CACHE`.
Para oferecer envio após a revisão, acrescente `--confirm-submit`.

Exemplo de interação:

```text
Revisão> Corrija somente meu telefone para 85 98888-1234
Telefone: (85) 99912-3456 → (85) 98888-1234. Demais campos preservados.
Revisão> Na verdade moro em Quixadá
Cidade: Fortaleza → Quixadá. Demais campos preservados.
Revisão> AUDIO "samples/correcao com espacos.wav"
Transcrição da correção: Meu e-mail está errado, o correto é ana arroba example ponto com
E-mail: anterior@example.com → ana@example.com. Demais campos preservados.
Revisão> CONCLUIR
```

O caminho do áudio é relativo ao diretório de execução; aspas externas são aceitas
para caminhos com espaços. Há uma nova inferência STT por arquivo de correção,
reutilizando o motor/modelo já carregado. Não há captura de microfone nesta versão.

## Comandos

| Entrada | Efeito |
|---|---|
| Instrução em linguagem natural | Propõe uma correção ou inclusão em um campo. |
| `AUDIO caminho` | Transcreve o novo arquivo e interpreta a instrução reconhecida. |
| `MOSTRAR` | Exibe os valores observados e as referências dos campos. |
| `PENDENCIAS` | Mostra problemas ativos e campos obrigatórios vazios/inválidos. |
| `PULAR` | Descarta o pedido de correção pendente e mantém os valores atuais. |
| `CONCLUIR` | Finaliza a revisão e permite seguir para a confirmação separada, se habilitada. |
| `ENCERRAR`, `SAIR` ou EOF | Encerra a sessão sem oferecer envio. |

Os comandos são digitados no terminal. O conteúdo de um arquivo de áudio é tratado
como pedido de correção pelo planejador, sem conceder autorização de envio.
`CONCLUIR` não descarta uma pergunta pendente: responda ou use `PULAR` primeiro.
`ENVIAR` durante a revisão só orienta o usuário a concluir; não executa submissão.

## Interpretação e aplicação

O mesmo modelo de linguagem configurado para o formulário recebe a instrução atual,
o inventário e, quando necessário, a pergunta/resposta do pedido pendente. Ele dispõe
somente de duas propostas: `fill_field` e `ask_clarification`. Nenhuma chamada do modelo
é encaminhada diretamente ao navegador. Um retorno vazio, várias propostas, uma tool
desconhecida ou argumentos inválidos são rejeitados antes da escrita.

Cada proposta precisa identificar um campo único e fornecer um trecho literal do
pedido que sustente o novo valor. E-mails, telefones e datas passam pelas regras
locais, comparando candidato e evidência normalizados. Selects exigem opção existente
e evidência do texto ou valor correspondente. Textos livres precisam constar literalmente
na evidência. Essa conferência limita alterações sem fundamento, mas não garante que
o modelo tenha interpretado corretamente a intenção; o usuário continua revisando o resultado.

Campos suportados: texto, textarea, search, e-mail, telefone, data, número, URL e
select nativo. Campos desabilitados, somente leitura e demais tipos são rejeitados.
Nesta versão, datas seguem os formatos da normalização existente e números de
`input[type=number]` precisam ser informados em algarismos. Limpeza de campos,
correção de vários campos em uma única resposta e controles customizados ficam
fora deste ciclo. Peça uma alteração por vez.

Quando o campo ou valor é ambíguo, o modelo propõe uma pergunta. As respostas curtas
completam somente aquele pedido. Após aplicar ou descartar o pedido, o contexto
pendente é limpo; valores de correções anteriores não servem de evidência para outra.

Antes da escrita, o host reinspeciona o formulário para detectar mudanças durante
a espera ou interpretação. Depois, confere o valor do campo, a estrutura e o estado
dos outros campos, os botões e a URL, realizando uma segunda conferência final.
Uma alteração adicional ou falha com resultado incerto encerra a revisão com
verificação inválida. A operação não é repetida automaticamente. O snapshot observado
é conservado quando possível, inclusive quando a página já sofreu um efeito colateral.

Um valor escrito e rejeitado pela validade nativa permanece visível como pendente
e pode receber uma nova correção. Pendências originais de normalização/extração só
saem da lista ativa quando a correção correspondente é verificada; outras falhas
permanecem. Os registros originais de normalização e extração continuam intactos.

## Envio e compatibilidade

Com `--review --confirm-submit`, `CONCLUIR` leva à revisão final dos valores e à
digitação exata de `ENVIAR`, usando o mecanismo existente. Pendências, estado incerto
ou veto de envio na transcrição inicial ou nas correções impedem essa etapa. Sem
`--confirm-submit`, concluir não oferece envio. Encerrar ou EOF também não o oferece.

`--review` é incompatível com `--json`. Pode ser combinado com `--clarify`: primeiro
ocorrem as perguntas automáticas de pendências de e-mail/telefone e depois a revisão
livre. Os modos `raw`, `rules` e `deepseek` continuam disponíveis para a etapa inicial;
as correções sempre passam pela validação local. Avaliações em lote não abrem revisão.

## Histórico

Os eventos `review_started`, `review_input`, `review_question`, `review_proposed`,
`review_record`, `review_updated` e `review_completed` registram a sessão. O último
estado conferido é salvo a cada alteração; interrupções marcam a verificação como
incompleta. Novos áudios usam
`review_audio_started` e `review_audio_transcribed`, preservando os eventos e a
transcrição do áudio inicial. As escritas passam pelos eventos de preenchimento existentes.

`form_data.json` inclui `review_records` (campo, valor anterior/novo, pedido, situação,
motivo e caminho do áudio quando houver), `review_transcriptions` e o estado final
atualizado. As situações são `applied` (escrito e aceito pelo formulário), `pending`
(escrito, mas rejeitado pela validade nativa), `rejected` (pedido não aplicado) e
`failed` (estado ou operação incerta, encerrando a revisão).
O resultado do pipeline inclui `review_records` e `review_seconds`.
O tempo de revisão inclui espera humana, STT adicional, interpretação e aplicação;
também entra em `total_seconds` e `post_stt_seconds`, sem alterar `form_seconds`
nem o tempo STT da gravação inicial. As dependências e o modelo do manifesto continuam
os mesmos, com a identificação `form-review-v1` para o fluxo de revisão.

Os registros contêm as informações fornecidas pelo usuário, como as transcrições
existentes. Os testes rápidos usam STT/LLM simulados e as integrações exercitam MCP
e Chromium reais; isso verifica o fluxo, sem demonstrar ganhos de usabilidade.
