# Spec 015 — Ajustes da 0.3.5: dashboard, Venn, explicações visuais, Excel e fórmulas

Status: Implementada · Criada: 2026-10-30 · Versão alvo: 0.3.5

## Contexto

Pedidos de uso da 0.3.0:

1. No dashboard, o subtítulo dos cartões e os textos das legendas não são editáveis.
2. No Venn, os grupos são digitados à mão; um erro de maiúscula ou acento faz o grupo não existir.
3. Cross Tab, Transpose e Join são conceitos difíceis para quem não trabalha com dados: o
   formulário não mostra o que acontece com a tabela.
4. O Output Data vem com Parquet, formato pouco usado fora de TI.
5. O arranjo dos painéis (e o tema, os tamanhos e as abas abertas) não é lembrado no
   programa instalado. Causa: o servidor interno sobe numa porta sorteada a cada abertura,
   e o navegador embutido guarda as preferências por endereço (porta incluída).
6. O Excel exportado tem sempre uma planilha só; não dá para juntar vários resultados num
   arquivo.
7. A Formula só cria colunas novas (alterar uma existente exige saber que basta repetir o nome).
8. Faltam funções comuns no Alteryx e no KNIME (datas, texto, números no padrão brasileiro).

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1501 | Painel Formato: campo **Subtítulo** (vazio = o automático) em gráficos, tabelas e Venn. |
| RF-1502 | Painel Formato: **textos da legenda e das categorias** — cada série, categoria ou conjunto pode ganhar outro nome no visual (legenda, eixo, tooltip e modo tabela). Legenda mostrada ou oculta e posição (acima ou abaixo) em todos os gráficos com legenda. |
| RF-1503 | Venn em "chave + grupo": ao escolher a coluna do grupo, os valores dela aparecem para marcar (com a contagem de linhas), no máximo 3. Busca quando há muitos valores. Valores já salvos que não existem mais aparecem marcados como "não encontrado". |
| RF-1504 | Cross Tab, Transpose e Join mostram no Configurar um **esquema visual** do que a ferramenta faz, montado com as colunas configuradas e, quando o fluxo já rodou, com uma amostra dos dados de entrada. Passar o mouse num valor destaca para onde ele vai. No Join, o esquema mostra quantas linhas saem em L, J e R e clicar numa saída mostra os dados dela. |
| RF-1505 | Output Data novo vem com **Excel** como formato. Caixas existentes não mudam. |
| RF-1506 | O programa instalado usa sempre o mesmo endereço local (porta fixa, com alternativa se estiver ocupada), e assim lembra painéis, tamanhos, tema, abas e zoom entre aberturas. |
| RF-1507 | Output Data em Excel: **nome da planilha** (padrão "Dados") e **se o arquivo já existir**: substituir o arquivo ou **adicionar/atualizar esta planilha**, mantendo as outras. Vários Output Data podem gravar planilhas diferentes no mesmo arquivo. Nome de planilha inválido para o Excel é recusado com mensagem clara. |
| RF-1508 | Formula: cada fórmula escolhe **criar coluna nova** ou **alterar coluna existente** (lista das colunas de entrada). Alterar mantém a posição da coluna. |
| RF-1509 | Novas funções de fórmula (todas com exemplo validado por teste e documentadas no assistente): texto (TrimLeft, TrimRight, PadLeft, PadRight, FindString, GetWord, SplitPart, CountWords, Reverse, RemoveAccents, DigitsOnly, RegexMatch, RegexReplace, RegexExtract), números (Mod, Ln, Log10, Exp, Sign, Trunc, Divide, Between, FormatNumber), conversão (ToInteger, IsNumber, ToNumberBR, DateParse), datas (Now, DateAdd, DateTrunc, StartOfMonth, EndOfMonth, Quarter, Week, Weekday, WeekdayName, MonthName, IsWeekend, DateFormat, Hour, Minute) e condicional (NullIf). |

## Fora do escopo

- Gravar no Excel com formatação (cores, larguras personalizadas, fórmulas do Excel).
- Funções de janela (linha anterior/seguinte) na Formula: ficam para uma ferramenta Multi-Row.

## Critérios de aceite

- Mudar o subtítulo e o nome de uma série no painel: o gráfico, a legenda e o modo tabela mostram os novos textos; o fluxo não roda de novo.
- Venn: escolher "produto" como grupo lista Cloud, AutoML, BI Pro… com contagem; marcar um 4º não é possível.
- Cross Tab com UF × mês: o esquema mostra a amostra "longa" virando "larga" com as colunas jan, fev…; passar o mouse num valor destaca a célula de destino.
- Dois Output Data com o mesmo arquivo e planilhas "Clientes" e "Vendas" (modo adicionar): o xlsx final tem as duas planilhas (teste).
- Fechar e abrir o programa instalado: painéis no lugar em que foram deixados.
- Formula alterando [nome] com Uppercase([nome]): a coluna continua na mesma posição.
- Cada função nova tem exemplo que roda contra o esquema de teste.
