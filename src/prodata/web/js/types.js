// Tipos de coluna em português (spec 029, RF-2921 e RF-2962): o mesmo rótulo curto em toda a interface,
// com o nome por extenso na dica. O motor fala Int64, Float64, String, Boolean e Date.

const LABELS = {
  Int64: ['123', 'número inteiro'],
  Float64: ['1,2', 'número decimal'],
  String: ['abc', 'texto'],
  Boolean: ['v/f', 'verdadeiro ou falso'],
  Date: ['data', 'data'],
};

/** Rótulo curto: 123, 1,2, abc, v/f ou data. Tipo desconhecido aparece como veio. */
export const typeLabel = (type) => LABELS[type]?.[0] || type || '';

/** Nome por extenso, para dicas: "número inteiro", "texto". */
export const typeName = (type) => LABELS[type]?.[1] || type || '';
