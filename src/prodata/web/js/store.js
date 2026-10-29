// Estado único da aplicação + eventos + histórico (desfazer/refazer).
//
// Regra: toda alteração do workflow passa por `mutate()`, que registra o histórico,
// marca nós afetados como pendentes e emite 'workflow:changed'.

const listeners = new Map();
const HISTORY_LIMIT = 100;
const COALESCE_MS = 800;

export const store = {
  catalog: null,
  tools: {}, // type -> spec
  datasets: [],
  connections: [],
  queries: [], // consultas de banco da aba Dados (spec 009)
  workflow: null,
  filePath: null, // arquivo .prodata.json fora da biblioteca, quando aberto/salvo por "Salvar como"

  savedSnapshot: '',
  execution: null,
  running: false,
  pending: new Set(), // nós alterados desde a última execução
  // nodeIds: todas as caixas selecionadas; nodeId só quando há exatamente uma (spec 012).
  selection: { nodeId: null, edgeId: null, containerId: null, nodeIds: [] },
  // via: inspecionando a entrada de uma caixa ({ nodeId, port }) em vez da saída de nodeId.
  inspect: { nodeId: null, anchor: null, via: null },
  view: 'designer',
};

const history = { undo: [], redo: [], lastKey: null, lastAt: 0 };

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

export function emit(event, payload) {
  for (const fn of listeners.get(event) || []) fn(payload);
}

// ------------------------------------------------------------------ workflow

const snapshot = () => JSON.stringify(store.workflow);

export function loadWorkflow(workflow, { saved = true, payload = {} } = {}) {
  store.workflow = workflow;
  store.savedSnapshot = saved ? snapshot() : '';
  store.execution = null;
  store.pending = new Set(workflow.nodes.map((n) => n.id));
  store.selection = { nodeId: null, edgeId: null, containerId: null, nodeIds: [] };
  store.inspect = { nodeId: null, anchor: null, via: null };
  history.undo = [];
  history.redo = [];
  emit('workflow:loaded', payload);
  emit('dirty', isDirty());
}

export const isDirty = () => store.workflow && snapshot() !== store.savedSnapshot;

export function markSaved() {
  store.savedSnapshot = snapshot();
  emit('dirty', false);
}

/**
 * Aplica uma alteração. `key` agrupa digitação contínua no mesmo campo em um
 * único passo de desfazer. `affects` lista nós cujo resultado fica desatualizado.
 */
export function mutate(fn, { key = null, affects = [], structural = false } = {}) {
  const now = Date.now();
  const coalesce = key && key === history.lastKey && now - history.lastAt < COALESCE_MS;
  if (!coalesce) {
    history.undo.push(snapshot());
    if (history.undo.length > HISTORY_LIMIT) history.undo.shift();
    history.redo = [];
  }
  history.lastKey = key;
  history.lastAt = now;

  fn(store.workflow);
  markPending(affects);
  emit('workflow:changed', { structural });
  emit('dirty', isDirty());
}

/**
 * Ajuste automático que não é ação do usuário (ex.: layout do dashboard montado ao abrir um fluxo antigo):
 * fica fora do desfazer e não marca como "não salvo" um fluxo que estava salvo.
 */
export function silently(fn) {
  const wasDirty = isDirty();
  fn(store.workflow);
  if (!wasDirty) store.savedSnapshot = snapshot();
}

/** Para gestos contínuos (arrastar): registra um passo de desfazer agora e confirma no fim. */
export function checkpoint() {
  history.undo.push(snapshot());
  history.redo = [];
  history.lastKey = null;
}

export function commit({ affects = [], structural = false } = {}) {
  markPending(affects);
  emit('workflow:changed', { structural });
  emit('dirty', isDirty());
}

function restore(serialized) {
  store.workflow = JSON.parse(serialized);
  const ids = new Set(store.workflow.nodes.map((n) => n.id));
  if (!ids.has(store.selection.nodeId)) store.selection.nodeId = null;
  store.selection.nodeIds = (store.selection.nodeIds || []).filter((id) => ids.has(id));
  store.selection.edgeId = null;
  if (!(store.workflow.containers || []).some((c) => c.id === store.selection.containerId)) store.selection.containerId = null;
  markPending(store.workflow.nodes.map((n) => n.id));
  history.lastKey = null;
  emit('workflow:changed', { structural: true });
  emit('selection');
  emit('dirty', isDirty());
}

export function undo() {
  if (!history.undo.length) return false;
  history.redo.push(snapshot());
  restore(history.undo.pop());
  return true;
}

export function redo() {
  if (!history.redo.length) return false;
  history.undo.push(snapshot());
  restore(history.redo.pop());
  return true;
}

export const canUndo = () => history.undo.length > 0;

// ------------------------------------------------------------------ abas (spec 010)

/** Tudo o que pertence a um fluxo aberto, inclusive o histórico de desfazer (privado deste módulo). */
export function snapshotState() {
  return {
    workflow: store.workflow,
    savedSnapshot: store.savedSnapshot,
    execution: store.execution,
    pending: store.pending,
    selection: store.selection,
    inspect: store.inspect,
    filePath: store.filePath,
    undo: history.undo,
    redo: history.redo,
  };
}

