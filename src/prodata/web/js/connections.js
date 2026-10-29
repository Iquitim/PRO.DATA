// Conexões com bancos (spec 005) e consultas de banco da aba Dados (spec 009).
// A senha só sai do navegador no momento de salvar; o servidor a guarda no cofre do Windows.
// Uma consulta salva vira uma fonte do Input Data, igual a um arquivo (valor `sql:<id>`).

import { addNode } from './actions.js';
import { api } from './api.js';
import { DND_DATASET, viewportCenter } from './canvas.js';
import { previewTable } from './datasets.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { commit, emit, on, QUERY_PREFIX, store } from './store.js';
import { confirmDialog, openDialog, toast, toastError } from './ui.js';

const KINDS = { postgres: 'PostgreSQL', mssql: 'SQL Server' };
const DEFAULT_PORTS = { postgres: 5432, mssql: 1433 };
const tablesCache = new Map();

export async function refreshConnections() {
  store.connections = await api.connections();
  emit('connections');
}

/** Tabelas de uma conexão (com cache por sessão). */
export async function connectionTables(id, { refresh = false } = {}) {
  if (refresh || !tablesCache.has(id)) tablesCache.set(id, api.connectionTables(id));
  try {
    return await tablesCache.get(id);
  } catch (err) {
    tablesCache.delete(id);
    throw err;
  }
}

export function slug(name) {
  const base = name.normalize('NFKD').replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase().slice(0, 40);
  return `${base || 'conexao'}_${Math.random().toString(36).slice(2, 6)}`;
}

export async function refreshQueries() {
  store.queries = await api.queries();
  emit('queries');
}

export function addQueryNode(q) {
  const c = viewportCenter();
  addNode('io.input_data', c.x - 94, c.y - 28, { dataset: `${QUERY_PREFIX}${q.id}`, __label: q.name });
}

// ------------------------------------------------------------------ cadastro

function field(label, control, help) {
  return h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control,
    help ? h('p', { class: 'field-help' }, help) : null);
}

