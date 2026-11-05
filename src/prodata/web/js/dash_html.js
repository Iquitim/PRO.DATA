// Dashboard em um arquivo HTML (spec 021): abre em qualquer navegador, sem instalar nada e sem internet.
// Com filtros na página, leva as colunas que os visuais usam; sem filtros, só os números já calculados.

import { api } from './api.js';
import { widgetsByNode, pageHeight } from './dash_model.js';
import { collectCss, saveDownload, stamp, toDataUri } from './dash_export.js';
import { activeFiltersText, isFilterActive } from './dash_filters.js';
import { button, fmt, h } from './dom.js';
import { store } from './store.js';
import { openDialog, toast, toastError } from './ui.js';

const size = (bytes) => (bytes >= 1048576 ? `${fmt.number(bytes / 1048576, 1)} MB` : `${fmt.int(Math.ceil(bytes / 1024))} KB`);

/** JSON dentro de <script>: nada no dado pode fechar a tag nem abrir comentário. */
const safeJson = (value) => JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
const escapeHtml = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

async function buildHtml(payload) {
  const [css, script, logo] = await Promise.all([collectCss(), fetch('/api/dashboard/viewer.js').then((r) => r.text()), toDataUri(new URL('/static/brand/protege-escudo.svg', location.href).href)]);
  const theme = document.documentElement.getAttribute('data-theme');
  const name = store.workflow.name || 'Dashboard';
  return `<!doctype html>
<html lang="pt-BR"${theme ? ` data-theme="${escapeHtml(theme)}"` : ''}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="PRO.DATA">
<title>${escapeHtml(name)}</title>
<style>${css.replace(/<\/style/gi, '<\\/style')}</style>
</head>
<body class="dash-viewer">
<main id="prodata-pagina"></main>
<script type="application/json" id="prodata-dados">${safeJson({ ...payload, name, logo })}</script>
<script>${script.replace(/<\/script/gi, '<\\/script')}</script>
</body>
</html>
`;
}

function snapshot(displayed) {
  const d = store.workflow.dashboard;
  return {
    exported_at: new Date().toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }),
    page: d.page, height: pageHeight(d.page), items: d.items, widgets: displayed,
    filters: [], options: [], nodes: {}, columns: {},
    fixed_filters: activeFiltersText(d.filters),
  };
}

async function save(payload) {
  const html = await buildHtml(payload);
  const saved = await saveDownload(`${store.workflow.name || 'Dashboard'} - ${stamp()}.html`, new Blob([html], { type: 'text/html' }));
  if (saved) toast(`Página salva: ${saved}`, { kind: 'success', detail: size(html.length) });
}

/** Avisa o que vai no arquivo antes de gerar: quem receber vê esses dados, inclusive o que estiver filtrado fora. */
export async function exportHtml(displayed) {
  const d = store.workflow.dashboard;
  const missing = d.items.filter((i) => i.kind === 'visual' && !displayed[i.node_id]).length;
  let info;
  try {
    info = d.filters?.length ? await api.dashboardExportData(store.workflow) : null;
  } catch (err) {
    toastError(err, 'Não foi possível preparar o HTML');
    return;
  }
  const warning = missing ? h('p', { class: 'api-warn' }, `${missing} visual(is) sem dados ficam de fora: execute o fluxo antes para incluí-los.`) : null;
  const run = (payload, close) => async () => {
    close();
    try {
      await save(payload);
    } catch (err) {
      toastError(err, 'Não foi possível gerar o HTML');
    }
  };
  if (!info || info.too_large) {
    const { close } = openDialog({
      title: 'Baixar como HTML',
      size: 'md',
      body: h('div', { class: 'stack-sm' },
        info?.too_large ? h('p', { class: 'api-warn' }, `Os dados dos filtros dariam ${size(info.bytes)}, grande demais para abrir bem num navegador. Dá para gerar sem filtros, com os números de agora.`) : null,
        h('p', {}, 'O arquivo abre em qualquer navegador, sem instalar nada. Ele leva os números que estão na tela'
          + (d.items.some((i) => displayed[i.node_id]?.widget_type === 'table') ? ' e as linhas das tabelas visíveis.' : '.')),
        activeFiltersText(d.filters) ? h('p', { class: 'muted' }, `Recorte de agora: ${activeFiltersText(d.filters)}`) : null,
        warning),
      actions: [button({ label: 'Cancelar', onClick: () => close() }),
        button({ label: 'Salvar HTML', icon: 'download', variant: 'primary', onClick: () => run(snapshot(displayed), close)() })],
    });
    return;
  }
  const saveWithData = (close) => run({
    ...snapshot(widgetsByNode()),
    filters: d.filters, options: info.options, nodes: info.nodes, columns: info.columns, fixed_filters: '',
  }, close);
  const { close } = openDialog({
    title: 'Baixar como HTML',
    size: 'md',
    body: h('div', { class: 'stack-sm' },
      h('p', {}, 'O arquivo abre em qualquer navegador e os filtros continuam funcionando, sem internet.'),
      h('div', { class: 'dash-html-warn' },
        h('strong', {}, 'Os dados vão dentro do arquivo'),
        h('p', {}, `${fmt.int(info.rows)} linhas e ${fmt.int(info.column_names.length)} colunas, cerca de ${size(info.bytes)}. Quem receber pode ver tudo isso, mesmo o que estiver filtrado fora.`),
        h('p', { class: 'muted' }, `Colunas: ${info.column_names.join(', ')}`)),
      d.filters.some(isFilterActive) ? h('p', { class: 'muted' }, `Abre com o recorte de agora: ${activeFiltersText(d.filters)}`) : null,
      warning),
    actions: [button({ label: 'Cancelar', onClick: () => close() }),
      button({ label: 'Salvar HTML', icon: 'download', variant: 'primary', onClick: () => saveWithData(close)() })],
  });
}
