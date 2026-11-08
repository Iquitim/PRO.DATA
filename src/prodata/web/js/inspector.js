// Inspector: propriedades do fluxo (sem seleção) ou configuração do nó selecionado.

import {
  CONTAINER_COLORS, duplicateNode, fitContainer, nodesInside, removeContainer, removeNodes, renameNode,
  setContainerEnabled, toggleDisabled, updateConfig, updateContainer,
} from './actions.js';
import { api } from './api.js';
import { cacheActions, heldBy, NODE_W, nodeHeight, selectionActions } from './canvas.js';
import { openApiEditor, placeholdersOf } from './apis.js';
import { connectionTables, openConnectionDialog, openQueryEditor, refreshQueries, slug } from './connections.js';
import { chooseFolder, isDesktop, reveal } from './desktop.js';
import { button, debounce, fmt, h } from './dom.js';
import { explainerEl } from './explainers.js';
import { isGuided, recipeOf, recipePatch } from './multirow_recipes.js';
import { renderFields } from './fields.js';
import { formatOf, openPreview } from './datasets.js';
import { icon } from './icons.js';
import {
  API_PREFIX, apiOf, mutate, node, nodeResult, on, QUERY_PREFIX, queryOf, select, selectedIds, selectMany, sourceLabel, store, toolOf, upstreamColumns,
} from './store.js';
import { showMenu, toast, toastError } from './ui.js';

let root;
let handlers = {};
const sheetsCache = new Map();

export function initInspector(el, opts) {
  root = el;
  handlers = opts;
  const rerender = () => render();
  on('selection', rerender);
  on('workflow:loaded', rerender);
  on('workflow:changed', ({ structural }) => {
    // Caixa selecionada muda por gestos no canvas (mover, ajustar): redesenha se o foco não está aqui.
    if (structural || (store.selection.containerId && !root.contains(document.activeElement))) rerender();
  });
  on('execution', rerender);
  on('datasets', rerender);
  on('queries', rerender);
  on('connections', () => { tablesState.clear(); rerender(); });
  render();
}

function render() {
  const scroll = root.scrollTop;
  const n = node(store.selection.nodeId);
  const c = (store.workflow?.containers || []).find((x) => x.id === store.selection.containerId);
  const many = selectedIds().length > 1 ? selectedIds() : null;
  root.replaceChildren(many ? multiPanel(many) : n ? nodePanel(n) : c ? containerPanel(c) : workflowPanel());
  root.scrollTop = scroll;
}

// ------------------------------------------------------------------ workflow

function workflowPanel() {
  const wf = store.workflow;
  if (!wf) return h('div');
  const results = Object.values(store.execution?.node_results || {});
  const count = (s) => results.filter((r) => r.status === s).length;
  return h('div', { class: 'inspector' },
    h('header', { class: 'inspector-header' },
      h('span', { class: 'inspector-icon neutral' }, icon('workflow', 18)),
      h('div', {}, h('div', { class: 'inspector-title' }, 'Fluxo'), h('div', { class: 'inspector-sub mono' }, wf.id))),
    h('div', { class: 'form pad' },
      h('div', { class: 'field' }, h('label', { class: 'field-label', for: 'wf-desc' }, 'Descrição'),
        h('textarea', { id: 'wf-desc', class: 'input', rows: 3,
          oninput: (e) => mutate((w) => { w.description = e.target.value; }, { key: 'wf:desc' }) }, wf.description || '')),
      h('dl', { class: 'stats' },
        stat('Caixas', wf.nodes.length), stat('Ligações', wf.edges.length),
        store.execution ? stat('Última execução', fmt.ms(store.execution.total_elapsed_ms)) : null,
        store.execution ? stat('Com erro', count('error')) : null),
      h('div', { class: 'hint-box' },
        h('strong', {}, 'Como montar um fluxo'),
        h('ul', {},
          h('li', {}, 'Cadastre arquivos na vista ', h('b', {}, 'Dados'), ' e arraste-os da aba ', h('b', {}, 'Fontes'), ' para o canvas.'),
          h('li', {}, 'Arraste ferramentas da paleta; solte sobre um fio para inserir no meio.'),
          h('li', {}, 'Puxe de uma saída para uma entrada para ligar, ou para o vazio para criar uma caixa.'),
          h('li', {}, 'Clique em uma saída (T/F, L/J/R…) para ver os dados dela.'),
          h('li', {}, h('kbd', {}, 'Ctrl'), '+', h('kbd', {}, 'Enter'), ' executa · ', h('kbd', {}, '?'), ' mostra os atalhos.')))));
}

