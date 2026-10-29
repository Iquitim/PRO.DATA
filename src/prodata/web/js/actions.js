// Operações de edição do grafo. Todas passam por store.mutate (histórico + eventos).

import { uid } from './dom.js';
import { descendants, inspect, mutate, node, select, store } from './store.js';
import { toast } from './ui.js';

const clone = (v) => JSON.parse(JSON.stringify(v));

export function addNode(type, x, y, config = {}) {
  const spec = store.tools[type];
  if (!spec) return null;
  const id = uid('n');
  const created = {
    id,
    type,
    label: config.__label || spec.name,
    x: Math.round(x / 10) * 10,
    y: Math.round(y / 10) * 10,
    config: { ...clone(spec.default_config), ...withoutMeta(config) },
  };
  mutate((wf) => wf.nodes.push(created), { affects: [id], structural: true });
  select(id);
  inspect(id);
  return created;
}

const withoutMeta = (config) => Object.fromEntries(Object.entries(config).filter(([k]) => !k.startsWith('__')));

/** Retorna a mensagem de erro se a conexão for inválida, ou null. */
export function connectionError(source, sourceHandle, target, targetHandle) {
  if (source === target) return 'Um nó não pode se conectar a ele mesmo.';
  if (descendants(target).has(source)) return 'Essa conexão criaria um ciclo.';
  const outPort = store.tools[node(source)?.type]?.outputs.find((p) => p.id === sourceHandle);
  const inPort = store.tools[node(target)?.type]?.inputs.find((p) => p.id === targetHandle);
  if (!outPort || !inPort) return 'Porta inexistente.';
  if ((outPort.kind === 'model') !== (inPort.kind === 'model')) {
    return inPort.kind === 'model' ? 'Esta entrada espera um modelo treinado [M].' : 'Esta entrada espera uma tabela.';
  }
  return null;
}

export function connect(source, sourceHandle, target, targetHandle) {
  const error = connectionError(source, sourceHandle, target, targetHandle);
  if (error) {
    toast(error, { kind: 'error', timeout: 3000 });
    return false;
  }
  mutate((wf) => {
    // Uma entrada aceita uma única conexão: a nova substitui a anterior.
    wf.edges = wf.edges.filter((e) => !(e.target === target && e.targetHandle === targetHandle));
    wf.edges.push({ id: uid('e'), source, sourceHandle, target, targetHandle });
  }, { affects: [target], structural: true });
  return true;
}

/** Primeira porta compatível (dados ou modelo) de um tipo de ferramenta. */
export function firstInput(type, kind = 'data') {
  return store.tools[type]?.inputs.find((p) => (p.kind === 'model') === (kind === 'model')) || null;
}

const snap = (v) => Math.round(v / 10) * 10;

/**
 * Insere um nó no meio de uma conexão existente. O nó é posicionado logo após a
 * origem e, se não houver espaço, o destino e tudo o que vem depois dele são
 * empurrados para a direita (contêineres acompanham).
 */
export function spliceIntoEdge(edgeId, nodeId, { nodeWidth = 188, gap = 60 } = {}) {
  const edge = store.workflow.edges.find((e) => e.id === edgeId);
  const spec = store.tools[node(nodeId)?.type];
  const input = spec?.inputs.find((p) => p.kind !== 'model');
  const output = spec?.outputs.find((p) => p.kind !== 'model');
  if (!edge || !input || !output) return false;
  const downstream = new Set([edge.target, ...descendants(edge.target)]);
  mutate((wf) => {
    const byId = (id) => wf.nodes.find((n) => n.id === id);
    const src = byId(edge.source);
    const tgt = byId(edge.target);
    const me = byId(nodeId);
    me.x = snap(src.x + nodeWidth + gap);
    me.y = snap(Math.abs(tgt.y - src.y) < 40 ? src.y : (src.y + tgt.y) / 2);

    const shift = snap(me.x + nodeWidth + gap - tgt.x);
    if (shift > 0) {
      const originX = tgt.x;
      for (const n of wf.nodes) if (downstream.has(n.id)) n.x += shift;
      for (const c of wf.containers || []) {
        if (c.x >= originX) c.x += shift;
        else if (c.x + c.width > originX) c.width += shift;
      }
    }

    const e = wf.edges.find((x) => x.id === edgeId);
    const { target, targetHandle } = e;
    e.target = nodeId;
    e.targetHandle = input.id;
    wf.edges.push({ id: uid('e'), source: nodeId, sourceHandle: output.id, target, targetHandle });
  }, { affects: [nodeId], structural: true });
  return true;
}

export function removeNodes(ids) {
  const set = new Set(ids);
  const affected = store.workflow.edges.filter((e) => set.has(e.source)).map((e) => e.target);
  mutate((wf) => {
    wf.nodes = wf.nodes.filter((n) => !set.has(n.id));
    wf.edges = wf.edges.filter((e) => !set.has(e.source) && !set.has(e.target));
  }, { affects: affected.filter((id) => !set.has(id)), structural: true });
  if (set.has(store.selection.nodeId)) select(null);
  if (set.has(store.inspect.nodeId)) inspect(null);
}

