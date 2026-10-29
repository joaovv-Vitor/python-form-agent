# Aplicação web V1

A [extensão Chrome](chrome-extension.md) também está disponível e usa o mesmo servidor.
Esta aplicação web continua independente, com todos os fluxos descritos abaixo.

A aplicação permite selecionar um dos quatro exemplos ou informar a URL de um formulário
HTML simples. O Cadastro original continua sendo o primeiro e o padrão. Recebe áudio
gravado pelo microfone ou enviado em arquivo e mostra os valores observados
no navegador automatizado, acompanha o processamento e permite perguntas e
correções por texto, microfone ou outro arquivo na mesma sessão. O envio é a simulação do
formulário de exemplo, com confirmação humana separada. URLs externas permitem
preenchimento e revisão; o envio automático fica habilitado apenas nos exemplos integrados.

## Executar localmente

Na raiz do repositório, com Python 3.12+ e Node.js 22.12+ (Node 24 recomendado):

```bash
python -m pip install -e '.[audio,web,dev]'
python -m playwright install chromium
```

Configure o provider no `.env` a partir do `.env.example`, caso ainda não esteja
configurado. A chave permanece no backend. As variáveis web também podem ficar
nesse arquivo; valores exportados no ambiente têm precedência.

Compile a interface:

```bash
cd frontend
npm ci
npm run build
cd ..
```

Inicie o serviço na raiz do projeto:

```bash
HF_HUB_CACHE=reports/model-cache form-web-py
```

