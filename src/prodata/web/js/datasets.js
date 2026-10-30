// Painel "Dados": upload, lista de arquivos e diálogo de pré-visualização com opções de leitura.

import { addNode } from './actions.js';
import { api, ApiError } from './api.js';
import { DND_DATASET, toWorld, viewportCenter } from './canvas.js';
import { button, debounce, fmt, h } from './dom.js';
import { renderFields } from './fields.js';
import { FORMAT_ICONS, icon } from './icons.js';
import { emit, mutate, on, sourceLabel, store } from './store.js';
import { chooseDataFile } from './desktop.js';
import { confirmDialog, openDialog, toast, toastError } from './ui.js';

const FORMAT_LABELS = {
  csv: 'CSV', excel: 'Excel', parquet: 'Parquet', json: 'JSON', ndjson: 'JSON Lines', arrow: 'Arrow',
};
const ENCODING_LABELS = { 'utf-8': 'UTF-8', 'utf-8-sig': 'UTF-8 (BOM)', cp1252: 'Windows-1252', 'latin-1': 'ISO-8859-1' };
const DELIMITER_LABELS = { ',': 'vírgula', ';': 'ponto e vírgula', '\t': 'tabulação', '|': 'barra vertical' };

export async function refreshDatasets() {
  store.datasets = await api.datasets();
  emit('datasets');
}

const accept = () => Object.keys(store.catalog.file_formats).join(',');

/** Lê as opções de leitura do catálogo (mesmos campos do nó Input Data). */
function readOptionFields() {
  return store.tools['io.input_data'].config_fields.filter((f) => f.group);
}

export function formatOf(name, options = {}) {
  if (options.format && options.format !== 'auto') return options.format;
  const ext = (name || '').toLowerCase().match(/\.[^.]+$/)?.[0];
  return store.catalog.file_formats[ext] || 'csv';
}

// ------------------------------------------------------------------ upload

export async function uploadFiles(files, { onUploaded } = {}) {
  for (const file of files) {
    const progress = h('progress', { max: 1, value: 0 });
    const dismiss = toast(`Enviando ${file.name}`, { timeout: 0, detail: fmt.bytes(file.size) });
    document.querySelector('#toasts .toast:last-child .toast-body')?.append(progress);
    try {
      let info;
      try {
        info = await api.uploadDataset(file, { onProgress: (p) => { progress.value = p; } });
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 409)) throw err;
        const ok = await confirmDialog({
          title: 'Arquivo já existe',
          message: `Já existe um dataset chamado "${file.name}". Substituir pelo novo arquivo?`,
          confirm: 'Substituir',
        });
        if (!ok) continue;
        info = await api.uploadDataset(file, { overwrite: true, onProgress: (p) => { progress.value = p; } });
      }
      await refreshDatasets();
      toast(`${info.name} enviado`, { kind: 'success', detail: `${FORMAT_LABELS[info.format]} · ${fmt.bytes(info.size_bytes)}` });
      if (onUploaded) onUploaded(info);
      // Planilha: abre a prévia para escolher a aba e onde a tabela começa (spec 011).
      else if (info.format === 'excel' && files.length === 1) openPreview(info.name);
    } catch (err) {
      toastError(err, `Falha ao enviar ${file.name}`);
    } finally {
      dismiss();
    }
  }
}

// ------------------------------------------------------------------ painel

/** Data e hora da última modificação do arquivo (vinculado ou cópia). */
const modifiedText = (d) => (d.modified_at ? `modificado em ${new Date(d.modified_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}` : '');

function datasetItem(d) {
  const meta = d.missing ? `Arquivo não encontrado: ${d.linked_path}`
    : d.linked_path ? `Vinculado · ${FORMAT_LABELS[d.format] || d.format} · ${modifiedText(d)}`
      : `${FORMAT_LABELS[d.format] || d.format} · ${fmt.bytes(d.size_bytes)} · ${fmt.date(d.modified_at)}`;
  return h('div', {
    class: ['dataset-item', d.linked_path && 'linked', d.missing && 'missing'],
    draggable: 'true',
    title: d.linked_path
      ? `Vinculado: ${d.linked_path}\nLido sempre na versão atual do arquivo.\nArraste para o canvas para criar um Input Data`
      : 'Cópia enviada ao PRO.DATA · arraste para o canvas para criar um Input Data',
    ondragstart: (e) => {
      e.dataTransfer.setData(DND_DATASET, d.name);
      e.dataTransfer.effectAllowed = 'copy';
    },
  },
  h('span', { class: 'dataset-icon' }, icon(d.missing ? 'alert' : d.linked_path ? 'link' : FORMAT_ICONS[d.format] || 'file', 16)),
  h('button', { type: 'button', class: 'dataset-main', disabled: d.missing, onclick: () => openPreview(d.name) },
    h('span', { class: 'dataset-name' }, d.name),
    h('span', { class: 'dataset-meta' }, meta)),
  h('div', { class: 'dataset-actions' },
    button({ icon: 'plus', title: 'Adicionar ao fluxo', size: 'sm', variant: 'ghost', onClick: () => addInputNode(d.name) }),
    button({ icon: 'trash', title: d.linked_path ? 'Remover o vínculo (o arquivo não é apagado)' : 'Excluir arquivo', size: 'sm', variant: 'ghost', onClick: () => removeDataset(d) })));
}