export function openConnectionDialog(existing = null, { onSaved } = {}) {
  const conn = existing
    ? { ...existing }
    : { id: '', name: '', kind: 'postgres', host: 'localhost', port: 0, database: '', user: '', ssl_mode: 'prefer', encrypt: true, trust_server_certificate: false };
  const status = h('div', { class: 'conn-status' });
  const input = (key, attrs = {}) => h('input', {
    class: 'input', value: conn[key] ?? '', oninput: (e) => { conn[key] = attrs.type === 'number' ? Number(e.target.value || 0) : e.target.value; }, ...attrs,
  });
  const password = h('input', {
    class: 'input', type: 'password', autocomplete: 'new-password',
    placeholder: existing?.has_password ? '•••••••• salva no cofre do Windows (deixe vazio para manter)' : '',
  });
  const port = input('port', { type: 'number', min: 0, max: 65535, placeholder: String(DEFAULT_PORTS[conn.kind]) });
  if (!conn.port) port.value = '';
  const tls = h('div', {});
  const drawTls = () => tls.replaceChildren(conn.kind === 'postgres'
    ? field('SSL', h('select', { class: 'input', onchange: (e) => { conn.ssl_mode = e.target.value; } },
      [['prefer', 'Preferir (padrão)'], ['require', 'Exigir'], ['disable', 'Desativado']].map(([v, l]) => h('option', { value: v, selected: conn.ssl_mode === v }, l))))
    : h('div', { class: 'stack-xs' },
      h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: conn.encrypt, onchange: (e) => { conn.encrypt = e.target.checked; } }), h('span', { class: 'switch-track' }), h('span', {}, 'Criptografar conexão')),
      h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: conn.trust_server_certificate, onchange: (e) => { conn.trust_server_certificate = e.target.checked; } }), h('span', { class: 'switch-track' }), h('span', {}, 'Confiar no certificado do servidor'))));
  drawTls();

  const save = async () => {
    if (!conn.name.trim()) conn.name = conn.database || conn.host;
    if (!conn.id) conn.id = slug(conn.name);
    const { has_password: _, ...payload } = conn;
    const saved = await api.saveConnection(payload, password.value === '' ? null : password.value);
    Object.assign(conn, saved);
    tablesCache.delete(conn.id);
    await refreshConnections();
    return saved;
  };
  const test = async () => {
    status.className = 'conn-status muted';
    status.replaceChildren(icon('clock', 14), 'Testando…');
    try {
      await save();
      const res = await api.testConnection(conn.id);
      status.className = `conn-status ${res.ok ? 'ok' : 'err'}`;
      status.replaceChildren(icon(res.ok ? 'check-circle' : 'alert', 14), res.message);
    } catch (err) {
      status.className = 'conn-status err';
      status.replaceChildren(icon('alert', 14), err.message);
    }
  };

  const { close } = openDialog({
    title: existing ? `Editar conexão · ${existing.name}` : 'Nova conexão com banco de dados',
    body: h('div', { class: 'form conn-form' },
      h('div', { class: 'conn-grid' },
        field('Nome', input('name', { placeholder: 'Ex.: Data Warehouse' })),
        field('Banco de dados', h('select', {
          class: 'input',
          onchange: (e) => { conn.kind = e.target.value; port.placeholder = String(DEFAULT_PORTS[conn.kind]); drawTls(); },
        }, Object.entries(KINDS).map(([v, l]) => h('option', { value: v, selected: conn.kind === v }, l))))),
      h('div', { class: 'conn-grid host' }, field('Servidor (host)', input('host')), field('Porta', port)),
      h('div', { class: 'conn-grid' }, field('Database', input('database')), field('Usuário', input('user', { autocomplete: 'off' }))),
      field('Senha', password, 'Guardada no Gerenciador de Credenciais do Windows; nunca vai para arquivos do projeto.'),
      tls,
      h('p', { class: 'hint-box small' }, icon('lock', 14),
        ' Somente leitura: apenas consultas SELECT/WITH são aceitas. Recomenda-se um usuário com permissão só de leitura.'),
      status),
    actions: [
      button({ label: 'Testar conexão', icon: 'check', onClick: test }),
      button({ label: 'Cancelar', onClick: () => close() }),
      button({
        label: 'Salvar', variant: 'primary', icon: 'save',
        onClick: async () => {
          try {
            const saved = await save();
            close();
            onSaved?.(saved);
            toast(`Conexão "${saved.name}" salva`, { kind: 'success', detail: saved.has_password ? 'Senha no cofre do Windows.' : 'Sem senha salva.' });
          } catch (err) {
            toastError(err, 'Não foi possível salvar a conexão');
          }
        },
      }),
    ],
  });
}