Abra [http://localhost:8000](http://localhost:8000). O serviço abre inicialmente o Cadastro
original. Em **Formulário de destino**, selecione outro exemplo ou informe uma URL e
pressione **Abrir formulário**. A troca encerra a sessão anterior e inspeciona o novo destino.
Durante o processamento ou a revisão, encerre a sessão antes de trocar de formulário.
O sistema prepara os campos reais antes de aceitar o áudio. Clique em **Usar microfone**, autorize
o acesso no navegador e depois clique em **Parar gravação**. Você pode cancelar a
gravação sem enviá-la. A opção de selecionar um arquivo continua disponível abaixo.
Escute a prévia e pressione **Preencher com áudio** quando estiver pronto; a gravação
não é enviada automaticamente. Na revisão, use o campo de texto
ou a seção **Corrigir campo por áudio**, que fica aberta: grave pelo microfone ou
selecione um arquivo e clique em **Enviar áudio de correção**. Diga o campo e o novo valor,
por exemplo, “Corrija minha cidade para Quixadá”; os demais campos são mantidos.
Para encerrar sem enviar, use
**Encerrar sessão**.

O microfone requer HTTPS ou localhost e permissão do navegador. Se o acesso for
negado ou não houver um dispositivo compatível, o envio de arquivos permanece
disponível. O microfone é liberado ao parar, cancelar ou sair da sessão. A gravação
para automaticamente perto do limite de duração e respeita o limite de tamanho;
o backend também valida os arquivos antes da transcrição. A interface aceita
WAV, MP3, MP4, M4A, FLAC, WebM e OGG; o formato da gravação é escolhido conforme
o suporte do navegador.

O primeiro uso pode baixar/carregar o modelo. O padrão reproduz a configuração
do caso perfeito no Cadastro: large-v3, português, CPU/int8, orientação de e-mail e regras
locais. Nos outros destinos, as dicas de transcrição são geradas a partir dos campos e opções
inspecionados. Para experimentar outro modelo, defina `WEB_STT_MODEL` no servidor e
registre a nova condição; essa mudança não é controle disponível ao usuário.

Para desenvolvimento com atualização automática da interface, mantenha a API
na porta 8000 e execute `npm run dev` em `frontend/`. Acesse o endereço informado
pelo Vite; `/api` e `/forms` são encaminhados para o backend. O servidor de desenvolvimento
fica restrito ao endereço local e não é a forma de publicação em produção.

## Sessões, eventos e dados

O catálogo mantém esta ordem e cada página pode ser aberta separadamente:

| Exemplo | URL local | Campos característicos |
|---|---|---|
| Cadastro original | `/forms/cadastro` | Os sete campos do formulário anterior, sem alterar seu HTML |
| Contato | `/forms/contato` | Assunto, mensagem e preferência de retorno |
| Inscrição em evento | `/forms/inscricao` | Evento, modalidade, data e acessibilidade |
| Suporte técnico | `/forms/suporte` | Produto, categoria, prioridade e descrição |

O preenchimento usa o inventário descoberto em cada página; o catálogo não fornece um mapa
de campos ao modelo. Os testes em `tests/integration/test_form_catalog.py` incluem valores
esperados diferentes para cada exemplo e verificam preenchimento, validade e envio simulado.

URLs externas devem usar HTTP/HTTPS, sem credenciais na URL, login ou redirecionamentos,
e apresentar um único formulário visível na página principal, com referências de campos únicas. Senhas, anexos, CAPTCHA,
componentes personalizados e formulários com várias etapas ficam fora desta versão.
Texto, textarea, listas nativas, datas, números, checkbox e radio podem ser inspecionados;
as limitações da revisão interativa continuam descritas no documento correspondente.

Destinos locais e privados adicionais precisam ser habilitados pelo operador em
`WEB_ALLOWED_FORM_HOSTS`, com nomes separados por vírgulas, e reinício do servidor.
Os exemplos integrados são resolvidos para os recursos empacotados e não dependem dessa
permissão. O navegador verifica destinos HTTP, bloqueia redirecionamentos, service workers
e WebSockets nas páginas externas. Essas verificações não substituem isolamento de rede:
mantenha o acesso controlado do piloto e use páginas autorizadas para o experimento.

- Uma sessão ativa por padrão; cada sessão tem cliente MCP, navegador, contexto
  de revisão e proprietário próprios. O cookie de propriedade é HTTP-only.
- O servidor reutiliza o motor STT e serializa suas inferências, inclusive as
  dos áudios de correção. Os arquivos são decodificados antes da inferência.
- Limites padrão: 25 MiB, 120 segundos por áudio, 15 minutos de inatividade ao
  aguardar o usuário e 600 segundos de limite operacional.
- Atualização da página ou reconexão SSE recupera a sessão do mesmo navegador.
  A conexão de eventos não mantém sozinha uma sessão inativa indefinidamente.
- Texto web é uma entrada literal. `AUDIO /caminho` digitado na conversa não
  abre arquivos locais; somente uploads recebidos e validados viram áudios.
- Cancelamento é cooperativo. Enquanto uma inferência nativa termina, a sessão
  pode ficar em **Encerrando**; novas ações no formulário ficam bloqueadas.
- Reiniciar o servidor perde as sessões em memória. Inicie uma nova sessão.
- JSONL é gravado continuamente em `reports/web/runs/`. Ao encerrar a sessão,
  `reports/web/sessions/<id>/form_data.json` conserva os dados finais e o histórico;
  os arquivos de áudio temporários de `reports/web/uploads/` são removidos.

A interface representa os campos sincronizados, com valores e validade
retornados pelo backend. Não é transmissão da tela do Chromium. Os campos não
são editáveis diretamente no frontend. A revisão suporta os tipos descritos em
[revisão interativa](revisao-interativa.md); a correção de checkbox/radio fica
fora da V1. O aceite dos termos pode ser declarado explicitamente no áudio inicial.

## Configuração

| Variável | Padrão | Finalidade |
|---|---|---|
| `WEB_DATA_DIR` | `reports/web` | Rastros e arquivos temporários |
| `WEB_HOST` | `127.0.0.1` | Endereço de escuta; o contêiner usa `0.0.0.0` internamente |
| `WEB_PORT` | `8000` | Porta da API e da interface compilada |
| `WEB_FRONTEND_DIR` | `frontend/dist` | Build estático da interface |
| `WEB_MAX_SESSIONS` | `1` | Número máximo de sessões ativas |
| `WEB_IDLE_SECONDS` | `900` | Expiração enquanto aguarda interação |
| `WEB_OPERATION_SECONDS` | `600` | Limite operacional antes de solicitar encerramento |
| `WEB_MAX_UPLOAD_BYTES` | `26214400` | Limite por arquivo |
| `WEB_MAX_AUDIO_SECONDS` | `120` | Duração máxima decodificada |
| `WEB_STT_MODEL` | `large-v3` | Modelo fixado pelo operador |
| `WEB_ALLOWED_FORM_HOSTS` | vazio | Hosts locais adicionais autorizados para o experimento |
| `WEB_COOKIE_SECURE` | `false` | Ativar em publicação HTTPS |
| `WEB_PUBLIC_ORIGIN` | origem da requisição | Origem HTTPS pública permitida para comandos |

`MODEL_PROFILE`, `LLM_*` e as chaves dos perfis continuam sendo as configurações
existentes do modelo de formulário. O perfil padrão é empacotado; para fornecer
outro arquivo, use `MODEL_PROFILES_FILE`. O destino web pertence à sessão e é independente
de `FORM_URL`; Chromium roda headless na web.

O frontend usa HTTP para comandos/upload e SSE para acompanhamento. A API inclui
`GET /api/session` para recuperar a sessão ativa do proprietário; as demais
rotas e os contratos estão no [plano](plano-web-v1.md). `GET /api/health` é um
teste de vida da API e informa os limites de áudio. Ele não valida credenciais
remotas nem o tempo de inferência; a preparação da primeira sessão verifica o
acesso ao formulário/Chromium e informa erros de configuração ao usuário.

## Implantar no homelab

Os arquivos `deploy/Dockerfile` e `deploy/compose.yaml` constroem a interface e
instalam o runtime Python, Chromium e dependências de áudio. O serviço roda com
usuário sem privilégios de root, um processo de API e modo headless.

No `.env` do servidor, configure as credenciais e sua origem real:

```dotenv
WEB_PUBLIC_ORIGIN=https://formularios.seu-dominio.com
```

Na raiz do checkout, no homelab:

```bash
docker compose --env-file .env -f deploy/compose.yaml config --quiet
docker compose --env-file .env -f deploy/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose.yaml logs -f web
```

O Compose publica a porta 8000 somente em `127.0.0.1`. Encaminhe seu domínio
HTTPS para essa porta pelo proxy do homelab e mantenha o controle de acesso do
piloto no proxy. Há um trecho de configuração de Nginx em
`deploy/nginx-location.conf.example`; adapte-o ao ambiente existente. Se o proxy
também estiver em contêiner, configure uma rede privada compartilhada e ajuste o
upstream, em vez de usar o loopback de outro contêiner.

O proxy precisa permitir uploads de 26 MiB incluindo o envelope multipart,
desabilitar buffering para SSE e manter conexões de acompanhamento abertas.
No Compose, cookies seguros ficam habilitados e a origem pública é obrigatória.
Não coloque chaves no build do frontend ou em variáveis públicas da interface.

Os volumes `form-data` e `whisper-cache` conservam rastros e pesos. Sessões ativas
não sobrevivem ao reinício. Não aumente o número de processos da API: as sessões
e o modelo residente pertencem a um único processo. O prazo de parada do contêiner
permite aguardar uma operação nativa dentro do limite configurado.

## Verificação

```bash
cd frontend
npm ci
npm run build
npm test
npm run format:check
cd ..
pytest
ruff check .
ruff format --check .
mypy
```

O teste `tests/integration/test_web_application.py` usa HTTP, frontend compilado,
MCP e Chromium reais, com STT/LLM simulados. Exercita upload, recarregamento,
correção, confirmação e limpeza. Exige o build anterior; sem o build, é ignorado
explicitamente. Salva capturas de desktop/celular em `reports/web-ui/`.

Na implementação local foram aprovados 303 testes Python, com um teste opcional
de Whisper real ignorado, além de dois testes de estado do frontend, build,
formatação, Ruff e mypy. O teste do wheel confirmou o empacotamento dos recursos
de runtime. O Compose foi validado sintaticamente. A imagem Docker e o piloto
real no i5/12 GB ainda precisam ser executados no homelab: o daemon Docker não
estava disponível no ambiente de desenvolvimento.

As verificações locais usaram Python 3.14 e Node.js 26. O contêiner foi preparado
com Python 3.12 e Node.js 24; esse ambiente deve ser confirmado na execução da
imagem. A preparação e limpeza reais de uma sessão local também foram verificadas
com a configuração do projeto, sem executar inferência nem chamar o provedor LLM.

Para o piloto, envie o áudio do caso perfeito pela interface e registre sucesso,
latência, pico de memória e limpeza após encerrar. Compare carga inicial com
modelo já carregado. Os testes com componentes simulados validam o fluxo de
software, não o desempenho do Whisper/LLM nem a capacidade do homelab.
