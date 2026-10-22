# Plano de implementação — aplicação web V1

Data: 22 de outubro de 2026.

Este documento propõe a implementação; não indica funcionalidades web já entregues.

Atualização de implementação (22/10/2026): os marcos 1 a 5 foram implementados e
validados localmente, incluindo o fluxo completo em HTTP/MCP/Chromium com modelos
simulados. O marco 6 tem arquivos de contêiner/proxy e Compose validados
sintaticamente; execução da imagem e piloto com modelos reais no homelab permanecem
pendentes. Consulte o [guia da V1](web-v1.md) para comandos e limites efetivos.

## 1. Objetivo e escopo

Disponibilizar a PoC como aplicação web no homelab, usando exclusivamente o
formulário padrão de `examples/test-form/index.html` e arquivos de áudio enviados
pelo usuário. Reaproveitar o núcleo Python, preservar a CLI e tornar o andamento
e a revisão acessíveis pela interface.

Fluxo da V1:

1. Abrir a aplicação e iniciar uma sessão.
2. Consultar os campos vazios do formulário padrão.
3. Selecionar um arquivo de áudio e iniciar o preenchimento.
4. Acompanhar transcrição, preenchimento e conferência.
5. Consultar resultados e pendências; responder a perguntas e corrigir um campo
   por vez, por texto ou por outro arquivo de áudio.
6. Concluir a revisão e, se desejar, confirmar o envio simulado do formulário padrão.
7. Encerrar a sessão e liberar seus recursos.

O formulário padrão tem sete campos: nome, e-mail, telefone, data de nascimento,
cidade, estado e aceite dos termos. O protótipo baixado usa seis campos e valores
fixos; a interface deverá passar a representar os sete campos reais, incluindo
as opções do select e o checkbox. O formulário atual confirma envio por um
indicador DOM de simulação; esta versão não inclui persistência de cadastro em banco.

Ficam para versões seguintes: URL arbitrária, outros formulários, captura de
microfone, transcrição contínua durante a fala, transmissão de vídeo do navegador,
edição manual direta dos campos e retomada de sessões após reinício do servidor.
A revisão mantém os tipos atualmente suportados pela `ReviewSession`; correção
de checkbox/radio não entra nesta versão. O aceite dos termos no preenchimento
inicial depende da declaração explícita do usuário.

## 2. Decisões de arquitetura

| Tema | Proposta para a V1 |
|---|---|
| Repositório | Frontend e backend no repositório atual |
| Frontend | Reaproveitar o protótipo React/TypeScript, com build local independente do gerador |
| API | FastAPI, em novo pacote `src/web_api/` |
| Comunicação | HTTP para comandos e upload; SSE para eventos do servidor |
| Núcleo | `AudioAgent`, `AudioFormPipeline`, `FormAgent`, `ReviewSession` e MCP existentes |
| Visualização | Representação dos campos reais a partir de inspeções e retornos das ferramentas |
| Autoridade sobre valores | DOM do navegador automatizado; frontend exibe o estado recebido |
| Sessões | Em memória, pertencentes ao usuário e com encerramento por inatividade |
| Processamento | Fila limitada; uma transcrição por vez; modelo STT compartilhado no processo |
| Implantação inicial | Um processo de API, build estático do frontend e proxy HTTPS existente |
| Dados locais | Volumes separados para cache do modelo, temporários e rastros |

SSE envia notificações do backend ao navegador; respostas do usuário continuam
sendo requisições HTTP. O processamento pertence à sessão, e não à conexão SSE.
Desconectar o acompanhamento não deve interromper o preenchimento nem iniciar
outra execução ao reconectar.

A V1 mostra uma **visualização sincronizada do formulário padrão**. Não promete
transmitir a tela do Chromium. Rótulos, valores, opções e validade vêm do backend;
cores e mensagens são apresentação. A estrutura será mantida durante upload,
processamento e revisão, inclusive ao atualizar a página com uma sessão ativa.

## 3. Organização proposta

```text
frontend/
  src/
    components/          # formulário, upload, mensagens e controles
    services/            # cliente HTTP e assinatura de eventos
    ...
src/
  audio_agent/           # STT existente
  form_agent/            # agente, adaptadores e MCP existentes
  voice_form/
    ...
    service.py           # coordenação compartilhada com a CLI
    interaction.py       # entradas e mensagens independentes do terminal
  web_api/
    app.py               # criação da API e ciclo de vida
    routes/              # sessões, arquivos, revisão e eventos
    schemas.py           # contratos HTTP e mensagens de apresentação
    sessions.py          # propriedade, estado e recursos de cada sessão
    worker.py            # execução, fila limitada e controle de concorrência
    events.py            # projeção de estado e distribuição de eventos
tests/
  ...
  unit/web_api/
  integration/
deploy/
  Dockerfile
  compose.yaml
docs/
  plano-web-v1.md
```

