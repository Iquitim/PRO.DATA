// Canvas do workflow: render incremental de nós e fios + interações por pointer events.

import {
  addNode, connect, connectionError, duplicateNode, firstInput, removeEdge, removeNodes, spliceIntoEdge,
  toggleDisabled,
  addContainer, CONTAINER_COLORS, disabledContainerAt, fitContainer, nodesInside, removeContainer,
  removeContainerWithNodes, setContainerEnabled, updateContainer,
  alignNodes, distributeNodes, moveOutOfContainer, setCachePoint, setDisabled, wrapInContainer,
} from './actions.js';
import { copySelection, cutSelection, hasClipboard, paste } from './clipboard.js';
import { $, clear, fmt, h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import {
  checkpoint, commit, emit, inspect, isSelected, node, nodeResult, on, select, selectedIds, selectMany, sourceLabel,
  store, toggleSelected, toolOf,
} from './store.js';
import { closeMenu, showMenu, toast } from './ui.js';

export const NODE_W = 188;
const NODE_MIN_H = 56;
const PORT_GAP = 18;
const MIN_ZOOM = 0.25;
const FIT_MIN_ZOOM = 1; // ao abrir, legibilidade vale mais que ver tudo (RF-407)
const MAX_ZOOM = 2;
const DRAG_THRESHOLD = 4;

const view = { x: 40, y: 30, zoom: 1 };
const els = {};
const nodeEls = new Map(); // id -> { el, key }
let gesture = null;
let lastTitleClick = { id: null, at: 0 };
let lastPointer = null; // posição do cursor sobre o canvas (para colar no lugar certo)
let handlers = {};

// ------------------------------------------------------------------ geometria

/** Altura do cartão: cresce com o número de portas para que nenhuma se sobreponha. */
export function nodeHeight(n) {
  const spec = toolOf(n);
  const ports = Math.max(spec?.inputs.length || 0, spec?.outputs.length || 0);
  return Math.max(NODE_MIN_H, (ports + 1) * PORT_GAP);
}

function portPoint(n, portId, output) {
  const ports = (output ? toolOf(n)?.outputs : toolOf(n)?.inputs) || [];
  const idx = Math.max(0, ports.findIndex((p) => p.id === portId));
  return { x: n.x + (output ? NODE_W : 0), y: n.y + (nodeHeight(n) * (idx + 1)) / (ports.length + 1) };
}

function curve(a, b) {
  const dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

function curveMid(a, b) {
  const dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
  // Ponto t=0.5 da Bézier cúbica: (P0 + 3P1 + 3P2 + P3) / 8
  return {
    x: (a.x + 3 * (a.x + dx) + 3 * (b.x - dx) + b.x) / 8,
    y: (a.y + 3 * a.y + 3 * b.y + b.y) / 8,
  };
}

export function toWorld(clientX, clientY) {
  const r = els.viewport.getBoundingClientRect();
  return { x: (clientX - r.left - view.x) / view.zoom, y: (clientY - r.top - view.y) / view.zoom };
}

export function viewportCenter() {
  const r = els.viewport.getBoundingClientRect();
  return toWorld(r.left + r.width / 2, r.top + r.height / 2);
}

// ------------------------------------------------------------------ view

function applyView() {
  els.world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
  const grid = 20 * view.zoom;
  els.viewport.style.backgroundSize = `${grid}px ${grid}px`;
  els.viewport.style.backgroundPosition = `${view.x}px ${view.y}px`;
  emit('zoom', view.zoom);
}

export function zoomBy(factor, clientX, clientY) {
  const r = els.viewport.getBoundingClientRect();
  const cx = clientX ?? r.left + r.width / 2;
  const cy = clientY ?? r.top + r.height / 2;
  const before = toWorld(cx, cy);
  view.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom * factor));
  view.x = cx - r.left - before.x * view.zoom;
  view.y = cy - r.top - before.y * view.zoom;
  applyView();
}

/** Ajusta à tela. `minZoom` evita que fluxos grandes abram ilegíveis (RF-407). */
export function fitView({ minZoom = MIN_ZOOM } = {}) {
  const wf = store.workflow;
  if (!wf?.nodes.length) {
    Object.assign(view, { x: 40, y: 30, zoom: 1 });
    applyView();
    return;
  }
  const boxes = [
    ...wf.nodes.map((n) => ({ x1: n.x - 20, y1: n.y - 10, x2: n.x + NODE_W + 20, y2: n.y + nodeHeight(n) + 10 })),
    ...(wf.containers || []).map((c) => ({ x1: c.x, y1: c.y, x2: c.x + c.width, y2: c.y + c.height })),
  ];
  const x1 = Math.min(...boxes.map((b) => b.x1));
  const y1 = Math.min(...boxes.map((b) => b.y1));
  const x2 = Math.max(...boxes.map((b) => b.x2));
  const y2 = Math.max(...boxes.map((b) => b.y2));
  const r = els.viewport.getBoundingClientRect();
  const pad = 40;
  view.zoom = Math.min(1.1, Math.max(minZoom, Math.min((r.width - pad * 2) / (x2 - x1), (r.height - pad * 2) / (y2 - y1))));
  // Se não couber inteiro, ancora no canto superior esquerdo (início do fluxo).
  const fitsX = (x2 - x1) * view.zoom <= r.width - pad;
  const fitsY = (y2 - y1) * view.zoom <= r.height - pad;
  view.x = fitsX ? (r.width - (x2 - x1) * view.zoom) / 2 - x1 * view.zoom : pad / 2 - x1 * view.zoom;
  view.y = fitsY ? (r.height - (y2 - y1) * view.zoom) / 2 - y1 * view.zoom : pad / 2 - y1 * view.zoom;
  applyView();
}

