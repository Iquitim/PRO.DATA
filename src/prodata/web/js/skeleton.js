// Esqueletos de carregamento (spec 029, RF-2991): o desenho do que vem, no lugar de espaço vazio.

import { h } from './dom.js';

const COLUMNS = [90, 170, 44, 96, 96, 70];
const block = (style) => h('div', { class: 'sk', style });

function line(widths, padding) {
  return h('div', { class: 'sk-line', style: { padding: `${padding}px 14px` } }, widths.map((w) => block({ width: `${w}px`, height: '12px' })));
}

/** Tabela carregando: cabeçalho e linhas com larguras um pouco diferentes, como dados de verdade. */
export function tableSkeleton(rows = 14) {
  return h('div', { class: 'sk-table', role: 'status', 'aria-label': 'Carregando a tabela' },
    line(COLUMNS, 16),
    Array.from({ length: rows }, (_, i) => line(COLUMNS.map((w, j) => w - ((i * 7 + j * 13) % 24)), 8)));
}

/** Cartão de gráfico carregando, com o título e barras. */
export function chartSkeleton() {
  return h('div', { class: 'sk-chart', role: 'status', 'aria-label': 'Carregando o gráfico' },
    block({ width: '45%', height: '14px', marginBottom: '6px' }),
    block({ width: '65%', height: '11px', marginBottom: '16px' }),
    Array.from({ length: 5 }, (_, i) => h('div', { class: 'sk-bar' }, block({ width: '50px', height: '11px' }), block({ width: `${88 - i * 13}%`, height: '16px' }))));
}