/** Reativa um fluxo congelado por snapshotState(). `payload` segue no evento workflow:loaded (ex.: { view }). */
export function restoreState(state, payload = {}) {
  Object.assign(store, {
    workflow: state.workflow,
    savedSnapshot: state.savedSnapshot,
    execution: state.execution,
    pending: state.pending,
    selection: state.selection,
    inspect: state.inspect,
    filePath: state.filePath,
  });
  history.undo = state.undo;
  history.redo = state.redo;
  history.lastKey = null;
  emit('workflow:loaded', payload);
  emit('execution');
  emit('selection');
  emit('inspect');
  emit('dirty', isDirty());
  emit('file');
}
export const canRedo = () => history.redo.length > 0;

// ------------------------------------------------------------------ consultas

export const node = (id) => store.workflow?.nodes.find((n) => n.id === id) || null;
export const toolOf = (n) => (n ? store.tools[n.type] : null);
export const nodeResult = (id) => store.execution?.node_results?.[id] || null;

export function descendants(id) {
  const out = new Set();
  const stack = [id];
  while (stack.length) {
    const current = stack.pop();
    for (const e of store.workflow.edges) {
      if (e.source === current && !out.has(e.target)) {
        out.add(e.target);
        stack.push(e.target);
      }
    }
  }
  return out;
}

function markPending(ids) {
  for (const id of ids) {
    store.pending.add(id);
    for (const d of descendants(id)) store.pending.add(d);
  }
}

/** Colunas que chegam a um nó (por porta), a partir da última execução. */
export function upstreamColumns(nodeId, portId = null) {
  const seen = new Map();
  for (const e of store.workflow.edges) {
    if (e.target !== nodeId) continue;
    if (portId && e.targetHandle !== portId) continue;
    const anchor = nodeResult(e.source)?.anchors?.[e.sourceHandle];
    for (const c of anchor?.columns || []) if (!seen.has(c.name)) seen.set(c.name, c);
  }
  return [...seen.values()];
}

/** Visuais de BI de nós que ainda existem e estão ativos (spec 010, RF-1005). */
export function liveWidgets() {
  const alive = new Set((store.workflow?.nodes || []).filter((n) => !n.disabled).map((n) => n.id));
  return (store.execution?.bi_widgets || []).filter((w) => alive.has(w.node_id));
}

export function setExecution(report, ranIds) {
  store.execution = mergeExecution(store.execution, report);
  for (const id of ranIds) store.pending.delete(id);
  emit('execution');
}

/** "Executar até aqui" só devolve parte dos nós: preserva o resultado dos demais. */
function mergeExecution(previous, report) {
  if (!previous || previous.workflow_id !== report.workflow_id) return report;
  const node_results = { ...previous.node_results, ...report.node_results };
  const edge_telemetry = { ...previous.edge_telemetry, ...report.edge_telemetry };
  const ran = new Set(Object.keys(report.node_results));
  const bi_widgets = [
    ...previous.bi_widgets.filter((w) => !ran.has(w.node_id)),
    ...report.bi_widgets,
  ];
  return { ...report, node_results, edge_telemetry, bi_widgets };
}

/** Prefixo das fontes do Input Data que são consultas de banco (spec 009). */
export const QUERY_PREFIX = 'sql:';
export const queryOf = (source) => (source?.startsWith(QUERY_PREFIX)
  ? store.queries.find((q) => q.id === source.slice(QUERY_PREFIX.length)) || null : null);

/** Nome amigável de uma fonte: nome da consulta ou arquivo sem extensão. */
export function sourceLabel(source) {
  if (source?.startsWith(QUERY_PREFIX)) return queryOf(source)?.name || 'Consulta de banco';
  return (source || '').replace(/\.[^.]+$/, '');
}

export function select(nodeId = null, edgeId = null, containerId = null) {
  store.selection = { nodeId, edgeId, containerId, nodeIds: nodeId ? [nodeId] : [] };
  emit('selection');
}

/** Seleção múltipla (spec 012). Com uma só caixa, equivale a select(id). */
export function selectMany(ids) {
  const unique = [...new Set(ids)].filter((id) => node(id));
  if (unique.length <= 1) {
    select(unique[0] || null);
    return;
  }
  store.selection = { nodeId: null, edgeId: null, containerId: null, nodeIds: unique };
  emit('selection');
}

export const selectedIds = () => store.selection.nodeIds || [];
export const isSelected = (id) => selectedIds().includes(id);

export function toggleSelected(id) {
  const ids = selectedIds();
  selectMany(ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);
}

export function inspect(nodeId, anchor = null, via = null) {
  const spec = toolOf(node(nodeId));
  const outputs = spec?.outputs || [];
  const valid = outputs.some((o) => o.id === anchor);
  store.inspect = { nodeId, anchor: valid ? anchor : outputs[0]?.id || null, via };
  emit('inspect');
}
