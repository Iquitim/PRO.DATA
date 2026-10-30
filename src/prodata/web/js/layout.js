// Painéis reposicionáveis (spec 006): três posições, três painéis, cada posição com no máximo um.
// Os painéis são movidos com appendChild, então mantêm estado e listeners.

import { $, button, h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { emit } from './store.js';
import { showMenu } from './ui.js';

const KEY = 'prodata.panels.v1';
const DENSITY_KEY = 'prodata.density';
const DENSITIES = { auto: 'Automática (compacta em telas menores)', comfortable: 'Confortável', compact: 'Compacta' };
let density = storage(DENSITY_KEY, 'auto');

/** Interface compacta em telas menores (spec 016): fontes, barras e espaçamentos menores. */
export function applyDensity() {
  const small = innerWidth < 1440 || innerHeight < 800;
  const compact = density === 'compact' || (density === 'auto' && small);
  const root = document.documentElement;
  if (root.classList.contains('compact') === compact) return;
  root.classList.toggle('compact', compact);
  emit('density', compact);
}

function setDensity(value) {
  density = value;
  persist(DENSITY_KEY, value);
  applyDensity();
}
const DND_PANEL = 'application/x-prodata-panel';

export const PANELS = {
  explorer: { title: 'Ferramentas e configuração', el: '#leftPanel' },
  results: { title: 'Resultados', el: '#results' },
  insights: { title: 'Gráficos e resumos', el: '#insights' },
};
const SLOTS = { left: 'Esquerda', right: 'Direita', bottom: 'Embaixo' };
const DEFAULT = { left: 'explorer', right: 'results', bottom: 'insights' };

let state = load();

function load() {
  const saved = storage(KEY, DEFAULT);
  const clean = {};
  const used = new Set();
  for (const slot of Object.keys(SLOTS)) {
    const id = saved?.[slot];
    clean[slot] = id in PANELS && !used.has(id) ? id : null;
    if (clean[slot]) used.add(clean[slot]);
  }
  return clean;
}

export const slotOf = (id) => Object.keys(SLOTS).find((s) => state[s] === id) || null;
export const isVisible = (id) => slotOf(id) !== null;

// Referências fixas aos painéis. Não usar querySelector depois: um painel fora do
// documento (entre uma troca e outra) não seria encontrado e se perderia.
const elements = {};

function apply() {
  // Cada painel vai para a sua posição ou para o depósito oculto. Só move o que mudou
  // (mover um elemento zera a rolagem dele); como todos são processados, cada posição
  // termina com exatamente um painel.
  for (const [id, el] of Object.entries(elements)) {
    const slot = slotOf(id);
    const target = slot ? $(`#slot-${slot}`) : $('#panelStore');
    if (el.parentElement !== target) target.append(el);
  }
  for (const slot of Object.keys(SLOTS)) document.body.classList.toggle(`slot-${slot}-empty`, !state[slot]);
  persist(KEY, state);
  emit('layout', { ...state });
}

/** Coloca o painel na posição; se ocupada, troca com o painel que estava lá. */
export function movePanel(id, slot) {
  const from = slotOf(id);
  if (from === slot) return;
  const displaced = state[slot];
  state[slot] = id;
  if (from) state[from] = displaced;
  apply();
}

export function hidePanel(id) {
  const slot = slotOf(id);
  if (!slot) return;
  state[slot] = null;
  apply();
}

/** Reexibe na posição padrão do painel, ou na primeira livre, ou desloca o da posição padrão. */
export function showPanel(id) {
  if (isVisible(id)) return;
  const home = Object.keys(DEFAULT).find((s) => DEFAULT[s] === id);
  const free = Object.keys(SLOTS).find((s) => !state[s]);
  state[!state[home] ? home : free || home] = id;
  apply();
}

export function togglePanel(id) {
  if (isVisible(id)) hidePanel(id);
  else showPanel(id);
}

export function resetLayout() {
  state = { ...DEFAULT };
  apply();
}

// ------------------------------------------------------------------ arraste

function buildDropTargets() {
  const layer = $('#panelDropTargets');
  layer.replaceChildren(...Object.entries(SLOTS).map(([slot, label]) => {
    const zone = h('div', { class: 'drop-zone', dataset: { slot } }, label, h('span', {}));
    zone.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes(DND_PANEL)) return;
      e.preventDefault();
      zone.classList.add('over');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('over');
      movePanel(e.dataTransfer.getData(DND_PANEL), slot);
    });
    return zone;
  }));
}

function describeTargets(dragged) {
  for (const zone of document.querySelectorAll('.drop-zone')) {
    const occupant = state[zone.dataset.slot];
    zone.querySelector('span').textContent = !occupant ? 'livre'
      : occupant === dragged ? 'posição atual' : `troca com ${PANELS[occupant].title}`;
  }
}

/** Alça de arraste + menu, inseridos no cabeçalho de cada painel. */
export function panelControls(id) {
  const grip = h('button', {
    type: 'button', class: 'btn btn-icon btn-ghost btn-sm panel-grip', draggable: 'true',
    title: 'Arraste para mover o painel', 'aria-label': `Mover painel ${PANELS[id].title}`,
    ondragstart: (e) => {
      e.dataTransfer.setData(DND_PANEL, id);
      e.dataTransfer.effectAllowed = 'move';
      describeTargets(id);
      // Mostra os alvos depois do início do arraste (alterar o DOM no dragstart cancela o gesto em alguns navegadores).
      requestAnimationFrame(() => document.body.classList.add('panel-dragging'));
    },
    ondragend: () => document.body.classList.remove('panel-dragging'),
  }, icon('grip', 14));
  const menu = button({
    icon: 'more', title: 'Opções do painel', size: 'sm', variant: 'ghost',
    onClick: (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      const here = slotOf(id);
      showMenu(r.left - 160, r.bottom + 4, [
        ...Object.entries(SLOTS).filter(([s]) => s !== here)
          .map(([s, label]) => ({ label: `Mover para: ${label}`, icon: 'panel', onSelect: () => movePanel(id, s) })),
        'separator',
        { label: 'Ocultar painel', icon: 'x', onSelect: () => hidePanel(id) },
      ]);
    },
  });
  return h('div', { class: 'panel-controls' }, grip, menu);
}

/** Menu "Painéis" da barra superior. */
export function openPanelsMenu(anchor) {
  const r = anchor.getBoundingClientRect();
  showMenu(r.left, r.bottom + 4, [
    ...Object.entries(PANELS).map(([id, p]) => ({
      label: isVisible(id) ? `${p.title} · ${SLOTS[slotOf(id)].toLowerCase()}` : `${p.title} · oculto`,
      icon: isVisible(id) ? 'check' : null,
      onSelect: () => togglePanel(id),
    })),
    'separator',
    ...Object.entries(DENSITIES).map(([value, label]) => ({
      label: `Densidade: ${label}`, icon: density === value ? 'check' : null, onSelect: () => setDensity(value),
    })),
    'separator',
    { label: 'Restaurar layout padrão', icon: 'refresh', onSelect: resetLayout },
  ]);
}

export function initLayout() {
  applyDensity();
  window.addEventListener('resize', applyDensity);
  for (const [id, p] of Object.entries(PANELS)) elements[id] = $(p.el);
  buildDropTargets();
  apply();
}
