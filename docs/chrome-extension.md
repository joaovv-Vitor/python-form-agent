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
5. Abra o site com o formulário e clique no ícone VozForm nessa aba.
6. No painel lateral, clique em **Usar formulário desta aba**. A conexão é automática.
7. Na primeira gravação, clique em **Ativar microfone** e depois em **Permitir microfone**
   na aba de autorização. Aceite a solicitação do Chrome; a extensão volta ao formulário.
   As próximas gravações começam diretamente no painel com **Usar microfone**.
   A aba de autorização permanece aberta, sem capturar áudio, para não encerrar uma
   permissão temporária do Chrome ao fechá-la. Feche essa aba quando terminar de usar.

O endereço padrão é `http://127.0.0.1:8000`; `http://localhost` e outras portas
locais também são aceitos, em **Configurações do servidor**. Não há código para copiar.
A extensão tem uma identidade fixa, definida pela chave pública do manifesto;
o servidor só inicia a conexão automática quando a origem enviada pelo Chrome corresponde
a essa identidade e a requisição usa o endereço local. A credencial interna é temporária,
fica em memória e muda a cada reinício. As chaves de IA continuam no `.env` do servidor.

**Migração da versão 0.1 para 0.2:** remova a extensão antiga em `chrome://extensions`
e carregue novamente `extension/dist`, pois a identidade mudou uma vez para ficar estável.
Isso não apaga os formulários nem a aplicação web. As próximas versões mantêm esse ID.

Depois de recompilar a extensão, clique em **Atualizar** no cartão do VozForm em
`chrome://extensions`. Recarregue também a aba do formulário para substituir o script
de campos já carregado. Abra novamente o painel e selecione o formulário.

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
- Se faltar um dado após o primeiro preenchimento, responda à pergunta com o
  microfone, um arquivo de áudio ou texto. Os campos já preenchidos são mantidos,
  e o microfone continua disponível para as próximas correções.
- Confira as pendências, os valores encontrados e as transcrições no painel.
- Conclua a revisão e envie pelo botão original do site.
- Encerre a sessão antes de selecionar outro formulário.

Se o microfone estiver bloqueado, o painel oferece novamente a autorização. Confira
as permissões do Chrome e do sistema operacional. Erros aparecem junto ao gravador;
quando ele está desabilitado, o painel explica qual etapa precisa terminar. A autorização
abre uma aba normal porque a solicitação inicial no painel lateral pode não ficar visível.
Essa etapa apenas verifica o dispositivo e fecha o fluxo de áudio; não envia gravações.
A confirmação do acesso bem-sucedido fica no armazenamento local da extensão e é
sincronizada entre as abas. Assim, voltar ao painel ou recarregá-lo não depende de uma
mensagem temporária nem de uma consulta de permissão desatualizada. O Chrome continua
validando cada captura; se o acesso for negado de fato, a confirmação é invalidada.

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
- Opções personalizadas com `role="radio"` ou `role="checkbox"` e estado
  `aria-checked`, como as alternativas de múltipla escolha do Google Forms.
  O inventário inclui o rótulo da pergunta quando disponível em um grupo ARIA,
  distingue grupos e relê o estado depois do clique. Se o site não confirmar a
  seleção, a operação informa erro.
- Páginas autenticadas podem ser usadas quando o formulário já estiver acessível
  na aba escolhida; a extensão não executa login.
- Iframes, outros campos customizados (como listas suspensas), select com seleção
  múltipla, senha, upload de arquivos e navegação entre etapas não são cobertos.
  A extensão não resolve CAPTCHA.
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

As dicas de transcrição reconhecem e-mail e telefone também em campos de texto
com rótulos ou nomes como `Email Address`, `email` e `phone`. Respostas de e-mail
com pausas e ponto final, como `ana, arroba, example, ponto com.`, são normalizadas
antes da conferência. Um endereço transcrito sem `@` ou `arroba` continua pedindo
confirmação em vez de escolher onde inserir o separador.

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
áudio e modelo de linguagem simulados. Eles verificam conexão sem código, gravação,
preenchimento da aba real, correção, confirmação perdida sem repetição e preservação da
interface web. Um teste específico usa o gerenciador de permissões do Chromium sem a flag
de aceitação automática, cobrindo autorização, nova tentativa e liberação do dispositivo.
Não substituem a avaliação do microfone físico nem da precisão do Whisper/LLM com dados reais.
