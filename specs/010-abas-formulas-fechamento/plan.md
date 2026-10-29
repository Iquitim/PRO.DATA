# Plano 010

## Backend

- `formula.FUNCTION_DOCS`: lista de `FunctionDoc(name, signature, category,
  description, example)` cobrindo as macros Alteryx e as funções do DuckDB mais
  usadas (Round, Abs, Coalesce, Trim, Replace, Substring, Year, Date_Diff…).
  `KEYWORDS` (IF/THEN/ELSEIF/ELSE/ENDIF) e `LOGICAL` (AND/OR/NOT/IN/TRUE/FALSE/NULL).
- `/api/catalog`: `formula_functions` passa a ser a lista de docs, e ganha
  `formula_keywords`. Teste: todo `example` passa em `formula.validate`.
- `desktop.py`: filtros de arquivo só com letras e espaços (regex do pywebview);
  `DesktopApi.set_dirty(bool)` e `close_app()`; handler `closing` cancela o
  fechamento quando há alterações e pede à página o diálogo
  (`window.prodataConfirmClose()`), numa thread para não travar a interface.

## Frontend

- `store.js`: `snapshotState()` / `restoreState()` incluem o histórico privado
  de desfazer; `liveWidgets()` filtra visuais por nó existente e ativo.
- `tabs.js`: lista de abas `{ key, state, view, title }`; a aba ativa vive no
  `store`, as outras ficam congeladas. `openTab(workflow, opts)`, `switchTab`,
  `closeTab` (com `askSave`), persistência em `localStorage`
  (`prodata.tabs`: só fluxos com origem — id da biblioteca ou caminho).
- `canvas.js`: `getView()`/`setView()`; `workflow:loaded` aceita `{ view }` para
  restaurar a posição em vez de "ajustar à tela".
- `formula_editor.js`: textarea transparente sobre um `<pre>` colorido (mesma
  fonte, padding e quebra), rolagem sincronizada; tokenizador próprio;
  popup de sugestões posicionado no cursor (espelho de medição); dica de
  assinatura; barra do assistente (Coluna ▾, ƒx Função ▾, operadores).
- `fields.js`: o widget `expression` usa o editor novo.
- `main.js`: `askSave()` com três opções; `beforeunload` e
  `window.prodataConfirmClose`; o estado sujo de todas as abas é enviado ao
  desktop (`set_dirty`).
- CSS: `font-variant-ligatures: none` em todo código; barra de abas numa nova
  linha do grid da página.
