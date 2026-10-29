# Plano 013

- `fields.js` (`selectColumns`): `setAll(keep | fn)` grava só o que difere do padrão.
- `nodes/reshape.py`: seis ferramentas declarativas (Polars: `pivot`, `unpivot`,
  `str.split` + `list.get`/`explode`, `with_row_index`, `cum_sum().over`, `join(how="cross")`).
- Remoção: `nodes/genai.py`, categoria e cores `genai`, nó da demonstração (o Predictor
  liga direto no Output), dados `tickets_suporte_ia.csv`; `build_services` regrava a
  demonstração se ela usar ferramentas que não existem mais.
- `canvas.js`: `edgeSamples()` (Bézier cúbica analítica) para `edgeThroughRect`/`edgeNear`;
  `onPointerMove` guarda o evento e `flushMove` roda no `requestAnimationFrame`
  (e antes do `pointerup`); `persist('prodata.view')` com `debounce`.
- Medição com Playwright + Chrome instalado (CPU normal e 4x mais lenta via CDP).
