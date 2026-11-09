// Jira na vista Dados (spec 030): conexão com token guiado e consulta sem escrever JQL.

import { addNode } from './actions.js';
import { api } from './api.js';
import { viewportCenter } from './canvas.js';
import { openLink } from './desktop.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { previewTable } from './datasets.js';
import { emit, JIRA_PREFIX, store } from './store.js';
import { confirmDialog, toast, toastError } from './ui.js';

const TOKEN_PAGE = 'https://id.atlassian.com/manage-profile/security/api-tokens';
const TABLES = [
  ['issues', 'Demandas', 'Uma linha por demanda, com status, responsável e datas.', 'list'],
  ['history', 'Histórico de alterações', 'Uma linha por mudança: quem mudou o quê e quando.', 'clock'],
  ['comments', 'Comentários', 'Uma linha por comentário. Costumam ter dados pessoais.', 'edit'],
];
const PERIODS = [[0, 'Sem limite de data'], [30, 'Últimos 30 dias'], [90, 'Últimos 90 dias'], [180, 'Últimos 6 meses'], [365, 'Último ano'], [730, 'Últimos 2 anos']];
const newId = (prefix) => `${prefix}_${Date.now().toString(36)}`;

export async function refreshJira() {
  const [connections, queries] = await Promise.all([api.jiraConnections(), api.jiraQueries()]);
  store.jiraConnections = connections;
  store.jiraQueries = queries;
  emit('jira');
}

export function addJiraNode(query) {
  const c = viewportCenter();
  addNode('io.input_data', c.x - 94, c.y - 28, { dataset: `${JIRA_PREFIX}${query.id}`, __label: query.name });
}

export async function removeJiraQuery(query) {
  await api.deleteJiraQuery(query.id);
  await refreshJira();
}

export async function removeJiraConnection(conn) {
  await api.deleteJiraConnection(conn.id);
  await refreshJira();
}

const field = (label, control, help) => h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control, help ? h('p', { class: 'field-help' }, help) : null);

function step(n, title, body) {
  return h('li', { class: 'jira-step' }, h('b', {}, String(n)), h('div', {}, h('strong', {}, title), body));
}

function testMessage(res) {
  const scoped = res.token_kind === 'com escopo';
  return h('div', { class: 'stack-xs' },
    h('div', { class: 'jira-ok' }, icon('check', 14), ` Conectado como ${res.display_name} · ${fmt.int(res.projects)} projeto${res.projects === 1 ? '' : 's'}`),
    scoped ? null : h('p', { class: 'field-warn' }, icon('alert', 13),
      ' Este é um token comum, que também poderia alterar dados. O PRO.DATA só lê, mas o mais seguro é criar um token com escopo só de leitura.'));
}

