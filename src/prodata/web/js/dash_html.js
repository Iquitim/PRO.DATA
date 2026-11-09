// Dashboard em um arquivo HTML (spec 021): abre em qualquer navegador, sem instalar nada e sem internet.
// Com filtros na página, leva as colunas que os visuais usam; sem filtros, só os números já calculados.
// Rótulo e senha (spec 026): a senha é obrigatória em Confidencial e Restrito, e os dados ficam cifrados.

import { api } from './api.js';
import { encryptText } from './dash_crypt.js';
import { widgetsByNode, pageHeight } from './dash_model.js';
import { collectCss, saveDownload, stamp, toDataUri } from './dash_export.js';
import { activeFiltersText, isFilterActive } from './dash_filters.js';
import { button, fmt, h } from './dom.js';
import { LABELS, labelPicker, passwordRequired } from './label_picker.js';
import { mutate, store } from './store.js';
import { openDialog, toast, toastError } from './ui.js';

const MIN_PASSWORD = 8;
// O arquivo não busca nada fora dele: nem um dado malicioso consegue mandar o conteúdo para outro endereço.
const VIEWER_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'";

const size = (bytes) => (bytes >= 1048576 ? `${fmt.number(bytes / 1048576, 1)} MB` : `${fmt.int(Math.ceil(bytes / 1024))} KB`);

/** JSON dentro de <script>: nada no dado pode fechar a tag nem abrir comentário. */
const safeJson = (value) => JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
const escapeHtml = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