// ------------------------------------------------------------------ render

function statusOf(n) {
  if (n.disabled) return 'disabled';
  const res = nodeResult(n.id);
  if (store.pending.has(n.id) && res?.status !== 'error') return 'pending';
  if (res?.extra?.held) return 'held'; // antes de um ponto de cache: não precisou executar
  return res?.status || 'pending';
}

const STATUS_TITLES = {
  executed: 'Executado', cached: 'Executado (cache)', error: 'Erro', skipped: 'Não executado',
  disabled: 'Desabilitado', pending: 'Alterado desde a última execução',
  held: 'Em cache: o ponto de cache adiante já tem o resultado',
};

function portEl(n, port, output, count) {
  const labelled = count > 1 || port.kind === 'model' || !['in', 'out'].includes(port.id);
  const top = (nodeHeight(n) * (port.index + 1)) / (count + 1);
  return h('div', {
    class: ['port', output ? 'out' : 'in', port.kind === 'model' && 'model',
      (output ? !store.inspect.via && store.inspect.nodeId === n.id && store.inspect.anchor === port.id
        : store.inspect.via?.nodeId === n.id && store.inspect.via?.port === port.id) && 'inspected'],
    style: { top: `${top}px` },
    dataset: { port: port.id, node: n.id },
    title: `${output ? 'Saída' : 'Entrada'} [${port.label}] · ${port.title}\n${output
      ? 'Clique para ver os dados que saem · arraste para conectar' : 'Clique para ver os dados que chegam'}`,
  }, labelled ? port.label : '');
}

function buildNode(n) {
  const spec = toolOf(n);
  const res = nodeResult(n.id);
  const status = statusOf(n);
  const inputs = (spec?.inputs || []).map((p, index) => ({ ...p, index }));
  const outputs = (spec?.outputs || []).map((p, index) => ({ ...p, index }));
  return h('div', {
    class: ['node', `status-${status}`,
      isSelected(n.id) && 'selected',
      n.cache_point && 'cache-point',
      !store.inspect.via && store.inspect.nodeId === n.id && 'inspected'],
    dataset: { id: n.id, category: spec?.category || 'prep' },
    style: { transform: `translate(${n.x}px, ${n.y}px)`, width: `${NODE_W}px`, height: `${nodeHeight(n)}px` },
  },
  h('div', {
    class: 'node-card',
    title: [n.label || spec?.name, res?.annotation, res?.error].filter(Boolean).join('\n'),
  },
  h('span', { class: 'node-icon' }, icon(spec?.icon || 'info', 16)),
  h('span', { class: 'node-text' },
    h('span', { class: 'node-label' }, n.label || spec?.name || n.type),
    h('span', { class: 'node-annot' }, status === 'error' ? 'Erro — veja a configuração' : res?.annotation || spec?.name || '')),
  h('span', { class: 'node-status', title: STATUS_TITLES[status] })),
  n.cache_point ? h('span', {
    class: 'node-cache', title: res?.extra?.frozen_at
      ? `Ponto de cache · resultado guardado em ${new Date(res.extra.frozen_at).toLocaleString('pt-BR')}`
      : 'Ponto de cache · execute para guardar o resultado',
  }, icon('database', 11), 'cache') : null,
  h('button', {
    type: 'button', class: 'node-delete', title: 'Excluir caixa (Delete)', 'aria-label': `Excluir ${n.label || spec?.name}`,
    onclick: (ev) => { ev.stopPropagation(); removeNodes([n.id]); },
  }, icon('trash', 13)),
  inputs.map((p) => portEl(n, p, false, inputs.length)),
  outputs.map((p) => portEl(n, p, true, outputs.length)));
}

function nodeKey(n) {
  const res = nodeResult(n.id);
  return JSON.stringify([n.type, n.label, n.disabled, n.cache_point, statusOf(n), res?.annotation, res?.error,
    res?.extra?.frozen_at, isSelected(n.id), !store.inspect.via && store.inspect.nodeId === n.id && store.inspect.anchor,
    store.inspect.via?.nodeId === n.id && store.inspect.via.port]);
}

function renderNodes() {
  const wf = store.workflow;
  const alive = new Set();
  for (const n of wf.nodes) {
    alive.add(n.id);
    const key = nodeKey(n);
    const current = nodeEls.get(n.id);
    if (current && current.key === key) {
      current.el.style.transform = `translate(${n.x}px, ${n.y}px)`;
      continue;
    }
    const el = buildNode(n);
    if (current) current.el.replaceWith(el);
    else els.nodes.append(el);
    nodeEls.set(n.id, { el, key });
  }
  for (const [id, { el }] of nodeEls) {
    if (!alive.has(id)) {
      el.remove();
      nodeEls.delete(id);
    }
  }
}

