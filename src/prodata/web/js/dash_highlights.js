// Destaques da linha do tempo (spec 030, RF-3047): cada um diz o critério que o marcou.
// Sem inteligência escondida: são médias, desvios e inclinações que qualquer pessoa consegue refazer.

const WINDOW = 8;
const MIN_HISTORY = 4;
const TREND_SPAN = 4;
const LIMIT_Z = 2;
const LIMIT_ROBUST = 3.5;
const MAX_MARKS = 8;

const num = (v, places = 1) => v.toLocaleString('pt-BR', { minimumFractionDigits: places, maximumFractionDigits: places });
const mean = (list) => list.reduce((a, b) => a + b, 0) / list.length;
const deviation = (list) => {
  const m = mean(list);
  return Math.sqrt(list.reduce((acc, v) => acc + (v - m) ** 2, 0) / list.length);
};
const median = (list) => {
  const s = [...list].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};

function peaks(values) {
  const out = [];
  values.forEach((v, i) => {
    if (i < MIN_HISTORY) return;
    const past = values.slice(Math.max(0, i - WINDOW), i);
    const sd = deviation(past);
    if (sd <= 0) return;
    const z = (v - mean(past)) / sd;
    if (Math.abs(z) < LIMIT_Z) return;
    out.push({
      index: i, kind: z > 0 ? 'pico' : 'queda', strength: Math.abs(z),
      text: `${num(Math.abs(z))} desvios ${z > 0 ? 'acima' : 'abaixo'} da média ${past.length === WINDOW ? `das últimas ${WINDOW}` : `das ${past.length} anteriores`} marcações`,
    });
  });
  return out;
}

function slope(list) {
  const mx = (list.length - 1) / 2;
  const my = mean(list);
  let top = 0;
  let bottom = 0;
  list.forEach((v, i) => { top += (i - mx) * (v - my); bottom += (i - mx) ** 2; });
  return top / bottom;
}

function turns(values) {
  const base = Math.abs(mean(values)) || 1;
  const out = [];
  for (let i = TREND_SPAN; i < values.length - TREND_SPAN; i += 1) {
    const before = slope(values.slice(i - TREND_SPAN, i + 1));
    const after = slope(values.slice(i, i + TREND_SPAN + 1));
    if (before * after >= 0 || Math.min(Math.abs(before), Math.abs(after)) < base * 0.05) continue;
    out.push({
      index: i, kind: 'tendência', strength: Math.abs(before - after) / base,
      text: `Vinha ${before > 0 ? 'subindo' : 'caindo'} nas ${TREND_SPAN} marcações anteriores e passou a ${after > 0 ? 'subir' : 'cair'} nas ${TREND_SPAN} seguintes`,
    });
  }
  // Marcações vizinhas contam a mesma virada: fica só a mais forte.
  return out.sort((a, b) => b.strength - a.strength).filter((m, i, all) => !all.slice(0, i).some((k) => Math.abs(k.index - m.index) < TREND_SPAN));
}

function outliers(values) {
  if (values.length < MIN_HISTORY * 2) return [];
  const center = median(values);
  const spread = median(values.map((v) => Math.abs(v - center))) * 1.4826;
  if (spread <= 0) return [];
  return values.flatMap((v, index) => {
    const score = Math.abs(v - center) / spread;
    if (score < LIMIT_ROBUST) return [];
    return [{ index, kind: 'fora do padrão', strength: score / 2, text: `${num(score)} vezes o desvio típico ${v > center ? 'acima' : 'abaixo'} da mediana de todo o período` }];
  });
}

/** Marcas por posição, as mais fortes primeiro cortadas em MAX_MARKS. Uma por momento: a de maior força. */
export function findHighlights(values) {
  const clean = values.map((v) => (Number.isFinite(v) ? v : 0));
  const byIndex = new Map();
  for (const mark of [...peaks(clean), ...turns(clean), ...outliers(clean)]) {
    const current = byIndex.get(mark.index);
    if (!current || mark.strength > current.strength) byIndex.set(mark.index, mark);
  }
  return [...byIndex.values()].sort((a, b) => b.strength - a.strength).slice(0, MAX_MARKS).sort((a, b) => a.index - b.index);
}
