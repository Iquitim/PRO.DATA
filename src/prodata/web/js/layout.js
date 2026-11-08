// Painéis reposicionáveis (spec 006): três posições, três painéis, cada posição com no máximo um.
// Os painéis são movidos com appendChild, então mantêm estado e listeners.

import { $, button, h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { emit, on, store } from './store.js';
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
const COLLAPSED_KEY = 'prodata.panels.recolhidos';
const SMALL_WINDOW = 1280;

export const PANELS = {
  explorer: { title: 'Ferramentas e configuração', el: '#leftPanel' },
  results: { title: 'Resultado', el: '#results' },
  insights: { title: 'Gráficos e resumos', el: '#insights' },
};
const SLOTS = { left: 'Esquerda', right: 'Direita', bottom: 'Embaixo' };
const DEFAULT = { left: 'explorer', right: 'results', bottom: 'insights' };

// Painéis recolhidos em faixa (spec 029, RF-2902). `auto`: recolhido só por a janela ser pequena: abre sozinho
// ao clicar numa caixa. Quem recolheu com a própria mão não é contrariado.
const collapsed = loadCollapsed();
let state = load();
// Modo foco (RF-2901): o arranjo de antes; enquanto houver, nada é gravado, e reabrir o programa volta ao normal.
let beforeFocus = null;

function loadCollapsed() {
  const saved = storage(COLLAPSED_KEY, null);
  if (saved) return { ids: new Set(saved.ids || []), auto: new Set(saved.auto || []) };
  const firstTimeSmall = storage(KEY, null) === null && innerWidth < SMALL_WINDOW;
  const ids = firstTimeSmall ? ['results', 'insights'] : [];
  return { ids: new Set(ids), auto: new Set(ids) };
}

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
  drawStrips();
  if (!beforeFocus) {
    persist(KEY, state);
    persist(COLLAPSED_KEY, { ids: [...collapsed.ids], auto: [...collapsed.auto] });
  }
  emit('layout', { ...state });
}

function stripFor(slot, id) {
  const count = id === 'insights' ? store.execution?.bi_widgets?.length : 0;
  const { title } = PANELS[id];
  return h('button', {
    type: 'button', class: ['panel-strip', slot !== 'bottom' && 'vertical'], title: `Abrir ${title}`, 'aria-label': `Abrir ${title}`,
    onclick: () => expandPanel(id),
  }, icon('chevron-right', 14), h('strong', {}, title), count ? h('small', {}, String(count)) : null,
  id === 'results' && collapsed.auto.has(id) ? h('small', {}, 'clique numa caixa para abrir') : null);
}

function drawStrips() {
  for (const slot of Object.keys(SLOTS)) {
    const id = state[slot];
    const closed = Boolean(id && collapsed.ids.has(id));
    const host = $(`#slot-${slot}`);
    host.querySelector(':scope > .panel-strip')?.remove();
    document.body.classList.toggle(`slot-${slot}-collapsed`, closed);
    if (closed) host.append(stripFor(slot, id));
  }
}

export function collapsePanel(id) {
  collapsed.ids.add(id);
  collapsed.auto.delete(id);
  apply();
}

export function expandPanel(id) {
  collapsed.ids.delete(id);
  collapsed.auto.delete(id);
  apply();
}

/** Clique numa caixa ou porta: abre o resultado que só estava recolhido por causa da janela pequena. */
export function openResultsOnClick() {
  if (collapsed.auto.has('results')) expandPanel('results');
}

/** Pedido explícito ("Ver resultados", "Configurar"): sai do foco e deixa o painel à vista. */
export function revealPanel(id) {
  leaveFocus();
  showPanel(id);
  if (collapsed.ids.has(id)) expandPanel(id);
}

export const inFocus = () => beforeFocus !== null;

export function enterFocus() {
  if (beforeFocus) return;
  beforeFocus = { ...state };
  for (const slot of Object.keys(SLOTS)) state[slot] = null;
  apply();
  emit('focus', true);
}

/** Devolve os painéis como estavam. Retorna false se não estava em foco. */
export function leaveFocus() {
  if (!beforeFocus) return false;
  state = beforeFocus;
  beforeFocus = null;
  apply();
  emit('focus', false);
  return true;
}

/** Coloca o painel na posição; se ocupada, troca com o painel que estava lá. */
export function movePanel(id, slot) {
  leaveFocus();
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
  leaveFocus();
  if (isVisible(id)) return;
  const home = Object.keys(DEFAULT).find((s) => DEFAULT[s] === id);
  const free = Object.keys(SLOTS).find((s) => !state[s]);
  state[!state[home] ? home : free || home] = id;
  apply();
}

export function togglePanel(id) {
  if (leaveFocus()) { revealPanel(id); return; }
  if (isVisible(id)) hidePanel(id);
  else showPanel(id);
}

export function resetLayout() {
  beforeFocus = null;
  collapsed.ids.clear();
  collapsed.auto.clear();
  emit('focus', false);
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
        { label: 'Recolher em faixa', icon: 'chevron-right', onSelect: () => collapsePanel(id) },
        { label: 'Ocultar painel', icon: 'x', onSelect: () => hidePanel(id) },
      ]);
    },
  });
  return h('div', { class: 'panel-controls' }, grip, menu);
}

const DENSITY_NAMES = { auto: 'automática', comfortable: 'confortável', compact: 'compacta' };

/** Clicar passa para a próxima densidade. */
export function densityMenuItem() {
  const order = Object.keys(DENSITIES);
  return {
    label: `Densidade: ${DENSITY_NAMES[density]}`, icon: 'columns', title: DENSITIES[density],
    onSelect: () => setDensity(order[(order.indexOf(density) + 1) % order.length]),
  };
}

/** Os painéis no menu Exibir: mostrar e ocultar cada um. */
export function panelMenuItems() {
  return Object.entries(PANELS).map(([id, p]) => ({
      label: isVisible(id) ? `${p.title} · ${SLOTS[slotOf(id)].toLowerCase()}${collapsed.ids.has(id) ? ' (recolhido)' : ''}` : `${p.title} · oculto`,
      icon: isVisible(id) ? 'check' : null,
      onSelect: () => togglePanel(id),
  }));
}

export function initLayout() {
  applyDensity();
  window.addEventListener('resize', applyDensity);
  for (const [id, p] of Object.entries(PANELS)) elements[id] = $(p.el);
  buildDropTargets();
  apply();
  on('execution', drawStrips); // o número de visuais na faixa dos gráficos
}