Os nomes são propostas de organização. A implementação deve manter a divisão
pequena, agrupando arquivos quando não houver responsabilidade suficiente para
justificar um módulo separado.

Atualizar também o empacotamento de `pyproject.toml`, a seleção de módulos do mypy,
as dependências opcionais da web, o `.gitignore` do frontend e a documentação.
O build deve incluir formulário, prompts e configuração de perfis necessária ao
runtime, sem depender de arquivos presentes apenas no checkout do desenvolvedor.

## 4. Coordenação e estado

### Reaproveitamento do código

Extrair gradualmente a coordenação de `voice_form/cli.py` para um serviço usado
pela CLI e pela API. A CLI continuará responsável por argumentos e interação de
terminal; a API por HTTP, autenticação da sessão e apresentação de eventos.

As chamadas de `input()` e `print()` não podem executar no fluxo web.
`ReviewSession` e `ClarificationSession` já recebem callbacks de entrada e eventos;
usar essa separação como ponto de adaptação. A confirmação de envio em
`form_agent/confirmation.py` também precisa separar a pergunta no terminal da
operação de confirmação executada pelo host.

Introduzir entradas tipadas para texto, áudio recebido, resposta, pular, concluir
e encerrar. O adaptador da CLI interpreta comandos como `AUDIO caminho`; a web
recebe arquivos e texto como dados distintos. Um texto digitado no navegador não
pode virar um caminho de arquivo no servidor. Caminhos de uploads são resolvidos
internamente pelo backend e nunca fornecidos pelo cliente.

### Dados por sessão

Guardar identificador, proprietário, timestamps, configuração efetiva, estado,
Application/cliente MCP, resultado atual, último snapshot observado, pendências,
pergunta em aberto, histórico de mensagens/correções, tarefa em execução e RunTrace.
O motor STT é compartilhado entre sessões, mantendo configuração fixa e acesso
serializado para evitar cargas concorrentes do modelo.

Estados propostos:

```text
preparando → pronto → na_fila → transcrevendo → preenchendo → verificando → revisando
revisando ↔ aguardando_resposta
revisando → revisao_concluida → enviando → enviado
```

Estados adicionais: `erro`, `encerrando`, `encerrado` e `expirado`.
Correções voltam ao estado de revisão após transcrição/aplicação/conferência.
Uma correção rejeitada sem escrita mantém a sessão utilizável; uma divergência
no navegador invalida a verificação e impede envio.

Cada sessão aceita uma operação mutável por vez. A sequência de inspeção,
interpretação, escrita e conferência deve ser serializada. A interface consulta
o snapshot mantido pelo backend, sem disparar inspeções concorrentes que disputem
o navegador com o agente.

### Ciclo de vida e limites iniciais

Valores iniciais propostos, configuráveis e sujeitos à medição no homelab:

- Uma sessão ativa e uma transcrição por vez no primeiro deploy. Ampliar somente
  após medir recursos e validar isolamento; testes já devem cobrir esse isolamento.
- Encerramento após 15 minutos sem atividade humana quando a sessão estiver
  aguardando interação. Processamento tem timeout próprio, separado da inatividade.
- Upload de até 25 MiB e até 2 minutos por áudio, com formatos atualmente aceitos:
  WAV, MP3, MP4, M4A e FLAC.
- Limite de bytes no proxy e na API; conferência de duração e decodificação antes
  da inferência. Extensão e MIME declarados não bastam para validar conteúdo.
- Fila com capacidade limitada e resposta explícita quando não houver capacidade.

Encerrar fecha navegador, subprocesso MCP, cliente do modelo e trace, e remove
os uploads temporários da sessão. A inferência nativa executada em thread não é
interrompida à força ao cancelar uma coroutine: sinalizar encerramento, impedir
novas ações e coordenar a limpeza com o término do trabalho. O estado final não
pode ser marcado como preenchimento bem-sucedido após um encerramento solicitado.

Sessões em memória expiram em reinícios. A interface explica essa situação e
oferece iniciar outra sessão; rastros já gravados permanecem para diagnóstico.

## 5. Contratos HTTP e eventos

Todas as rotas de sessão validam propriedade e estado. Os nomes abaixo são
propostos; fixar o contrato antes de integrar o frontend.