async function removeConnection(c) {
  const used = store.workflow?.nodes.some((n) => n.config?.connection === c.id);
  const dependents = store.queries.filter((q) => q.connection === c.id).length;
  const warnings = [
    dependents ? ` ${dependents} consulta(s) da aba Dados usam esta conexão e deixarão de funcionar.` : '',
    used ? ' Este fluxo usa a conexão e deixará de funcionar.' : '',
  ].join('');
  const ok = await confirmDialog({
    title: 'Excluir conexão',
    message: `Excluir "${c.name}" e a senha guardada no cofre do Windows?${warnings}`,
    confirm: 'Excluir',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteConnection(c.id);
    tablesCache.delete(c.id);
    await refreshConnections();
  } catch (err) {
    toastError(err, 'Não foi possível excluir');
  }
}

// ------------------------------------------------------------------ editor de consulta (spec 009)

/**
 * Cria ou edita uma consulta de banco da aba Dados: conexão, tabela ou SQL livre, prévia e nome.
 * `initial` pré-preenche (ex.: conversão do Database Input); `onSaved(query)` substitui a ação padrão.
 */
export function openQueryEditor({ query = null, connectionId = '', initial = {}, onSaved = null } = {}) {
  const state = {
    id: query?.id || '',
    name: query?.name || initial.name || '',
    connection: query?.connection || initial.connection || connectionId || store.connections[0]?.id || '',
    mode: query?.mode || initial.mode || 'table',
    table: query?.table || initial.table || '',
    query: query?.query || initial.query || '',
    cache_results: query?.cache_results ?? initial.cache_results ?? false,
  };
  let nameTouched = Boolean(state.name);
  const list = h('div', { class: 'explorer-list' });
  const search = h('input', { class: 'input input-search input-sm', type: 'search', placeholder: 'Buscar tabela' });
  const meta = h('div', { class: 'preview-meta' }, h('span', { class: 'muted' }, 'Escolha uma tabela ou escreva uma consulta para ver a prévia.'));
  const grid = h('div', { class: 'preview-table' });
  const queryBox = h('textarea', {
    class: 'input code', rows: 9, spellcheck: false, placeholder: 'SELECT * FROM vendas WHERE ...',
    oninput: (e) => { state.query = e.target.value; },
  }, state.query);
  const nameInput = h('input', {
    class: 'input', value: state.name, placeholder: 'Ex.: Vendas do mês',
    oninput: (e) => { state.name = e.target.value; nameTouched = true; },
  });
  const connSelect = h('select', { class: 'input' });
  let tables = [];

  const conn = () => store.connections.find((c) => c.id === state.connection) || null;
  const definition = () => ({ connection: state.connection, mode: state.mode, table: state.table, query: state.query });
  const suggestName = () => {
    if (nameTouched) return;
    state.name = state.mode === 'table' && state.table ? state.table.split('.').pop() : state.name;
    nameInput.value = state.name;
  };

  const showPreview = async () => {
    if (!conn()) return;
    grid.classList.add('loading');
    meta.replaceChildren(h('span', { class: 'muted' }, 'Consultando…'));
    try {
      const res = await api.previewQuery(definition(), 100);
      meta.replaceChildren(h('span', { class: 'badge' }, icon('check', 12), KINDS[conn().kind]),
        h('span', { class: 'muted' }, `${res.columns.length} colunas · prévia de ${fmt.int(res.rows.length)} linhas`));
      grid.replaceChildren(previewTable(res.columns, res.rows));
    } catch (err) {
      meta.replaceChildren(h('span', { class: 'text-error' }, icon('alert', 14), err.message));
      grid.replaceChildren();
    } finally {
      grid.classList.remove('loading');
    }
  };

  const drawList = () => {
    const q = search.value.trim().toLowerCase();
    const shown = tables.filter((t) => !q || t.qualified.toLowerCase().includes(q));
    list.replaceChildren(...(shown.length ? shown.map((t) => h('button', {
      type: 'button', class: ['explorer-item', state.table === t.qualified && 'active'],
      onclick: () => { state.table = t.qualified; suggestName(); drawList(); showPreview(); },
    }, icon(t.type === 'view' ? 'eye' : 'table', 14), h('span', { class: 'ellipsis' }, h('span', { class: 'muted' }, `${t.schema}.`), t.name)))
      : [h('p', { class: 'muted pad' }, !conn() ? 'Escolha ou cadastre uma conexão.' : tables.length ? 'Nenhuma tabela encontrada.' : 'Carregando…')]));
  };
  search.addEventListener('input', debounce(drawList, 150));

  const loadTables = () => {
    tables = [];
    drawList();
    if (!conn()) return;
    connectionTables(state.connection).then((t) => { tables = t; drawList(); })
      .catch((err) => list.replaceChildren(h('p', { class: 'text-error pad' }, icon('alert', 14), err.message)));
  };
  const drawConnections = () => {
    connSelect.replaceChildren(
      h('option', { value: '' }, store.connections.length ? 'Escolha uma conexão…' : 'Nenhuma conexão cadastrada'),
      ...store.connections.map((c) => h('option', { value: c.id, selected: c.id === state.connection }, `${c.name} · ${KINDS[c.kind]}`)));
  };
  connSelect.addEventListener('change', () => { state.connection = connSelect.value; loadTables(); grid.replaceChildren(); });
  drawConnections();

  const tablePane = h('div', { class: 'explorer-side' }, h('div', { class: 'pad-sm' }, search), list);
  const queryPane = h('div', { class: 'explorer-side pad stack-sm' },
    h('label', { class: 'field-label' }, 'Consulta SQL (somente leitura)'), queryBox,
    button({ label: 'Pré-visualizar', icon: 'play', onClick: showPreview }),
    h('p', { class: 'field-help' }, icon('lock', 12), ' Somente SELECT/WITH. A prévia traz até 100 linhas.'));
  const side = h('div', { class: 'explorer-left' });
  const tabs = h('div', { class: 'segmented small' }, [['table', 'Tabela'], ['query', 'Consulta SQL']].map(([m, l]) => h('button', {
    type: 'button', class: 'segment', dataset: { m },
    onclick: () => setMode(m),
  }, l)));
  const setMode = (m) => {
    state.mode = m;
    for (const b of tabs.children) b.setAttribute('aria-selected', String(b.dataset.m === m));
    side.replaceChildren(m === 'table' ? tablePane : queryPane);
    if (m === 'query') queryBox.focus();
  };
  setMode(state.mode);

  const header = h('div', { class: 'query-head' },
    h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Nome da consulta'), nameInput),
    h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Conexão'),
      h('div', { class: 'row' }, connSelect, button({
        icon: 'plus', title: 'Nova conexão',
        onClick: () => openConnectionDialog(null, { onSaved: (c) => { state.connection = c.id; drawConnections(); loadTables(); } }),
      }))),
    h('label', { class: 'switch query-cache', title: 'Desligado: o banco é consultado de novo a cada execução.' },
      h('input', { type: 'checkbox', checked: state.cache_results, onchange: (e) => { state.cache_results = e.target.checked; } }),
      h('span', { class: 'switch-track' }), h('span', {}, 'Reaproveitar resultado entre execuções')));

  const persistQuery = async () => {
    if (!state.connection) throw new Error('Escolha uma conexão.');
    if (state.mode === 'table' && !state.table) throw new Error('Escolha uma tabela.');
    if (state.mode === 'query' && !state.query.trim()) throw new Error('Escreva a consulta.');
    const name = state.name.trim() || (state.mode === 'table' ? state.table.split('.').pop() : 'Consulta SQL');
    const saved = await api.saveQuery({ ...state, name, id: state.id || slug(name) });
    state.id = saved.id;
    await refreshQueries();
    // Caixas que leem esta consulta ficam desatualizadas até a próxima execução.
    const users = (store.workflow?.nodes || []).filter((n) => n.config?.dataset === `${QUERY_PREFIX}${saved.id}`);
    if (users.length) commit({ affects: users.map((n) => n.id) });
    return saved;
  };
  const finish = async (addToFlow) => {
    try {
      const saved = await persistQuery();
      close();
      if (onSaved) onSaved(saved);
      else if (addToFlow) addQueryNode(saved);
      toast(`Consulta "${saved.name}" salva`, { kind: 'success', detail: 'Disponível no Input Data, como um arquivo.' });
    } catch (err) {
      toastError(err, 'Não foi possível salvar a consulta');
    }
  };

  const { close } = openDialog({
    title: query ? `Editar consulta · ${query.name}` : 'Nova consulta de banco',
    size: 'xl',
    body: h('div', { class: 'stack-sm' }, header,
      h('div', { class: 'preview-layout explorer' },
        h('div', { class: 'explorer-col' }, h('div', { class: 'pad-sm' }, tabs), side),
        h('div', { class: 'preview-main' }, meta, grid))),
    actions: [
      button({ label: 'Cancelar', onClick: () => close() }),
      onSaved ? null : button({ label: 'Salvar', icon: 'save', onClick: () => finish(false) }),
      button({
        label: onSaved ? 'Salvar' : 'Salvar e adicionar ao fluxo',
        icon: onSaved ? 'save' : 'plus', variant: 'primary', onClick: () => finish(true),
      }),
    ].filter(Boolean),
  });

  loadTables();
  if ((state.mode === 'table' && state.table) || (state.mode === 'query' && state.query)) showPreview();
}