const stat = (label, value) => h('div', { class: 'stat' }, h('dt', {}, label), h('dd', {}, value));

// ------------------------------------------------------------------ nó

function statusBanner(n) {
  const res = nodeResult(n.id);
  const pending = store.pending.has(n.id);
  if (n.disabled) return banner('muted', 'power', 'Caixa desabilitada: não é executada, e as caixas depois dela ficam sem entrada.');
  if (res?.status === 'error') {
    return banner('error', 'alert', res.error, res.error_field ? `Campo: ${res.error_field}` : null);
  }
  if (!res || pending) {
    return banner('muted', 'clock', res ? 'Alterado desde a última execução.' : 'Ainda não executado.',
      null, button({ icon: 'target', label: 'Executar até aqui', size: 'sm', onClick: () => handlers.runTo(n.id) }));
  }
  if (res.extra?.held) {
    return banner('cache', 'database', 'Em cache: não executou nesta rodada.',
      'O ponto de cache adiante já tem o resultado. Mude algo antes dele (ou use "Atualizar cache") para executar de novo.');
  }
  if (res.status === 'skipped') return banner('muted', 'skip', res.error || 'Não executado.');
  // Avisos da execução (spec 018): ex.: valores que o Select não conseguiu converter.
  const warnings = res.extra?.warnings || [];
  if (warnings.length) {
    return banner('warn', 'alert', `Executou com ${warnings.length} aviso(s)`, h('ul', { class: 'banner-list' }, warnings.map((w) => h('li', {}, w))));
  }

  const anchors = Object.entries(res.anchors);
  const parts = anchors.filter(([, a]) => a.kind === 'data')
    .map(([port, a]) => `${anchors.length > 1 ? `[${port}] ` : ''}${fmt.int(a.row_count)} linhas`);
  const extra = [];
  const metrics = res.extra?.ml_metrics;
  if (metrics) {
    extra.push(metrics.task === 'classification'
      ? `Acurácia ${fmt.number(metrics.accuracy_pct)}% · F1 ${fmt.number(metrics.f1_pct)}%`
      : `R² ${fmt.number(metrics.r2, 3)} · MAE ${fmt.number(metrics.mae)}`,
    `medido em ${fmt.int(metrics.validation_rows)} linhas de validação`);
  }
  const file = res.extra?.exported_file;
  const path = res.extra?.exported_path;
  let action = null;
  if (path) {
    // Pasta escolhida pelo usuário (spec 009): mostra onde ficou e, no desktop, abre o Explorer.
    action = h('div', { class: 'stack-xs' }, h('span', { class: 'mono small break' }, path),
      isDesktop() ? button({ icon: 'folder', label: 'Mostrar na pasta', size: 'sm', onClick: () => reveal(path) }) : null);
  } else if (file) {
    action = h('a', { class: 'btn btn-sm', href: `/api/exports/${encodeURIComponent(file)}`, download: file },
      icon('download', 14), h('span', {}, file));
  }
  return banner('success', 'check-circle',
    `${parts.join(' · ') || 'Executado'} · ${res.status === 'cached' ? 'cache' : fmt.ms(res.elapsed_ms)}`,
    extra.join(' · ') || null, action);
}