| Operação | Rota proposta | Comportamento |
|---|---|---|
| Criar sessão | `POST /api/sessions` | Reserva recursos e abre o formulário fixo; retorna ID/estado |
| Consultar | `GET /api/sessions/{id}` | Estado, snapshot, mensagens, pendências e operações permitidas |
| Acompanhar | `GET /api/sessions/{id}/events` | SSE com sequência e identificação dos eventos |
| Áudio inicial | `POST /api/sessions/{id}/audio` | Upload multipart; aceita operação e retorna `202` |
| Texto/resposta | `POST /api/sessions/{id}/messages` | Entrega entrada à revisão ou ao esclarecimento pendente |
| Áudio de correção | `POST /api/sessions/{id}/corrections/audio` | Novo upload para a mesma revisão e o mesmo formulário |
| Descartar pedido | `POST /api/sessions/{id}/review/skip` | Descarta o pedido pendente sem alterar valores |
| Concluir revisão | `POST /api/sessions/{id}/review/complete` | Finaliza revisão; pergunta pendente exige resposta ou descarte |
| Confirmar envio | `POST /api/sessions/{id}/submit` | Exige confirmação explícita e estado verificado |
| Encerrar | `DELETE /api/sessions/{id}` | Solicita encerramento idempotente e limpeza |
| Saúde | `GET /api/health` | Verifica o serviço; prontidão do runtime é informada separadamente |

Ao criar a sessão, o frontend pode acompanhar `preparando` até receber os campos
inspecionados. O upload só é liberado em `pronto`. O formulário de destino é uma
configuração do servidor; estas rotas não recebem URL arbitrária.

Cada evento público contém sequência, ID da sessão/operação, horário, tipo e
payload de apresentação. Exemplos: mudança de estado, transcrição disponível,
valor escrito, valor conferido, pergunta, correção aplicada, erro e envio confirmado.
Valores recém-escritos podem aparecer como aguardando conferência; o sucesso só
é mostrado após a verificação correspondente.

O callback de eventos alimenta tanto o RunTrace quanto a interface. Publicação
originada em thread precisa respeitar o event loop. A distribuição não pode
bloquear o agente por causa de um cliente lento; usar buffer limitado e permitir
recuperar o snapshot completo. Reconexão usa a sequência para recuperar eventos
disponíveis; se o histórico não estiver no buffer, reidrata estado por `GET`.

A confirmação de envio deve estar vinculada à versão dos valores revisados.
Reinspecionar antes do envio, manter os bloqueios por pendências/veto e revogar
a autorização após a tentativa, como no fluxo existente. Não repetir envio
automaticamente após timeout. A interface só exibe sucesso após confirmação
retornada pelo backend para o formulário simulado.

## 6. Interface da V1

Usar a última versão baixada do protótipo como referência visual, trazendo fontes
para `frontend/`. Remover dependências de execução/configurações exclusivas do
gerador e estabelecer um build reproduzível com lockfile e versões verificadas.

Substituir a entrada de URL por uma identificação do formulário padrão. Mostrar
os campos assim que a sessão estiver pronta, antes de selecionar ou enviar áudio.
Substituir todos os controles de gravação por seleção de arquivo, nome/tamanho,
opção de trocar/remover e botão explícito para iniciar o preenchimento. Não
solicitar permissão de microfone.

Manter formulário e painel lateral na mesma estrutura durante toda a sessão.
O painel reúne upload, atividade atual e mensagens, com entrada de texto e novo
arquivo na revisão. Oferecer cancelar pedido pendente, concluir revisão e encerrar.
No celular, controles não devem cobrir campos ou impedir rolagem.

Eliminar dados e resultados fixos, timers de sucesso e a correção que sempre
troca a cidade por Quixadá. A animação pode indicar espera, mas campos,
pendências, progresso e sucesso devem depender de eventos reais. A mensagem
"todos os campos obrigatórios estão preenchidos" precisa derivar do estado
recebido. Não rotular a representação como transmissão ao vivo do navegador.

## 7. Marcos de implementação

| Marco | Trabalho principal | Critério de conclusão |
|---|---|---|
| 1. Base web | Trazer frontend, tornar build independente, criar API e preparar layout do formulário fixo | Frontend compila, API responde e tela tem espaço para os sete campos e upload, sem valores fictícios |
| 2. Serviço e sessões | Extrair coordenação, adaptar entradas, criar proprietário/estado/recursos e encerramento | Sessão pronta mostra os campos inspecionados; criar/consultar/encerrar libera recursos; CLI mantém comportamento |
| 3. Áudio até formulário | Upload validado, fila, STT compartilhado e pipeline real | Um arquivo do caso perfeito preenche o DOM real e gera resultado/rastro; API segue responsiva |
| 4. Acompanhamento | SSE, projeção dos eventos e visualização sincronizada | Etapas e valores reais chegam ao frontend; recarregar/reconectar recupera a mesma sessão |
| 5. Revisão e envio | Perguntas, correção por texto/arquivo, conclusão e confirmação separada | Corrigir um campo preserva os demais; pendência bloqueia envio; confirmação produz sucesso simulado verificado |
| 6. Implantação e piloto | Contêiner, volumes, proxy, acesso controlado e validação no homelab | Fluxo completo funciona pelo domínio com áudio real e medição de recursos |

