# Catálogo proposto de áudio pt-BR

Este diretório contém um **roteiro de coleta**, não um corpus já gravado. Os 19 enunciados
são fictícios. Os arquivos de áudio referenciados ainda não existem; rodar avaliação A/C
agora registra STT_ERROR por arquivo ausente. Os nomes de cenários não comprovam que uma
amostra tenha ruído, fala rápida ou sotaque: essas condições precisam ser coletadas e anotadas.

```text
evaluation/audio/
├── cases.example.csv             # roteiros e oráculos a revisar no piloto
├── cases.csv                     # cópia local com referências realmente gravadas
├── failure-review.example.csv    # esquema de revisão humana por run_id
└── audios/
    ├── speaker_001/
    └── speaker_002/
```

Mantém-se o local já existente no projeto em vez de criar outro `dataset/` concorrente.
Caminhos de áudio e formulário são relativos ao CSV. `expected_json` usa labels únicos ou
id/name inequívocos, strings para controles de texto/select e booleanos para checkbox/radio.
Não usar valores nulos ou arrays como oráculo. O CSV rejeita IDs repetidos e estrutura inválida.
`submitted` é expectativa; `submission_authorized` é permissão do protocolo, ainda dependente
de `--allow-submission`. Referência vazia é permitida para silêncio em A, não para B.

## Proposta de coleta pequena

Piloto: dois falantes e seis enunciados, para revisar instruções, gravação e oráculos.
Rodada principal sugerida: quatro falantes × oito enunciados × duas condições (limpa/ruído
controlado) = 64 áudios, mais casos de correção se houver tempo. Não é requisito implementar
nem gravar essa quantidade agora. Distribua nomes fictícios, cidades, e-mails, telefones,
datas, negação e informação extra. Reserve falantes/enunciados para teste antes de ajustar
prompts; não escolha apenas os áudios que o sistema transcreve bem.

Use WAV mono e parâmetros de captura fixos, por exemplo PCM 16-bit/16 kHz, mantendo o
original se for necessário converter. Registre duração, dispositivo, ambiente, ruído,
condição, falante pseudonimizado, data da sessão e transformação aplicada em um catálogo
auxiliar restrito. Não exigir dados demográficos que não respondam a uma pergunta do TCC.
Se estudar sotaques, use autodescrição voluntária e critérios declarados, sem inferir identidade.

O `reference_text` deve representar o que foi **realmente falado**, inclusive pausas lexicais,
hesitações e autocorreções, não apenas copiar o roteiro. Uma segunda pessoa pode revisar
texto e oráculo, com adjudicação de divergências. O oráculo contém somente os dados finais
inequívocos. Não juntar fragmentos de telefone incompleto por adivinhação. Em contradição
sem correção explícita, deixe o campo indeterminado fora do esperado e documente essa regra.

O caso `phone` usa uma sequência inventada com DDD 00; não discar, validar como contato real
ou substituir por telefone de participante. E-mails usam example.com. Os nomes Pessoa Alfa
etc. e datas são dados de roteiro, sem relação com os falantes.

## Privacidade e compartilhamento

Pseudônimos de falante não tornam uma gravação de voz anônima. Mantenha áudios, autorização
para coleta/uso e qualquer vínculo de identidade em armazenamento restrito e separado.
Defina finalidade, retenção, acesso e descarte com a instituição e seu protocolo de pesquisa;
não publique voz por estar em uma pasta `speaker_001`. O guia da ANPD trata das hipóteses e
cuidados aplicáveis à pesquisa e aos fins acadêmicos; a finalidade acadêmica exige análise
própria do tratamento. [Guia oficial da ANPD](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-orientativo-tratamento-de-dados-pessoais-para-fins-academicos-e-para-a-realizacao-de-estudos-e-pesquisas).

Os áudios permanecem ignorados no Git; catálogos com dados fictícios e hashes podem ser
versionados. Para uma versão reproduzível do corpus, arquive um pacote privado autorizado,
identificado por versão e hashes, e registre o procedimento de acesso. Um hash sozinho
não substitui o arquivo. JSONL/CSV também contêm transcrição e valores de formulário e
seguem os mesmos controles de acesso. Não colocar credenciais ou dados reais nesses artefatos.

TTS pode criar amostras auxiliares para smoke tests com texto conhecido; rotule como sintético
e não misture com o conjunto humano ao discutir sotaques, hesitações ou ruído natural.
Nenhum áudio sintético foi apresentado como gravação humana nesta alteração.

## Revisão das falhas

Copie `failure-review.example.csv` e preencha somente com execuções observadas. `primary_cause`
sugerida: stt, semantic_mapping, field_identification, tool_call, automation, validation,
submission, provider, unresolved. São rótulos humanos de causa, distintos de `error_codes`.
Inclua o evento JSONL e o contraste B/C que sustentam a classificação. Use uma causa principal
ou unresolved; mantenha fatores secundários nas notas para não contar a mesma falha duas vezes.
Não calcular percentuais de “erros do STT” apenas contando casos com WER positivo.
