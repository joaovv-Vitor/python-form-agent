# Auditoria final

Registro histórico da etapa de integração de áudio descrita abaixo. A evolução
posterior, com tratamento de dados, comparação DeepSeek e piloto real, está
documentada no [protocolo atual](experimentos.md), na
[comparação dos tratamentos](comparacao-tratamentos.md) e no
[caso perfeito](caso-perfeito.md).

Base: `abe8f52a3cfa7c2cc56084328be5b5f155f002d9`. Alterações mantidas na árvore de trabalho,
sem commits automáticos. A [auditoria inicial](auditoria-inicial.md) registra achados antes
 das modificações e o plano; esta revisão descreve o resultado entregue.

## Antes e depois

| Aspecto | Antes | Depois |
|---|---|---|
| Entrada por áudio | Transcrição seguida de cópia manual | AudioFormPipeline compõe AudioAgent e FormAgent; CLI própria |
| Independência | Interfaces LLM/STT/tools separadas | Mesmos contratos; adaptadores continuam isolados |
| Avaliação | Texto, quatro casos, browser compartilhado | Texto legado e modos A/B/C com catálogo comum e sessão nova por tentativa |
| Autorização | Verbos em janela textual | Permissão externa ao LLM, veto negativo, trava no BrowserController e confirmação humana pós-preenchimento |
| Submissão | Qualquer clique bem-sucedido contado como envio | Apenas submit nativo autorizado, válido e com indicador novo de confirmação |
| Verificação | Read anterior podia dispensar leitura final | Releitura após última escrita, snapshots e recusa de estado alterado desde revisão |
| Resultado funcional | Lista relatada de campos | Valores DOM, extras, pré-preenchimento, validade e política de submissão |
| Diagnóstico | Erro genérico e logging esparso | Códigos por estágio, eventos JSONL, dados e referências por execução |
| Reprodução | Perfis e metadados STT já existentes | Manifesto do experimento, versões/hash de prompt, parâmetros explícitos, hashes e ambiente |
| Browser | Inventário nativo e resolução parcial | Correções para visibilidade, readonly/fieldset, placeholder e aria-labelledby; leitura efetiva e cenários dinâmicos |
| Transporte | MCP próprio com timeout/locks | Mesmo transporte; handshake coordenado, envelopes/argumentos validados, stderr drenado, timeout invalida conexão |
| Dataset | CSV ilustrativo de duas referências | 19 roteiros fictícios, oráculos estruturados, falantes pseudonimizados e protocolo de coleta/revisão |

A arquitetura final está diagramada em [experimentos.md](experimentos.md). Não foram
introduzidos banco, API web, framework multiagente, fila, serviço cloud ou frontend.

## Etapas entregues

1. **Confiabilidade da execução e medição.** Autorização explícita, lista fixa de tools,
   validação de argumentos, distinção entre tentativa e confirmação, releitura final,
   identificação por referência e snapshots. Isolamento por tentativa elimina contaminação
   da avaliação anterior. A busca parcial deixa de aceitar IDs de uma letra dentro de palavras.
2. **Composição áudio–formulário.** Serviço pequeno que conserva a transcrição estruturada,
   passa o texto bruto para FormAgent e registra falhas antes/depois da transcrição.
   Falha STT e texto vazio não executam o agente de formulário. As CLIs antigas continuam disponíveis.
3. **Rastreabilidade.** Callback de eventos no núcleo, writer JSONL local, manifesto sem chave
   de API, prompts v1/v2 empacotados e parâmetros LLM/STT registrados. Não há infraestrutura
   distribuída. A confirmação inclui valores pré-existentes e verifica novamente o snapshot.
4. **Avaliação A/B/C.** Reuso dos relatórios e das métricas de formulário; WER/CER com normalização
   versionada, RTF e latências por etapa; sucesso funcional separado de diferença textual.
   Referência vazia em B é INPUT_ERROR; silêncio em A pode ser avaliado sem WER definido.
5. **Cenários, dataset e documentação.** 43 cenários de formulário, 20 condições de áudio,
   fixtures nativas e protocolo de coleta. Análise de agência, causas revisadas por humanos,
   hipóteses e ameaças à validade documentadas.

Os blocos foram desenvolvidos e verificados incrementalmente. Marcos: 38 testes rápidos +
4 integrações na primeira etapa; 41 rápidos após composição; 45 após observabilidade;
76 aprovações após avaliação e transporte; suíte final descrita abaixo.

## Validação executada

- Suíte completa: **86 passed, 1 skipped**. O teste ignorado é o Whisper real, condicionado
  a `RUN_WHISPER_INTEGRATION=1` e à amostra configurada.
- Ruff check e format --check aprovados; mypy aprovado nos **39 módulos de código**.
  Não foram adicionados `type: ignore` ou desativações de regras. A supressão ampla existente
  no adaptador Whisper foi removida; o import opcional permanece confinado ao adaptador.
- Integrações locais cobrem MCP/Chromium, controles nativos, máscara, radio e correção de opção,
  placeholder/ARIA, campos dinâmicos, troca de DOM, bloqueio de clique, validação e recusa JS.
