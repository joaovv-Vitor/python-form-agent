# Arquitetura da POC — diagrama editável

- [Arquivo Draw.io](arquitetura_poc.drawio)
- [SVG exportado pelo diagrams.net](arquitetura_poc.svg)
- Referência visual: [arquitetura_correcao.png](arquitetura_correcao.png).
- Referência inicial de organização: `diagram.png`, imagem enviada pelo usuário.

O visual tem identidade própria: azul profundo no pipeline, azul-petróleo nas
ferramentas MCP, vinho no LLM e na revisão, ocre no áudio e na confirmação humana
e tons de ardósia nas entradas e no navegador. Os ícones usam traços coloridos
sobre círculos claros. Os marcadores numéricos são quadrados com cantos suaves.

Os 19 ícones (13 componentes e seis cabeçalhos) foram substituídos por pictogramas
vetoriais próprios: teclado, arquivo musical, transcrição, controles deslizantes,
formulário com cursor, rede neural, lupa de revisão, setas RPC, confirmação,
hierarquia de ferramentas, cursor de automação e formulário. Os arquivos não
dependem de imagens externas. Os fluxos principais mantêm numeração e legenda.

O desenho preserva o recorte da aplicação Python/CLI da referência. A aplicação web
e a extensão Chrome também existem no repositório, mas não integram esse recorte.
Não foram acrescentadas ao desenho.

Os containers delimitam a aplicação Python, o pipeline inicial, os recursos de LLM
e revisão, as ferramentas e a confirmação, o subprocesso MCP e o navegador.
São agrupamentos visuais; os grupos de responsabilidade não representam novos
serviços ou processos.

## Componentes e relacionamentos preservados

| Origem | Relação | Destino |
|---|---|---|
| Instrução em texto | Entrada | FormAgent |
| Arquivo de áudio inicial | Entrada | AudioAgent |
| AudioAgent | Transcrição | Tratamento dos dados |
| Tratamento dos dados | Instrução tratada ou bruta | FormAgent |
| FormAgent | Ida e volta | OpenAICompatibleModel |
| ReviewSession | Ida e volta | OpenAICompatibleModel |
| FormAgent | Tools e resultados | BrowserToolsClient |
| ReviewSession | inspect_form / fill_field e resultados | BrowserToolsClient |
| Confirmação humana | Autoriza envio | BrowserToolsClient |
| BrowserToolsClient | JSON-RPC por stdio, ida e volta | Servidor MCP |
| Servidor MCP | Ida e volta | BrowserController |
| BrowserController | Ida e volta | Navegador e formulário |
| Usuário | Correções e interação | ReviewSession |
| ReviewSession | Novo áudio e transcrição, ida e volta | AudioAgent |

AudioAgent mantém a validação e o faster-whisper no mesmo componente, como na
referência. Raw, regras locais e DeepSeek continuam sendo alternativas da etapa
de tratamento. RunTrace e ClarificationSession permanecem em anotações, sem
introduzir conexões ou componentes adicionais.

A leitura do código confirmou o compartilhamento de modelo, cliente MCP e
AudioAgent, a reutilização da sessão de navegador e a autorização de envio pelo
host. Fontes: `src/form_agent/bootstrap.py`, `src/voice_form/pipeline.py`,
`src/voice_form/review.py`, `src/voice_form/cli.py`,
`src/form_agent/adapters/mcp_client.py` e `src/form_agent/mcp/server.py`.

## Validação realizada em 2026-11-04

- MCP oficial `@drawio/mcp` 1.10.1: `list_pages`, `open_drawio_xml` e `get_page`.
- Abertura do arquivo local `arquitetura_poc.drawio` pelo menu
  **Ficheiro → Abrir de → Aparelho** do diagrams.net no Safari.
- A versão com figuras foi aberta pelo MCP no diagrams.net; o editor exibiu
  130 formas (incluindo ícones, textos e legenda) e 14 conectores.
- Exportação SVG nativa, aparência clara, margem de 24 px e diagrama incorporado.
- Inspeção visual do SVG final no Safari; dimensões de 2560 × 1462.
- XML e referências internas válidos; os 14 relacionamentos são iguais no
  `.drawio` e na cópia incorporada ao SVG.
- Conferência dos caminhos exportados: 23 segmentos ortogonais e zero cruzamentos
  entre os interiores dos segmentos de conectores distintos.
- Conferência dos 19 ícones: todos têm caminhos vetoriais renderizados no SVG.
- A substituição dos 19 ícones e da paleta foi conferida contra a versão anterior;
  os 13 componentes e 14 relações foram preservados.
- A versão com identidade própria foi aberta no diagrams.net pelo MCP, exportada
  novamente como SVG e inspecionada no Safari.

Para editar, abra o `.drawio` no [diagrams.net](https://app.diagrams.net/).
O SVG também contém uma cópia editável do diagrama.
