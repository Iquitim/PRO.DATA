// Paleta de ferramentas: busca, grupos por categoria, clique ou arraste para adicionar.

import { addNode } from './actions.js';
import { addContainerAtCenter, DND_CONTAINER, DND_TOOL, viewportCenter } from './canvas.js';
import { clear, h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { store } from './store.js';

const collapsed = new Set(storage('prodata.palette.collapsed', []));

function signature(tool) {
  const ins = tool.inputs.map((p) => p.label).join('·');
  const outs = tool.outputs.map((p) => p.label).join('·');
  return ins ? `${ins} → ${outs}` : `→ ${outs}`;
}

function toolItem(tool) {
  return h('button', {
    type: 'button',
    class: 'tool-item',
    draggable: 'true',
    dataset: { category: tool.category },
    title: `${tool.description}\n\nClique para adicionar ou arraste para o canvas (solte sobre um fio para inserir no meio).`,
    ondragstart: (e) => {
      e.dataTransfer.setData(DND_TOOL, tool.type);
      e.dataTransfer.effectAllowed = 'copy';
    },
    onclick: () => {
      const c = viewportCenter();
      addNode(tool.type, c.x - 80 + (Math.random() * 40 - 20), c.y - 28 + (Math.random() * 40 - 20));
    },
  },
  h('span', { class: 'tool-icon' }, icon(tool.icon, 16)),
  h('span', { class: 'tool-name' }, tool.name),
  h('span', { class: 'tool-sig' }, signature(tool)));
}

export function renderPalette(root) {
  const search = h('input', {
    class: 'input input-search', type: 'search', placeholder: 'Buscar ferramenta', 'aria-label': 'Buscar ferramenta',
  });
  const list = h('div', { class: 'palette-list' });

  // Grupo recolhível, igual para Organização e para as categorias de ferramentas.
  const group = (id, label, items, q) => {
    const open = q || !collapsed.has(id);
    return h('section', { class: 'palette-group', dataset: { category: id } },
      h('button', {
        type: 'button',
        class: 'palette-group-header',
        'aria-expanded': String(Boolean(open)),
        onclick: () => {
          if (collapsed.has(id)) collapsed.delete(id); else collapsed.add(id);
          persist('prodata.palette.collapsed', [...collapsed]);
          draw();
        },
      }, icon(open ? 'chevron-down' : 'chevron-right', 14), h('span', { class: 'cat-dot' }), label,
      h('span', { class: 'count' }, items.length)),
      open ? h('div', { class: 'palette-tools' }, items) : null);
  };

  const draw = () => {
    const q = search.value.trim().toLowerCase();
    clear(list);
    if (!q || ORG_KEYWORDS.includes(q)) list.append(group('org', 'Organização', [organizationItem()], q));
    for (const cat of store.catalog.categories) {
      const tools = store.catalog.tools.filter((t) => t.category === cat.id && !t.hidden
        && (!q || `${t.name} ${t.description} ${t.type}`.toLowerCase().includes(q)));
      if (tools.length) list.append(group(cat.id, cat.label, tools.map(toolItem), q));
    }
    if (!list.childElementCount) list.append(h('p', { class: 'muted pad' }, 'Nenhuma ferramenta encontrada.'));
  };

  search.addEventListener('input', draw);
  root.replaceChildren(h('div', { class: 'panel-search' }, search), list);
  draw();
}

const ORG_KEYWORDS = 'caixa de organização organizacao contêiner conteiner etapa grupo';

/** Caixa de organização (contêiner de etapa): não é ferramenta de dados, mas aparece como item da paleta. */
function organizationItem() {
  return h('button', {
    type: 'button',
    class: 'tool-item',
    draggable: 'true',
    dataset: { category: 'org' },
    title: 'Caixa para agrupar etapas do fluxo (atalho G).\n\nClique para criar no centro ou arraste para o canvas; solta sobre nós, ela os envolve.',
    ondragstart: (e) => {
      e.dataTransfer.setData(DND_CONTAINER, '1');
      e.dataTransfer.effectAllowed = 'copy';
    },
    onclick: addContainerAtCenter,
  },
  h('span', { class: 'tool-icon' }, icon('group', 16)),
  h('span', { class: 'tool-name' }, 'Caixa de organização'),
  h('span', { class: 'tool-sig' }, 'etapa'));
}