/** Ponto de cache (spec 012): quando foi guardado e como atualizar ou remover. */
function cacheBanner(n) {
  if (!n.cache_point) return null;
  const at = nodeResult(n.id)?.extra?.frozen_at;
  // Só o resultado desta caixa é guardado; as anteriores ficam puladas (spec 016).
  const skipped = [...heldBy()].filter(([, cp]) => cp.id === n.id).map(([id]) => node(id)).filter(Boolean);
  const names = skipped.slice(0, 4).map((k) => k.label || toolOf(k)?.name).join(', ') + (skipped.length > 4 ? '…' : '');
  return banner('cache', 'database', 'Ponto de cache',
    at ? `Guarda só o resultado desta caixa (${new Date(at).toLocaleString('pt-BR')}). `
      + (skipped.length ? `Por isso ${skipped.length} caixa(s) anterior(es) não executam enquanto nada mudar antes daqui: ${names}.`
        : 'Nenhuma caixa anterior precisou ser pulada.')
      : 'Execute o fluxo para guardar o resultado desta caixa. Depois, as caixas anteriores não precisam executar.',
    h('div', { class: 'stack-xs' },
      // Renovação (spec 017): arquivos de origem já invalidam o cache sozinhos; bancos precisam de prazo.
      h('label', { class: 'cache-refresh' }, h('span', {}, 'Renovar'),
        h('select', {
          class: 'input input-sm', 'aria-label': 'Quando renovar o cache',
          onchange: (e) => mutate((wf) => { wf.nodes.find((k) => k.id === n.id).cache_refresh = e.target.value; }, { affects: [n.id] }),
        }, [['changes', 'quando algo antes mudar (padrão)'], ['daily', 'também todo dia'], ['hourly', 'também a cada hora']]
          .map(([v, l]) => h('option', { value: v, selected: (n.cache_refresh || 'changes') === v }, l)))),
      h('p', { class: 'field-help' }, 'Arquivos de origem atualizados também renovam o cache. Para bancos de dados, use "todo dia".')),
    h('div', { class: 'row wrap' },
      skipped.length ? button({ icon: 'target', label: `Mostrar as ${skipped.length} puladas`, size: 'sm', onClick: () => selectMany(skipped.map((k) => k.id)) }) : null,
      button({ icon: 'refresh', label: 'Atualizar cache', size: 'sm', onClick: () => handlers.refreshCache(n.id) }),
      button({ icon: 'x', label: 'Remover', size: 'sm', variant: 'ghost', onClick: () => cacheActions(n)[1].onSelect() })));
}

/** De quando são os dados de uma fonte (spec 017): data do arquivo, vínculo ou consulta refeita. */
function sourceBanner(n) {
  if (n.type !== 'io.input_data') return null;
  const extra = nodeResult(n.id)?.extra || {};
  const when = (iso) => new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  if (extra.source_linked) {
    return banner('muted', 'link', `Arquivo vinculado · modificado em ${when(extra.source_modified)}`,
      `${extra.source_linked}. A cada execução, se o arquivo mudou, ele é relido e só o que depende dele roda de novo.`);
  }
  if (extra.source_modified) {
    return banner('muted', 'clock', `Cópia enviada em ${when(extra.source_modified)}`,
      'Este arquivo é uma cópia: atualizar o original não muda o fluxo. Para acompanhar uma planilha atualizada todo dia, use "Vincular arquivo" na vista Dados.');
  }
  if (extra.source_read_at) {
    return banner('muted', 'database', `Consulta feita em ${when(extra.source_read_at)}`,
      'Consultas ao banco são refeitas a cada execução (a menos que "Reaproveitar resultado" esteja ligado).');
  }
  return null;
}

