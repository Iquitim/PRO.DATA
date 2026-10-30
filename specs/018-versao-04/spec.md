# Spec 018 — Versão 0.4: abertura com sinal de vida, xlsb, Select completo e correções

Status: Implementada · Criada: 2026-10-30 · Versão: 0.4.0

## Contexto (o que foi verificado no código)

| # | Pedido | Situação encontrada |
|---|--------|---------------------|
| 1 | Sinal de vida ao abrir | O programa importa as bibliotecas pesadas (Polars, DuckDB, scikit-learn) e sobe o servidor **antes** de mostrar qualquer janela: alguns segundos sem nenhum retorno. |
| 2 | Abrir `.xlsb` | A biblioteca de leitura já entende xlsb; a extensão só não estava liberada. |
| 3 | Reordenar colunas no Select | O Select mantém sempre a ordem de entrada. |
| 4 | Conversão de tipos no Select | **Defeito.** Texto → Data e Texto → Booleano **dão erro**; Texto → Inteiro transforma " 12 " e "12.0" em vazio; Texto → Decimal transforma "1.234,56" e "12,5" em vazio **sem aviso** (perda silenciosa de dados). |
| 5 | Formula: escolher coluna existente | **Defeito.** Ao trocar "Resultado em", o formulário não se redesenha: o campo "Coluna a alterar" nunca aparece. Causa geral: campos que controlam outros **dentro de listas** não redesenhavam o formulário. |
| 6 | Média entre colunas | Não existe função que receba várias colunas (só Greatest/Least). |
| 7 | Coluna calculada some depois do Join | **Defeito.** Quando a chave vem da entrada da direita (R), o Join descarta a coluna da chave da direita no J — inclusive uma coluna calculada usada como chave. |
| 8 | Indicativo de espaços em branco | O perfil conta células vazias, mas não mostra na tabela, nem conta valores com espaço no início ou no fim. |
| 9 | Indicativo de execução | Só a barra de status muda; não dá para ver o que está rodando. |

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1801 | Ao clicar no programa (instalado ou zip), uma tela de abertura com o escudo, o nome e a versão aparece imediatamente — antes de carregar as bibliotecas —, mostra o passo atual ("Carregando o motor de dados…", "Iniciando o servidor local…", "Abrindo a janela…") e fecha quando a janela principal aparece. Em caso de falha, fecha antes da mensagem de erro. |
| RF-1802 | `.xlsb` aceito em enviar, vincular, prévia (escolha de planilha) e Input Data. |
| RF-1803 | Select: arrastar as linhas para mudar a ordem das colunas na saída; botão para voltar à ordem original. Colunas novas que chegarem depois ficam no fim. |
| RF-1804 | Conversões do Select: texto para número aceita espaços, padrão brasileiro (1.234,56 e 12,5), "R$" e inteiros escritos como "12.0"; texto para booleano aceita sim/não, s/n, true/false, 1/0, verdadeiro/falso; texto para data aceita 2026-10-29, 29/10/2026, 2026-10 e data e hora; número para data entende o número de série do Excel. Valores que não convertem viram vazio **e são avisados** (quantos e exemplos) no Configurar e no Log. |
| RF-1805 | Campos que mostram/escondem outros dentro de listas (ex.: "Resultado em" da Formula) redesenham o formulário na hora. |
| RF-1806 | Funções de várias colunas na Formula: `Average`, `Sum`, `Median`, `Max` e `Min` com 2 ou mais valores (nulos ignorados). |
| RF-1807 | Join: o J mantém as colunas das chaves dos dois lados; a da direita com o prefixo de colunas repetidas quando o nome coincidir. |
| RF-1808 | Na tabela de resultados e na prévia de arquivos, colunas de texto com células vazias (ou só espaços) ou com espaços no início/fim mostram um aviso no cabeçalho, com as contagens; o Perfil mostra as mesmas contagens. |
| RF-1809 | Durante a execução, a caixa que está rodando brilha; as que já terminaram ficam normais e as que ainda vão rodar ficam esmaecidas; a barra de status mostra "Executando… 3/8". A interface consulta `GET /api/execute/{id}/progress` a cada 250 ms. Sem animação para quem pede menos movimento no sistema. |

## Critérios de aceite

- Select converte " 12 ", "12.0", "1.234,56", "sim", "29/10/2026" e 45229 (data do Excel) e avisa "abc" (teste).
- Formula: trocar para "coluna existente" mostra a lista de colunas (teste no navegador).
- `Average([a], [b], [c])` com um nulo devolve a média dos outros dois (teste).
- Join com a coluna calculada como chave em R: a coluna aparece no J (teste).
- `.xlsb` de exemplo é lido com a escolha de planilha (teste).
- Espaços: célula só com espaços aparece como "vazio (espaços)", espaço sobrando aparece como ␣, e o
  cabeçalho e o Perfil mostram as contagens (teste no navegador).
- Durante a execução, a caixa da vez tem a animação de brilho (teste no navegador).

## Implementação

| Item | Onde |
|------|------|
| Tela de abertura | `packaging/make_icon.py` (gera `splash.png`), `packaging/prodata.spec` (`Splash`), `desktop.py` (`splash_text`, `close_splash`) |
| xlsb | `ingestion/detect.py`, filtro do diálogo em `desktop.py`; amostra em `tests/data/amostra.xlsb` |
| Select | `nodes/prep.py` (`order`, avisos), `engine/convert.py` (conversões tolerantes), `web/js/fields.js` (arrastar, setas, "Ordem original") |
| Formulário | `web/js/inspector.js` (redesenho para campos controladores dentro de listas) |
| Funções de várias colunas | `engine/formula.py` (`_variadic`) |
| Join | `nodes/transform.py` (`coalesce=False` e prefixo nas colunas repetidas) |
| Espaços | `engine/profiling.py` (`padded_count`), `web/js/datasets.js` (`cell`, `spacesBadge`), `web/js/results.js` |
| Execução | `engine/runner.py` (`progress`), `api/routes/execution.py`, `web/js/canvas.js` (`showProgress`), `web/js/main.js` |

Testes: `tests/test_v04.py` e a bateria de navegador da versão.
