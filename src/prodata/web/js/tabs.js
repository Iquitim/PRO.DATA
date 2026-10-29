// Abas de fluxos (spec 010). A aba ativa vive no `store`; as outras ficam congeladas
// (fluxo, execução, desfazer/refazer, seleção e posição do canvas) até serem reativadas.

import { getView } from './canvas.js';
import { persist, storage, uid } from './dom.js';
import { emit, isDirty, loadWorkflow, restoreState, snapshotState, store } from './store.js';

const TABS_KEY = 'prodata.tabs';
const tabs = []; // { key, frozen: estado congelado ou null (ativa), view }
let active = -1;

export const tabCount = () => tabs.length;
export const activeIndex = () => active;

const stateOf = (i) => (i === active ? snapshotState() : tabs[i].frozen);

export function tabInfo(i) {
  const st = stateOf(i);
  const dirty = i === active ? isDirty() : JSON.stringify(st.workflow) !== st.savedSnapshot;
  return { key: tabs[i].key, name: st.workflow?.name || 'Sem nome', dirty, filePath: st.filePath };
}

export const anyDirty = () => tabs.some((_, i) => tabInfo(i).dirty);
export const dirtyTabs = () => tabs.map((_, i) => i).filter((i) => tabInfo(i).dirty);

/** Aba que já mostra este fluxo (pelo arquivo ou, na biblioteca, pelo id). */
export function findTab(workflowId, filePath = null) {
  return tabs.findIndex((_, i) => {
    const st = stateOf(i);
    if (filePath || st.filePath) return Boolean(filePath && st.filePath && st.filePath.toLowerCase() === filePath.toLowerCase());
    return st.workflow?.id === workflowId && Boolean(st.savedSnapshot);
  });
}

function freeze() {
  if (active < 0) return;
  tabs[active].frozen = snapshotState();
  tabs[active].view = getView();
}

/** Aba nova e intocada (sem caixas e sem alterações) pode ser reaproveitada. */
function activeIsPristine() {
  const wf = store.workflow;
  return Boolean(wf) && !wf.nodes.length && !(wf.containers || []).length && !store.filePath && !isDirty();
}

export function openTab(workflow, { saved = true, filePath = null } = {}) {
  if (active < 0 || !activeIsPristine()) {
    freeze();
    tabs.push({ key: uid('t'), frozen: null, view: null });
    active = tabs.length - 1;
  }
  store.filePath = filePath;
  loadWorkflow(workflow, { saved });
  changed();
}

export function switchTab(i) {
  if (i === active || !tabs[i]) return;
  freeze();
  active = i;
  const tab = tabs[i];
  const state = tab.frozen;
  tab.frozen = null;
  restoreState(state, { view: tab.view });
  changed();
}

/** Remove a aba sem perguntar nada (quem chama já resolveu as alterações). */
export function removeTab(i) {
  if (tabs.length <= 1) return false;
  tabs.splice(i, 1);
  if (i === active) {
    active = Math.min(i, tabs.length - 1);
    const tab = tabs[active];
    const state = tab.frozen;
    tab.frozen = null;
    restoreState(state, { view: tab.view });
  } else if (i < active) {
    active -= 1;
  }
  changed();
  return true;
}

/** Abas com origem (biblioteca ou arquivo) são lembradas para a próxima abertura do programa. */
export function persistTabs() {
  const items = [];
  let activeItem = 0;
  tabs.forEach((_, i) => {
    const st = stateOf(i);
    let item = null;
    if (st.filePath) item = { kind: 'file', path: st.filePath };
    else if (st.savedSnapshot && st.workflow) item = { kind: 'library', id: st.workflow.id };
    if (!item) return;
    if (i === active) activeItem = items.length;
    items.push(item);
  });
  persist(TABS_KEY, { items, active: activeItem });
}

export const savedTabs = () => storage(TABS_KEY, null);

function changed() {
  persistTabs();
  emit('tabs');
}