/** Várias caixas selecionadas (spec 012): ações de grupo e a lista das selecionadas. */
function multiPanel(ids) {
  const nodes = ids.map(node).filter(Boolean);
  const actions = selectionActions(ids).filter((a) => a !== 'separator');
  return h('div', { class: 'inspector' },
    h('header', { class: 'inspector-header' },
      h('span', { class: 'inspector-icon neutral' }, icon('check', 18)),
      h('div', { class: 'grow' }, h('div', { class: 'inspector-title' }, `${nodes.length} caixas selecionadas`),
        h('div', { class: 'inspector-sub' }, 'Arraste qualquer uma para mover todas'))),
    h('p', { class: 'inspector-desc' }, 'Shift ou Ctrl + clique adiciona ou tira uma caixa da seleção; Shift + arrastar no vazio seleciona com um retângulo.'),
    h('div', { class: 'pad stack-sm' },
      h('div', { class: 'multi-actions' }, actions.map((a) => button({
        icon: a.icon, label: a.label, size: 'sm', variant: a.danger ? 'danger' : '', disabled: a.disabled, onClick: a.onSelect,
      }))),
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Caixas selecionadas'),
        h('div', { class: 'member-list' }, nodes.map((n) => h('button', {
          type: 'button', class: ['member', n.disabled && 'disabled'], onclick: () => select(n.id),
        }, icon(toolOf(n)?.icon || 'info', 14), h('span', { class: 'ellipsis' }, n.label || toolOf(n)?.name)))))));
}

function banner(kind, iconName, title, detail = null, action = null) {
  return h('div', { class: `banner banner-${kind}`, role: kind === 'error' ? 'alert' : null },
    icon(iconName, 15),
    h('div', { class: 'banner-body' }, h('div', {}, title), detail ? h('div', { class: 'banner-detail' }, detail) : null,
      action ? h('div', { class: 'banner-action' }, action) : null));
}

// Valores distintos de colunas da entrada, guardados até a próxima execução (spec 015).
const valuesCache = new Map();
on('execution', () => valuesCache.clear());

/** Valores de uma coluna que chega na caixa (pela porta indicada ou pela primeira ligada). */
function upstreamValues(nodeId, column, port = null, search = '') {
  const edge = store.workflow.edges.find((e) => e.target === nodeId && (!port || e.targetHandle === port));
  if (!edge || !nodeResult(edge.source)?.anchors?.[edge.sourceHandle]) return Promise.reject(new Error('sem execução'));
  const key = `${edge.source}|${edge.sourceHandle}|${column}|${search}`;
  if (!valuesCache.has(key)) {
    const pending = api.columnValues(store.workflow.id, edge.source, edge.sourceHandle, column, 500, search);
    pending.catch(() => valuesCache.delete(key));
    valuesCache.set(key, pending);
  }
  return valuesCache.get(key);
}

function nodeContext(n) {
  const spec = toolOf(n);
  const res = nodeResult(n.id);
  const ctx = {
    columns: (port) => upstreamColumns(n.id, port || null),
    extraInputs: () => (toolOf(n)?.inputs || []).filter((p) => p.when).flatMap((p) => {
      const edge = store.workflow.edges.find((e) => e.target === n.id && e.targetHandle === p.id);
      if (!edge) return [];
      const from = node(edge.source);
      return [{ id: p.id, source: from?.label || toolOf(from)?.name || edge.source, fallback: p.title }];
    }),
    values: (column, port, search) => upstreamValues(n.id, column, port || null, search || ''),
    datasets: store.datasets,
    errorField: res?.status === 'error' ? res.error_field?.split('.')[0] : null,
    selfColumn: () => {
      const cfg = store.workflow.nodes.find((k) => k.id === n.id)?.config;
      return cfg?.target === 'new' ? cfg.column : null;
    },
  };
  if (n.type === 'io.input_data') Object.assign(ctx, sourceContext(n, spec));
  if (n.type === 'io.output_data') ctx.chooseFolder = chooseFolder;
  if (n.type === 'io.database_input') Object.assign(ctx, databaseContext(n));
  if (n.type === 'io.api_loop') {
    Object.assign(ctx, {
      apis: store.apis,
      needsLoop: (a) => placeholdersOf(a).length > 0,
      columnsWanted: placeholdersOf,
      currentApi: () => store.apis.find((a) => a.id === node(n.id)?.config.source) || null,
      onEditApi: (a) => openApiEditor({ source: a, onSaved: () => {} }),
      onNewApi: () => openApiEditor({ onSaved: (saved) => updateConfig(n.id, ['source'], saved.id) }),
    });
  }
  return ctx;
}