async function buildHtml(payload, password) {
  const [css, script, logo] = await Promise.all([collectCss(), fetch('/api/dashboard/viewer.js').then((r) => r.text()), toDataUri(new URL('/static/brand/protege-escudo.svg', location.href).href)]);
  const theme = document.documentElement.getAttribute('data-theme');
  const name = store.workflow.name || 'Dashboard';
  const data = { ...payload, name, logo };
  // Com senha, nem o nome do fluxo fica em claro: só o rótulo, para quem recebe saber como tratar o arquivo.
  const block = password
    ? `<script type="application/json" id="prodata-cifrado">${safeJson({ ...(await encryptText(JSON.stringify(data), password)), label: payload.label, label_name: payload.label_name })}</script>`
    : `<script type="application/json" id="prodata-dados">${safeJson(data)}</script>`;
  return `<!doctype html>
<html lang="pt-BR"${theme ? ` data-theme="${escapeHtml(theme)}"` : ''}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="PRO.DATA">
<meta http-equiv="Content-Security-Policy" content="${VIEWER_CSP}">
<title>${password ? 'Documento protegido' : escapeHtml(name)}</title>
<style>${css.replace(/<\/style/gi, '<\\/style')}</style>
</head>
<body class="dash-viewer">
<main id="prodata-pagina"></main>
${block}
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
    frozen_filters: d.filters || [], // sem os filtros no arquivo, ainda apagam as categorias de fora
  };
}

async function save(payload, password, counts) {
  const d = store.workflow.dashboard;
  const label = d.confidentiality || 'interno';
  const html = await buildHtml({ ...payload, label, label_name: LABELS[label] }, password);
  const saved = await saveDownload(`${store.workflow.name || 'Dashboard'} - ${stamp()}.html`, new Blob([html], { type: 'text/html' }));
  if (!saved) return;
  api.dashboardExportLog({ kind: 'HTML', file: String(saved).split(/[\\/]/).pop(), label, rows: counts.rows ?? null, columns: counts.columns ?? null, password: Boolean(password) })
    .catch((err) => toastError(err, 'O arquivo foi salvo, mas não entrou no registro de exportações'));
  toast(`Página salva: ${saved}`, { kind: 'success', detail: size(html.length) });
}

/** Rótulo e senha no diálogo. `read()` devolve a senha, ou lança o motivo de não poder gerar. */
function protection() {
  const first = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', 'aria-label': 'Senha do arquivo', placeholder: 'Senha' });
  const second = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', 'aria-label': 'Repita a senha', placeholder: 'Repita a senha' });
  const hint = h('p', { class: 'field-help' });
  const current = () => store.workflow.dashboard.confidentiality || 'interno';
  const describe = () => {
    hint.textContent = passwordRequired(current())
      ? `Obrigatória em ${LABELS[current()]}. Mínimo de ${MIN_PASSWORD} caracteres. Quem perder a senha não recupera o arquivo, mas pode gerar outro no PRO.DATA.`
      : `Opcional neste rótulo. Mínimo de ${MIN_PASSWORD} caracteres, se usar. Envie a senha por outro canal, separada do arquivo.`;
  };
  const select = labelPicker({
    value: current(),
    place: 'html',
    onChange: (level) => {
      mutate((wf) => { wf.dashboard.confidentiality = level; });
      describe();
    },
  });
  describe();
  return {
    el: h('div', { class: 'dash-html-protect' },
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Rótulo de confidencialidade'), select),
      h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Senha para abrir o arquivo'), h('div', { class: 'stack-xs' }, first, second), hint)),
    read: () => {
      const password = first.value;
      if (!password && passwordRequired(current())) throw new Error(`O rótulo ${LABELS[current()]} exige senha.`);
      if (password && password.length < MIN_PASSWORD) throw new Error(`A senha precisa ter pelo menos ${MIN_PASSWORD} caracteres.`);
      if (password !== second.value) throw new Error('As duas senhas não são iguais.');
      return password;
    },
  };
}

/** Avisa o que vai no arquivo antes de gerar: quem receber vê esses dados, inclusive o que estiver filtrado fora. */
export async function exportHtml(displayed) {
  const d = store.workflow.dashboard;
  const missing = d.items.filter((i) => i.kind === 'visual' && !displayed[i.node_id]).length;
  let info;
  try {
    info = d.filters?.length || d.timeline?.column ? await api.dashboardExportData(store.workflow) : null;
  } catch (err) {
    toastError(err, 'Não foi possível preparar o HTML');
    return;
  }
  const guard = protection();
  const warning = missing ? h('p', { class: 'api-warn' }, `${missing} visual(is) sem dados ficam de fora: execute o fluxo antes para incluí-los.`) : null;
  const run = (payload, counts, getClose) => async () => {
    let password;
    try {
      password = guard.read();
    } catch (err) {
      toast(err.message, { kind: 'error' });
      return;
    }
    getClose()();
    try {
      await save(payload, password, counts);
    } catch (err) {
      toastError(err, 'Não foi possível gerar o HTML');
    }
  };
  if (!info || info.too_large) {
    const box = openDialog({
      title: 'Baixar como HTML',
      size: 'md',
      body: h('div', { class: 'stack-sm' },
        info?.too_large ? h('p', { class: 'api-warn' }, `Os dados dos filtros dariam ${size(info.bytes)}, grande demais para abrir bem num navegador. Dá para gerar sem filtros, com os números de agora.`) : null,
        h('p', {}, 'O arquivo abre em qualquer navegador, sem instalar nada. Ele leva os números que estão na tela'
          + (d.items.some((i) => displayed[i.node_id]?.widget_type === 'table') ? ' e as linhas das tabelas visíveis.' : '.')),
        activeFiltersText(d.filters) ? h('p', { class: 'muted' }, `Recorte de agora: ${activeFiltersText(d.filters)}`) : null,
        guard.el,
        warning),
      actions: [button({ label: 'Cancelar', onClick: () => box.close() }),
        button({ label: 'Salvar HTML', icon: 'download', variant: 'primary', onClick: () => run(snapshot(displayed), {}, () => box.close)() })],
    });
    return;
  }
  const payload = {
    ...snapshot(widgetsByNode()),
    filters: d.filters, options: info.options, nodes: info.nodes, columns: info.columns, fixed_filters: '',
    timeline: d.timeline?.column ? d.timeline : null, scenes: d.timeline?.column ? d.scenes : [],
  };
  const box = openDialog({
    title: 'Baixar como HTML',
    size: 'md',
    body: h('div', { class: 'stack-sm' },
      h('p', {}, d.timeline?.column ? 'O arquivo abre em qualquer navegador e a linha do tempo, a história e os filtros continuam funcionando, sem internet.' : 'O arquivo abre em qualquer navegador e os filtros continuam funcionando, sem internet.'),
      h('div', { class: 'dash-html-warn' },
        h('strong', {}, 'Os dados vão dentro do arquivo'),
        h('p', {}, `${fmt.int(info.rows)} linhas e ${fmt.int(info.column_names.length)} colunas, cerca de ${size(info.bytes)}. Quem receber pode ver tudo isso, mesmo o que estiver filtrado fora.`),
        h('p', { class: 'muted' }, `Colunas: ${info.column_names.join(', ')}`)),
      d.filters.some(isFilterActive) ? h('p', { class: 'muted' }, `Abre com o recorte de agora: ${activeFiltersText(d.filters)}`) : null,
      guard.el,
      warning),
    actions: [button({ label: 'Cancelar', onClick: () => box.close() }),
      button({ label: 'Salvar HTML', icon: 'download', variant: 'primary', onClick: () => run(payload, { rows: info.rows, columns: info.column_names.length }, () => box.close)() })],
  });
}
