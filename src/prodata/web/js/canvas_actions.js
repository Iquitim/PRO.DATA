// Ações sobre as caixas selecionadas e o ponto de cache, usadas nos menus.

import {
  alignNodes,
  distributeNodes,
  moveOutOfContainer,
  nodesInside,
  removeNodes,
  setCachePoint,
  setDisabled,
  wrapInContainer,
} from './actions.js';
import { renameContainer } from './canvas_containers.js';
import { NODE_W, nodeHeight } from './canvas_geometry.js';
import { state } from './canvas_state.js';
import { icon } from './icons.js';
import { node, store } from './store.js';

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
    return [{ label: 'Cachear até aqui e executar', icon: 'database', onSelect: () => { setCachePoint(n.id, true); state.handlers.run?.(); } }];
  }
  return [
    { label: 'Atualizar cache (reler tudo antes)', icon: 'refresh', onSelect: () => state.handlers.refreshCache?.(n.id) },
    { label: 'Remover ponto de cache', icon: 'x', onSelect: () => setCachePoint(n.id, false) },
  ];
}