/** Input Data: arquivos e consultas da aba Dados no mesmo seletor (spec 009). */
function sourceContext(n, spec) {
  const cfg = n.config;
  const isApi = Boolean(cfg.dataset?.startsWith(API_PREFIX));
  const isQuery = isApi || Boolean(cfg.dataset?.startsWith(QUERY_PREFIX));
  const ctx = {
    queries: store.queries,
    apis: store.apis,
    needsLoop: (a) => placeholdersOf(a).length > 0,
    isQuery,
    fileOptions: !isQuery,
    onNewQuery: () => openQueryEditor({ onSaved: (saved) => setSource(n, `${QUERY_PREFIX}${saved.id}`) }),
  };
  if (isApi) {
    const a = apiOf(cfg.dataset);
    ctx.onPreview = () => a && openApiEditor({ source: a, onSaved: () => {} });
    return ctx;
  }
  if (isQuery) {
    const q = queryOf(cfg.dataset);
    ctx.onPreview = () => q && openQueryEditor({ query: q, onSaved: () => {} });
    return ctx;
  }
  ctx.format = formatOf(cfg.dataset, cfg);
  ctx.sheets = sheetsCache.get(cfg.dataset) || [];
  ctx.onPreview = () => openPreview(cfg.dataset, {
    options: Object.fromEntries(spec.config_fields.filter((f) => f.group).map((f) => [f.name, cfg[f.name]])),
    onApply: (opts) => mutate((wf) => Object.assign(wf.nodes.find((x) => x.id === n.id).config, opts),
      { affects: [n.id], structural: true }),
  });
  if (ctx.format === 'excel' && cfg.dataset && !sheetsCache.has(cfg.dataset)) {
    sheetsCache.set(cfg.dataset, []);
    api.previewDataset(cfg.dataset, { format: 'excel' }, 1)
      .then((p) => { sheetsCache.set(cfg.dataset, p.sheets); render(); })
      .catch(() => sheetsCache.delete(cfg.dataset));
  }
  return ctx;
}

/** Troca a fonte e, se o nome da caixa ainda é o automático, acompanha o nome da fonte. */
function setSource(n, source) {
  const automatic = !n.label || n.label === toolOf(n)?.name || n.label === sourceLabel(n.config.dataset);
  mutate((wf) => {
    const x = wf.nodes.find((k) => k.id === n.id);
    x.config.dataset = source;
    if (automatic) x.label = sourceLabel(source);
  }, { affects: [n.id], structural: true });
}

/** Database Input (antigo) → consulta da aba Dados + Input Data, no mesmo lugar e com as mesmas ligações. */
async function convertLegacy(n, saved = null) {
  const cfg = n.config;
  const name = n.label && n.label !== toolOf(n)?.name ? n.label
    : cfg.mode === 'table' ? cfg.table.split('.').pop() || 'Consulta SQL' : 'Consulta SQL';
  try {
    saved = saved || await api.saveQuery({
      id: slug(name), name, connection: cfg.connection, mode: cfg.mode, table: cfg.table, query: cfg.query,
      cache_results: cfg.cache_results,
    });
    await refreshQueries();
    mutate((wf) => {
      const x = wf.nodes.find((k) => k.id === n.id);
      x.type = 'io.input_data';
      x.config = { ...structuredClone(store.tools['io.input_data'].default_config), dataset: `${QUERY_PREFIX}${saved.id}`, limit: cfg.limit || 0 };
      x.label = saved.name;
    }, { affects: [n.id], structural: true });
    toast('Convertido para Input Data', { kind: 'success', detail: `A consulta "${saved.name}" está na vista Dados.` });
  } catch (err) {
    toastError(err, 'Não foi possível converter');
  }
}