function renderEdges() {
  const wf = store.workflow;
  const byId = new Map(wf.nodes.map((n) => [n.id, n]));
  const paths = [];
  const pills = [];
  for (const e of wf.edges) {
    const s = byId.get(e.source);
    const t = byId.get(e.target);
    if (!s || !t) continue;
    const a = portPoint(s, e.sourceHandle, true);
    const b = portPoint(t, e.targetHandle, false);
    const d = curve(a, b);
    const tele = store.execution?.edge_telemetry?.[e.id];
    const fresh = tele && !store.pending.has(e.source);
    const model = toolOf(s)?.outputs.find((p) => p.id === e.sourceHandle)?.kind === 'model';
    paths.push(`<g class="edge${store.selection.edgeId === e.id ? ' selected' : ''}${model ? ' model' : ''}${fresh ? ' live' : ''}" data-edge="${e.id}">
      <path class="edge-hit" d="${d}"/><path class="edge-line" d="${d}"/></g>`);
    const touchesSelection = [e.source, e.target].includes(store.selection.nodeId);
    if (fresh && tele.kind === 'data' && touchesSelection) {
      const m = curveMid(a, b);
      pills.push(h('button', {
        type: 'button',
        class: 'edge-pill',
        style: { left: `${m.x}px`, top: `${m.y}px` },
        dataset: { edge: e.id },
        title: `${fmt.int(tele.row_count)} linha(s) · clique para ver os dados`,
      }, fmt.compact(tele.row_count)));
    }
  }
  if (gesture?.type === 'connect' && gesture.moved) {
    paths.push(`<path class="edge-draft" d="${curve(gesture.from, gesture.to)}"/>`);
  }
  els.svg.innerHTML = paths.join('');
  els.pills.replaceChildren(...pills);
}