export function removeEdge(edgeId) {
  const edge = store.workflow.edges.find((e) => e.id === edgeId);
  if (!edge) return;
  mutate((wf) => {
    wf.edges = wf.edges.filter((e) => e.id !== edgeId);
  }, { affects: [edge.target], structural: true });
  select(null);
}

export function duplicateNode(id) {
  const original = node(id);
  if (!original) return null;
  return addNode(original.type, original.x + 40, original.y + 60, {
    ...clone(original.config),
    __label: `${original.label} (cópia)`,
  });
}

export function toggleDisabled(id) {
  mutate((wf) => {
    const n = wf.nodes.find((x) => x.id === id);
    n.disabled = !n.disabled;
  }, { affects: [id], structural: true });
}

export function updateConfig(id, path, value) {
  mutate((wf) => {
    const n = wf.nodes.find((x) => x.id === id);
    setPath(n.config, path, value);
  }, { key: `${id}:${path.join('.')}`, affects: [id] });
}

export function renameNode(id, label) {
  mutate((wf) => {
    wf.nodes.find((x) => x.id === id).label = label;
  }, { key: `${id}:label` });
}

export function setPath(obj, path, value) {
  let cur = obj;
  path.slice(0, -1).forEach((k, i) => {
    if (cur[k] === undefined || cur[k] === null) cur[k] = typeof path[i + 1] === 'number' ? [] : {};
    cur = cur[k];
  });
  cur[path.at(-1)] = value;
}

export function getPath(obj, path) {
  return path.reduce((cur, k) => (cur === undefined || cur === null ? undefined : cur[k]), obj);
}

// ------------------------------------------------------------------ contêineres de etapa (spec 006)

export const CONTAINER_COLORS = [
  ['#3b82f6', 'Azul'], ['#8b5cf6', 'Violeta'], ['#06b6d4', 'Ciano'], ['#10b981', 'Verde'],
  ['#f59e0b', 'Âmbar'], ['#ec4899', 'Rosa'], ['#64748b', 'Cinza'],
];

export function addContainer(x, y, { width = 440, height = 240, title } = {}) {
  const count = (store.workflow.containers || []).length;
  const created = {
    id: uid('c'),
    title: title || `${count + 1} · Nova etapa`,
    color: CONTAINER_COLORS[count % CONTAINER_COLORS.length][0],
    x: snap(x), y: snap(y), width, height,
  };
  mutate((wf) => {
    wf.containers = wf.containers || [];
    wf.containers.push(created);
  }, { structural: true });
  select(null, null, created.id);
  return created;
}

export function updateContainer(id, patch, { key = null } = {}) {
  // Não estrutural: o canvas redesenha as caixas a cada mudança; o Inspector mantém o foco.
  mutate((wf) => Object.assign(wf.containers.find((c) => c.id === id), patch), { key });
}

export function removeContainer(id) {
  mutate((wf) => {
    wf.containers = wf.containers.filter((c) => c.id !== id);
  }, { structural: true });
  select(null);
}

/** Exclui a etapa e os nós de dentro num único passo de desfazer. */
export function removeContainerWithNodes(id, nodeWidth = 188) {
  const c = store.workflow.containers.find((x) => x.id === id);
  const ids = new Set(nodesInside(c, nodeWidth).map((n) => n.id));
  const affected = store.workflow.edges.filter((e) => ids.has(e.source) && !ids.has(e.target)).map((e) => e.target);
  mutate((wf) => {
    wf.containers = wf.containers.filter((x) => x.id !== id);
    wf.nodes = wf.nodes.filter((n) => !ids.has(n.id));
    wf.edges = wf.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target));
  }, { affects: affected, structural: true });
  select(null);
  if (ids.has(store.inspect.nodeId)) inspect(null);
}

/** Nós cujo centro está dentro do contêiner. */
export function nodesInside(container, nodeWidth = 188, nodeHeight = 56) {
  return store.workflow.nodes.filter((n) => {
    const cx = n.x + nodeWidth / 2;
    const cy = n.y + nodeHeight / 2;
    return cx >= container.x && cx <= container.x + container.width && cy >= container.y && cy <= container.y + container.height;
  });
}

/** Ajusta o contêiner para envolver os nós de dentro, com margem e espaço para o título. */
export function fitContainer(id, nodeWidth = 188, heightOf = () => 56, only = null) {
  const c = store.workflow.containers.find((x) => x.id === id);
  // `only`: envolver exatamente estes nós (ex.: caixa solta sobre eles); senão, os de dentro.
  const inside = only || nodesInside(c, nodeWidth);
  if (!inside.length) return false;
  const pad = 20;
  const x1 = Math.min(...inside.map((n) => n.x)) - pad;
  const y1 = Math.min(...inside.map((n) => n.y)) - pad - 30;
  const x2 = Math.max(...inside.map((n) => n.x + nodeWidth)) + pad;
  const y2 = Math.max(...inside.map((n) => n.y + heightOf(n))) + pad;
  updateContainer(id, { x: snap(x1), y: snap(y1), width: snap(x2 - x1), height: snap(y2 - y1) });
  return true;
}