/** Tabelas por conexão: array, {error} ou ausente (carregando). */
const tablesState = new Map();

function databaseContext(n) {
  const cfg = n.config;
  const conn = store.connections.find((c) => c.id === cfg.connection);
  if (conn && !tablesState.has(conn.id)) {
    tablesState.set(conn.id, null);
    connectionTables(conn.id)
      .then((t) => { tablesState.set(conn.id, t); render(); })
      .catch((err) => { tablesState.set(conn.id, { error: err.message }); render(); });
  }
  return {
    connections: store.connections,
    connectionChosen: Boolean(conn),
    tables: conn ? tablesState.get(conn.id) : null,
    onNewConnection: () => openConnectionDialog(),
    onExplore: (override = {}) => conn && openQueryEditor({
      initial: {
        name: n.label, connection: conn.id, mode: override.query !== undefined ? 'query' : cfg.mode,
        table: cfg.table, query: override.query ?? cfg.query, cache_results: cfg.cache_results,
      },
      onSaved: (saved) => convertLegacy(n, saved),
    }),
  };
}

/** Campos cuja mudança altera a visibilidade de outros (show_if) pedem redesenho. */
function controllingFields(spec) {
  const names = new Set(['format', 'dataset', 'connection', 'source']);
  const walk = (fields) => fields.forEach((f) => {
    Object.keys(f.show_if || {}).forEach((k) => names.add(k));
    if (f.options_by_type) names.add(f.name); // a marca de opção inválida depende do valor escolhido
    // Colunas do J (spec 019): chaves, lado das chaves e prefixo mudam a lista.
    if (f.source === 'join') ['keys', 'left', 'right', 'keys_mode', 'right_prefix'].forEach((k) => names.add(k));
    else if (f.source) names.add(f.source); // ex.: a coluna do grupo do Venn muda a lista de valores
    if (f.item_fields) walk(f.item_fields);
  });
  walk(spec.config_fields);
  return names;
}

/** Na receita numérica, a lista de colunas só traz número: texto não tem diferença nem variação. */
function leadContext(n, multirow) {
  const ctx = nodeContext(n);
  if (!multirow || !recipeOf(n.config.recipe).numeric) return ctx;
  return { ...ctx, columns: (port) => (ctx.columns(port) || []).filter((c) => ['Int64', 'Float64'].includes(c.type)) };
}

/** A fórmula que a receita escreveu, à vista: é ela que roda, e dá para assumir a partir dali. */
function formulaBox(n, onEdit) {
  const root = h('div', { class: 'mr-formula' });
  root.refresh = () => {
    const cfg = store.workflow.nodes.find((k) => k.id === n.id)?.config || n.config;
    root.hidden = !isGuided(cfg);
    root.replaceChildren(...(cfg.expression
      ? [h('span', { class: 'field-label' }, 'A fórmula que vai rodar'), h('code', {}, cfg.expression),
        button({ icon: 'edit', label: 'Editar esta fórmula', size: 'sm', variant: 'ghost', onClick: onEdit })]
      : [h('p', { class: 'field-help' }, 'Escolha a coluna para montar a fórmula.')]));
  };
  root.refresh();
  return root;
}

