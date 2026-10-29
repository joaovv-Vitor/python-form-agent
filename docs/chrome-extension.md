# Extensão VozForm para Chrome

A extensão é uma segunda interface do projeto. A aplicação web permanece em
`http://127.0.0.1:8000/`, com o catálogo, a entrada por URL e o fluxo de envio
simulado já existentes. CLI e avaliações também continuam disponíveis.

A extensão preenche os campos na **aba escolhida pelo usuário**, usando a sessão
do próprio Chrome. Ela grava áudio ou aceita um arquivo, permite correções por
texto e áudio e conduz a revisão. O envio é manual, no botão do próprio site.

## Preparar e executar

Use o mesmo ambiente Python e `.env` da aplicação web. Na raiz do projeto:

```bash
cd frontend
npm ci
npm run build
npm run build:extension
cd ..
HF_HUB_CACHE=reports/model-cache .venv/bin/form-web-py
```

O build web escreve em `frontend/dist`; o da extensão escreve em `extension/dist`.
Um build não apaga o outro. A pasta `extension/public` contém os arquivos fonte do
manifesto, do service worker e do script de interação com os campos. O painel
fica em `frontend/src/extension` e compartilha o gravador de áudio com a web.

Requer Chrome 116+ e o servidor Python rodando. Se o servidor já estava ligado
antes de atualizar o código, reinicie-o para disponibilizar as novas rotas.

## Instalar no Chrome

1. Abra `chrome://extensions` e ative **Modo do desenvolvedor**.
2. Clique em **Carregar sem compactação**.
3. Selecione a pasta **`extension/dist`** deste projeto, que contém `manifest.json`.
4. Fixe o VozForm na barra de extensões para facilitar o acesso.
5. Abra `http://127.0.0.1:8000/extension/setup` e copie o código de conexão.
6. Abra o site com o formulário e clique no ícone VozForm nessa aba.
7. No painel lateral, confira o endereço do servidor, cole o código e clique em
   **Usar formulário desta aba**.

O endereço padrão é `http://127.0.0.1:8000`; `http://localhost` e outras portas
locais também são aceitos. O código muda a cada reinício do servidor. É guardado
somente no armazenamento da sessão do Chrome. Chaves do provedor de IA continuam
no servidor, no `.env`, e não são incluídas no pacote da extensão.

Depois de recompilar a extensão, clique em **Atualizar** no cartão do VozForm em
`chrome://extensions`. Abra novamente o painel e selecione o formulário.

Se o Chrome não liberar o acesso à aba, volte ao site do formulário e clique no
ícone **VozForm na barra de extensões**. Abrir apenas o painel pelo seletor lateral
do Chrome não concede o mesmo acesso temporário. Depois use **Usar formulário desta aba**.
Páginas internas como `chrome://extensions` servem para instalar/atualizar a extensão;
o preenchimento é iniciado na aba do site.

## Usar

- Grave, pare e ouça antes de clicar em **Preencher com áudio**, ou escolha um
  arquivo WAV, MP3, MP4, M4A, FLAC, WebM ou OGG.
- Durante a revisão, peça uma correção por texto ou envie outro áudio. O gravador
  usa os mesmos limites de tamanho e duração da aplicação web.
- Confira as pendências, os valores encontrados e as transcrições no painel.
- Conclua a revisão e envie pelo botão original do site.
- Encerre a sessão antes de selecionar outro formulário.

A sessão permanece vinculada à aba original: trocar de aba não muda o destino.
Uma navegação, recarga ou substituição do formulário pode invalidar a sessão;
nesse caso, encerre e selecione a página novamente. Fechar o painel solicita o
encerramento da sessão; se a conexão cair, os comandos expiram em até 30 segundos.
O preenchimento já aplicado permanece na página. O assistente não reverte valores
ao encerrar e não restaura uma revisão após fechar o painel.

Por padrão, `WEB_MAX_SESSIONS=1` limita o servidor a uma sessão por vez, contando
web e extensão. Encerre a anterior ou configure `WEB_MAX_SESSIONS=2` para trabalhar
com as duas interfaces simultaneamente. O processamento de fala permanece serial.

## Escopo desta versão

- Um formulário HTML visível na página principal, com até 200 controles.
- Campos nativos de texto, e-mail, telefone, URL, número, data/hora, textarea,
  select simples, checkbox e radio. Referências estáveis distinguem controles sem
  ID e opções radio com o mesmo nome.
- Páginas autenticadas podem ser usadas quando o formulário já estiver acessível
  na aba escolhida; a extensão não executa login.
- Iframes, campos customizados, seleção múltipla, senha, upload de arquivos e
  navegação entre etapas não são cobertos. A extensão não resolve CAPTCHA.
- A revisão confere se outros campos mudaram; mudanças automáticas do site ou
  edições manuais durante a revisão podem exigir reiniciar a sessão.

Permissões: acesso temporário à aba escolhida (`activeTab`), execução do script
de campos (`scripting`), painel lateral (`sidePanel`), armazenamento da sessão
(`storage`) e comunicação HTTP com o servidor local. Não há permissão permanente
para ler todos os sites. O painel transfere o áudio e o inventário/valores dos
campos ao servidor selecionado; o processamento usa o provedor de IA configurado
e os registros locais do projeto.

## Arquitetura e verificações

O servidor continua usando `AudioFormPipeline`, `FormAgent`, esclarecimento e
`ReviewSession`. Para sessões da extensão, `ExtensionToolsClient` substitui apenas
o transporte de ferramentas. Para sessões web, MCP/Playwright continua igual.

O painel consulta comandos pendentes e devolve resultados autenticados. Cada
comando tem ID, URL e identificador do documento. O script só oferece inspeção,
leitura e preenchimento; não executa código recebido do servidor e não oferece
clique em envio. Respostas são guardadas por ID para que uma confirmação perdida
não repita o preenchimento.

```bash
.venv/bin/pytest -q tests/unit/web_api/test_extension.py
.venv/bin/pytest -q tests/integration/test_web_application.py
cd frontend
npm test
npm run format:check
```

Os testes de navegador carregam o pacote real no Chromium do Playwright, com
áudio e modelo de linguagem simulados. Eles verificam gravação, preenchimento da
aba real, correção, confirmação perdida sem repetição e preservação da interface
web. Não substituem a avaliação da precisão do Whisper/LLM com dados reais.
