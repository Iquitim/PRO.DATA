// Imagem PNG da página ou de um visual, com a faixa do rótulo e dos filtros.

import { api } from './api.js';
import { renderPng, savePng, stamp } from './dash_export.js';
import { activeFiltersText } from './dash_filters.js';
import { PAGE_W, pageHeight } from './dash_model.js';
import { dash, nodeLabel, page } from './dash_state.js';
import { h } from './dom.js';
import { LABELS } from './label_picker.js';
import { store } from './store.js';
import { confirmDialog, toast, toastError } from './ui.js';

export async function exportPage() {
  const d = dash();
  if (!d) return;
  const widgets = page.shownWidgets();
  const missing = d.items.filter((i) => i.kind === 'visual' && !widgets[i.node_id]).length;
  if (!store.execution || missing) {
    const ok = await confirmDialog({
      title: 'Baixar imagem',
      message: store.execution
        ? `${missing} visual(is) sem dados (com erro, desativados ou não executados) vão ficar de fora da imagem.`
        : 'O fluxo ainda não foi executado: a imagem vai sair sem os visuais. Execute antes com "Atualizar dados".',
      confirm: 'Baixar assim mesmo',
    });
    if (!ok) return;
  }
  const strip = 40;
  const content = withStrip(page.pageEl({ exporting: true }), PAGE_W, pageHeight(d.page));
  const data = await renderPng(content, PAGE_W, pageHeight(d.page) + strip, { background: d.page.background || 'var(--bg)' });
  const saved = await savePng(`${store.workflow.name || 'Dashboard'} - ${stamp()}`, data);
  if (saved) { logImage(saved); toast(`Imagem salva: ${saved}`, { kind: 'success' }); }
}

/** Faixa da imagem: o rótulo, sempre, e os filtros ativos. */
function exportStrip(note) {
  const level = dash().confidentiality || 'interno';
  const recorte = activeFiltersText(dash().filters);
  return h('p', { class: ['dash-export-filters', 'label-bar', `label-${level}`] },
    `Classificação: ${LABELS[level]}${note ? ` · ${note}` : ''}${recorte ? ` · Filtros: ${recorte}` : ''}`);
}

/** A página é posicionada de forma absoluta: fica numa caixa própria, abaixo da faixa, para não cobri-la. */
export function withStrip(content, width, height, note = page.stripNote?.()) {
  return h('div', { style: { width: `${width}px` } }, exportStrip(note),
    h('div', { style: { position: 'relative', width: `${width}px`, height: `${height}px` } }, content));
}

function logImage(file) {
  const level = dash().confidentiality || 'interno';
  api.dashboardExportLog({ kind: 'PNG', file: String(file).split(/[\\/]/).pop(), label: level })
    .catch((err) => toastError(err, 'A imagem foi salva, mas não entrou no registro de exportações'));
}

export async function exportVisual(item) {
  const w = page.shownWidgets()[item.node_id];
  if (!w) { toast('Execute o fluxo antes de baixar este visual.'); return; }
  try {
    const strip = 40;
    const wrap = withStrip(h('div', { class: 'dash-page dash-export', style: { width: `${item.w}px`, height: `${item.h}px`, backgroundColor: 'transparent' } },
      page.itemEl({ ...item, x: 0, y: 0 }, { [item.node_id]: w }, { exporting: true })), item.w, item.h);
    const data = await renderPng(wrap, item.w, item.h + strip, { background: 'transparent' });
    const saved = await savePng(`${w.title || nodeLabel(item.node_id)} - ${stamp()}`, data);
    if (saved) { logImage(saved); toast(`Imagem salva: ${saved}`, { kind: 'success' }); }
  } catch (err) {
    toastError(err, 'Não foi possível gerar a imagem');
  }
}
