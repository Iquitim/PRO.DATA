// Organização da vista Dados (spec 034): pastas, nome de exibição, descrição, responsável e fixadas.
// Só metadados de tela, guardados neste computador: nenhum fluxo muda quando a pessoa organiza.

import { api } from './api.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';
import { emit, store } from './store.js';
import { openDialog, toastError } from './ui.js';

export const FOLDER_COLORS = {
  azul: { label: 'Azul', value: 'var(--accent)' },
  verde: { label: 'Verde', value: 'var(--ok)' },
  ambar: { label: 'Âmbar', value: 'var(--warn)' },
  roxo: { label: 'Roxo', value: 'var(--cat-ml)' },
  vermelho: { label: 'Vermelho', value: 'var(--err)' },
  cinza: { label: 'Cinza', value: 'var(--text-3)' },
};
const EMPTY = Object.freeze({ folder: '', label: '', description: '', owner: '', pinned: false });
const EXAMPLES = ['Numerário', 'Vendas', 'Fechamento do mês', 'Cadastros', 'Indicadores'];

export const infoOf = (key) => store.organization.sources[key] || EMPTY;
export const folders = () => store.organization.folders;
export const folderOf = (id) => (id ? folders().find((f) => f.id === id) || null : null);
export const colorOf = (folder) => FOLDER_COLORS[folder?.color]?.value || 'var(--text-3)';

function set(org) {
  store.organization = org;
  emit('organization');
  return org;
}

export async function refreshOrganization() {
  try {
    set(await api.organization());
  } catch {
    // Sem a organização a vista continua funcionando, só sem pastas.
  }
}

async function call(promise, failure) {
  try {
    return set(await promise);
  } catch (err) {
    toastError(err, failure);
    return null;
  }
}

export const changeSources = (keys, changes) => call(api.changeSources(keys, changes), 'Não foi possível salvar a organização');
export const deleteFolder = (id) => call(api.deleteFolder(id), 'Não foi possível excluir a pasta');
export const moveFolder = (id, position) => call(api.moveFolder(id, position), 'Não foi possível mover a pasta');

/** Id da pasta com esse nome; cria se não existir. Para agrupar fontes novas sem perguntar (spec 035). */
export async function ensureFolder(name) {
  const wanted = name.trim().slice(0, 60);
  const found = folders().find((f) => f.name.toLowerCase() === wanted.toLowerCase());
  if (found) return found.id;
  const org = await call(api.addFolder(wanted, Object.keys(FOLDER_COLORS)[folders().length % 5]), 'Não foi possível criar a pasta');
  return org ? org.folders.find((f) => f.name.toLowerCase() === wanted.toLowerCase())?.id || null : null;
}

/** A fonte foi excluída: a organização dela sai junto, sem aviso (não há o que a pessoa decidir). */
export async function forgetSources(keys) {
  try { set(await api.forgetSources(keys)); } catch { /* sobra só uma entrada órfã, inofensiva */ }
}

/** Mostra como a pasta vai aparecer na lista, enquanto a pessoa digita e escolhe a cor. */
function folderPreview(name, color, count) {
  return h('div', { class: 'org-preview', style: { '--folder': FOLDER_COLORS[color].value }, 'aria-hidden': 'true' },
    h('span', { class: 'org-preview-label' }, 'Assim ela aparece na lista'),
    h('div', { class: 'org-folder-title' },
      h('span', { class: 'org-folder-icon' }, icon('folder-closed', 16)),
      h('strong', {}, name || 'Nome da pasta'),
      h('span', { class: 'org-count' }, String(count))));
}

/**
 * Criar ou editar uma pasta. Resolve com o id da pasta, ou null se a pessoa desistir.
 * `count`: quantas fontes vão entrar nela, para a prévia mostrar o número certo.
 */
export function folderDialog(folder = null, { count = 0 } = {}) {
  return new Promise((resolve) => {
    let color = folder?.color || Object.keys(FOLDER_COLORS)[folders().length % 5];
    let answer = null;
    const preview = h('div');
    const name = h('input', {
      class: 'input', maxlength: 60, value: folder?.name || '', 'aria-label': 'Nome da pasta',
      placeholder: `Ex.: ${EXAMPLES[folders().length % EXAMPLES.length]}`,
      oninput: () => draw(),
      onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } },
    });
    const swatches = h('div', { class: 'org-swatches', role: 'radiogroup', 'aria-label': 'Cor da pasta' });
    const draw = () => {
      preview.replaceChildren(folderPreview(name.value.trim(), color, count));
      swatches.replaceChildren(...Object.entries(FOLDER_COLORS).map(([key, c]) => h('button', {
        type: 'button', role: 'radio', class: 'org-swatch', title: c.label, 'aria-label': c.label,
        'aria-checked': String(key === color), style: { '--folder': c.value },
        onclick: () => { color = key; draw(); },
      }, key === color ? icon('check', 14) : null)));
    };
    const save = async () => {
      const text = name.value.trim();
      if (!text) { name.focus(); name.classList.add('invalid'); return; }
      const org = await call(folder ? api.updateFolder(folder.id, text, color) : api.addFolder(text, color),
        folder ? 'Não foi possível salvar a pasta' : 'Não foi possível criar a pasta');
      if (!org) return;
      answer = folder ? folder.id : org.folders.at(-1).id;
      dialog.close();
    };
    draw();
    const dialog = openDialog({
      title: folder ? 'Editar pasta' : 'Nova pasta',
      size: 'sm',
      onClose: () => resolve(answer),
      body: h('div', { class: 'stack-sm org-dialog' },
        folder ? null : h('p', { class: 'dialog-text' },
          'Junte fontes do mesmo assunto, de qualquer tipo: arquivos, consultas, APIs e constantes. Os fluxos não mudam.'),
        h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Nome'), name),
        h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Cor'), swatches),
        preview),
      actions: [
        button({ label: 'Cancelar', variant: 'ghost', onClick: () => dialog.close() }),
        button({ label: folder ? 'Salvar' : 'Criar pasta', variant: 'primary', onClick: save }),
      ],
    });
    name.focus();
  });
}

/**
 * Itens de menu para mover fontes: cada pasta com a sua cor, "Sem pasta" e "Nova pasta…".
 * `before`: roda logo antes de mover, como desmarcar as fontes marcadas.
 */
export function moveItems(keys, current = null, before = () => {}) {
  const move = (folder) => { before(); return changeSources(keys, { folder }); };
  return [
    { heading: keys.length > 1 ? `Mover ${keys.length} fontes para` : 'Mover para' },
    ...folders().map((f) => ({
      label: f.name, icon: 'folder-closed', color: colorOf(f), disabled: f.id === current, onSelect: () => move(f.id),
    })),
    { label: 'Sem pasta', icon: 'x', disabled: current === '', onSelect: () => move('') },
    'separator',
    { label: 'Nova pasta…', icon: 'plus',
      onSelect: async () => { const id = await folderDialog(null, { count: keys.length }); if (id) await move(id); } },
  ];
}
