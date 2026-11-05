// Estado do dashboard na tela, compartilhado por página, edição, inserção e exportação.

import { growToFit } from './dash_model.js';
import { mutate, store } from './store.js';
import { toast } from './ui.js';

export const ui = { mode: 'view', zoom: null, selected: new Set(), scale: 1 };
export const els = {};
// O que as partes precisam da página, preenchido por dashboard.js: evita que elas dependam dele.
export const page = { render: () => {}, root: null, pageEl: null, itemEl: null, shownWidgets: null };

export const dash = () => store.workflow?.dashboard;
export const itemById = (id) => dash()?.items.find((i) => i.id === id);
export const nodeOf = (nodeId) => store.workflow.nodes.find((k) => k.id === nodeId);
export const nodeLabel = (nodeId) => {
  const n = nodeOf(nodeId);
  return n?.label || store.tools[n?.type]?.name || nodeId;
};
export const newId = () => `d_${Math.random().toString(36).slice(2, 8)}`;

export function commitLayout(fn, opts = {}) {
  let grew = false;
  mutate((wf) => { fn(wf.dashboard); grew = growToFit(wf.dashboard); }, opts);
  if (grew) toast('Os itens passaram do fim da página: a altura passou a ser livre.');
}
