# VozForm para Chrome

Fontes do manifesto e dos scripts em `public/`. O painel está em
`../frontend/src/extension/` e reutiliza o gravador da aplicação web.

Compile com `npm run build:extension` em `frontend/` e carregue **`extension/dist`**
em `chrome://extensions` → Modo do desenvolvedor → Carregar sem compactação.

Consulte [instalação, uso e limites](../docs/chrome-extension.md). A aplicação web
continua disponível e usa o mesmo servidor Python.
