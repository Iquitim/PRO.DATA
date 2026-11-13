// Números e barras de qualidade das colunas: o mesmo desenho para arquivo e pasta de arquivos na vista Dados.

import { fmt, h } from './dom.js';

export function stat(label, value, hint = '') {
  return h('div', { class: 'dv-stat' }, h('span', {}, label), h('strong', {}, value), hint ? h('small', {}, hint) : null);
}

/** Barras de qualidade por coluna, na amostra lida: verde preenchido, âmbar texto vazio, vermelho sem valor. */
export function columnQuality(preview) {
  const total = preview.rows.length || 1;
  return h('section', { class: 'dv-card stack-sm' },
    h('h3', {}, 'Qualidade das colunas'),
    h('p', { class: 'field-help' }, `Nas primeiras ${fmt.int(preview.rows.length)} linhas · verde: preenchido · âmbar: texto vazio · vermelho: sem valor`),
    preview.columns.slice(0, 14).map((c) => {
      const values = preview.rows.map((r) => r[c.name]);
      const nul = values.filter((v) => v === null || v === undefined).length;
      const empty = values.filter((v) => typeof v === 'string' && !v.trim()).length;
      const pct = (n) => `${(n / total) * 100}%`;
      return h('div', { class: 'dv-quality' },
        h('span', { class: 'mono ellipsis', title: c.name }, c.name),
        h('span', { class: 'dv-quality-bar', title: `${nul} sem valor · ${empty} texto vazio` },
          h('span', { class: 'q-ok', style: { width: pct(total - nul - empty) } }),
          h('span', { class: 'q-empty', style: { width: pct(empty) } }),
          h('span', { class: 'q-null', style: { width: pct(nul) } })),
        h('span', { class: 'muted' }, `${Math.round(((total - nul - empty) / total) * 100)}%`));
    }));
}