O marco 3 é a primeira entrega vertical utilizável: formulário padrão + upload +
preenchimento real. Os marcos 4 a 6 completam a V1 descrita neste documento.
Não é necessário fechar um cronograma antes de medir o marco 3 no servidor.

## 8. Implantação no homelab

Preparar imagem de runtime com Python, dependências de áudio, Chromium e
dependências de sistema compatíveis. Fazer o build do frontend em etapa própria,
e servir seus arquivos estáticos junto da API, sob a mesma origem HTTPS. Manter
o proxy já utilizado no homelab, configurando upload e conexões SSE sem buffering.

Executar uma única instância/processo da API enquanto as sessões estiverem em
memória. Workers independentes não compartilham sessões, filas ou cache STT.
O Chromium deve operar em modo headless no servidor.

Persistir o cache dos pesos e os rastros em volumes; uploads são temporários.
Fornecer credenciais somente ao backend por configuração do servidor. Para o
piloto acessível pelo domínio, usar controle de acesso no proxy e vincular cada
sessão ao cliente autorizado, com credencial de sessão protegida; conhecer um ID
não deve dar acesso às mensagens ou aos arquivos de outra sessão. Restringir
comandos de mutação à origem da aplicação e não publicar endpoints de arquivos
ou caminhos internos sem validação de propriedade.

Manter o perfil reprodutível do caso perfeito como configuração inicial:
`large-v3`, português, CPU/int8, tratamento `rules` e orientação de e-mail usada
no piloto documentado. Contexto automático do formulário continua disponível,
mas sua comparação com as dicas fixas deve ficar identificada como condição
separada. O usuário não troca o modelo a cada upload.

Medir primeira carga e execução com modelo já carregado, tempo STT/total, pico
de RAM e recuperação após encerrar sessões. Alterar modelo ou limite de sessões
somente com nova avaliação de qualidade e recursos no i5/12 GB.

## 9. Validação e critérios de aceite

Testes rápidos continuam sem chamadas reais ao provedor ou download de pesos.
Integrações exercitam API, MCP e Chromium com STT/LLM simulados; um piloto manual
separado valida áudio e modelos reais no homelab.

Casos essenciais:

- Formulário padrão correto e visível antes do upload; sete campos e valores
  iniciais correspondem à inspeção real, inclusive opções e checkbox.
- Áudio válido, vazio, corrompido, extensão indevida, tamanho/duração excedidos e
  falha de STT/provedor. Falha anterior ao preenchimento não inventa valores.
- Uma operação por sessão; limite de capacidade; nenhuma duplicação automática
  ao reconectar ou repetir uma confirmação de envio.
- Separação entre sessões/proprietários e recusa de IDs/arquivos não pertencentes
  ao cliente. Texto recebido não consegue selecionar arquivos locais.
- Pendência pergunta ao usuário; resposta retoma o pedido correto; pular descarta
  somente o pedido pendente. Correção por texto e áudio preserva outros campos.
- Reconexão e atualização da página recuperam estado; encerramento, expiração,
  erro e shutdown não deixam navegadores ou subprocessos abandonados.
- Envio sem confirmação, com pendência, veto, estado alterado ou resultado incerto
  é bloqueado. Envio simulado confirmado corresponde ao indicador do DOM.
- Fluxo visual utilizável em desktop e celular, inclusive mensagens, erros e
  controles desabilitados durante operações incompatíveis.

Executar os checks de qualidade Python já existentes e o build/verificação de
tipos do frontend, com testes de comportamento para as transições relevantes.
Após alterar a coordenação, conferir regressão da CLI e das avaliações em lote.

A V1 estará concluída quando uma pessoa acessar pelo domínio, consultar o
formulário padrão, enviar um áudio real, acompanhar os valores efetivos, corrigir
um campo na mesma sessão, concluir e confirmar o envio simulado, com rastros
compatíveis com a avaliação da PoC e sem depender do terminal do servidor.

## 10. Referências usadas no planejamento

- Código atual: `voice_form/cli.py`, `pipeline.py`, `review.py`, `clarification.py`,
  `audio_agent/engines/faster_whisper.py`, `form_agent/bootstrap.py`,
  `confirmation.py`, `experiments.py` e adaptadores de MCP/navegador.
- [Configuração e limites do caso perfeito](caso-perfeito.md).
- [Revisão interativa existente](revisao-interativa.md).
- [FastAPI: upload de arquivos](https://fastapi.tiangolo.com/tutorial/request-files/).
- [FastAPI: referência de SSE](https://fastapi.tiangolo.com/fr/reference/sse/).

Documentação FastAPI consultada via Context7 em 22/10/2026. Escolher e fixar versões
compatíveis na etapa de implementação, sem assumir que as versões amplas do
protótipo ou do ambiente de geração constituem um ambiente de produção validado.
