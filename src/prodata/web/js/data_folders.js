// Lista organizada da vista Dados (spec 034, RF-3401..3407 e RF-3430..3432): pastas por assunto, fixadas,
// filtros com contagem e ordem. Arrastar um cartão até a pasta move a fonte; Ctrl+clique marca várias.

import { allSources, hasProblem, isUnused, KINDS, matches, usageText, usesOf } from './data_sources.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';
import { changeSources, colorOf, deleteFolder, folderDialog, folderOf, folders, moveFolder, moveItems } from './organization.js';
import { confirmDialog, showMenu } from './ui.js';

const DND_KEYS = 'application/x-prodata-sources';
const PREFS = 'prodata.dados.lista';
const OPENED = 'prodata.dados.abertas';
const FILTERS = [
  ['all', 'Todas', null],
  ['problem', 'Com problema', 'alert'],
  ['unused', 'Sem uso', 'clock'],
  ['pinned', 'Fixadas', 'star'],
];
const SORTS = { name: 'Nome', used: 'Mais usadas', recent: 'Mais recentes' };
const TEST = { all: () => true, problem: hasProblem, unused: isUnused, pinned: (s) => s.info.pinned };

function load(key, fallback) {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) || '{}') }; } catch { return { ...fallback }; }
}
function keep(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* sem armazenamento: só não lembra */ }
}

// Preferências de quem usa este computador: modo, ordem, pastas recolhidas, dica dispensada.
const prefs = load(PREFS, { mode: 'folders', sort: 'name', collapsed: [], tipDone: false });
const opened = load(OPENED, {});
const state = { filter: 'all', picked: new Set() };
const savePrefs = () => keep(PREFS, prefs);

/** Lembra quando a fonte foi aberta, para "Mais recentes". */
export function markOpened(key) {
  opened[key] = Date.now();
  const recent = Object.entries(opened).sort((a, b) => b[1] - a[1]).slice(0, 200);
  keep(OPENED, Object.fromEntries(recent));
}

function recency(source) {
  const file = source.kind === 'file' && source.raw.modified_at ? Date.parse(source.raw.modified_at) : 0;
  return Math.max(file, opened[source.key] || 0);
}

const byName = (a, b) => a.title.localeCompare(b.title, 'pt-BR', { sensitivity: 'base' });
const ORDER = {
  name: byName,
  used: (a, b) => usesOf(b).length - usesOf(a).length || byName(a, b),
  recent: (a, b) => recency(b) - recency(a) || byName(a, b),
};

/** O que vai junto ao arrastar ou mover: as marcadas, se esta for uma delas; senão, só esta. */
const keysFor = (source) => (state.picked.has(source.key) ? [...state.picked] : [source.key]);
/** Depois de agir sobre as marcadas, a marcação acaba: a próxima ação vale só para a fonte clicada. */
const unpick = () => state.picked.clear();

/**
 * `ctx`: selectedKey, onOpen(key, opts), redraw() (redesenha a lista com a busca atual).
 * Devolve o elemento da lista e `draw(search)`.
 */
