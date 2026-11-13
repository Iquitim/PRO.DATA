// Pasta de arquivos como fonte da vista Dados (spec 035): cadastro com a lista ao vivo, visão geral e a caixa antiga.
// A pasta é lida onde está, nunca copiada nem alterada; os fluxos guardam só `folder:<id>`.

import { addNode } from './actions.js';
import { api } from './api.js';
import { viewportCenter } from './canvas.js';
import { columnQuality, stat } from './data_stats.js';
import { previewTable, refreshDatasets } from './datasets.js';
import { chooseFolder, isDesktop } from './desktop.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { changeSources, ensureFolder } from './organization.js';
import { emit, FOLDER_PREFIX, mutate, store } from './store.js';
import { confirmDialog, toast, toastError } from './ui.js';

const EXCEL = /\.(xlsx|xlsm|xlsb|xls)$/i;
const READ_FIELDS = ['format', 'delimiter', 'encoding', 'decimal', 'sheet', 'skip_rows', 'skip_columns', 'has_header',
  'null_values', 'infer_schema_rows', 'parse_dates'];
const when = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—');

export async function refreshFolderSources() {
  store.folderSources = await api.folderSources();
  emit('folders');
}

export function addFolderNode(source) {
  const c = viewportCenter();
  addNode('io.input_data', c.x - 94, c.y - 28, { dataset: `${FOLDER_PREFIX}${source.id}`, __label: source.name });
}

export async function removeFolderSource(source) {
  const ok = await confirmDialog({
    title: 'Esquecer a pasta',
    message: `Tirar "${source.name}" da vista Dados? A pasta ${source.folder} e os arquivos dela continuam onde estão.`,
    confirm: 'Esquecer a pasta', danger: true,
  });
  if (!ok) return;
  await api.deleteFolderSource(source.id);
  await refreshFolderSources();
}

// ------------------------------------------------------------------ lista de arquivos e desenho

function fileRow(f) {
  return h('li', { class: ['fd-file', f.odd && 'odd'], title: f.odd ? 'Colunas diferentes das do primeiro arquivo: o que faltar fica vazio.' : f.name },
    icon('file', 14),
    h('span', { class: 'fd-file-name mono ellipsis' }, f.name),
    f.odd ? h('span', { class: 'fd-odd' }, icon('alert', 11), 'colunas diferentes') : null,
    h('span', { class: 'fd-file-meta' }, `${fmt.bytes(f.size_bytes)} · ${when(f.modified_at)}`));
}

/** "3 arquivos → 1 tabela": o desenho do que a pasta vira, com os arquivos de verdade. */
function stackArt(preview, pattern) {
  const files = preview.files || [];
  const shown = files.slice(0, 4);
  return h('div', { class: 'fd-art', role: 'img', 'aria-label': `${files.length} arquivos empilhados numa tabela` },
    h('div', { class: 'fd-art-files' },
      shown.map((f, i) => h('span', { class: 'fd-art-file', style: { '--i': String(i) } }, icon('file', 12), f.name)),
      files.length > 4 ? h('span', { class: 'fd-art-more' }, `+ ${files.length - 4}`) : null,
      files.length ? null : h('span', { class: 'fd-art-file empty' }, icon('file', 12), pattern || '*')),
    h('span', { class: 'fd-art-arrow' }, icon('arrow-down', 14), 'empilha'),
    h('span', { class: 'fd-art-table' }, icon('table', 14),
      preview.columns ? `1 tabela · ${preview.columns.length} colunas` : '1 tabela'));
}

function problem(preview, pattern) {
  if (preview.missing) return h('p', { class: 'api-warn' }, icon('alert', 14), ` ${preview.error}`);
  if (preview.error) return h('p', { class: 'api-warn' }, icon('alert', 14), ` ${preview.error}`);
  if (!preview.total) {
    return h('p', { class: 'api-warn' }, icon('alert', 14),
      ` Nenhum arquivo da pasta casa com ${pattern || '*'}. Confira o padrão: * vale qualquer trecho, como vendas_*.xlsx.`);
  }
  return null;
}