/** Conexão: endereço, token criado no navegador, teste na hora. O token não volta para a tela. */
export function jiraConnectionEditor(existing, { onSaved }, host) {
  const state = { name: existing?.name || 'Jira', site: existing?.site || '', email: existing?.email || '', token: '' };
  const result = h('div', { class: 'jira-result', 'aria-live': 'polite' });
  const input = (key, attrs = {}) => h('input', { class: 'input', value: state[key], oninput: (e) => { state[key] = e.target.value; }, ...attrs });
  const request = () => ({ site: state.site, email: state.email, token: state.token, id: existing?.id || '' });
  const test = async () => {
    result.replaceChildren(h('p', { class: 'muted' }, 'Testando…'));
    try {
      const res = await api.testJira(request());
      result.replaceChildren(testMessage(res));
      return res;
    } catch (err) {
      result.replaceChildren(h('p', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
      return null;
    }
  };
  const save = async () => {
    const res = await test();
    if (!res) return;
    try {
      const saved = await api.saveJiraConnection({
        connection: { id: existing?.id || newId('jira'), name: state.name.trim() || 'Jira', site: res.site },
        email: state.email || null, token: state.token || null,
      });
      await refreshJira();
      toast(`Conexão ${saved.name} salva`, { kind: 'success' });
      host.close();
      onSaved?.(saved);
    } catch (err) {
      toastError(err, 'Não foi possível salvar a conexão');
    }
  };
  const body = h('div', { class: 'stack-md jira-form' },
    h('ol', { class: 'jira-steps' },
      step(1, 'Diga qual é o seu Jira', h('div', { class: 'stack-xs' },
        input('site', { placeholder: 'empresa.atlassian.net', 'aria-label': 'Endereço do Jira' }),
        h('p', { class: 'field-help' }, 'Pode colar o endereço de qualquer página do Jira.'))),
      step(2, 'Crie um token de leitura', h('div', { class: 'stack-xs' },
        button({ icon: 'globe', label: 'Criar meu token', onClick: () => openLink(TOKEN_PAGE) }),
        h('p', { class: 'field-help' }, 'Abre a página da Atlassian no navegador. Escolha ', h('b', {}, 'criar token com escopos'), ', selecione Jira e marque só as permissões de leitura, como ', h('code', {}, 'read:jira-work'), ' e ', h('code', {}, 'read:jira-user'), '.'))),
      step(3, 'Cole aqui', h('div', { class: 'stack-xs' },
        field('E-mail da sua conta Atlassian', input('email', { type: 'email', autocomplete: 'off' })),
        field('Token', input('token', { type: 'password', autocomplete: 'off', placeholder: existing?.has_token ? 'Guardado no cofre. Cole outro para trocar.' : '', 'aria-label': 'Token' }), 'Fica no cofre do Windows e nunca vai para fluxos, arquivos ou registros.')))),
    field('Nome da conexão', input('name')),
    result);
  return {
    title: existing ? `Editar conexão · ${existing.name}` : 'Conectar ao Jira',
    body,
    actions: [
      button({ label: 'Cancelar', onClick: () => host.close() }),
      button({ label: 'Testar', onClick: test }),
      button({ label: 'Salvar', variant: 'primary', onClick: save }),
    ],
  };
}

function chips(list, selected, onToggle, labelOf = (x) => x, valueOf = (x) => x) {
  return h('div', { class: 'value-list jira-chips' }, list.map((item) => {
    const value = valueOf(item);
    const on = selected.includes(value);
    return h('button', { type: 'button', class: ['value-chip', on && 'on'], 'aria-pressed': String(on), onclick: () => onToggle(value) },
      icon(on ? 'check' : 'plus', 12), h('span', { class: 'ellipsis' }, labelOf(item)));
  }));
}

const definition = (q) => ({
  connection: q.connection, table: q.table, projects: q.projects, issue_types: q.issue_types, statuses: q.statuses,
  assignees: [], period_field: q.period_field, period_days: q.period_days, advanced: q.advanced, jql: q.jql, fields: q.fields,
});

function queryStatus(query, onChange) {
  const when = query.synced_at ? new Date(query.synced_at).toLocaleString('pt-BR') : null;
  const line = h('p', { class: 'field-help' }, when
    ? `Guardada aqui: ${fmt.int(query.rows)} linhas, atualizada em ${when}.`
    : query.interrupted ? 'A última carga parou no meio: a próxima continua de onde ficou.' : 'Ainda não foi carregada. A primeira carga acontece ao executar o fluxo.');
  const reload = async () => {
    const yes = await confirmDialog({ title: 'Reler tudo do Jira?', message: 'Refaz a carga inteira. É o que remove daqui o que foi excluído no Jira.', confirm: 'Reler tudo' });
    if (!yes) return;
    line.textContent = 'Relendo do Jira…';
    try {
      const res = await api.reloadJiraQuery(query.id);
      toast(`${fmt.int(res.rows)} linhas relidas do Jira`, { kind: 'success' });
      await refreshJira();
      onChange?.();
    } catch (err) {
      line.textContent = err.message;
    }
  };
  const forget = async () => {
    await api.forgetJiraQuery(query.id);
    toast('Guardado local apagado', { kind: 'success' });
    await refreshJira();
    onChange?.();
  };
  return h('div', { class: 'stack-xs jira-status' }, line, h('div', { class: 'row' },
    button({ icon: 'refresh', label: 'Reler tudo', size: 'sm', onClick: reload }),
    when ? button({ icon: 'trash', label: 'Apagar o guardado', size: 'sm', variant: 'ghost', onClick: forget }) : null));
}

function tablePicker(state, redraw) {
  return h('div', { class: 'jira-tables', role: 'radiogroup', 'aria-label': 'O que trazer' }, TABLES.map(([value, name, about, ic]) => h('button', {
    type: 'button', role: 'radio', 'aria-checked': String(state.table === value), class: ['jira-table', state.table === value && 'on'], dataset: { table: value },
    onclick: () => { state.table = value; redraw(); },
  }, h('span', { class: 'jira-table-head' }, icon(ic, 14), h('b', {}, name)), h('small', {}, about))));
}

function filterControls(state, catalog, redraw) {
  const toggle = (key) => (value) => {
    state[key] = state[key].includes(value) ? state[key].filter((x) => x !== value) : [...state[key], value];
    redraw();
  };
  return [
    field('Projetos', chips(catalog.projects, state.projects, toggle('projects'), (p) => `${p.name} (${p.key})`, (p) => p.key)),
    field('Tipos', chips(catalog.issue_types, state.issue_types, toggle('issue_types')), 'Nenhum marcado: todos.'),
    field('Status', chips(catalog.statuses, state.statuses, toggle('statuses')), 'Nenhum marcado: todos.'),
    field('Período', h('div', { class: 'row' },
      h('select', { class: 'input', 'aria-label': 'Data usada no período', onchange: (e) => { state.period_field = e.target.value; redraw(); } },
        [['created', 'Criadas'], ['updated', 'Atualizadas'], ['resolved', 'Resolvidas']].map(([v, t]) => h('option', { value: v, selected: state.period_field === v }, t))),
      h('select', { class: 'input', 'aria-label': 'Período', onchange: (e) => { state.period_days = Number(e.target.value); redraw(); } },
        PERIODS.map(([v, t]) => h('option', { value: v, selected: state.period_days === v }, t))))),
  ];
}

function jqlText(state) {
  if (state.advanced) return state.jql;
  const q = (v) => `"${v.replace(/"/g, '\\"')}"`;
  const parts = [];
  if (state.projects.length) parts.push(`project in (${state.projects.map(q).join(', ')})`);
  if (state.issue_types.length) parts.push(`issuetype in (${state.issue_types.map(q).join(', ')})`);
  if (state.statuses.length) parts.push(`status in (${state.statuses.map(q).join(', ')})`);
  if (state.period_days) parts.push(`${state.period_field} >= -${state.period_days}d`);
  return parts.length ? `${parts.join(' AND ')} ORDER BY created ASC` : '';
}

/** Consulta: o que trazer, de quais projetos e com quais filtros, com a prévia antes de salvar. */
export function jiraQueryEditor({ query = null, connectionId = '', onSaved }, host) {
  const state = {
    name: query?.name || '', connection: query?.connection || connectionId || store.jiraConnections[0]?.id || '', table: query?.table || 'issues',
    projects: query?.projects || [], issue_types: query?.issue_types || [], statuses: query?.statuses || [], period_field: query?.period_field || 'created',
    period_days: query?.period_days || 0, advanced: query?.advanced || false, jql: query?.jql || '', fields: query?.fields || [],
  };
  let catalog = null;
  const form = h('div', { class: 'stack-md jira-form' }, h('p', { class: 'muted' }, 'Lendo os projetos do Jira…'));
  const meta = h('div', { class: 'jira-meta' });
  const grid = h('div', { class: 'jira-grid' });
  const preview = debounce(async () => {
    if (!jqlText(state)) { meta.replaceChildren(h('span', { class: 'muted' }, 'Escolha ao menos um projeto para ver a prévia.')); grid.replaceChildren(); return; }
    meta.replaceChildren(h('span', { class: 'muted' }, 'Consultando o Jira…'));
    try {
      const res = await api.previewJira(definition(state));
      meta.replaceChildren(h('span', { class: 'badge' }, icon('check', 12), `cerca de ${fmt.int(res.total)} demandas`), h('span', { class: 'muted' }, `prévia de ${fmt.int(res.rows.length)} linhas`));
      grid.replaceChildren(previewTable(res.columns, res.rows));
    } catch (err) {
      meta.replaceChildren(h('span', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
      grid.replaceChildren();
    }
  }, 400);
  const jqlBox = h('code', { class: 'jira-jql' });
  const redraw = () => {
    if (!catalog) return;
    jqlBox.textContent = jqlText(state) || 'Escolha ao menos um projeto';
    form.replaceChildren(...[
      field('Nome da consulta', h('input', { class: 'input', value: state.name, placeholder: 'Ex.: Demandas do time de Dados', oninput: (e) => { state.name = e.target.value; } })),
      store.jiraConnections.length > 1 ? field('Conexão', h('select', { class: 'input', onchange: (e) => { state.connection = e.target.value; load(); } },
        store.jiraConnections.map((c) => h('option', { value: c.id, selected: c.id === state.connection }, c.name)))) : null,
      field('O que trazer', tablePicker(state, redraw)),
      state.table === 'comments' ? h('p', { class: 'field-warn' }, icon('alert', 13), ' Comentários costumam ter nomes e dados pessoais. Traga só se precisar, e use o rótulo certo ao compartilhar.') : null,
      h('label', { class: 'jira-advanced' }, h('input', { type: 'checkbox', checked: state.advanced, onchange: (e) => { state.advanced = e.target.checked; if (e.target.checked && !state.jql) state.jql = jqlText({ ...state, advanced: false }); redraw(); } }), ' Escrever o JQL à mão'),
      ...(state.advanced
        ? [field('JQL', h('textarea', { class: 'input code', rows: 4, spellcheck: false, 'aria-label': 'JQL', oninput: (e) => { state.jql = e.target.value; preview(); } }, state.jql))]
        : [...filterControls(state, catalog, redraw), field('O filtro em JQL', jqlBox, 'Montado sozinho a partir das escolhas acima.')]),
      state.table === 'issues' && catalog.fields.length ? field('Campos personalizados', chips(catalog.fields, state.fields, (id) => { state.fields = state.fields.includes(id) ? state.fields.filter((x) => x !== id) : [...state.fields, id]; redraw(); }, (f) => f.name, (f) => f.id)) : null,
      query ? queryStatus(store.jiraQueries.find((q) => q.id === query.id) || query, () => host.close()) : null,
      h('div', { class: 'stack-xs' }, meta, grid),
    ].filter(Boolean));
    preview();
  };
  const load = async () => {
    try {
      catalog = await api.jiraCatalog(state.connection);
      redraw();
    } catch (err) {
      form.replaceChildren(h('p', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
    }
  };
  load();
  const save = async () => {
    const name = state.name.trim();
    if (!name) { toast('Dê um nome à consulta', { kind: 'error' }); return; }
    try {
      const saved = await api.saveJiraQuery({ id: query?.id || newId('consulta'), name, ...definition(state) });
      await refreshJira();
      toast(`Consulta ${saved.name} salva`, { kind: 'success' });
      host.close();
      onSaved?.(saved);
    } catch (err) {
      toastError(err, 'Não foi possível salvar a consulta');
    }
  };
  return {
    title: query ? `Editar consulta · ${query.name}` : 'Nova consulta do Jira',
    body: form,
    actions: [button({ label: 'Cancelar', onClick: () => host.close() }), button({ label: 'Salvar', variant: 'primary', onClick: save })],
  };
}