/**
 * Liga/desliga a caixa: desligada, todos os nós de dentro ficam desativados (não executam);
 * ligada, eles voltam a executar. Um único passo de desfazer.
 */
export function setContainerEnabled(id, enabled, nodeWidth = 188) {
  const c = store.workflow.containers.find((x) => x.id === id);
  const ids = nodesInside(c, nodeWidth).map((n) => n.id);
  mutate((wf) => {
    wf.containers.find((x) => x.id === id).disabled = !enabled;
    for (const n of wf.nodes) if (ids.includes(n.id)) n.disabled = !enabled;
  }, { affects: ids, structural: true });
}

/** Caixa desligada que contém o ponto (centro de um nó), se houver. */
export function disabledContainerAt(n, nodeWidth = 188, nodeHeight = 56) {
  const cx = n.x + nodeWidth / 2;
  const cy = n.y + nodeHeight / 2;
  return (store.workflow.containers || []).find((c) => c.disabled
    && cx >= c.x && cx <= c.x + c.width && cy >= c.y && cy <= c.y + c.height) || null;
}

// ------------------------------------------------------------------ várias caixas (spec 012)

export function setDisabled(ids, disabled) {
  const set = new Set(ids);
  mutate((wf) => {
    for (const n of wf.nodes) if (set.has(n.id)) n.disabled = disabled;
  }, { affects: ids, structural: true });
}

/** Alinha em linha (mesmo y) ou em coluna (mesmo x), pela primeira caixa da esquerda/de cima. */
export function alignNodes(ids, axis) {
  const nodes = store.workflow.nodes.filter((n) => ids.includes(n.id));
  if (nodes.length < 2) return;
  const anchor = axis === 'row' ? Math.min(...nodes.map((n) => n.y)) : Math.min(...nodes.map((n) => n.x));
  const set = new Set(ids);
  mutate((wf) => {
    for (const n of wf.nodes) {
      if (!set.has(n.id)) continue;
      if (axis === 'row') n.y = snap(anchor);
      else n.x = snap(anchor);
    }
  }, { structural: true });
}

/** Espaça igualmente na horizontal (row) ou vertical (column); sem espaço, abre o mínimo legível. */
export function distributeNodes(ids, axis, { nodeWidth = 188, heightOf = () => 56, gap = 50 } = {}) {
  const key = axis === 'row' ? 'x' : 'y';
  const size = (n) => (axis === 'row' ? nodeWidth : heightOf(n));
  const nodes = store.workflow.nodes.filter((n) => ids.includes(n.id)).sort((a, b) => a[key] - b[key]);
  if (nodes.length < 2) return;
  const start = nodes[0][key];
  const span = nodes.at(-1)[key] + size(nodes.at(-1)) - start;
  const total = nodes.reduce((sum, n) => sum + size(n), 0);
  const space = Math.max(gap, (span - total) / (nodes.length - 1));
  const positions = new Map();
  let cursor = start;
  for (const n of nodes) {
    positions.set(n.id, snap(cursor));
    cursor += size(n) + space;
  }
  mutate((wf) => {
    for (const n of wf.nodes) if (positions.has(n.id)) n[key] = positions.get(n.id);
  }, { structural: true });
}

/** Nova caixa de organização envolvendo exatamente estas caixas. */
export function wrapInContainer(ids, { nodeWidth = 188, heightOf = () => 56 } = {}) {
  const nodes = store.workflow.nodes.filter((n) => ids.includes(n.id));
  if (!nodes.length) return null;
  const created = addContainer(Math.min(...nodes.map((n) => n.x)), Math.min(...nodes.map((n) => n.y)));
  fitContainer(created.id, nodeWidth, heightOf, nodes);
  return created;
}

/** Tira as caixas das caixas de organização: descem para logo abaixo, mantendo a disposição. */
export function moveOutOfContainer(ids, { nodeWidth = 188, heightOf = () => 56 } = {}) {
  const nodes = store.workflow.nodes.filter((n) => ids.includes(n.id));
  const holders = (store.workflow.containers || []).filter((c) => nodesInside(c, nodeWidth).some((n) => ids.includes(n.id)));
  if (!holders.length) return false;
  const bottom = Math.max(...holders.map((c) => c.y + c.height));
  const dy = snap(bottom + 40 - Math.min(...nodes.map((n) => n.y)));
  const wasOff = new Set(nodes.filter((n) => disabledContainerAt(n, nodeWidth, heightOf(n))).map((n) => n.id));
  const set = new Set(ids);
  mutate((wf) => {
    for (const n of wf.nodes) {
      if (!set.has(n.id)) continue;
      n.y += dy;
      if (wasOff.has(n.id)) n.disabled = false; // saiu de uma caixa desligada: volta a executar
    }
  }, { affects: [...wasOff], structural: true });
  return true;
}

/** Ponto de cache (spec 012): liga/desliga numa caixa. */
export function setCachePoint(id, on) {
  mutate((wf) => {
    wf.nodes.find((n) => n.id === id).cache_point = on;
  }, { structural: true });
}
