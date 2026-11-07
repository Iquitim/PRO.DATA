// Caixas no canvas: o cartão de cada uma, com situação, portas e selos, desenhado só quando algo muda.

import { removeNodes } from './actions.js';
import { h } from './dom.js';
import { icon } from './icons.js';
import { isSelected, nodeResult, store, toolOf, visibleInputs } from './store.js';
import { els, nodeEls, state } from './canvas_state.js';
import { NODE_W, nodeHeight } from './canvas_geometry.js';
import { MAX_ANIMATED_NEW, setFlowTarget } from './canvas_edges.js';

function statusOf(n) {
  if (n.disabled) return 'disabled';
  const res = nodeResult(n.id);
  if (store.pending.has(n.id) && res?.status !== 'error') return 'pending';
  if (res?.extra?.held) return 'held'; // antes de um ponto de cache: não precisou executar
  return res?.status || 'pending';
}

/**
 * Caixas puladas por pontos de cache (spec 016): id da caixa → o ponto de cache que a dispensou.
 * Só o resultado do ponto de cache é guardado; as caixas antes dele não executam enquanto nada mudar.
 */
export function heldBy() {
  const out = new Map();
  const parents = new Map();
  for (const e of store.workflow?.edges || []) {
    if (!parents.has(e.target)) parents.set(e.target, []);
    parents.get(e.target).push(e.source);
  }
  for (const cp of (store.workflow?.nodes || []).filter((n) => n.cache_point && nodeResult(n.id)?.extra?.cache_point === 'frozen')) {
    const stack = [...(parents.get(cp.id) || [])];
    while (stack.length) {
      const id = stack.pop();
      if (out.has(id) || !nodeResult(id)?.extra?.held) continue;
      out.set(id, cp);
      stack.push(...(parents.get(id) || []));
    }
  }
  return out;
}

const STATUS_TITLES = {
  executed: 'Executado', cached: 'Executado (cache)', error: 'Erro', skipped: 'Não executado',
  disabled: 'Desabilitado', pending: 'Alterado desde a última execução',
  held: 'Pulada: o ponto de cache adiante já tem o resultado, então esta caixa não precisou executar',
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
  const inputs = visibleInputs(n).map((p, index) => ({ ...p, index }));
  const outputs = (spec?.outputs || []).map((p, index) => ({ ...p, index }));
  const cp = state.held.get(n.id);
  const annotation = status === 'error' ? 'Erro — veja a configuração'
    : cp && status === 'held' ? 'Pulada pelo cache'
      : res?.annotation || spec?.name || '';
  return h('div', {
    class: ['node', `status-${status}`, cp && store.selection.nodeId === cp.id && 'held-focus',
      isSelected(n.id) && 'selected',
      n.cache_point && 'cache-point',
      !store.inspect.via && store.inspect.nodeId === n.id && 'inspected'],
    dataset: { id: n.id, category: spec?.category || 'prep' },
    style: { transform: `translate(${n.x}px, ${n.y}px)`, width: `${NODE_W}px`, height: `${nodeHeight(n)}px` },
  },
  h('div', {
    class: 'node-card',
    title: [n.label || spec?.name, res?.annotation, res?.error,
      cp && status === 'held' ? `Não executou: o ponto de cache “${cp.label || toolOf(cp)?.name}” já tem o resultado.` : null,
    ].filter(Boolean).join('\n'),
  },
  h('span', { class: 'node-icon' }, icon(spec?.icon || 'info', 16)),
  h('span', { class: 'node-text' },
    h('span', { class: 'node-label' }, n.label || spec?.name || n.type),
    h('span', { class: 'node-annot' }, annotation)),
  h('span', { class: 'node-status', title: STATUS_TITLES[status] })),
  res?.extra?.dq_failed ? h('span', { class: 'node-alert', title: 'Linhas que falharam nas regras: saem por [F]' },
    `${res.extra.dq_failed} falharam`) : null,
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
  return JSON.stringify([n.type, n.label, n.disabled, n.cache_point, statusOf(n), res?.annotation, res?.error, visibleInputs(n).map((p) => p.id),
    res?.extra?.frozen_at, res?.extra?.dq_failed, isSelected(n.id), !store.inspect.via && store.inspect.nodeId === n.id && store.inspect.anchor,
    state.held.get(n.id)?.id, state.held.get(n.id) && store.selection.nodeId === state.held.get(n.id).id,
    store.inspect.via?.nodeId === n.id && store.inspect.via.port]);
}

/**
 * Andamento da execução nas caixas (spec 018): a da vez brilha, as concluídas ganham um sinal e as que
 * ainda vão rodar ficam esmaecidas. `null` limpa tudo ao terminar.
 */
export function showProgress(progress) {
  const order = new Set(progress?.order || []);
  for (const [id, { el }] of nodeEls) {
    const done = progress?.done?.[id];
    el.classList.toggle('run-now', !!progress && progress.running === id && !done);
    el.classList.toggle('run-done', !!done);
    el.classList.toggle('run-wait', !!progress && order.has(id) && !done && progress.running !== id);
  }
  els.viewport.classList.toggle('is-running', !!progress);
  const running = progress?.running || null;
  setFlowTarget(running);
}

export function renderNodes() {
  const wf = store.workflow;
  state.held = heldBy();
  const alive = new Set();
  // Caixa recém-criada surge com um leve crescimento; abrir um fluxo não anima nada.
  const unseen = nodesWorkflow === wf.id ? wf.nodes.filter((n) => !nodeEls.has(n.id)) : [];
  if (unseen.length <= MAX_ANIMATED_NEW) for (const n of unseen) enteringUntil.set(n.id, performance.now() + ENTER_MS);
  nodesWorkflow = wf.id;
  for (const n of wf.nodes) {
    alive.add(n.id);
    const key = nodeKey(n);
    const current = nodeEls.get(n.id);
    if (current && current.key === key) {
      current.el.style.transform = `translate(${n.x}px, ${n.y}px)`;
      continue;
    }
    const el = buildNode(n);
    // A caixa nova costuma ser refeita logo em seguida, ao ser selecionada: a animação continua nela.
    if (enteringUntil.get(n.id) > performance.now()) el.classList.add('node-enter');
    else enteringUntil.delete(n.id);
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

let nodesWorkflow = null;
const ENTER_MS = 200;
const enteringUntil = new Map();