function nodePanel(n) {
  const spec = toolOf(n);
  if (!spec) return banner('error', 'alert', `Ferramenta desconhecida: ${n.type}`);
  const controlling = controllingFields(spec);
  const multirow = spec.explainer === 'multirow';
  const lead = spec.explainer === 'api_loop' ? spec.config_fields.slice(0, 2) : multirow ? spec.config_fields.slice(0, 3) : [];
  const rest = spec.config_fields.slice(lead.length);
  // Esquema visual (Cross Tab, Transpose, Join): redesenha quando a configuração muda (spec 015).
  const explainer = spec.explainer ? explainerEl(n, spec) : null;
  const refreshExplainer = debounce(() => explainer?.refresh(), 200);
  const recipeFormula = multirow ? formulaBox(n, () => onChange(['recipe'], 'custom')) : null;
  const onChange = (path, value) => {
    if (n.type === 'io.input_data' && path.length === 1 && path[0] === 'dataset') {
      setSource(n, value);
      render();
      return;
    }
    updateConfig(n.id, path, value);
    if (multirow && path.length === 1) {
      const now = store.workflow.nodes.find((k) => k.id === n.id).config;
      for (const [key, next] of Object.entries(recipePatch(now, path[0]))) updateConfig(n.id, [key], next);
      recipeFormula?.refresh();
      // A coluna escolhida muda "Coluna a alterar" e o nome sugerido; em texto digitado, redesenhar tiraria o foco.
      if (path[0] === 'base' && nodeContext(n).columns()?.length) { render(); return; }
    }
    refreshExplainer();
    const nested = path.length > 1 && path.some((k) => typeof k === 'string' && controlling.has(k) && k !== path[0]);
    const redraw = nested || path.length === 1
      && (controlling.has(path[0]) || (Array.isArray(value) && !['grid'].includes(spec.config_fields.find((f) => f.name === path[0])?.widget)));
    if (redraw) render();
  };

  const more = button({
    icon: 'more', title: 'Mais ações', variant: 'ghost',
    onClick: (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      showMenu(r.left, r.bottom + 4, [
        { label: 'Duplicar', icon: 'copy', shortcut: 'Ctrl+D', onSelect: () => duplicateNode(n.id) },
        { label: n.disabled ? 'Habilitar' : 'Desabilitar', icon: 'power', onSelect: () => toggleDisabled(n.id) },
        ...cacheActions(n),
        'separator',
        { label: 'Excluir', icon: 'trash', danger: true, shortcut: 'Del', onSelect: () => removeNodes([n.id]) },
      ]);
    },
  });

  return h('div', { class: 'inspector', dataset: { category: spec.category } },
    h('header', { class: 'inspector-header' },
      h('span', { class: 'inspector-icon' }, icon(spec.icon, 18)),
      h('div', { class: 'grow' },
        h('input', { class: 'inspector-title-input', value: n.label || spec.name, 'aria-label': 'Nome da caixa',
          oninput: (e) => renameNode(n.id, e.target.value) }),
        h('div', { class: 'inspector-sub' }, spec.name, h('span', { class: 'mono' }, ` · ${n.id}`))),
      button({ icon: 'target', title: 'Executar até aqui', variant: 'ghost', onClick: () => handlers.runTo(n.id) }),
      more),
    h('p', { class: 'inspector-desc' }, spec.description),
    spec.hidden ? banner('muted', 'info', 'Ferramenta antiga, fora da paleta.',
      'O Input Data agora lê consultas de banco cadastradas na vista Dados.',
      button({ icon: 'refresh', label: 'Converter para Input Data', size: 'sm', onClick: () => convertLegacy(n) })) : null,
    cacheBanner(n),
    statusBanner(n),
    sourceBanner(n),
    lead.length ? h('div', { class: 'pad' }, renderFields(lead, n.config, onChange, leadContext(n, multirow))) : null,
    recipeFormula,
    explainer,
    h('div', { class: 'pad' }, rest.length
      ? renderFields(rest, n.config, onChange, nodeContext(n))
      : h('p', { class: 'muted' }, 'Esta ferramenta não tem configurações.')));
}

// ------------------------------------------------------------------ caixa de organização (spec 007)

