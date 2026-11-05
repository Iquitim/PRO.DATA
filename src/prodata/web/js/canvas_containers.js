// Caixas de organização no canvas: desenho, renomear, soltar e o menu delas.

import {
  CONTAINER_COLORS,
  addContainer,
  fitContainer,
  nodesInside,
  removeContainer,
  removeContainerWithNodes,
  setContainerEnabled,
  updateContainer,
} from './actions.js';
import { NODE_W, nodeHeight } from './canvas_geometry.js';
import { els, state, viewportCenter } from './canvas_state.js';
import { copySelection, cutSelection } from './clipboard.js';
import { clear, h } from './dom.js';
import { icon } from './icons.js';
import { select, store } from './store.js';
import { showMenu } from './ui.js';

export function renderContainers() {
  clear(els.containers);
  for (const c of store.workflow.containers || []) {
    els.containers.append(h('div', {
      class: ['container-box', store.selection.containerId === c.id && 'selected', c.disabled && 'off'],
      dataset: { container: c.id },
      style: {
        left: `${c.x}px`, top: `${c.y}px`, width: `${c.width}px`, height: `${c.height}px`,
        '--container-color': c.color,
        '--container-fill': `${Math.round((c.opacity ?? 0.05) * 100)}%`,
      },
    },
    h('div', { class: 'container-title', title: 'Arraste para mover a etapa e seus nós · duplo clique para renomear' },
      h('span', { class: 'container-dot' }), h('span', { class: 'container-name' }, c.title),
      c.disabled ? h('span', { class: 'container-state' }, 'desligada') : null,
      h('button', {
        type: 'button', class: ['container-toggle', !c.disabled && 'on'], role: 'switch', 'aria-checked': String(!c.disabled),
        title: c.disabled ? 'Ligar caixa (reativa os nós de dentro)' : 'Desligar caixa (desativa os nós de dentro)',
        onclick: (ev) => { ev.stopPropagation(); setContainerEnabled(c.id, Boolean(c.disabled), NODE_W); },
      })),
    c.description ? h('div', { class: 'container-desc' }, c.description) : null,
    h('div', { class: 'container-resize', title: 'Arraste para redimensionar' })));
  }
}

export function placeContainerEl(c) {
  const el = els.containers.querySelector(`[data-container="${c.id}"]`);
  if (el) Object.assign(el.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.width}px`, height: `${c.height}px` });
}

/** Troca o título por um campo de texto; Enter/sair confirma, Esc cancela. */
export function renameContainer(id) {
  const c = store.workflow.containers.find((x) => x.id === id);
  const label = els.containers.querySelector(`[data-container="${id}"] .container-name`);
  if (!c || !label) return;
  const input = h('input', { class: 'container-rename', value: c.title, 'aria-label': 'Nome da etapa' });
  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    if (save && title && title !== c.title) updateContainer(id, { title });
    else state.render({ containers: true });
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish(true);
    if (e.key === 'Escape') finish(false);
    e.stopPropagation();
  });
  input.addEventListener('blur', () => finish(true));
  input.addEventListener('pointerdown', (e) => e.stopPropagation());
  label.replaceWith(input);
  input.focus();
  input.select();
}

/** Caixa solta da paleta: se cair sobre nós, envolve esses nós; senão nasce com tamanho padrão. */
export function dropContainer(world) {
  // Só os nós bem perto do ponto de soltura (sob o cursor ou vizinhos imediatos na mesma linha).
  const probe = { x: world.x - NODE_W, y: world.y - 40, width: NODE_W * 2, height: 80 };
  const hits = nodesInside(probe, NODE_W);
  const created = addContainer(world.x - 220, world.y - 120);
  if (hits.length) fitContainer(created.id, NODE_W, nodeHeight, hits);
  requestAnimationFrame(() => renameContainer(created.id));
}

export function addContainerAtCenter() {
  const c = viewportCenter();
  const created = addContainer(c.x - 220, c.y - 120);
  requestAnimationFrame(() => renameContainer(created.id));
}

export function containerMenu(id, x, y, pasteItem) {
  const c = store.workflow.containers.find((k) => k.id === id);
  select(null, null, id);
  showMenu(x, y, [
    { label: 'Renomear', icon: 'edit', onSelect: () => renameContainer(id) },
    { label: 'Ajustar aos nós de dentro', icon: 'fit', onSelect: () => fitContainer(id, NODE_W, nodeHeight) },
    { label: c.disabled ? 'Ligar etapa' : 'Desligar etapa', icon: 'power', onSelect: () => setContainerEnabled(id, Boolean(c.disabled), NODE_W) },
    'separator',
    { label: 'Copiar etapa', icon: 'copy', shortcut: 'Ctrl+C', onSelect: () => copySelection({ nodeWidth: NODE_W }) },
    { label: 'Recortar etapa', icon: 'scissors', shortcut: 'Ctrl+X', onSelect: () => cutSelection({ nodeWidth: NODE_W }) },
    pasteItem,
    'separator',
    ...CONTAINER_COLORS.map(([color, name]) => ({
      label: `Cor: ${name}`, icon: c.color === color ? 'check' : 'palette', onSelect: () => updateContainer(id, { color }),
    })),
    'separator',
    { label: 'Excluir etapa (mantém as caixas)', icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeContainer(id) },
    { label: 'Excluir etapa e caixas de dentro', icon: 'trash', danger: true, onSelect: () => removeContainerWithNodes(id, NODE_W) },
  ]);
}
