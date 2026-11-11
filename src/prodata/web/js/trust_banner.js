// Abertura protegida (spec 028, RF-2821..2823): faixa no topo do canvas quando o fluxo veio de fora.
// Quem decide é o servidor; aqui a pessoa vê o que o fluxo faz e escolhe confiar ou só olhar.

import { api } from './api.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';
import { inspect, select, store } from './store.js';
import { toast, toastError } from './ui.js';

const GROUPS = [
  { title: 'Lê', kinds: { file: ['file', 'arquivo'], folder: ['directory', 'pasta do computador'], query: ['database', 'banco'], api: ['globe', 'internet'] } },
  { title: 'Calcula', kinds: { formula: ['function', 'fórmula'], sql: ['terminal', 'SQL'], subflow: ['workflow', 'executa outro fluxo'] } },
  { title: 'Grava', kinds: { output: ['download', 'arquivo'] } },
];

let host = null;
let collapsed = false;
let onConfirmed = () => {};

/** Pergunta ao servidor se o fluxo aberto está liberado. Sempre a resposta de agora: é ela que vale. */
export async function refreshTrust() {
  const wf = store.workflow;
  if (!wf) return null;
  try {
    const res = await api.trustState(wf);
    if (store.workflow !== wf) return store.trust;
    store.trust = { workflowId: wf.id, ...res };
  } catch {
    // Sem resposta, a tela não libera nada: quem executa é o servidor, e ele recusa o que estiver bloqueado.
    store.trust = { workflowId: wf.id, protected: false, summary: [] };
  }
  draw();
  return store.trust;
}

export const isProtected = () => Boolean(store.trust?.protected && store.trust.workflowId === store.workflow?.id);

/** Antes de executar: no modo protegido, nada roda. Pedido pela pessoa, a faixa abre e explica. */
export async function blockedByTrust({ auto = false } = {}) {
  const trust = await refreshTrust();
  if (!trust?.protected) return false;
  if (!auto) {
    collapsed = false;
    draw();
    toast('Fluxo em modo protegido: nada foi executado', { kind: 'info', detail: 'Confira o que ele faz na faixa do topo e escolha Confiar e executar.' });
  }
  return true;
}

function itemEl(item) {
  const group = GROUPS.find((g) => g.kinds[item.kind]);
  const [name, word] = group.kinds[item.kind];
  return h('button', {
    type: 'button', class: ['trust-item', item.missing && 'missing'], title: 'Selecionar esta caixa',
    onclick: () => { select(item.node_id); inspect(item.node_id); },
  }, icon(name, 14), h('b', {}, item.label), h('span', { class: 'trust-kind' }, word),
  h('span', { class: 'trust-detail mono' }, item.detail),
  item.missing ? h('span', { class: 'trust-missing' }, 'não cadastrada aqui') : null);
}

async function confirm() {
  try {
    const res = await api.trustConfirm(store.workflow);
    store.trust = { workflowId: store.workflow.id, ...res };
    draw();
    toast('Fluxo liberado neste computador', { kind: 'success' });
    onConfirmed();
  } catch (err) {
    toastError(err, 'Não foi possível liberar o fluxo');
  }
}

function draw() {
  if (!host) return;
  if (!isProtected()) {
    host.replaceChildren();
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const items = store.trust.summary || [];
  if (collapsed) {
    host.replaceChildren(h('button', {
      type: 'button', class: 'trust-chip', onclick: () => { collapsed = false; draw(); },
    }, icon('shield', 14), 'Modo protegido: nada executa', icon('chevron-down', 12)));
    return;
  }
  const groups = GROUPS.map((g) => ({ ...g, items: items.filter((i) => g.kinds[i.kind]) })).filter((g) => g.items.length);
  host.replaceChildren(h('section', { class: 'trust-banner', role: 'region', 'aria-label': 'Fluxo em modo protegido' },
    h('header', { class: 'trust-head' },
      h('span', { class: 'trust-mark' }, icon('shield', 18)),
      h('div', { class: 'grow' },
        h('strong', {}, 'Este fluxo veio de fora: nada foi executado'),
        h('p', {}, 'Confira o que ele lê, calcula e grava. Clique num item para ver a caixa. Você pode editar à vontade; executar só depois de confiar.')),
      button({ icon: 'eye', label: 'Só olhar', variant: 'ghost', onClick: () => { collapsed = true; draw(); } }),
      button({ icon: 'check', label: 'Confiar e executar', variant: 'primary', onClick: confirm })),
    groups.length
      ? h('div', { class: 'trust-groups' }, groups.map((g) => h('div', { class: 'trust-group' },
        h('span', { class: 'trust-group-title' }, g.title), g.items.map(itemEl))))
      : h('p', { class: 'muted' }, 'O fluxo não lê fontes, não calcula fórmulas e não grava arquivos.')));
}

/** `root`: onde a faixa fica, sobre o canvas. `confirmed`: o que fazer depois de liberar (executar). */
export function initTrustBanner(root, { confirmed } = {}) {
  host = h('div', { class: 'trust-host', hidden: true });
  root.append(host);
  onConfirmed = confirmed || onConfirmed;
}

/** Ao trocar de fluxo, a faixa volta aberta: cada fluxo de fora merece a explicação. */
export function resetTrustBanner() {
  collapsed = false;
}