async function removeQuery(q) {
  const used = store.workflow?.nodes.some((n) => n.config?.dataset === `${QUERY_PREFIX}${q.id}`);
  const ok = await confirmDialog({
    title: 'Excluir consulta',
    message: `Excluir a consulta "${q.name}"?${used ? ' Este fluxo usa a consulta e deixará de funcionar.' : ''}`,
    confirm: 'Excluir',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteQuery(q.id);
    await refreshQueries();
  } catch (err) {
    toastError(err, 'Não foi possível excluir');
  }
}

// ------------------------------------------------------------------ painel

function queryItem(q) {
  const c = store.connections.find((x) => x.id === q.connection);
  const what = q.mode === 'table' ? q.table : q.query.split(/\s+/).join(' ').slice(0, 40);
  return h('div', {
    class: 'dataset-item query-item', draggable: 'true', title: 'Arraste para o canvas para criar um Input Data',
    ondragstart: (e) => {
      e.dataTransfer.setData(DND_DATASET, `${QUERY_PREFIX}${q.id}`);
      e.dataTransfer.effectAllowed = 'copy';
    },
  },
  h('span', { class: 'dataset-icon' }, icon('server', 16)),
  h('button', { type: 'button', class: 'dataset-main', onclick: () => openQueryEditor({ query: q }), title: 'Editar consulta e ver prévia' },
    h('span', { class: 'dataset-name' }, q.name),
    h('span', { class: 'dataset-meta' }, `${c ? c.name : 'conexão excluída'} · ${what.trim()}`)),
  h('div', { class: 'dataset-actions' },
    button({ icon: 'plus', title: 'Adicionar ao fluxo', size: 'sm', variant: 'ghost', onClick: () => addQueryNode(q) }),
    button({ icon: 'trash', title: 'Excluir consulta', size: 'sm', variant: 'ghost', onClick: () => removeQuery(q) })));
}

export function renderQueriesSection(root) {
  const list = h('div', { class: 'dataset-list' });
  const draw = () => list.replaceChildren(...(store.queries.length
    ? store.queries.map(queryItem)
    : [h('p', { class: 'muted pad' }, store.connections.length
      ? 'Nenhuma consulta. Crie uma para ler uma tabela ou um SQL no Input Data.'
      : 'Cadastre uma conexão abaixo e crie consultas para usá-las no Input Data.')]));
  on('queries', draw);
  on('connections', draw);
  root.append(
    h('div', { class: 'panel-subtitle row space-between' }, 'Consultas de banco',
      button({ icon: 'plus', label: 'Nova', size: 'sm', variant: 'ghost', onClick: () => openQueryEditor() })),
    list);
  draw();
}

function connectionItem(c) {
  return h('div', { class: 'dataset-item conn-item' },
    h('span', { class: 'dataset-icon' }, icon('link', 16)),
    h('button', { type: 'button', class: 'dataset-main', onclick: () => openQueryEditor({ connectionId: c.id }), title: 'Nova consulta com esta conexão' },
      h('span', { class: 'dataset-name' }, c.name),
      h('span', { class: 'dataset-meta' }, `${KINDS[c.kind]} · ${c.host}/${c.database}${c.has_password ? '' : ' · sem senha'}`)),
    h('div', { class: 'dataset-actions' },
      button({ icon: 'edit', title: 'Editar conexão', size: 'sm', variant: 'ghost', onClick: () => openConnectionDialog(c) }),
      button({ icon: 'trash', title: 'Excluir conexão', size: 'sm', variant: 'ghost', onClick: () => removeConnection(c) })));
}

export function renderConnectionsSection(root) {
  const list = h('div', { class: 'dataset-list' });
  const draw = () => list.replaceChildren(...(store.connections.length
    ? store.connections.map(connectionItem)
    : [h('p', { class: 'muted pad' }, 'Nenhuma conexão. PostgreSQL e SQL Server são suportados.')]));
  on('connections', draw);
  root.append(
    h('div', { class: 'panel-subtitle row space-between' }, 'Conexões com bancos',
      button({ icon: 'plus', label: 'Nova', size: 'sm', variant: 'ghost', onClick: () => openConnectionDialog() })),
    list);
  draw();
}