- Um teste de composição usa **STT e LLM simulados, com MCP/Chromium reais**: “Ceara” produz
  WER 0,25 contra “Ceará”, enquanto `Estado=CE` resulta em sucesso funcional. Isso verifica
  o instrumento de medição, não estima a qualidade de modelos reais.
- Testes de transporte exercitam concorrência serializada e timeout com subprocesso real;
  testes de provider verificam normalização de erros, JSON inválido e parâmetros opcionais.
- Testes STT rápidos verificam composição, erro/vazio, cache/lazy loading e consumo de
  segmentos. Não baixam pesos nem acionam inferência real.
- Instalação editável e cinco comandos com `--help` verificados; startup/saída da CLI textual
  e erro estruturado da CLI de voz testados sem requisição ao provider.
- `audio-evaluate-py` executado com um arquivo ausente: manteve o FAIL em CSV/HTML/JSONL,
  sem inventar transcrição ou baixar modelo. O catálogo de 19 roteiros foi carregado/validado.
- `git diff --check` aprovado. Nenhum commit foi criado.

Ambiente verificado: Python 3.14.7. A configuração continua compatível sintaticamente com
Python 3.12+, mas não houve execução em um segundo interpretador nesta sessão. As restrições
do sandbox bloquearam Chromium e o despertar do loop após `asyncio.to_thread`; os testes
foram executados fora dessa restrição com formulários locais. O problema de ambiente foi
reproduzido separadamente, sem mascará-lo com mocks no código de produção.

## O que foi preservado e por quê

LanguageModel, ModelSession, ToolClient, SpeechToTextEngine, AudioPreprocessor, a independência
dos dois componentes, lazy loading/cache, perfis, OpenAI compatível, MCP próprio, encapsulamento
Playwright, métricas micro e CSV/HTML. Essas separações já permitiam a composição e não
justificavam outro framework. `inspect_form` foi enriquecido; não se criou uma tool concorrente
`get_form_state`. Os nomes AudioAgent/FormAgent e do projeto foram mantidos.

As mudanças de compatibilidade deliberadas são de comportamento: envio exige autorização
externa/confirmação; expectativa no CSV não autoriza sozinha; resultado funcional usa valores
exatos e estado observado; retries LLM são zero. Os comandos de texto e áudio permanecem,
mas resultados anteriores devem ser reexecutados sob a nova definição, não comparados sem ressalva.

## Limitações remanescentes e prioridades

| Prioridade | Limitação | Próxima ação justificada |
|---|---|---|
| P0 para evidência empírica do TCC | Roteiros não são corpus; sem avaliação real de STT/LLM nesta sessão | Coleta autorizada, revisão de referências/oráculos e piloto A/B/C |
| P1 metodológica | Códigos observados não provam causas semânticas/STT | Contraste B/C pareado, repetição e adjudicação com evidência JSONL |
| P2 | Negação textual conservadora pode bloquear intenções válidas; correções/ambiguidades dependem do LLM | Medir falso bloqueio/erro semântico, preservando permissão externa |
| P2 | Estado observa controles nativos visíveis e escritas declaradas, não toda mutação transitória | Definir formulário experimental e ampliar observação somente com hipótese concreta |
| P2 | Confirmação de envio depende de indicador específico | Validar oráculo em cada formulário; não inferir persistência no backend |
| P2 | Um só runtime/hardware e modelos remotos potencialmente mutáveis | Arquivar ambiente/pesos/configuração e repetir em condições controladas |
| P2 | Historico é limitado por turnos, mas não por orçamento total de tokens/tools por resposta | Medir custo/tamanho antes de adicionar política de truncamento |
| P3 | Widgets customizados, iframes, múltiplos formulários/grupos dinâmicos complexos, Shadow DOM fechado | Fixtures e contrato por cenário, antes de ampliar automação |
| P3 | Validações JS assíncronas, autocomplete de rede e hidratação de frameworks | Experimentos controlados específicos; não prometer suporte universal |

A trava não impede JavaScript da própria página de enviar dados ao receber input/change.
O escopo é execução das tools por um host confiável em formulários controlados. O seletor de
sucesso é um oráculo experimental, não uma garantia sobre servidores externos. A composição
não transforma um pipeline STT em um segundo agente autônomo; a fundamentação da nomenclatura
está em [experimentos.md](experimentos.md), com literatura primária.

## Experimentos seguintes e ameaças à validade

Primeiro, piloto de gravação e revisão; depois A/B/C pareados com variação de um fator por
rodada. A arquitetura permite testar tolerância a erros lexicais, sensibilidade a entidades,
propagação de correções, efeito de VAD/modelo STT, efeito de prompt/provider e proteção de
submissão quando “não” é perdido na transcrição. As métricas disponíveis e suas fórmulas estão
no [protocolo experimental](experimentos.md); não foram criadas estimativas de desempenho real.

A validade interna depende de manter estado, ordem, cache, parâmetros e oráculos controlados;
a externa é limitada pelo tamanho e diversidade do corpus e dos formulários; a de construção
é limitada por WER não medir compreensão, pelo proxy de envio e pelo conjunto observável de
controles. Amostras por falante/caso não são independentes. Sem gravações reais, revisão dos
oráculos, replicações e análise de incerteza, os testes de software validam a infraestrutura,
não as hipóteses empíricas do TCC. O detalhamento está no protocolo e na proposta de dataset.
