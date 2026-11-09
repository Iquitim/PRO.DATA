// Consulta do Jira em passos (spec 031): o que trazer, de quais projetos, filtros e conferência.

import { api } from './api.js';
import { previewTable } from './datasets.js';
import { button, debounce, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { field, newId, refreshJira, step } from './jira_ui.js';
import { store } from './store.js';
import { confirmDialog, toast, toastError } from './ui.js';

const TABLES = [
  ['issues', 'Demandas', 'Uma linha por demanda, com status, responsável e datas.', 'list'],
  ['history', 'Histórico de alterações', 'Uma linha por mudança: quem mudou o quê e quando.', 'clock'],
  ['comments', 'Comentários', 'Uma linha por comentário. Costumam ter dados pessoais.', 'edit'],
];
const WHAT = { issues: 'as demandas', history: 'o histórico das demandas', comments: 'os comentários das demandas' };
const PERIODS = [[0, 'Sem limite de data'], [30, 'Últimos 30 dias'], [90, 'Últimos 90 dias'], [180, 'Últimos 6 meses'], [365, 'Último ano'], [730, 'Últimos 2 anos']];
const DATES = [['created', 'Criadas'], ['updated', 'Atualizadas'], ['resolved', 'Resolvidas']];
const CATEGORIES = [['new', 'A fazer'], ['indeterminate', 'Em andamento'], ['done', 'Concluído'], ['', 'Outros']];
const SHOWN_PROJECTS = 30;

const fold = (text) => String(text ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const unique = (list) => [...new Set(list)].sort((a, b) => a.localeCompare(b, 'pt-BR'));
const listText = (list) => (list.length < 2 ? list.join('') : `${list.slice(0, -1).join(', ')} e ${list.at(-1)}`);
const toggled = (list, value) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

const definition = (q) => ({
  connection: q.connection, table: q.table, projects: q.projects, issue_types: q.issue_types, statuses: q.statuses,
  assignees: [], period_field: q.period_field, period_days: q.period_days, advanced: q.advanced, jql: q.jql, fields: q.fields,
});

function chip(label, on, onClick) {
  return h('button', { type: 'button', class: ['value-chip', on && 'on'], 'aria-pressed': String(on), onclick: onClick },
    icon(on ? 'check' : 'plus', 12), h('span', { class: 'ellipsis' }, label));
}

const chips = (list, selected, onToggle) => h('div', { class: 'value-list jira-chips' },
  list.map((value) => chip(value, selected.includes(value), () => onToggle(value))));

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

function queryStatus(query, onChange) {
  const when = query.synced_at ? new Date(query.synced_at).toLocaleString('pt-BR') : null;
  const line = h('p', { class: 'field-help' }, when
    ? `Guardada aqui: ${fmt.int(query.rows)} linhas, atualizada em ${when}.`
    : query.interrupted ? 'A última carga parou no meio: a próxima continua de onde ficou.' : 'Ainda não foi carregada. A primeira carga acontece ao executar o fluxo.');
  const reload = async () => {
    const yes = await confirmDialog({ title: 'Reler tudo do Jira?', message: 'Refaz a carga inteira. Raramente é preciso: o que sai da consulta já some a cada atualização.', confirm: 'Reler tudo' });
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

/** Busca e escolha de projetos. Digitar só refaz a lista, para o campo não perder o foco. */
function projectPicker(state, catalog, onChange) {
  const nameOf = (key) => catalog.projects.find((p) => p.key === key)?.name || key;
  const list = h('div', { class: 'value-list jira-chips jira-projects' });
  const drawList = () => {
    const words = fold(state.search).split(/\s+/).filter(Boolean);
    const found = catalog.projects.filter((p) => !state.projects.includes(p.key) && words.every((w) => fold(`${p.name} ${p.key}`).includes(w)));
    list.replaceChildren(...found.slice(0, SHOWN_PROJECTS).map((p) => chip(`${p.name} (${p.key})`, false, () => { state.search = ''; onChange([...state.projects, p.key]); })));
    if (!found.length) list.append(h('p', { class: 'field-help' }, state.search ? 'Nenhum projeto com esse nome.' : 'Todos os projetos já foram escolhidos.'));
    if (found.length > SHOWN_PROJECTS) list.append(h('p', { class: 'field-help' }, `Mais ${fmt.int(found.length - SHOWN_PROJECTS)} projetos. Digite para encontrar o seu.`));
  };
  const search = h('input', {
    class: 'input input-search', type: 'search', value: state.search, 'aria-label': 'Buscar projeto',
    placeholder: `Buscar entre ${fmt.int(catalog.projects.length)} projetos`,
    oninput: (e) => { state.search = e.target.value; drawList(); },
  });
  drawList();
  return h('div', { class: 'stack-xs' },
    state.projects.length ? h('div', { class: 'value-list jira-chips jira-chosen', 'aria-label': 'Projetos escolhidos' },
      state.projects.map((key) => chip(`${nameOf(key)} (${key})`, true, () => onChange(state.projects.filter((x) => x !== key))))) : null,
    search, list);
}

function statusGroups(statuses, selected, categories, onToggle) {
  return h('div', { class: 'stack-xs' }, CATEGORIES.map(([key, title]) => {
    const group = statuses.filter((s) => (CATEGORIES.some(([k]) => k && k === categories[s]) ? categories[s] : '') === key);
    return group.length ? h('div', { class: 'jira-status-group' }, h('small', {}, title), chips(group, selected, onToggle)) : null;
  }).filter(Boolean));
}

/** Uma frase com o que vai ser trazido, para conferir sem ler JQL. */
function summaryText(state, catalog) {
  if (state.advanced) return 'Vai trazer o que o JQL acima pedir.';
  const names = state.projects.map((key) => catalog.projects.find((p) => p.key === key)?.name || key);
  let text = `Vai trazer ${WHAT[state.table]} de ${listText(names)}`;
  if (state.issue_types.length) text += `, do tipo ${listText(state.issue_types)}`;
  if (state.statuses.length) text += `, no status ${listText(state.statuses)}`;
  if (state.period_days) {
    const period = PERIODS.find(([v]) => v === state.period_days)[1].toLowerCase();
    text += `, ${DATES.find(([v]) => v === state.period_field)[1].toLowerCase()} nos ${period}`;
  }
  return `${text}.`;
}

/** Consulta em passos: cada um só aparece quando o anterior já tem o que precisa. */
export function jiraQueryEditor({ query = null, connectionId = '', onSaved }, host) {
  const state = {
    name: query?.name || '', connection: query?.connection || connectionId || store.jiraConnections[0]?.id || '', table: query?.table || 'issues',
    projects: query?.projects || [], issue_types: query?.issue_types || [], statuses: query?.statuses || [], period_field: query?.period_field || 'created',
    period_days: query?.period_days || 0, advanced: query?.advanced || false, jql: query?.jql || '', fields: query?.fields || [],
    search: '', more: Boolean(query?.advanced || query?.fields?.length),
  };
  let catalog = null;
  const scopes = new Map();
  const form = h('div', { class: 'stack-md jira-form' }, h('p', { class: 'muted' }, 'Lendo os projetos do Jira…'));
  const meta = h('div', { class: 'jira-meta' });
  const grid = h('div', { class: 'jira-grid' });

  const options = () => {
    const known = state.projects.map((key) => scopes.get(key));
    if (known.some((s) => !s)) return { loading: true, types: [], statuses: [] };
    if (known.some((s) => !s.available)) return { partial: true, types: catalog.issue_types, statuses: catalog.statuses };
    const all = known.flatMap((s) => s.issue_types);
    const chosen = state.issue_types.length ? all.filter((t) => state.issue_types.includes(t.name)) : all;
    return { types: unique(all.map((t) => t.name)), statuses: unique(chosen.flatMap((t) => t.statuses)) };
  };
  const prune = () => {
    const { loading, types } = options();
    if (loading) return;
    state.issue_types = state.issue_types.filter((t) => types.includes(t));
    const { statuses } = options(); // depende dos tipos que sobraram
    state.statuses = state.statuses.filter((s) => statuses.includes(s));
  };
  const loadScopes = async () => {
    const missing = state.projects.filter((key) => !scopes.has(key));
    if (!missing.length) return;
    await Promise.all(missing.map((key) => api.jiraScope(state.connection, key)
      .catch(() => ({ available: false, issue_types: [] }))
      .then((scope) => scopes.set(key, scope))));
    redraw();
  };
  const preview = debounce(async () => {
    if (!jqlText(state)) { meta.replaceChildren(); grid.replaceChildren(); return; }
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

  const filtersStep = () => {
    const { loading, partial, types, statuses } = options();
    if (loading) return h('p', { class: 'muted' }, 'Lendo os tipos e status dos projetos escolhidos…');
    const names = listText(state.projects);
    return h('div', { class: 'stack-sm' },
      h('p', { class: 'field-help' }, partial
        ? 'O Jira não informou os status de algum projeto escolhido. Aparecem os do Jira inteiro.'
        : `Só aparecem os tipos e status que existem em ${names}. Sem nada marcado, vem tudo.`),
      field('Tipos', chips(types, state.issue_types, (v) => { state.issue_types = toggled(state.issue_types, v); redraw(); })),
      statuses.length ? field('Status', statusGroups(statuses, state.statuses, catalog.status_categories || {}, (v) => { state.statuses = toggled(state.statuses, v); redraw(); })) : null,
      field('Período', h('div', { class: 'row' },
        h('select', { class: 'input', 'aria-label': 'Data usada no período', onchange: (e) => { state.period_field = e.target.value; redraw(); } },
          DATES.map(([v, t]) => h('option', { value: v, selected: state.period_field === v }, t))),
        h('select', { class: 'input', 'aria-label': 'Período', onchange: (e) => { state.period_days = Number(e.target.value); redraw(); } },
          PERIODS.map(([v, t]) => h('option', { value: v, selected: state.period_days === v }, t))))));
  };

  const moreOptions = () => {
    const generated = jqlText({ ...state, advanced: false });
    return h('details', { class: 'jira-more', ...(state.more ? { open: true } : {}), ontoggle: (e) => { state.more = e.target.open; } },
      h('summary', {}, 'Mais opções'),
      h('div', { class: 'stack-sm' },
        h('label', { class: 'jira-advanced' }, h('input', {
          type: 'checkbox', checked: state.advanced,
          onchange: (e) => { state.advanced = e.target.checked; if (state.advanced && !state.jql) state.jql = generated; redraw(); },
        }), ' Escrever o JQL à mão'),
        state.advanced
          ? field('JQL', h('textarea', { class: 'input code', rows: 4, spellcheck: false, 'aria-label': 'JQL', oninput: (e) => { state.jql = e.target.value; preview(); } }, state.jql))
          : field('O filtro em JQL', h('code', { class: 'jira-jql' }, generated || 'Escolha ao menos um projeto'), 'Montado sozinho a partir das escolhas acima.'),
        state.table === 'issues' && catalog.fields.length ? field('Campos personalizados', h('div', { class: 'value-list jira-chips' },
          catalog.fields.map((f) => chip(f.name, state.fields.includes(f.id), () => { state.fields = toggled(state.fields, f.id); redraw(); })))) : null));
  };

  function redraw() {
    if (!catalog) return;
    prune();
    const ready = state.advanced ? Boolean(state.jql.trim()) : state.projects.length > 0;
    let n = 1;
    const projectsOn = (projects) => { state.projects = projects; loadScopes(); redraw(); };
    const steps = [
      step(n++, 'O que você quer trazer?', h('div', { class: 'stack-xs' },
        store.jiraConnections.length > 1 ? field('Conexão', h('select', { class: 'input', onchange: (e) => { state.connection = e.target.value; scopes.clear(); load(); } },
          store.jiraConnections.map((c) => h('option', { value: c.id, selected: c.id === state.connection }, c.name)))) : null,
        tablePicker(state, redraw),
        state.table === 'comments' ? h('p', { class: 'field-warn' }, icon('alert', 13), ' Comentários costumam ter nomes e dados pessoais. Traga só se precisar, e use o rótulo certo ao compartilhar.') : null)),
    ];
    if (!state.advanced) {
      steps.push(step(n++, 'De quais projetos?', projectPicker(state, catalog, projectsOn)));
      if (state.projects.length) steps.push(step(n++, 'Quer filtrar?', filtersStep()));
    }
    if (ready) {
      steps.push(step(n++, 'Confira e dê um nome', h('div', { class: 'stack-sm' },
        h('p', { class: 'jira-summary' }, summaryText(state, catalog)),
        h('div', { class: 'stack-xs' }, meta, grid),
        field('Nome da consulta', h('input', { class: 'input', value: state.name, placeholder: 'Ex.: Demandas do time de Dados', oninput: (e) => { state.name = e.target.value; } })))));
    }
    form.replaceChildren(...[
      h('ol', { class: 'jira-steps' }, steps),
      moreOptions(),
      query ? queryStatus(store.jiraQueries.find((q) => q.id === query.id) || query, () => host.close()) : null,
    ].filter(Boolean));
    if (ready) preview();
  }

  async function load() {
    try {
      catalog = await api.jiraCatalog(state.connection);
      loadScopes();
      redraw();
    } catch (err) {
      form.replaceChildren(h('p', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
    }
  }
  load();

  const save = async () => {
    const name = state.name.trim();
    if (!jqlText(state)) { toast('Escolha ao menos um projeto', { kind: 'error' }); return; }
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