function filesCard(preview, title = 'Arquivos que entram') {
  const odd = (preview.files || []).filter((f) => f.odd).length;
  return h('section', { class: 'dv-card stack-sm fd-files-card' },
    h('div', { class: 'row space-between' }, h('h3', {}, title), h('span', { class: 'org-count' }, String(preview.total || 0))),
    odd ? h('p', { class: 'field-help' }, icon('alert', 12), ` ${odd} arquivo(s) com colunas diferentes do primeiro: as colunas que faltarem ficam vazias.`) : null,
    h('ul', { class: 'fd-file-list' }, (preview.files || []).map((f) => fileRow(f))),
    preview.checked && preview.total > preview.checked
      ? h('p', { class: 'field-help' }, `As colunas foram conferidas nos ${preview.checked} primeiros arquivos.`) : null);
}

// ------------------------------------------------------------------ visão geral no detalhe

export function folderOverview(source) {
  const box = h('div', { class: 'stack-sm fd-overview' }, h('p', { class: 'muted' }, 'Lendo a pasta…'));
  api.previewFolder(source, 100).then((preview) => {
    const trouble = problem(preview, source.pattern);
    if (trouble) {
      box.replaceChildren(trouble, h('p', { class: 'field-help' }, 'Ajuste a pasta ou o padrão em Cadastro.'));
      return;
    }
    const newest = (preview.files || []).reduce((a, f) => (f.modified_at > a ? f.modified_at : a), '');
    const sample = { columns: preview.columns, rows: preview.rows };
    box.replaceChildren(
      h('div', { class: 'dv-stats' },
        stat('Arquivos', fmt.int(preview.total), source.pattern),
        stat('Colunas', fmt.int(preview.columns.length)),
        stat('Mais recente', when(newest), 'lida onde está, sem cópia'),
        stat('Pasta', h('span', { class: 'mono fd-path ellipsis', title: source.folder }, source.folder))),
      h('div', { class: 'dv-split' }, filesCard(preview), columnQuality(sample)),
      h('section', { class: 'dv-card stack-sm' },
        h('h3', {}, 'Prévia: primeiras linhas, já empilhadas'),
        h('p', { class: 'field-help' }, `Um pedaço de cada arquivo.${source.file_column ? ` A coluna [${source.file_column}] diz de onde veio cada linha.` : ''}`),
        previewTable(preview.columns, preview.rows.slice(0, 14))));
  }).catch((err) => box.replaceChildren(h('p', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`)));
  return box;
}

// ------------------------------------------------------------------ cadastro

function field(label, control, help) {
  return h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control, help ? h('p', { class: 'field-help' }, help) : null);
}

const baseName = (path) => String(path || '').split(/[\\/]/).filter(Boolean).pop() || '';
const linkedPaths = () => new Set(store.datasets.filter((d) => d.linked_path).map((d) => d.linked_path.toLowerCase()));

const MODES = {
  stack: {
    title: 'Uma tabela só', icon: 'table',
    text: 'Empilha os arquivos, um embaixo do outro. Os que chegarem depois entram sozinhos. Para arquivos com as mesmas colunas, como um por filial ou por mês.',
    art: ['file', 'file', 'file', 'arrow-down', 'table'],
  },
  each: {
    title: 'Um por arquivo', icon: 'file',
    text: 'Cada arquivo vira uma fonte separada, lida onde está. Para arquivos diferentes entre si, como cadastros e relatórios de assuntos distintos.',
    art: ['file', 'file', 'file', 'arrow-down', 'table', 'table', 'table'],
  },
};

function modeCard(key, current, choose) {
  const m = MODES[key];
  const files = m.art.slice(0, 3);
  const tables = m.art.slice(4);
  return h('button', { type: 'button', role: 'radio', class: 'fd-mode', 'aria-checked': String(key === current), dataset: { mode: key }, onclick: () => choose(key) },
    h('span', { class: 'fd-mode-art', 'aria-hidden': 'true' },
      h('span', { class: 'fd-mode-row files' }, files.map(() => icon('file', 13))),
      icon('arrow-down', 11),
      h('span', { class: 'fd-mode-row tables' }, tables.map(() => icon('table', 13)))),
    h('span', { class: 'fd-mode-text' }, h('strong', {}, m.title), h('small', {}, m.text)));
}

/** "4 arquivos → 4 fontes": o desenho do modo Um por arquivo. */
function eachArt(preview, group) {
  const files = preview.files || [];
  return h('div', { class: 'fd-art', role: 'img', 'aria-label': `${files.length} arquivos, cada um uma fonte` },
    h('div', { class: 'fd-art-files' },
      files.slice(0, 4).map((f) => h('span', { class: 'fd-art-file' }, icon('file', 12), f.name)),
      files.length > 4 ? h('span', { class: 'fd-art-more' }, `+ ${files.length - 4}`) : null),
    h('span', { class: 'fd-art-arrow' }, icon('arrow-down', 14), 'cada um vira uma fonte'),
    h('span', { class: 'fd-art-table' }, icon('folder-closed', 14),
      `${files.length} fonte${files.length === 1 ? '' : 's'}${group ? ` na pasta ${group}` : ''}`));
}

function eachCard(preview) {
  const known = linkedPaths();
  const folder = String(preview.folder || '');
  const rows = (preview.files || []).map((f) => {
    const already = known.has(`${folder}\\${f.name}`.toLowerCase()) || known.has(`${folder}/${f.name}`.toLowerCase());
    return h('li', { class: ['fd-file', already && 'known'] }, icon('file', 14),
      h('span', { class: 'fd-file-name mono ellipsis' }, f.name),
      already ? h('span', { class: 'fd-known' }, 'já vinculado') : null,
      h('span', { class: 'fd-file-meta' }, `${fmt.bytes(f.size_bytes)} · ${when(f.modified_at)}`));
  });
  return h('section', { class: 'dv-card stack-sm fd-files-card' },
    h('div', { class: 'row space-between' }, h('h3', {}, 'Fontes que serão criadas'), h('span', { class: 'org-count' }, String(preview.total || 0))),
    h('ul', { class: 'fd-file-list' }, rows),
    h('p', { class: 'field-help' }, icon('clock', 12), ' Vale para os arquivos de hoje: os que chegarem depois não entram sozinhos. Para isso, use Uma tabela só.'));
}

/** Formulário para a vista Dados. `existing`: a fonte a editar, ou null para criar (com a escolha entre os dois modos). */
export function folderEditor(existing = null, { onSaved, onLinked } = {}, host = {}) {
  const value = { name: '', folder: '', pattern: '*.xlsx', file_column: 'arquivo', sheet: '', ...(existing || {}) };
  const state = { mode: 'stack', group: true, groupName: '', groupEdited: false, total: 0 };
  const input = (key, attrs = {}) => h('input', {
    class: 'input', value: value[key] ?? '', ...attrs,
    oninput: (e) => { value[key] = e.target.value; if (key !== 'name') schedule(); syncSheet(); },
  });
  const name = input('name', { maxlength: 80, placeholder: 'Ex.: Vendas do mês' });
  const folder = input('folder', { class: 'input mono', placeholder: 'D:\\Fechamento\\2026-10' });
  const pattern = input('pattern', { class: 'input mono', placeholder: 'vendas_*.xlsx' });
  const column = input('file_column', { maxlength: 60, placeholder: 'vazio = não criar' });
  const sheet = input('sheet', { placeholder: 'primeira aba' });
  const sheetField = field('Aba do Excel', sheet, 'Vale para todos os arquivos. Vazio = a primeira aba de cada um.');
  const syncSheet = () => { sheetField.hidden = state.mode !== 'stack' || !EXCEL.test(value.pattern || ''); };
  const groupName = h('input', { class: 'input', maxlength: 60, placeholder: 'Nome da pasta na lista',
    oninput: (e) => { state.groupName = e.target.value; state.groupEdited = true; schedule(); } });
  const groupCheck = h('input', { type: 'checkbox', checked: true,
    onchange: (e) => { state.group = e.target.checked; groupName.disabled = !state.group; schedule(); } });
  const live = h('div', { class: 'fd-live' });
  const form = h('div', { class: 'stack-sm fd-form' });
  const modes = h('div', { class: 'fd-modes', role: 'radiogroup', 'aria-label': 'Como ler a pasta' });
  const primary = button({ icon: 'check', label: existing ? 'Salvar' : 'Cadastrar pasta', variant: 'primary', onClick: () => (state.mode === 'each' ? linkEach() : save()) });

  const syncGroup = () => {
    if (!state.groupEdited) { state.groupName = baseName(value.folder); groupName.value = state.groupName; }
  };
  const setLabel = () => {
    const text = state.mode === 'each' ? `Vincular ${state.total || ''} arquivo${state.total === 1 ? '' : 's'}`.replace('  ', ' ') : existing ? 'Salvar' : 'Cadastrar pasta';
    primary.querySelector('span').textContent = text;
  };
  const choose = (mode) => { state.mode = mode; drawForm(); refresh(); };
  const pick = async () => {
    const chosen = await chooseFolder(value.folder);
    if (!chosen) return;
    value.folder = chosen;
    folder.value = chosen;
    if (!value.name) { value.name = baseName(chosen); name.value = value.name; }
    schedule();
  };
  const drawForm = () => {
    modes.replaceChildren(...Object.keys(MODES).map((k) => modeCard(k, state.mode, choose)));
    const where = field('Pasta', h('div', { class: 'row' }, folder, isDesktop() ? button({ icon: 'directory', label: 'Escolher…', onClick: pick }) : null),
      'Caminho completo. Só esta pasta, sem subpastas.');
    const which = field('Arquivos', pattern, '* vale qualquer trecho e ? um caractere. Ex.: vendas_*.xlsx');
    form.replaceChildren(...(state.mode === 'stack'
      ? [field('Nome', name), where, which, field('Coluna com o nome do arquivo', column, 'Diz de qual arquivo veio cada linha. Vazio = não criar.'), sheetField]
      : [where, which,
        h('div', { class: 'field' },
          h('label', { class: 'fd-check' }, groupCheck, ' Agrupar numa pasta da vista Dados'),
          groupName,
          h('p', { class: 'field-help' }, 'As fontes novas ficam juntas na lista, como as pastas da organização.'))]));
    syncSheet();
    setLabel();
  };
  const draw = (preview) => {
    state.total = preview.total || 0;
    setLabel();
    const trouble = problem(preview, value.pattern);
    if (state.mode === 'each') {
      live.replaceChildren(h('span', { class: 'org-preview-label' }, 'O que vai ser criado'),
        eachArt(preview, state.group ? state.groupName : ''), trouble || eachCard({ ...preview, folder: value.folder.trim() }));
      return;
    }
    const odd = (preview.files || []).some((f) => f.odd);
    live.replaceChildren(
      h('span', { class: 'org-preview-label' }, 'O que vai entrar'),
      stackArt(preview, value.pattern),
      odd && !existing ? h('div', { class: 'fd-suggest' }, icon('info', 14),
        h('span', {}, 'Os arquivos têm colunas diferentes. Se forem assuntos distintos, cada um pode virar uma fonte.'),
        button({ label: 'Usar Um por arquivo', size: 'sm', onClick: () => choose('each') })) : null,
      trouble || filesCard(preview, 'Arquivos que casam'));
  };
  const refresh = async () => {
    syncGroup();
    if (!value.folder.trim()) {
      state.total = 0;
      setLabel();
      live.replaceChildren(h('span', { class: 'org-preview-label' }, state.mode === 'each' ? 'O que vai ser criado' : 'O que vai entrar'),
        state.mode === 'each' ? eachArt({ files: [] }, '') : stackArt({ files: [] }, value.pattern),
        h('p', { class: 'field-help' }, 'Escolha a pasta para ver os arquivos que entram.'));
      return;
    }
    try { draw(await api.previewFolder({ ...value, name: value.name || 'pasta' }, 60)); } catch (err) { live.replaceChildren(h('p', { class: 'text-error' }, err.message)); }
  };
  const schedule = debounce(refresh, 350);

  const save = async () => {
    if (!value.name.trim()) { name.focus(); name.classList.add('invalid'); return; }
    const body = Object.fromEntries(Object.entries(value).filter(([k]) => k !== 'status'));
    try {
      const saved = existing ? await api.updateFolderSource(existing.id, body) : await api.createFolderSource(body);
      await refreshFolderSources();
      toast(existing ? 'Pasta salva' : 'Pasta cadastrada', { kind: 'success', detail: `${saved.status.files} arquivo(s) entram hoje.` });
      onSaved?.(saved);
    } catch (err) {
      toastError(err, 'Não foi possível salvar a pasta');
    }
  };
  const linkEach = async () => {
    try {
      const out = await api.linkEachFile(value.folder, value.pattern);
      const names = out.linked.map((d) => d.name);
      await refreshDatasets();
      const group = state.group && state.groupName.trim();
      if (group && names.length) {
        const id = await ensureFolder(group);
        if (id) await changeSources(names.map((n) => `file:${n}`), { folder: id });
      }
      const skipped = out.skipped.length ? ` ${out.skipped.length} já estavam vinculados.` : '';
      toast(names.length ? `${names.length} arquivo(s) vinculados` : 'Nada novo para vincular',
        { kind: names.length ? 'success' : 'info', detail: `${group && names.length ? `Na pasta ${group}.` : ''}${skipped}`.trim() });
      onLinked?.(names);
    } catch (err) {
      toastError(err, 'Não foi possível vincular os arquivos');
    }
  };
  drawForm();
  refresh();
  return {
    title: existing ? `Editar ${existing.name}` : 'Nova pasta de arquivos',
    body: h('div', { class: 'fd-wrap' },
      existing ? null : modes,
      h('div', { class: 'fd-editor' },
        h('div', { class: 'stack-sm' },
          existing ? h('p', { class: 'field-help' }, 'Todos os arquivos da pasta que casam com o padrão viram uma tabela só, um embaixo do outro. A pasta é lida onde está: nada é copiado nem alterado.') : null,
          form),
        live)),
    actions: [
      button({ label: 'Cancelar', variant: 'ghost', onClick: () => host.close?.() }),
      primary,
    ],
  };
}

// ------------------------------------------------------------------ caixa antiga (spec 033)

/** Leva a caixa Input Folder para a vista Dados: cria a fonte (ou usa uma igual) e troca por Input Data no lugar. */
export async function convertLegacyFolder(n, defaultName = 'Input Folder') {
  const cfg = n.config;
  const same = (s) => s.folder.toLowerCase() === String(cfg.folder || '').trim().toLowerCase()
    && s.pattern.toLowerCase() === String(cfg.pattern || '').trim().toLowerCase();
  try {
    let source = store.folderSources.find(same);
    if (!source) {
      const base = n.label && n.label !== defaultName ? n.label : (String(cfg.folder || '').split(/[\\/]/).filter(Boolean).pop() || 'Pasta');
      const body = { name: base, folder: cfg.folder, pattern: cfg.pattern, file_column: cfg.file_column ?? 'arquivo',
        ...Object.fromEntries(READ_FIELDS.filter((k) => cfg[k] !== undefined).map((k) => [k, cfg[k]])) };
      for (let i = 1; !source; i += 1) {
        try {
          source = await api.createFolderSource({ ...body, name: i === 1 ? base : `${base} (${i})` });
        } catch (err) {
          if (err.status !== 409 || i > 5) throw err;
        }
      }
      await refreshFolderSources();
    }
    mutate((wf) => {
      const x = wf.nodes.find((k) => k.id === n.id);
      x.type = 'io.input_data';
      x.config = { ...structuredClone(store.tools['io.input_data'].default_config), dataset: `${FOLDER_PREFIX}${source.id}`, limit: cfg.limit || 0 };
      x.label = source.name;
    }, { affects: [n.id], structural: true });
    toast('Pasta levada para a vista Dados', { kind: 'success', detail: `"${source.name}" agora é uma fonte, lida pelo Input Data.` });
  } catch (err) {
    toastError(err, 'Não foi possível levar a pasta');
  }
}