export function organizedList(ctx) {
  const el = h('div', { class: 'org-list' });
  let search = '';

  const redraw = () => draw(search);
  const toggle = (id) => {
    prefs.collapsed = prefs.collapsed.includes(id) ? prefs.collapsed.filter((x) => x !== id) : [...prefs.collapsed, id];
    savePrefs();
    redraw();
  };

  function card(source) {
    const kind = KINDS[source.kind];
    const n = usesOf(source).length;
    const folder = prefs.mode === 'kinds' ? folderOf(source.info.folder) : null;
    return h('button', {
      type: 'button', draggable: 'true', dataset: { key: source.key },
      class: ['dv-card-item', ctx.selectedKey === source.key && 'active', state.picked.has(source.key) && 'picked'],
      title: source.info.label ? `${source.title}\nNome original: ${source.name}` : source.name,
      'aria-pressed': state.picked.has(source.key) ? 'true' : null,
      onclick: (e) => {
        if (e.ctrlKey || e.metaKey) {
          state.picked.has(source.key) ? state.picked.delete(source.key) : state.picked.add(source.key);
          redraw();
          return;
        }
        state.picked.clear();
        ctx.onOpen(source.key);
      },
      oncontextmenu: (e) => { e.preventDefault(); cardMenu(source, e.clientX, e.clientY); },
      ondragstart: (e) => {
        const keys = keysFor(source);
        e.dataTransfer.setData(DND_KEYS, JSON.stringify(keys));
        e.dataTransfer.effectAllowed = 'move';
        el.classList.add('dragging');
        const ghost = h('span', { class: 'org-drag-ghost' }, icon(kind.icon, 14), keys.length > 1 ? `${keys.length} fontes` : source.title);
        document.body.append(ghost);
        e.dataTransfer.setDragImage(ghost, 12, 12);
        setTimeout(() => ghost.remove(), 0);
      },
      ondragend: () => el.classList.remove('dragging'),
    },
    h('span', { class: 'dv-card-icon', style: { '--kind': kind.color } }, icon(kind.icon, 17)),
    h('span', { class: 'dv-card-name' },
      h('strong', { class: 'ellipsis' }, source.title),
      source.info.pinned ? h('span', { class: 'org-star', title: 'Fixada no topo' }, icon('star', 12)) : null),
    h('span', { class: ['dv-state', `tone-${source.state.tone}`] }, source.state.label),
    h('span', { class: 'dv-card-meta ellipsis' },
      source.info.label ? [h('span', { class: 'mono org-original' }, source.name), ' · '] : null, source.meta),
    h('span', { class: 'dv-card-foot' },
      h('span', { class: ['dv-card-use', !n && 'none'] }, usageText(source)),
      folder ? h('span', { class: 'org-folder-pill', style: { '--folder': colorOf(folder) } }, folder.name) : null));
  }

  function cardMenu(source, x, y) {
    const keys = keysFor(source);
    const pinned = keys.every((k) => allSources().find((s) => s.key === k)?.info.pinned);
    showMenu(x, y, [
      keys.length > 1 ? { heading: `${keys.length} fontes marcadas` } : { label: 'Abrir', icon: 'eye', onSelect: () => ctx.onOpen(source.key) },
      { label: pinned ? 'Desafixar' : 'Fixar no topo', icon: 'star', onSelect: () => { unpick(); changeSources(keys, { pinned: !pinned }); } },
      { label: 'Mover para…', icon: 'folder-closed', onSelect: () => showMenu(x, y, moveItems(keys, keys.length > 1 ? null : source.info.folder, unpick)) },
      keys.length > 1 ? null : { label: 'Dar um nome de exibição', icon: 'edit', onSelect: () => ctx.onOpen(source.key, { rename: true }) },
      keys.length > 1 ? null : { label: state.picked.has(source.key) ? 'Desmarcar' : 'Marcar para mover junto', icon: 'check',
        onSelect: () => { state.picked.has(source.key) ? state.picked.delete(source.key) : state.picked.add(source.key); redraw(); } },
    ].filter(Boolean));
  }

  /** Soltar cartões aqui faz `onDrop(keys)`. A área acende enquanto algo passa por cima. */
  function dropTarget(node, onDrop) {
    node.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes(DND_KEYS)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      node.classList.add('drop-over');
    });
    node.addEventListener('dragleave', (e) => { if (!node.contains(e.relatedTarget)) node.classList.remove('drop-over'); });
    node.addEventListener('drop', (e) => {
      node.classList.remove('drop-over');
      const raw = e.dataTransfer.getData(DND_KEYS);
      if (!raw) return;
      e.preventDefault();
      unpick();
      onDrop(JSON.parse(raw));
    });
    return node;
  }

  function folderMenu(folder, x, y, index) {
    const list = folders();
    showMenu(x, y, [
      { label: 'Renomear ou mudar a cor', icon: 'edit', onSelect: () => folderDialog(folder, { count: countIn(folder.id) }) },
      { label: 'Mover para cima', icon: 'arrow-up', disabled: index === 0, onSelect: () => moveFolder(folder.id, index - 1) },
      { label: 'Mover para baixo', icon: 'arrow-down', disabled: index === list.length - 1, onSelect: () => moveFolder(folder.id, index + 1) },
      'separator',
      { label: 'Excluir pasta', icon: 'trash', danger: true, onSelect: () => removeFolder(folder) },
    ]);
  }

  const countIn = (id) => allSources().filter((s) => s.info.folder === id).length;

  async function removeFolder(folder) {
    const n = countIn(folder.id);
    const ok = !n || await confirmDialog({
      title: `Excluir a pasta ${folder.name}?`,
      message: `As ${n} fonte(s) dela voltam para "Sem pasta". Nenhuma fonte é apagada e nenhum fluxo muda.`,
      confirm: 'Excluir pasta', danger: true,
    });
    if (ok) await deleteFolder(folder.id);
  }

  /** Um grupo da lista. `folder`: pasta de verdade (tem menu e cor); `drop`: o que soltar aqui faz. */
  function group({ id, title, items, color, iconName, folder = null, index = 0, drop = null, empty = null }) {
    const closed = prefs.collapsed.includes(id);
    const head = h('div', { class: ['org-folder-title', folder && 'is-folder'], style: { '--folder': color } },
      h('button', { type: 'button', class: 'org-toggle', 'aria-expanded': String(!closed), onclick: () => toggle(id),
        title: closed ? 'Mostrar' : 'Recolher' },
      icon(closed ? 'chevron-right' : 'chevron-down', 14),
      h('span', { class: 'org-folder-icon' }, icon(iconName, 15)),
      h('strong', { class: 'ellipsis' }, title),
      h('span', { class: 'org-count' }, String(items.length))),
      folder ? button({ icon: 'more', title: `Opções da pasta ${folder.name}`, size: 'sm', variant: 'ghost',
        onClick: (e) => { const r = e.currentTarget.getBoundingClientRect(); folderMenu(folder, r.left, r.bottom + 4, index); } }) : null);
    const body = closed ? null : items.length ? items.map(card) : empty;
    const section = h('section', { class: ['org-group', closed && 'closed'], dataset: { group: id } }, head, body);
    return drop ? dropTarget(section, drop) : section;
  }

  /** Dica da primeira pasta: aparece com 5 fontes ou mais e nenhuma pasta, até a pessoa dispensar (RF-3407). */
  function tip() {
    const chips = [['file', 'extrato.xlsx'], ['query', 'Saldos do ERP'], ['api', 'Cotação do dia']];
    return h('section', { class: 'org-tip' },
      h('div', { class: 'org-tip-art', 'aria-hidden': 'true' },
        h('div', { class: 'org-tip-chips' }, chips.map(([k, label]) => h('span', { class: 'org-tip-chip', style: { '--kind': KINDS[k].color } }, icon(KINDS[k].icon, 11), label))),
        h('span', { class: 'org-tip-arrow' }, icon('arrow-down', 14)),
        h('span', { class: 'org-tip-folder' }, icon('folder-closed', 14), 'Numerário', h('b', {}, '3'))),
      h('div', { class: 'org-tip-text' },
        h('strong', {}, 'Organize por assunto'),
        h('p', {}, 'Junte arquivos, consultas e APIs do mesmo tema numa pasta. Os fluxos continuam iguais.')),
      h('div', { class: 'row' },
        button({ icon: 'plus', label: 'Criar a primeira pasta', size: 'sm', variant: 'primary', onClick: () => folderDialog() }),
        button({ label: 'Agora não', size: 'sm', variant: 'ghost', onClick: () => { prefs.tipDone = true; savePrefs(); redraw(); } })));
  }

  function toolbar() {
    const seg = (mode, label, iconName) => h('button', {
      type: 'button', role: 'radio', class: 'org-seg', 'aria-checked': String(prefs.mode === mode),
      onclick: () => { prefs.mode = mode; savePrefs(); redraw(); },
    }, icon(iconName, 13), label);
    return h('div', { class: 'org-toolbar' },
      h('div', { class: 'org-segmented', role: 'radiogroup', 'aria-label': 'Agrupar a lista' },
        seg('folders', 'Pastas', 'folder-closed'), seg('kinds', 'Tipos', 'stack')),
      h('label', { class: 'org-sort', title: 'Ordenar' }, icon('sort', 13),
        h('select', { 'aria-label': 'Ordenar fontes', onchange: (e) => { prefs.sort = e.target.value; savePrefs(); redraw(); } },
          Object.entries(SORTS).map(([k, label]) => h('option', { value: k, selected: k === prefs.sort }, label)))));
  }

  function chips(base) {
    return h('div', { class: 'org-chips', role: 'radiogroup', 'aria-label': 'Filtrar fontes' }, FILTERS.map(([k, label, ic]) => {
      const n = base.filter(TEST[k]).length;
      if (k !== 'all' && !n && state.filter !== k) return null;
      return h('button', {
        type: 'button', role: 'radio', class: ['org-chip', `org-chip-${k}`], 'aria-checked': String(state.filter === k),
        onclick: () => { state.filter = state.filter === k ? 'all' : k; redraw(); },
      }, ic ? icon(ic, 12) : null, label, h('b', {}, String(n)));
    }));
  }

  function pickedBar() {
    const keys = [...state.picked];
    return h('div', { class: 'org-picked', role: 'status' },
      h('strong', {}, `${keys.length} marcada${keys.length > 1 ? 's' : ''}`),
      button({ icon: 'folder-closed', label: 'Mover para', size: 'sm',
        onClick: (e) => { const r = e.currentTarget.getBoundingClientRect(); showMenu(r.left, r.bottom + 4, moveItems(keys, null, unpick)); } }),
      button({ icon: 'star', label: 'Fixar', size: 'sm', onClick: () => { unpick(); changeSources(keys, { pinned: true }); } }),
      button({ icon: 'x', title: 'Desmarcar todas (Esc)', size: 'sm', variant: 'ghost', onClick: () => { state.picked.clear(); redraw(); } }));
  }

  function groups(sources, narrowed) {
    const pinned = sources.filter((s) => s.info.pinned);
    const rest = state.filter === 'pinned' ? [] : sources.filter((s) => !s.info.pinned);
    const out = [];
    if (pinned.length) {
      out.push(group({ id: 'pinned', title: 'Fixadas', items: pinned, color: 'var(--warn)', iconName: 'star',
        drop: (keys) => changeSources(keys, { pinned: true }) }));
    }
    const newFolder = () => h('button', { type: 'button', class: 'org-new-folder', onclick: () => folderDialog() }, icon('plus', 14), 'Nova pasta');
    // Sem nenhuma pasta ainda, o modo Pastas continua agrupando por tipo, como antes, e oferece a primeira pasta.
    if (prefs.mode === 'kinds' || !folders().length) {
      for (const [kind, meta] of Object.entries(KINDS)) {
        const items = rest.filter((s) => s.kind === kind);
        if (items.length) out.push(group({ id: `kind:${kind}`, title: meta.title, items, color: meta.color, iconName: meta.icon }));
      }
      if (prefs.mode === 'folders' && !narrowed) out.push(newFolder());
      return out;
    }
    const known = new Set(folders().map((f) => f.id));
    folders().forEach((folder, index) => {
      const items = rest.filter((s) => s.info.folder === folder.id);
      if (narrowed && !items.length) return;
      out.push(group({
        id: folder.id, title: folder.name, items, color: colorOf(folder), iconName: 'folder-closed', folder, index,
        drop: (keys) => changeSources(keys, { folder: folder.id }),
        empty: h('div', { class: 'org-empty-drop' }, icon('download', 14), 'Arraste fontes para cá'),
      }));
    });
    const loose = rest.filter((s) => !known.has(s.info.folder));
    if (loose.length || !narrowed) {
      out.push(group({
        id: 'loose', title: 'Sem pasta', items: loose, color: 'var(--text-3)', iconName: 'stack',
        drop: (keys) => changeSources(keys, { folder: '' }),
        empty: h('div', { class: 'org-empty-drop' }, 'Tudo organizado em pastas'),
      }));
    }
    if (!narrowed) out.push(newFolder());
    return out;
  }

  function draw(text = search) {
    search = text;
    const all = allSources();
    const live = new Set(all.map((s) => s.key));
    for (const key of state.picked) if (!live.has(key)) state.picked.delete(key);
    const base = all.filter((s) => matches(s, search));
    if (!base.some(TEST[state.filter]) && state.filter !== 'all') state.filter = 'all';
    const sources = base.filter(TEST[state.filter]).sort(ORDER[prefs.sort]);
    const narrowed = Boolean(search.trim()) || state.filter !== 'all';
    const showTip = prefs.mode === 'folders' && !folders().length && all.length >= 5 && !prefs.tipDone && !narrowed;
    el.replaceChildren(...[
      toolbar(),
      chips(base),
      state.picked.size ? pickedBar() : null,
      showTip ? tip() : null,
      h('div', { class: 'dv-groups' }, sources.length ? groups(sources, narrowed) : h('p', { class: 'muted pad' }, 'Nenhuma fonte encontrada.')),
    ].filter(Boolean));
  }

  el.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.picked.size) { state.picked.clear(); redraw(); }
  });
  return { el, draw };
}