function renderContainers() {
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

function placeContainerEl(c) {
  const el = els.containers.querySelector(`[data-container="${c.id}"]`);
  if (el) Object.assign(el.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.width}px`, height: `${c.height}px` });
}

/** Troca o título por um campo de texto; Enter/sair confirma, Esc cancela. */
function renameContainer(id) {
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
    else render({ containers: true });
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
function dropContainer(world) {
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

function containerMenu(id, x, y, pasteItem) {
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

export function render({ containers = false } = {}) {
  if (!store.workflow) return;
  if (containers) renderContainers();
  renderNodes();
  renderEdges();
  els.empty.hidden = store.workflow.nodes.length > 0;
}

function moveNodeEl(n) {
  const entry = nodeEls.get(n.id);
  if (entry) entry.el.style.transform = `translate(${n.x}px, ${n.y}px)`;
}

// ------------------------------------------------------------------ hit testing

function edgeNear(world, tolerance = 16) {
  let best = null;
  for (const g of els.svg.querySelectorAll('g.edge')) {
    const path = g.querySelector('.edge-line');
    const len = path.getTotalLength();
    for (let i = 1; i < 24; i += 1) {
      const p = path.getPointAtLength((len * i) / 24);
      const d = Math.hypot(p.x - world.x, p.y - world.y);
      if (d < tolerance / view.zoom && (!best || d < best.d)) best = { id: g.dataset.edge, d };
    }
  }
  return best?.id || null;
}

/**
 * Fio que atravessa o retângulo de um nó (inserção entre duas caixas).
 * Ignora fios ligados ao próprio nó; vence o fio com mais pontos dentro do retângulo.
 */
function edgeThroughRect(rect, ignoreNodeId = null, pad = 12) {
  let best = null;
  for (const g of els.svg.querySelectorAll('g.edge')) {
    const edge = store.workflow.edges.find((e) => e.id === g.dataset.edge);
    if (!edge || edge.source === ignoreNodeId || edge.target === ignoreNodeId) continue;
    const path = g.querySelector('.edge-line');
    const len = path.getTotalLength();
    let hits = 0;
    for (let i = 1; i < 40; i += 1) {
      const p = path.getPointAtLength((len * i) / 40);
      if (p.x >= rect.x - pad && p.x <= rect.x + rect.w + pad && p.y >= rect.y - pad && p.y <= rect.y + rect.h + pad) hits += 1;
    }
    if (hits && (!best || hits > best.hits)) best = { id: edge.id, hits };
  }
  return best?.id || null;
}

/** Área sem nós nem fios por baixo (para posicionar nós criados automaticamente). */
export function isAreaFree(x, y, w = NODE_W, hgt = NODE_MIN_H) {
  const pad = 20;
  const overlapsNode = store.workflow.nodes.some((n) => n.x < x + w + pad && n.x + NODE_W + pad > x
    && n.y < y + hgt + pad && n.y + nodeHeight(n) + pad > y);
  return !overlapsNode && !edgeThroughRect({ x, y, w, h: hgt });
}

/** Só nós soltos (sem conexões) e com entrada e saída de dados podem ser inseridos num fio. */
function canSplice(n) {
  const spec = toolOf(n);
  return Boolean(spec?.inputs.some((p) => p.kind !== 'model') && spec?.outputs.some((p) => p.kind !== 'model'))
    && !store.workflow.edges.some((e) => e.source === n.id || e.target === n.id);
}

function highlightEdge(id) {
  for (const g of els.svg.querySelectorAll('g.edge')) g.classList.toggle('drop-target', g.dataset.edge === id);
}

// ------------------------------------------------------------------ seleção múltipla, cache e entradas (spec 012)

function drawMarquee(x1, y1, x2, y2) {
  const r = els.viewport.getBoundingClientRect();
  Object.assign(els.marquee.style, {
    left: `${Math.min(x1, x2) - r.left}px`, top: `${Math.min(y1, y2) - r.top}px`,
    width: `${Math.abs(x2 - x1)}px`, height: `${Math.abs(y2 - y1)}px`,
  });
  els.marquee.hidden = false;
}

/** Mostra na tabela o que chega pela entrada `port` de `nodeId` (a saída da caixa ligada nela). */
export function inspectInput(nodeId, port) {
  const edge = store.workflow.edges.find((e) => e.target === nodeId && e.targetHandle === port);
  select(nodeId);
  if (!edge) {
    toast('Esta entrada não está ligada a nada', { kind: 'info', detail: 'Ligue uma saída nela para ver os dados que chegam.' });
    return;
  }
  inspect(edge.source, edge.sourceHandle, { nodeId, port });
}

const geometry = () => ({ nodeWidth: NODE_W, heightOf: nodeHeight });

/** Ações para várias caixas (menu do botão direito e painel do Inspector). */
export function selectionActions(ids) {
  const nodes = ids.map(node).filter(Boolean);
  const inAnyContainer = (store.workflow.containers || []).some((c) => nodesInside(c, NODE_W).some((n) => ids.includes(n.id)));
  const allDisabled = nodes.every((n) => n.disabled);
  return [
    { label: 'Alinhar em linha', icon: 'columns', onSelect: () => alignNodes(ids, 'row') },
    { label: 'Alinhar em coluna', icon: 'list', onSelect: () => alignNodes(ids, 'column') },
    { label: 'Distribuir na horizontal', icon: 'split', onSelect: () => distributeNodes(ids, 'row', geometry()) },
    { label: 'Distribuir na vertical', icon: 'stack', onSelect: () => distributeNodes(ids, 'column', geometry()) },
    'separator',
    {
      label: 'Agrupar em caixa de organização', icon: 'group',
      onSelect: () => { const c = wrapInContainer(ids, geometry()); if (c) requestAnimationFrame(() => renameContainer(c.id)); },
    },
    { label: 'Tirar da caixa de organização', icon: 'arrow-down', disabled: !inAnyContainer, onSelect: () => moveOutOfContainer(ids, geometry()) },
    'separator',
    { label: allDisabled ? 'Habilitar todas' : 'Desabilitar todas', icon: 'power', onSelect: () => setDisabled(ids, !allDisabled) },
    { label: `Excluir ${ids.length} caixas`, icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeNodes(ids) },
  ];
}

/** Ponto de cache: cachear e executar, atualizar ou remover (spec 012). */
export function cacheActions(n) {
  if (!n.cache_point) {
    return [{ label: 'Cachear até aqui e executar', icon: 'database', onSelect: () => { setCachePoint(n.id, true); handlers.run?.(); } }];
  }
  return [
    { label: 'Atualizar cache (reler tudo antes)', icon: 'refresh', onSelect: () => handlers.refreshCache?.(n.id) },
    { label: 'Remover ponto de cache', icon: 'x', onSelect: () => setCachePoint(n.id, false) },
  ];
}

// ------------------------------------------------------------------ gestos

function onPointerDown(e) {
  if (e.button === 2) return;
  closeMenu();
  const target = e.target;
  const world = toWorld(e.clientX, e.clientY);

  if (target.closest('.container-toggle, .node-delete')) {
    return; // botões dentro de caixas tratam o próprio clique; não iniciam arraste
  }
  if (e.button !== 1 && target.closest('.container-resize')) {
    const c = store.workflow.containers.find((k) => k.id === target.closest('.container-box').dataset.container);
    gesture = { type: 'container-resize', id: c.id, w: c.width, h: c.height, start: world,
      startX: e.clientX, startY: e.clientY, moved: false };
  } else if (e.button !== 1 && target.closest('.container-title')) {
    const c = store.workflow.containers.find((k) => k.id === target.closest('.container-box').dataset.container);
    // Os nós de dentro são definidos no início do gesto e acompanham o contêiner.
    const members = nodesInside(c, NODE_W).map((n) => ({ id: n.id, x: n.x, y: n.y }));
    gesture = { type: 'container-move', id: c.id, x: c.x, y: c.y, members, start: world,
      startX: e.clientX, startY: e.clientY, moved: false };
  } else if (e.button !== 1 && (e.shiftKey || e.ctrlKey || e.metaKey) && !target.closest('.node, .edge-pill, g.edge')) {
    // Shift/Ctrl + arrastar no vazio: retângulo de seleção (spec 012). Ctrl soma à seleção atual.
    gesture = { type: 'marquee', start: world, startX: e.clientX, startY: e.clientY, moved: false,
      additive: e.ctrlKey || e.metaKey };
  } else if (e.button === 1 || (!target.closest('.node, .edge-pill, g.edge'))) {
    gesture = { type: 'pan', startX: e.clientX, startY: e.clientY, vx: view.x, vy: view.y, moved: false };
  } else if ((e.shiftKey || e.ctrlKey || e.metaKey) && target.closest('.node') && !target.closest('.port')) {
    gesture = { type: 'toggle', id: target.closest('.node').dataset.id, startX: e.clientX, startY: e.clientY, moved: false };
  } else if (target.closest('.port.out')) {
    const { node: nodeId, port } = target.closest('.port').dataset;
    gesture = { type: 'connect', nodeId, port, from: portPoint(node(nodeId), port, true), to: world,
      startX: e.clientX, startY: e.clientY, moved: false };
  } else if (target.closest('.node')) {
    const id = target.closest('.node').dataset.id;
    const n = node(id);
    const inPort = target.closest('.port.in')?.dataset.port || null;
    if (selectedIds().length > 1 && isSelected(id) && !inPort) {
      // Arrastar uma das selecionadas move o grupo inteiro.
      const members = selectedIds().map(node).filter(Boolean).map((m) => ({ id: m.id, x: m.x, y: m.y }));
      gesture = { type: 'group-drag', id, members, start: world, startX: e.clientX, startY: e.clientY, moved: false };
    } else {
      gesture = { type: 'drag', id, dx: world.x - n.x, dy: world.y - n.y, startX: e.clientX, startY: e.clientY,
        moved: false, inPort };
    }
  } else if (target.closest('.edge-pill')) {
    gesture = { type: 'pill', edge: target.closest('.edge-pill').dataset.edge };
  } else if (target.closest('g.edge')) {
    gesture = { type: 'edge', edge: target.closest('g.edge').dataset.edge };
  }
  try {
    els.viewport.setPointerCapture(e.pointerId);
  } catch {
    /* ponteiro já liberado (ex.: evento sintético); o gesto segue sem captura */
  }
}

function onPointerMove(e) {
  lastPointer = { x: e.clientX, y: e.clientY };
  if (!gesture) return;
  const far = Math.hypot(e.clientX - gesture.startX, e.clientY - gesture.startY) > DRAG_THRESHOLD;
  if (!gesture.moved && !far) return;
  const world = toWorld(e.clientX, e.clientY);

  if (gesture.type === 'pan') {
    gesture.moved = true;
    view.x = gesture.vx + (e.clientX - gesture.startX);
    view.y = gesture.vy + (e.clientY - gesture.startY);
    applyView();
    els.viewport.classList.add('panning');
  } else if (gesture.type === 'container-move' || gesture.type === 'container-resize') {
    if (!gesture.moved) checkpoint();
    gesture.moved = true;
    const c = store.workflow.containers.find((k) => k.id === gesture.id);
    const dx = Math.round((world.x - gesture.start.x) / 10) * 10;
    const dy = Math.round((world.y - gesture.start.y) / 10) * 10;
    if (gesture.type === 'container-resize') {
      c.width = Math.max(200, gesture.w + dx);
      c.height = Math.max(120, gesture.h + dy);
    } else {
      c.x = gesture.x + dx;
      c.y = gesture.y + dy;
      for (const m of gesture.members) {
        const n = node(m.id);
        n.x = m.x + dx;
        n.y = m.y + dy;
        moveNodeEl(n);
      }
      renderEdges();
    }
    placeContainerEl(c);
  } else if (gesture.type === 'marquee') {
    gesture.moved = true;
    gesture.end = world;
    drawMarquee(gesture.startX, gesture.startY, e.clientX, e.clientY);
  } else if (gesture.type === 'group-drag') {
    if (!gesture.moved) checkpoint();
    gesture.moved = true;
    const dx = Math.round((world.x - gesture.start.x) / 10) * 10;
    const dy = Math.round((world.y - gesture.start.y) / 10) * 10;
    for (const m of gesture.members) {
      const n = node(m.id);
      n.x = m.x + dx;
      n.y = m.y + dy;
      moveNodeEl(n);
    }
    renderEdges();
  } else if (gesture.type === 'drag') {
    if (!gesture.moved) checkpoint();
    gesture.moved = true;
    const n = node(gesture.id);
    n.x = Math.round((world.x - gesture.dx) / 10) * 10;
    n.y = Math.round((world.y - gesture.dy) / 10) * 10;
    moveNodeEl(n);
    renderEdges();
    gesture.spliceEdge = canSplice(n)
      ? edgeThroughRect({ x: n.x, y: n.y, w: NODE_W, h: nodeHeight(n) }, n.id) : null;
    highlightEdge(gesture.spliceEdge);
  } else if (gesture.type === 'connect') {
    gesture.moved = true;
    gesture.to = world;
    renderEdges();
    const hover = document.elementFromPoint(e.clientX, e.clientY)?.closest('.port.in');
    for (const p of els.nodes.querySelectorAll('.port.in.can-drop, .port.in.cannot-drop')) {
      p.classList.remove('can-drop', 'cannot-drop');
    }
    if (hover) {
      const ok = !connectionError(gesture.nodeId, gesture.port, hover.dataset.node, hover.dataset.port);
      hover.classList.add(ok ? 'can-drop' : 'cannot-drop');
    }
  }
}

function onPointerUp(e) {
  const g = gesture;
  gesture = null;
  els.viewport.classList.remove('panning');
  if (!g) return;

  if (g.type === 'pan' && !g.moved) {
    select(null);
  } else if (g.type === 'marquee') {
    els.marquee.hidden = true;
    if (g.moved) {
      const box = { x1: Math.min(g.start.x, g.end.x), y1: Math.min(g.start.y, g.end.y),
        x2: Math.max(g.start.x, g.end.x), y2: Math.max(g.start.y, g.end.y) };
      const hits = store.workflow.nodes.filter((n) => n.x < box.x2 && n.x + NODE_W > box.x1
        && n.y < box.y2 && n.y + nodeHeight(n) > box.y1).map((n) => n.id);
      selectMany(g.additive ? [...selectedIds(), ...hits] : hits);
    } else if (!g.additive) {
      select(null);
    }
  } else if (g.type === 'toggle') {
    toggleSelected(g.id);
  } else if (g.type === 'group-drag') {
    if (g.moved) {
      commit();
      // Caixas levadas para dentro de uma etapa desligada também ficam desativadas.
      const toDisable = g.members.map((m) => node(m.id))
        .filter((n) => n && !n.disabled && disabledContainerAt(n, NODE_W, nodeHeight(n))).map((n) => n.id);
      if (toDisable.length) setDisabled(toDisable, true);
    } else {
      select(g.id);
      inspect(g.id);
    }
  } else if (g.type === 'container-move' || g.type === 'container-resize') {
    if (g.moved) {
      commit({ affects: [], structural: true });
    } else {
      // Duplo clique detectado aqui: o redesenho da seleção troca o elemento entre os cliques.
      const now = Date.now();
      const isDouble = lastTitleClick.id === g.id && now - lastTitleClick.at < 400;
      lastTitleClick = { id: g.id, at: now };
      if (isDouble) renameContainer(g.id);
      else if (store.selection.containerId !== g.id) select(null, null, g.id);
    }
  } else if (g.type === 'drag') {
    if (g.moved) {
      commit();
      highlightEdge(null);
      if (g.spliceEdge) spliceIntoEdge(g.spliceEdge, g.id, { nodeWidth: NODE_W });
      // Nó levado para dentro de uma caixa desligada também fica desativado.
      const moved = node(g.id);
      if (moved && !moved.disabled && disabledContainerAt(moved, NODE_W, nodeHeight(moved))) toggleDisabled(g.id);
    } else if (g.inPort) {
      inspectInput(g.id, g.inPort);
    } else {
      select(g.id);
      inspect(g.id, store.inspect.nodeId === g.id && !store.inspect.via ? store.inspect.anchor : null);
    }
  } else if (g.type === 'connect') {
    if (!g.moved) {
      select(g.nodeId);
      inspect(g.nodeId, g.port);
    } else {
      const hover = document.elementFromPoint(e.clientX, e.clientY)?.closest('.port.in');
      if (hover) connect(g.nodeId, g.port, hover.dataset.node, hover.dataset.port);
      else if (!document.elementFromPoint(e.clientX, e.clientY)?.closest('.node')) {
        openQuickAdd(e.clientX, e.clientY, g);
      }
      renderEdges();
    }
  } else if (g.type === 'pill') {
    const edge = store.workflow.edges.find((x) => x.id === g.edge);
    if (edge) {
      select(edge.source);
      inspect(edge.source, edge.sourceHandle);
    }
  } else if (g.type === 'edge') {
    select(null, g.edge);
  }
}

function onWheel(e) {
  e.preventDefault();
  if (e.ctrlKey || Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
    zoomBy(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX, e.clientY);
  } else {
    view.x -= e.deltaX;
    applyView();
  }
}

/** Seleciona a caixa e põe o foco no nome dela no Inspector. */
function renameNodeInInspector(id) {
  select(id);
  requestAnimationFrame(() => {
    const input = document.querySelector('.inspector-title-input');
    input?.focus();
    input?.select();
  });
}

function onContextMenu(e) {
  e.preventDefault();
  const world = toWorld(e.clientX, e.clientY);
  const pasteItem = (label = 'Colar aqui') => ({
    label, icon: 'clipboard', shortcut: 'Ctrl+V', disabled: !hasClipboard(), onSelect: () => paste(world),
  });
  const containerEl = e.target.closest('.container-title, .container-resize');
  if (containerEl) {
    containerMenu(containerEl.closest('.container-box').dataset.container, e.clientX, e.clientY, pasteItem());
    return;
  }
  const nodeEl = e.target.closest('.node');
  const edgeEl = e.target.closest('g.edge');
  if (nodeEl && selectedIds().length > 1 && isSelected(nodeEl.dataset.id)) {
    showMenu(e.clientX, e.clientY, [
      ...selectionActions(selectedIds()),
      'separator',
      { label: 'Copiar', icon: 'copy', shortcut: 'Ctrl+C', onSelect: () => copySelection({ nodeWidth: NODE_W }) },
      { label: 'Recortar', icon: 'scissors', shortcut: 'Ctrl+X', onSelect: () => cutSelection({ nodeWidth: NODE_W }) },
    ]);
  } else if (nodeEl) {
    const id = nodeEl.dataset.id;
    const n = node(id);
    select(id);
    showMenu(e.clientX, e.clientY, [
      { label: 'Configurar', icon: 'settings', onSelect: () => select(id) },
      { label: 'Executar até aqui', icon: 'target', shortcut: 'Ctrl+Shift+Enter', onSelect: () => handlers.runTo?.(id) },
      { label: 'Ver resultados', icon: 'table', onSelect: () => inspect(id) },
      ...cacheActions(n),
      'separator',
      { label: 'Copiar', icon: 'copy', shortcut: 'Ctrl+C', onSelect: () => copySelection({ nodeWidth: NODE_W }) },
      { label: 'Recortar', icon: 'scissors', shortcut: 'Ctrl+X', onSelect: () => cutSelection({ nodeWidth: NODE_W }) },
      pasteItem('Colar'),
      { label: 'Duplicar', icon: 'copy', shortcut: 'Ctrl+D', onSelect: () => duplicateNode(id) },
      'separator',
      { label: 'Renomear', icon: 'edit', onSelect: () => renameNodeInInspector(id) },
      { label: n.disabled ? 'Habilitar' : 'Desabilitar', icon: 'power', onSelect: () => toggleDisabled(id) },
      'separator',
      { label: 'Excluir', icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeNodes([id]) },
    ]);
  } else if (edgeEl) {
    const edge = store.workflow.edges.find((x) => x.id === edgeEl.dataset.edge);
    select(null, edge.id);
    showMenu(e.clientX, e.clientY, [
      { label: 'Ver dados deste fio', icon: 'table', onSelect: () => inspect(edge.source, edge.sourceHandle) },
      { label: 'Inserir ferramenta no meio…', icon: 'plus', onSelect: () => openQuickAdd(e.clientX, e.clientY, { to: world, splice: edge.id }) },
      { label: 'Excluir conexão', icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeEdge(edge.id) },
    ]);
  } else {
    showMenu(e.clientX, e.clientY, [
      pasteItem(),
      { label: 'Selecionar todas as caixas', icon: 'check', shortcut: 'Ctrl+A', onSelect: () => selectMany(store.workflow.nodes.map((n) => n.id)) },
      'separator',
      { label: 'Adicionar ferramenta aqui…', icon: 'plus', onSelect: () => openQuickAdd(e.clientX, e.clientY, { to: world }) },
      {
        label: 'Nova caixa de organização aqui', icon: 'group', shortcut: 'G',
        onSelect: () => { const c = addContainer(world.x, world.y); requestAnimationFrame(() => renameContainer(c.id)); },
      },
      'separator',
      { label: 'Ajustar à tela', icon: 'fit', shortcut: 'F', onSelect: fitView },
    ]);
  }
}

// ------------------------------------------------------------------ arrastar da paleta / painel de dados

export const DND_TOOL = 'application/x-prodata-tool';
export const DND_DATASET = 'application/x-prodata-dataset';
export const DND_CONTAINER = 'application/x-prodata-container';

function onDragOver(e) {
  const types = e.dataTransfer.types;
  if (!types.includes(DND_TOOL) && !types.includes(DND_DATASET) && !types.includes(DND_CONTAINER)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
  highlightEdge(types.includes(DND_TOOL) ? dropEdge(toWorld(e.clientX, e.clientY)) : null);
}

/** Fio sob a caixa que seria criada no ponto do cursor (ou bem perto da linha). */
function dropEdge(world) {
  const rect = { x: world.x - NODE_W / 2, y: world.y - NODE_MIN_H / 2, w: NODE_W, h: NODE_MIN_H };
  return edgeThroughRect(rect) || edgeNear(world);
}

function onDrop(e) {
  const tool = e.dataTransfer.getData(DND_TOOL);
  const dataset = e.dataTransfer.getData(DND_DATASET);
  if (e.dataTransfer.types.includes(DND_CONTAINER)) {
    e.preventDefault();
    dropContainer(toWorld(e.clientX, e.clientY));
    return;
  }
  if (!tool && !dataset) return;
  e.preventDefault();
  highlightEdge(null);
  const world = toWorld(e.clientX, e.clientY);
  const x = world.x - NODE_W / 2;
  const y = world.y - NODE_MIN_H / 2;
  if (dataset) {
    addNode('io.input_data', x, y, { dataset, __label: sourceLabel(dataset) });
    return;
  }
  const edgeId = dropEdge(world);
  const created = addNode(tool, x, y);
  if (created && edgeId && canSplice(created)) spliceIntoEdge(edgeId, created.id, { nodeWidth: NODE_W });
}

// ------------------------------------------------------------------ adicionar rápido (puxar fio para o vazio)

function openQuickAdd(clientX, clientY, source) {
  const fromPort = source.nodeId
    ? toolOf(node(source.nodeId)).outputs.find((p) => p.id === source.port)
    : null;
  const kind = fromPort?.kind || 'data';
  const tools = Object.values(store.tools).filter((t) => !t.hidden && (!fromPort || firstInput(t.type, kind))
    && (!source.splice || (firstInput(t.type) && t.outputs.some((p) => p.kind !== 'model'))));

  const list = h('div', { class: 'quick-list', role: 'listbox' });
  const input = h('input', { class: 'input', placeholder: fromPort ? 'Conectar a…' : 'Adicionar ferramenta…', 'aria-label': 'Buscar ferramenta' });
  const panel = h('div', { class: 'quick-add', style: { left: `${clientX}px`, top: `${clientY}px` } }, input, list);
  let active = 0;
  let shown = [];

  const choose = (t) => {
    panel.remove();
    const at = source.to;
    const created = addNode(t.type, at.x, at.y - NODE_MIN_H / 2);
    if (created && source.nodeId) connect(source.nodeId, source.port, created.id, firstInput(t.type, kind).id);
    if (created && source.splice) spliceIntoEdge(source.splice, created.id, { nodeWidth: NODE_W });
  };
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    shown = tools.filter((t) => !q || `${t.name} ${t.description}`.toLowerCase().includes(q)).slice(0, 8);
    active = Math.min(active, Math.max(0, shown.length - 1));
    list.replaceChildren(...shown.map((t, i) => h('button', {
      type: 'button', role: 'option', class: ['quick-item', i === active && 'active'], dataset: { category: t.category },
      onclick: () => choose(t),
    }, h('span', { class: 'tool-icon' }, icon(t.icon, 15)), h('span', {}, t.name))));
  };
  input.addEventListener('input', () => { active = 0; draw(); });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown') { active = Math.min(active + 1, shown.length - 1); draw(); ev.preventDefault(); }
    if (ev.key === 'ArrowUp') { active = Math.max(active - 1, 0); draw(); ev.preventDefault(); }
    if (ev.key === 'Enter' && shown[active]) choose(shown[active]);
    if (ev.key === 'Escape') panel.remove();
  });
  const outside = (ev) => {
    if (!panel.contains(ev.target)) {
      panel.remove();
      document.removeEventListener('pointerdown', outside, true);
    }
  };
  document.addEventListener('pointerdown', outside, true);
  document.body.append(panel);
  const r = panel.getBoundingClientRect();
  panel.style.left = `${Math.min(clientX, innerWidth - r.width - 8)}px`;
  panel.style.top = `${Math.min(clientY, innerHeight - 320)}px`;
  draw();
  input.focus();
}

// ------------------------------------------------------------------ init

export function initCanvas(root, opts = {}) {
  handlers = opts;
  els.viewport = root;
  els.world = $('.canvas-world', root);
  els.containers = $('.canvas-containers', root);
  els.svg = $('.canvas-edges', root);
  els.pills = $('.canvas-pills', root);
  els.nodes = $('.canvas-nodes', root);
  els.empty = $('.canvas-empty', root);
  els.marquee = h('div', { class: 'canvas-marquee', hidden: true });
  root.append(els.marquee);

  root.addEventListener('pointerdown', onPointerDown);
  root.addEventListener('pointermove', onPointerMove);
  root.addEventListener('pointerup', onPointerUp);
  root.addEventListener('pointercancel', () => { gesture = null; els.marquee.hidden = true; });
  root.addEventListener('pointerleave', () => { lastPointer = null; });
  root.addEventListener('wheel', onWheel, { passive: false });
  root.addEventListener('contextmenu', onContextMenu);
  root.addEventListener('dragover', onDragOver);
  root.addEventListener('dragleave', () => highlightEdge(null));
  root.addEventListener('drop', onDrop);
  root.addEventListener('dblclick', (e) => {
    if (!e.target.closest('.node, .container-box')) openQuickAdd(e.clientX, e.clientY, { to: toWorld(e.clientX, e.clientY) });
  });

  on('workflow:loaded', (payload) => {
    nodeEls.forEach(({ el }) => el.remove());
    nodeEls.clear();
    render({ containers: true });
    // Trocar de aba volta para a posição em que o fluxo estava; abrir um fluxo ajusta à tela.
    if (payload?.view) {
      Object.assign(view, payload.view);
      applyView();
    } else {
      requestAnimationFrame(() => fitView({ minZoom: FIT_MIN_ZOOM }));
    }
  });
  // Caixas são poucas: redesenhar sempre mantém título/descrição/cor em dia durante a edição.
  on('workflow:changed', () => render({ containers: true }));
  on('selection', () => render({ containers: true }));
  on('inspect', () => render());
  on('execution', () => render());

  const saved = storage('prodata.view', null);
  if (saved) Object.assign(view, saved);
  applyView();
  on('zoom', () => persist('prodata.view', view));
}

export const currentZoom = () => view.zoom;
export const getView = () => ({ ...view });

/** Ponto do canvas sob o cursor, se ele estiver sobre o canvas; senão null. */
export function pointerWorld() {
  if (!lastPointer || !els.viewport) return null;
  const r = els.viewport.getBoundingClientRect();
  const inside = lastPointer.x >= r.left && lastPointer.x <= r.right && lastPointer.y >= r.top && lastPointer.y <= r.bottom;
  return inside ? toWorld(lastPointer.x, lastPointer.y) : null;
}
