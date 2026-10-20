# Esclarecimento de pendências com o usuário

O modo opcional `--clarify` acrescenta um ciclo de esclarecimento após o preenchimento
inicial, antes da revisão de envio. A primeira versão aceita respostas digitadas no
terminal e trata e-mails e telefones brasileiros. Não requer novas dependências.

## Uso

```bash
voice-form-agent-py caminho/para/audio.wav --language pt --clarify
voice-form-agent-py caminho/para/audio.wav --language pt --clarify --confirm-submit
```

É possível usar `--data-treatment rules` (padrão), `deepseek` ou `raw`. Nos dois
primeiros, as pendências estruturadas do tratamento alimentam as perguntas. Em
`raw`, a identificação se limita aos campos obrigatórios vazios ou inválidos
observados no formulário. `--json` e `--clarify` são incompatíveis; os executores
de avaliação em lote não ativam a interação automaticamente.

## Critérios

| Situação | Comportamento |
|---|---|
| E-mail/telefone pendente nas regras ou na extração | Solicitar o valor completo. |
| Valores conflitantes do mesmo tipo | Pedir ao usuário o valor final; não escolher automaticamente. |
| Vários campos compatíveis com uma pendência das regras | Pedir primeiro o número ou identificador do campo. |
| E-mail/telefone obrigatório vazio | Solicitar o dado. |
| E-mail/telefone com validade nativa falsa | Solicitar um valor válido. |
| Campo opcional vazio, sem pendência | Manter o estado atual. |
| Campo desabilitado, somente leitura ou de outro tipo | Não solicitar resposta nesta versão. |
| Campo sem associação inequívoca ou fora do escopo | Conservar a pendência original. |
| Falha operacional ou estado não verificável | Não usar perguntas de dados para tentar reparar a falha. |

Campos com tipo `email`/`tel` são reconhecidos diretamente. Campos de texto usam
rótulo, nome ou identificador explícitos de e-mail/telefone. Um campo genérico como
"Contato" não é classificado automaticamente. Referências duplicadas impedem a
aplicação segura da resposta.

## Interação e aplicação

1. Preencher os dados que o fluxo inicial conseguiu processar.
2. Associar as pendências aos campos inspecionados.
3. Fazer uma pergunta específica por vez.
4. Validar a resposta pelas mesmas regras locais usadas no tratamento de dados.
5. Preencher somente o campo escolhido através do MCP existente.
6. Inspecionar o formulário e conferir o valor e a validade nativa, além de verificar
   que os valores dos outros campos foram preservados.
7. Continuar com a próxima pendência e mostrar o resultado atualizado.

São permitidas duas respostas por campo; a escolha do campo, quando necessária,
também tem limite de duas tentativas. `PULAR` conserva a pendência e continua;
`ENCERRAR` ou fim da entrada (EOF) interrompe as perguntas. Respostas inválidas
localmente não são escritas. Se apenas a restrição nativa rejeitar um valor após
a aplicação, o sistema explica a rejeição e permite a tentativa restante; o valor
rejeitado pode permanecer visível, acompanhado da pendência.

O ciclo conserva a sessão do navegador e não chama novamente o reconhecimento de
fala ou o LLM. A resposta é tratada como dado do campo escolhido. Mudanças no estado
do formulário durante a espera ou alterações adicionais após a escrita interrompem
o esclarecimento e invalidam a verificação; não há nova tentativa automática de
uma operação com resultado incerto.

Com `--clarify`, o preenchimento inicial não recebe autorização de envio, mesmo
quando o pipeline é usado programaticamente com `authorize_submission=True`.
Na CLI, `--confirm-submit` mantém a confirmação separada por `ENVIAR`, após a
resolução das pendências. O veto de envio da transcrição original continua valendo.

## Histórico e avaliação

A transcrição, normalização e extração originais são preservadas como evidência.
As pendências resolvidas saem da lista ativa `issues`, mas permanecem em
`initial_issues`, nos registros do tratamento e nos eventos JSONL. Outras falhas
não são removidas ao corrigir um campo.

O resultado do pipeline inclui `clarifications`, com identificador do campo,
candidatos, motivo, número de tentativas, valor confirmado e situação:
`resolved`, `skipped`, `cancelled`, `exhausted` ou `failed`.
Os eventos `clarification_question` e `clarification_answer` registram as perguntas
e respostas. `form_data.json` inclui o histórico e o estado final atualizado.
Esses artefatos contêm dados digitados e seguem os mesmos cuidados de armazenamento
das transcrições existentes.

`clarification_seconds` inclui o tempo de espera humana e de aplicação das respostas.
`total_seconds` e `post_stt_seconds` também incluem essa etapa; `form_seconds`
continua medindo somente o preenchimento inicial. Comparações de latência precisam
considerar essa diferença.

Para um piloto, compare o estado inicial com o final nos mesmos casos e registre
correção por campo, pendências resolvidas, perguntas necessárias/desnecessárias e
quantidade de interações. Os testes automatizados usam respostas e STT/LLM simulados;
a integração usa MCP e navegador reais. Eles verificam funcionamento, sem demonstrar
ganho de desempenho com usuários reais.

Dados plausíveis e com formato válido ainda podem estar semanticamente errados.
O mecanismo identifica as situações acima; não é um estimador geral de confiança
da transcrição. Datas, outros tipos de campo e respostas por voz ficam fora desta
primeira versão.
