// Painel "Dados" do Designer (spec 028, RF-2806): só buscar e arrastar fontes ao canvas.
// Cadastrar, editar e excluir ficam na vista Dados; cada fonte tem o atalho "Abrir em Dados".

import { addApiNode } from './apis.js';
import { DND_DATASET } from './canvas.js';
import { addQueryNode } from './connections.js';
import { allSources, KINDS, matches } from './data_sources.js';
import { addInputNode } from './datasets.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';
import { on } from './store.js';

const PANEL_KINDS = ['file', 'query', 'api'];

function item(source, openInData) {
  const kind = KINDS[source.kind];
  const add = () => (source.kind === 'file' ? addInputNode(source.id) : source.kind === 'query' ? addQueryNode(source.raw) : addApiNode(source.raw));
  return h('div', {
    class: 'dataset-item', draggable: source.draggable ? 'true' : 'false',
    title: source.draggable ? 'Arraste para o canvas para criar um Input Data' : source.loop ? 'Use o + para criar um API Loop' : source.state.label,
    ondragstart: (e) => {
      if (!source.draggable) { e.preventDefault(); return; }
      e.dataTransfer.setData(DND_DATASET, source.dragValue);
      e.dataTransfer.effectAllowed = 'copy';
    },
  },
  h('span', { class: 'dataset-icon', style: { color: kind.color } }, icon(source.loop ? 'repeat' : kind.icon, 16)),
  h('button', { type: 'button', class: 'dataset-main', title: 'Abrir em Dados', onclick: () => openInData(source.key) },
    h('span', { class: 'dataset-name' }, source.name),
    h('span', { class: 'dataset-meta' }, source.meta)),
  h('div', { class: 'dataset-actions' },
    button({ icon: 'plus', title: source.loop ? 'Adicionar API Loop ao fluxo' : 'Adicionar ao fluxo', size: 'sm', variant: 'ghost', disabled: source.state.tone === 'err', onClick: add }),
    button({ icon: 'chevron-right', title: 'Abrir em Dados', size: 'sm', variant: 'ghost', onClick: () => openInData(source.key) })));
}

/** `openInData(key)`: leva à vista Dados com a fonte escolhida. */
export function renderSourcesPanel(root, { openInData }) {
  let query = '';
  const list = h('div', { class: 'dataset-list' });
  const draw = () => {
    const sources = allSources().filter((s) => PANEL_KINDS.includes(s.kind) && matches(s, query));
    list.replaceChildren(...(sources.length
      ? PANEL_KINDS.flatMap((kind) => {
        const items = sources.filter((s) => s.kind === kind);
        return items.length ? [h('div', { class: 'panel-subtitle' }, KINDS[kind].title), ...items.map((s) => item(s, openInData))] : [];
      })
      : [h('p', { class: 'muted pad' }, query ? 'Nenhuma fonte encontrada.' : 'Nenhuma fonte ainda. Cadastre na vista Dados.')]));
  };
  for (const event of ['datasets', 'queries', 'apis', 'connections']) on(event, draw);
  root.replaceChildren(
    h('div', { class: 'pad stack-sm' },
      h('input', { type: 'search', class: 'input input-search', placeholder: 'Buscar fonte', 'aria-label': 'Buscar fonte', oninput: (e) => { query = e.target.value; draw(); } }),
      button({ icon: 'database', label: 'Gerenciar em Dados', size: 'sm', onClick: () => openInData(null) }),
      h('p', { class: 'field-help' }, 'Arraste uma fonte para o canvas, ou solte um arquivo do computador direto nele.')),
    list);
  draw();
}
