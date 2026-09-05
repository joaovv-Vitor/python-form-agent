# Auditoria inicial e plano de evolução

Base lida antes de qualquer alteração: `abe8f52a3cfa7c2cc56084328be5b5f155f002d9`.
Árvore Git limpa. Foram lidos os 29 módulos em `src`, os 11 arquivos de testes,
README, pyproject, perfis, exemplo de ambiente (sem ler segredos), os dois CSVs e o HTML.
Não há AGENTS.md aplicável nem prompt externo. Há 2.659 linhas em código e testes.

## Arquitetura encontrada (A)

```text
form-agent-py → bootstrap.Application → FormAgent
                                     ├─ LanguageModel → OpenAICompatibleModel
                                     └─ ToolClient → BrowserToolsClient
                                          → subprocesso JSON-RPC/MCP
                                          → mcp.server → BrowserController → Playwright
form-evaluate-py → mesmo bootstrap → métricas microagregadas → CSV/HTML
audio-agent-py → AudioAgent → AudioPreprocessor → SpeechToTextEngine
                                                → FasterWhisperSpeechToTextEngine
                                                → TranscriptionResult
```

O pré-processamento valida caminho, extensão e tamanho; não converte nem limpa áudio.
O modelo recebe inventário + instrução e conserva histórico apenas dentro de uma execução.
O browser reinspeciona a cada resolução: controles criados após interação já podem ser
descobertos, mas o inventário inicial enviado ao LLM pode ficar desatualizado.

## Pontos fortes (B)

- Protocols de LLM, sessão, tools e STT pequenos; núcleo independente dos SDKs.
- Bootstrap comum, perfis configuráveis, exceções de provider normalizadas.
- Limite de turnos, bloqueio de tool desconhecida e de clique sem intenção textual.
- Resolução semântica normaliza caixa/acentos e rejeita empates.
- Playwright encapsulado; STT com lazy loading e cache por configuração do modelo.
- Resultados STT ricos, CSV validado, métricas e relatórios separados do executor.
- Testes rápidos independentes dos serviços; Whisper real opt-in.

## Problemas técnicos (C/E)

| Prioridade | Evidência na base | Consequência / decisão |
|---|---|---|
| P0 para A/C | Não há composição nem runners de áudio | Impede experimento integrado; criar serviço por composição, sem reconstruir agentes |
| P1 | `submission_requested` aceita `Talvez eu queira enviar amanhã`, menção à palavra `envie` e `Não desejo de forma alguma que você envie` | Texto não deve conceder autoridade; estado explícito e negação como veto conservador |
| P1 | `_record_output` chama qualquer `click_button` bem-sucedido de envio | Clique, tentativa e confirmação são diferentes; exigir evidência observável configurada |
| P1 | `read` não é invalidado após nova escrita e falha na releitura conserva valor escrito | Relato pode declarar valor incorreto; releitura final obrigatória e falha explícita |
| P1 | `evaluate` reutiliza uma Application/browser em todos os casos | Contaminação entre tentativas; contexto novo por tentativa |
| P1 | `server._handle` transforma exceções do browser em mensagem genérica | Perde origem; transportar código estruturado sem expor traceback |
| P1 | Lista de tools do servidor define o conjunto inteiro autorizado | Servidor anunciando tool extra amplia poderes; interseção com lista fixa do núcleo |
| P2 | Inspeção inclui hidden, submit como campo; não lê aria-labelledby; resolução não usa placeholder | Inventário e localização divergem; corrigir controles nativos prioritários |
| P2 | Grupos radio compartilham name; saída usa somente label | Empates/colisões; preservar referência e rejeitar resolução não única |
| P2 | MCP stderr em PIPE nunca drenado; versão JSON-RPC não é verificada; argumentos convertidos com str | Risco de bloqueio, incompatibilidade e coerção; endurecer transporte existente |
| P2 | Timeout não invalida conexão com operação ainda em execução | Resultado tardio/efeito incerto; encerrar conexão, sem retry automático de mutação |
| P2 | Prompt inline e parâmetros implícitos | Experimento não identifica sua configuração exata |
| P3 | Iframes, widgets customizados, validação JS arbitrária | Exigem contratos por formulário; documentar, não generalizar agora |