function containerPanel(c) {
  const inside = nodesInside(c, NODE_W);
  const swatch = (color, name) => h('button', {
    type: 'button', class: ['swatch-btn', c.color === color && 'active'], style: { background: color },
    title: name, 'aria-label': `Cor ${name}`,
    onclick: () => { updateContainer(c.id, { color }); render(); },
  });
  return h('div', { class: 'inspector' },
    h('header', { class: 'inspector-header' },
      h('span', { class: 'inspector-icon', style: { color: c.color, background: `${c.color}22` } }, icon('group', 18)),
      h('div', { class: 'grow' },
        h('input', { class: 'inspector-title-input', value: c.title, 'aria-label': 'Nome da etapa',
          oninput: (e) => updateContainer(c.id, { title: e.target.value }, { key: `${c.id}:title` }) }),
        h('div', { class: 'inspector-sub' }, 'Etapa', h('span', { class: 'mono' }, ` · ${c.id}`))),
      button({ icon: 'trash', title: 'Excluir etapa (mantém as caixas)', variant: 'ghost', onClick: () => removeContainer(c.id) })),
    h('p', { class: 'inspector-desc' }, 'Agrupa visualmente uma parte do fluxo. Arraste o título no canvas para mover a etapa junto com as caixas de dentro.'),
    h('div', { class: ['container-switch', c.disabled && 'off'] },
      h('label', { class: 'switch' },
        h('input', { type: 'checkbox', checked: !c.disabled, onchange: (e) => setContainerEnabled(c.id, e.target.checked, NODE_W) }),
        h('span', { class: 'switch-track' }), h('strong', {}, c.disabled ? 'Etapa desligada' : 'Etapa ligada')),
      h('p', { class: 'field-help' }, c.disabled
        ? 'As caixas de dentro estão desativadas e não executam. Ligue para reativá-las.'
        : 'Desligar desativa todas as caixas de dentro; elas deixam de executar.')),
    h('div', { class: 'form pad' },
      h('div', { class: 'field' }, h('label', { class: 'field-label', for: 'c-desc' }, 'Descrição'),
        h('textarea', { id: 'c-desc', class: 'input', rows: 3, placeholder: 'Ex.: limpeza e padronização da base de clientes',
          oninput: (e) => updateContainer(c.id, { description: e.target.value }, { key: `${c.id}:desc` }) }, c.description || '')),
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Cor'),
        h('div', { class: 'row wrap' }, CONTAINER_COLORS.map(([color, name]) => swatch(color, name)),
          h('label', { class: 'swatch-custom', title: 'Outra cor' }, icon('palette', 14),
            h('input', { type: 'color', value: c.color, 'aria-label': 'Escolher outra cor',
              onchange: (e) => { updateContainer(c.id, { color: e.target.value }); render(); } })))),
      h('div', { class: 'field' }, h('label', { class: 'field-label', for: 'c-op' }, `Intensidade do fundo · ${Math.round((c.opacity ?? 0.05) * 100)}%`),
        h('input', { id: 'c-op', type: 'range', min: 0, max: 0.4, step: 0.01, value: c.opacity ?? 0.05,
          oninput: (e) => {
            updateContainer(c.id, { opacity: Number(e.target.value) }, { key: `${c.id}:opacity` });
            e.target.previousElementSibling.textContent = `Intensidade do fundo · ${Math.round(Number(e.target.value) * 100)}%`;
          } })),
      h('div', { class: 'field' },
        h('span', { class: 'field-label' }, `Caixas dentro da etapa (${inside.length})`),
        inside.length
          ? h('div', { class: 'member-list' }, inside.map((n) => h('button', {
            type: 'button', class: ['member', n.disabled && 'disabled'], onclick: () => select(n.id),
          }, icon(toolOf(n)?.icon || 'info', 14), h('span', { class: 'ellipsis' }, n.label || toolOf(n)?.name))))
          : h('p', { class: 'field-help' }, 'Nenhuma caixa dentro. Arraste caixas para dentro da etapa ou mude o tamanho dela.')),
      h('div', { class: 'stack-xs' },
        button({ icon: 'fit', label: 'Ajustar às caixas de dentro', disabled: !inside.length, onClick: () => fitContainer(c.id, NODE_W, nodeHeight) }))));
}
