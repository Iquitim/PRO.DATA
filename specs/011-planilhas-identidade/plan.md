# Plano 011

- `ReadOptions.skip_columns`; `read_table` recorta colunas depois do leitor; `resolve_options`
  detecta delimitador no texto após `skip_rows`.
- Excel: o fastexcel usa posições absolutas para `header_row`/`skip_rows` (verificado com
  planilhas cuja tabela começa em B4), então "pular linhas" equivale às linhas do Excel.
  Colunas totalmente vazias à esquerda já são descartadas pelo leitor; `skip_columns` conta
  a partir da tabela lida.
- Prévia: guias de abas (`.sheet-tabs`); abertura automática após upload de Excel.
- Marca: `web/brand/` (SVG oficial + variante clara), `css/brand.css` carregado por último
  (tokens, barra superior, Dashboard), Open Sans embutida (OFL), `packaging/brand/` com o
  escudo em PNG para gerar o `.ico`.