## Dívidas acadêmicas (D)

- Apenas quatro casos textuais em um formulário simplificado; nenhum áudio versionado.
- Resultado avaliado é a lista de preenchimentos relatados, não todo o estado observado.
- Não é possível atribuir falha ao STT só porque a transcrição difere da referência.
- Falta pareamento A (STT), B (texto de referência), C (áudio até formulário).
- Sem manifesto de código, parâmetros, prompt e hashes dos artefatos; dependências em faixas.
- Temperatura zero não garante identidade de saída entre execuções/provedores/hardware.
- Nomes `AudioAgent` e “multiagente” precisam de fundamentação; nomes de classes não provam agência.

## Baseline de qualidade

Python 3.14.7; pytest: 24 passed, 1 skipped (Whisper), 1 failed (Chromium impedido pelo
sandbox). Executado o mesmo teste MCP/Chromium fora do sandbox, com FORM_URL local e
HEADLESS=true: 1 passed. A falha inicial é de ambiente, não evidência de regressão.
Ruff check e format --check passaram (40 arquivos); mypy passou nos 29 módulos.

Os testes de contratos existentes são úteis, porém o único roundtrip real testa apenas
um campo. Fakes aceitam todo clique e devolvem sempre João; escondem validade, efeitos
colaterais e releitura obsoleta. Testes de `_best` verificam algoritmo isolado, não a
resolução DOM. Ampliar integração local em vez de substituir todos os mocks.

## Plano incremental

| Etapa / commit conceitual | Objetivo e justificativa | Arquivos / mudanças | Validação | Risco / impacto arquitetural e no TCC | Conclusão |
|---|---|---|---|---|---|
| 1 `fix: enforce explicit submission and verify observed form state` | Corrigir medição antes de ampliar experimento | core schemas/agent/errors, browser, MCP, runner; autorização fora das tools, observação de valores, isolamento | negação longa, tool inventada, releitura obsoleta, validação, MCP real; Ruff/mypy | Médio: envio passa a exigir autorização separada. Mesmas camadas; elimina falso sucesso | Sem clique não autorizado, sem sucesso por clique apenas, tentativas isoladas |
| 2 `feat: compose audio and form workflows` | Viabilizar objetivo principal com menor acoplamento | novo `voice_form`, CLI e entry point; compor AudioAgent e FormAgent | fake STT + FormAgent real, vazio/erro STT; Ruff/mypy | Baixo: APIs existentes preservadas; nova composição | Áudio aceito pela CLI e transcrição encaminhada sem reinterpretação automática |
| 3 `feat: record experiment provenance` | Reconstruir e comparar execuções | eventos JSONL, manifesto, prompt empacotado/versionado, config LLM | eventos ordenados, ausência de chave, hash/config; Ruff/mypy | Baixo: callback opcional, sem backend; sustenta reprodutibilidade | Run ID, tempos, parâmetros, hashes e falhas persistidos |
| 4 `feat: evaluate speech and end-to-end form success` | Separar qualidade textual de sucesso funcional | estender evaluation, CSV áudio, runners A/B/C e relatórios existentes | WER/CER, vazio, falha de estágio, efeitos colaterais, sucesso com WER>0; Ruff/mypy | Médio: definição explícita das métricas; reaproveita avaliação | Três modos, tentativas, métricas por estágio e evidências sem atribuição causal automática |
| 5 `test: document adversarial experiments and dataset protocol` | Tornar limites e hipóteses defensáveis | fixtures HTML, testes adversariais, dataset catalogado, README e docs | suíte completa, lint, formato, tipos e empacotamento | Baixo: sem novas infraestruturas; protocolo de coleta ainda depende de gravações humanas | Auditoria final, matriz de cenários, fontes, ameaças à validade e comandos verificáveis |

Alternativas à composição: subprocessar a CLI de áudio exige parse/serialização desnecessários;
injetar Whisper no FormAgent quebra independência; framework multiagente não acrescenta
controle experimental. Um serviço Python que encadeia os resultados basta.

Não criar `get_form_state`: enriquecer `inspect_form` com valores/validade evita duplicação.
Snapshots inicial/final têm ganho mensurável (alterações extras, pré-preenchimento), sem
criar um gerenciador de estado, grafo de dependências ou nova tool.