/** Vincular (spec 017): em vez de copiar, lê o arquivo onde está — pasta da rede, OneDrive — sempre atualizado. */
async function linkFile() {
  const path = await chooseDataFile();
  if (!path) return;
  try {
    let info;
    try {
      info = await api.linkDataset(path);
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 409) throw err;
      const base = path.split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
      info = await api.linkDataset(path, `${base}_vinculado${path.match(/\.[^.\\/]+$/)?.[0] || ''}`);
    }
    await refreshDatasets();
    toast(`${info.name} vinculado`, { kind: 'success', detail: 'O PRO.DATA lê sempre a versão atual do arquivo, sem cópia.' });
  } catch (err) {
    toastError(err, 'Não foi possível vincular o arquivo');
  }
}

function addInputNode(name, options = {}) {
  const c = viewportCenter();
  addNode('io.input_data', c.x - 80, c.y - 28, { ...options, dataset: name, __label: sourceLabel(name) });
}

async function removeDataset(d) {
  const { name } = d;
  const used = store.workflow?.nodes.some((n) => n.config?.dataset === name);
  const warn = used ? ' Este fluxo usa a fonte e deixará de funcionar.' : '';
  const ok = await confirmDialog(d.linked_path ? {
    title: 'Remover vínculo',
    message: `Remover o vínculo com "${d.linked_path}"? O arquivo continua onde está.${warn}`,
    confirm: 'Remover vínculo',
  } : {
    title: 'Excluir arquivo',
    message: `Excluir "${name}" de storage/datasets?${warn}`,
    confirm: 'Excluir',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteDataset(name);
    await refreshDatasets();
    toast(d.linked_path ? `Vínculo com ${name} removido` : `${name} excluído`, { kind: 'success' });
  } catch (err) {
    toastError(err, 'Não foi possível excluir');
  }
}

export function renderDatasetsPanel(root) {
  const input = h('input', { type: 'file', multiple: true, hidden: true, accept: accept(),
    onchange: (e) => { uploadFiles([...e.target.files]); e.target.value = ''; } });
  const drop = h('button', { type: 'button', class: 'dropzone', onclick: () => input.click() },
    icon('upload', 20),
    h('strong', {}, 'Enviar arquivos'),
    h('span', {}, 'Arraste aqui ou clique · CSV, Excel, Parquet, JSON, Arrow'));
  for (const type of ['dragenter', 'dragover']) {
    drop.addEventListener(type, (e) => {
      if (!e.dataTransfer.types.includes('Files')) return;
      e.preventDefault();
      drop.classList.add('over');
    });
  }
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    uploadFiles([...e.dataTransfer.files]);
  });

  const list = h('div', { class: 'dataset-list' });
  const draw = () => {
    list.replaceChildren(...(store.datasets.length
      ? store.datasets.map(datasetItem)
      : [h('p', { class: 'muted pad' }, 'Nenhum arquivo ainda.')]));
  };
  on('datasets', draw);
  const link = button({
    icon: 'link', label: 'Vincular arquivo', size: 'sm', class: 'btn btn-sm link-file',
    title: 'Vincular um arquivo da rede ou do computador: lido onde está, sempre na versão atual (para planilhas atualizadas todo dia)',
    onClick: linkFile,
  });
  root.replaceChildren(h('div', { class: 'pad stack-sm' }, drop, input, link,
    h('p', { class: 'field-help' }, 'Enviar faz uma cópia. Vincular lê o original: se ele for atualizado, o fluxo pega a versão nova.')),
    h('div', { class: 'panel-subtitle' }, 'Arquivos'), list);
  draw();
}

/** Soltar arquivos do sistema direto no canvas: envia e cria o nó Input Data no ponto. */
export function enableFileDropOnCanvas(viewport) {
  viewport.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
      e.preventDefault();
      viewport.classList.add('file-over');
    }
  });
  viewport.addEventListener('dragleave', () => viewport.classList.remove('file-over'));
  viewport.addEventListener('drop', (e) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    viewport.classList.remove('file-over');
    const at = toWorld(e.clientX, e.clientY);
    let offset = 0;
    uploadFiles([...e.dataTransfer.files], {
      onUploaded: (info) => {
        const created = addNode('io.input_data', at.x - 80, at.y - 28 + offset, { dataset: info.name, __label: sourceLabel(info.name) });
        offset += 110;
        if (created && info.format === 'excel') {
          openPreview(info.name, {
            applyLabel: 'Usar estas opções',
            onApply: (opts) => mutate((wf) => Object.assign(wf.nodes.find((n) => n.id === created.id).config, opts),
              { affects: [created.id], structural: true }),
          });
        }
      },
    });
  });
}

// ------------------------------------------------------------------ pré-visualização

function detectedSummary(preview) {
  const o = preview.options;
  const parts = [FORMAT_LABELS[o.format] || o.format];
  if (o.format === 'csv') {
    parts.push(ENCODING_LABELS[o.encoding] || o.encoding, `delimitador ${DELIMITER_LABELS[o.delimiter] || o.delimiter}`,
      `decimal "${o.decimal}"`);
  }
  if (o.format === 'excel' && preview.sheets.length) parts.push(`aba ${o.sheet || preview.sheets[0]}`);
  return parts.join(' · ');
}

export function previewTable(columns, rows) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data-table compact' },
    h('thead', {}, h('tr', {}, columns.map((c) => h('th', {},
      h('div', { class: 'th-name' }, c.name), h('div', { class: 'th-type' }, c.type))))),
    h('tbody', {}, rows.map((r) => h('tr', {}, columns.map((c) => cell(r[c.name], c.type)))))));
}

export function cell(value, type) {
  if (value === null || value === undefined) return h('td', { class: 'null' }, 'null');
  const numeric = type === 'Int64' || type === 'Float64';
  const text = numeric ? fmt.number(value) : typeof value === 'boolean' ? (value ? 'verdadeiro' : 'falso') : String(value);
  return h('td', { class: numeric ? 'num' : '', title: text.length > 40 ? text : null }, text);
}

/**
 * Abre o diálogo de preview. Com `onApply`, o botão principal devolve as opções
 * escolhidas (usado pelo Inspector); sem ele, cria um nó Input Data.
 */
export function openPreview(name, { options = {}, onApply, applyLabel = 'Aplicar ao nó' } = {}) {
  const defaults = Object.fromEntries(readOptionFields().map((f) => [f.name, f.default]));
  const chosen = { ...defaults, ...options };
  let preview = null;
  let drawnFor = '';
  const formPane = h('div', { class: 'preview-options' });
  const meta = h('div', { class: 'preview-meta' }, 'Lendo arquivo…');
  const sheetBar = h('div', { class: 'sheet-tabs', role: 'tablist', 'aria-label': 'Abas da planilha', hidden: true });
  const tablePane = h('div', { class: 'preview-table' });

  // Abas do Excel como guias, igual ao rodapé do Excel (spec 011).
  const drawSheets = () => {
    const sheets = preview?.sheets || [];
    sheetBar.hidden = sheets.length < 2;
    const current = chosen.sheet || sheets[0];
    sheetBar.replaceChildren(h('span', { class: 'sheet-tabs-label' }, icon('table', 13), `${sheets.length} abas`),
      ...sheets.map((name) => h('button', {
        type: 'button', role: 'tab', class: ['sheet-tab', name === current && 'active'], 'aria-selected': String(name === current),
        onclick: () => {
          if (name === current) return;
          chosen.sheet = name;
          drawSheets();
          drawForm();
          load();
        },
      }, name)));
  };

  const drawForm = () => {
    formPane.replaceChildren(renderFields(readOptionFields(), chosen, (path, value) => {
      chosen[path[0]] = value;
      load();
      if (['format', 'has_header'].includes(path[0])) drawForm();
      if (path[0] === 'sheet') drawSheets();
    }, { format: preview?.options.format || formatOf(name, chosen), sheets: preview?.sheets || [] }));
  };

  const load = debounce(async () => {
    tablePane.classList.add('loading');
    try {
      preview = await api.previewDataset(name, chosen, 100);
      const rows = preview.row_count === null ? '' : ` · ${fmt.int(preview.row_count)} linhas`;
      meta.replaceChildren(
        h('span', { class: 'badge' }, icon('check', 12), 'Detectado'),
        h('span', {}, detectedSummary(preview)),
        h('span', { class: 'muted' }, `${preview.columns.length} colunas${rows} · ${fmt.bytes(preview.info.size_bytes)}`));
      tablePane.replaceChildren(previewTable(preview.columns, preview.rows));
      drawSheets();
      const formKey = `${preview.options.format}|${preview.sheets.join(',')}`;
      if (formKey !== drawnFor) drawForm();
      drawnFor = formKey;
    } catch (err) {
      meta.replaceChildren(h('span', { class: 'text-error' }, icon('alert', 14), err.message));
      tablePane.replaceChildren();
    } finally {
      tablePane.classList.remove('loading');
    }
  }, 250);

  const { close } = openDialog({
    title: name,
    size: 'xl',
    body: h('div', { class: 'preview-layout' }, formPane, h('div', { class: 'preview-main' }, meta, sheetBar, tablePane)),
    actions: [
      button({ label: 'Cancelar', onClick: () => close() }),
      button({
        label: onApply ? applyLabel : 'Adicionar ao fluxo',
        icon: onApply ? 'check' : 'plus',
        variant: 'primary',
        onClick: () => {
          close();
          if (onApply) onApply(chosen);
          else addInputNode(name, chosen);
        },
      }),
    ],
  });
  drawForm();
  load();
}
