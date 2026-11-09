// Fontes de dados num só formato (spec 028): arquivos, consultas, APIs e conexões, com tipo, situação e uso.
// A vista Dados e o painel lateral do Designer leem daqui, para mostrarem sempre a mesma coisa.

import { api } from './api.js';
import { placeholdersOf } from './apis.js';
import { showValue, TYPES } from './constants.js';
import { fmt } from './dom.js';
import { API_PREFIX, JIRA_PREFIX, QUERY_PREFIX, store } from './store.js';

export const KINDS = {
  file: { title: 'Arquivos', one: 'arquivo', color: 'var(--cat-inout)', icon: 'file' },
  query: { title: 'Consultas de banco', one: 'consulta', color: 'var(--cat-transform)', icon: 'server' },
  api: { title: 'APIs', one: 'API', color: 'var(--cat-ml)', icon: 'globe' },
  jira: { title: 'Consultas do Jira', one: 'consulta do Jira', color: 'var(--cat-transform)', icon: 'list' },
  jiraconn: { title: 'Conexões com o Jira', one: 'conexão com o Jira', color: 'var(--cat-org)', icon: 'link' },
  conn: { title: 'Conexões com bancos', one: 'conexão', color: 'var(--cat-org)', icon: 'database' },
  const: { title: 'Constantes', one: 'constante compartilhada', color: 'var(--cat-bi)', icon: 'hash' },
};

const JIRA_TABLES = { issues: 'Demandas', history: 'Histórico', comments: 'Comentários' };
const FORMAT_LABELS = { csv: 'CSV', excel: 'Excel', parquet: 'Parquet', json: 'JSON', ndjson: 'JSON Lines', arrow: 'Arrow' };
const DB_LABELS = { postgres: 'PostgreSQL', sqlserver: 'SQL Server' };

/** Onde cada fonte é usada, nos fluxos da biblioteca. Atualizado ao abrir a vista e depois de salvar. */
export const usage = { map: {}, loaded: false };

export async function refreshUsage() {
  try {
    usage.map = await api.usage();
  } catch {
    usage.map = {};
  }
  usage.loaded = true;
  return usage.map;
}

const ok = { label: 'ok', tone: 'ok' };

function hostOf(url) {
  try { return new URL(url.replace(/\{[^}]*\}/g, 'x')).hostname; } catch { return url; }
}

/** Usos de uma fonte: por fluxo, com as caixas que a leem e o que vem depois. */
export function usesOf(source) {
  if (source.kind !== 'conn') return usage.map[source.usageKey] || [];
  // Conexão: é usada pelas consultas dela, e cada consulta pelos seus fluxos.
  const byFlow = new Map();
  for (const q of store.queries.filter((x) => x.connection === source.id)) {
    for (const entry of usage.map[`${QUERY_PREFIX}${q.id}`] || []) {
      const seen = byFlow.get(entry.workflow_id);
      if (seen) {
        seen.readers.push(...entry.readers);
        seen.downstream.push(...entry.downstream.filter((d) => !seen.downstream.some((x) => x.id === d.id)));
      } else {
        byFlow.set(entry.workflow_id, { ...entry, readers: [...entry.readers], downstream: [...entry.downstream] });
      }
    }
  }
  return [...byFlow.values()];
}

/** Todas as fontes, já com o que a tela precisa: nome, detalhe, situação e chave de uso. */
export function allSources() {
  const out = [];
  for (const d of store.datasets) {
    out.push({
      kind: 'file', key: `file:${d.name}`, id: d.name, usageKey: d.name, name: d.name, raw: d,
      meta: d.missing ? `não encontrado: ${d.linked_path}`
        : d.linked_path ? `vinculado · ${FORMAT_LABELS[d.format] || d.format}`
          : `${FORMAT_LABELS[d.format] || d.format} · ${fmt.bytes(d.size_bytes)}`,
      state: d.missing ? { label: 'não encontrado', tone: 'err' } : d.linked_path ? { label: 'vinculado', tone: 'info' } : ok,
      draggable: !d.missing, dragValue: d.name,
    });
  }
  for (const q of store.queries) {
    const conn = store.connections.find((c) => c.id === q.connection);
    out.push({
      kind: 'query', key: `query:${q.id}`, id: q.id, usageKey: `${QUERY_PREFIX}${q.id}`, name: q.name, raw: q,
      meta: `${conn ? conn.name : 'conexão excluída'} · ${q.mode === 'table' ? q.table : 'SQL escrito'}`,
      state: conn ? ok : { label: 'sem conexão', tone: 'err' },
      draggable: Boolean(conn), dragValue: `${QUERY_PREFIX}${q.id}`,
    });
  }
  for (const a of store.apis) {
    const wants = placeholdersOf(a);
    out.push({
      kind: 'api', key: `api:${a.id}`, id: a.id, usageKey: `${API_PREFIX}${a.id}`, name: a.name, raw: a,
      meta: `${hostOf(a.url)}${wants.length ? ` · variável ${wants.map((w) => `{${w}}`).join(', ')}` : ''}`,
      state: a.missing_secrets?.length ? { label: 'falta segredo', tone: 'warn' } : ok,
      draggable: !wants.length, dragValue: `${API_PREFIX}${a.id}`, loop: wants.length > 0,
    });
  }
  for (const q of store.jiraQueries) {
    const conn = store.jiraConnections.find((c) => c.id === q.connection);
    out.push({
      kind: 'jira', key: `jira:${q.id}`, id: q.id, usageKey: `${JIRA_PREFIX}${q.id}`, name: q.name, raw: q,
      meta: `${JIRA_TABLES[q.table]}${q.rows !== null && q.rows !== undefined ? ` · ${fmt.int(q.rows)} linhas` : ''}`,
      state: !conn ? { label: 'sem conexão', tone: 'err' } : !conn.has_token ? { label: 'falta token', tone: 'warn' } : q.interrupted ? { label: 'carga parada', tone: 'warn' } : ok,
      draggable: Boolean(conn), dragValue: `${JIRA_PREFIX}${q.id}`,
    });
  }
  for (const c of store.jiraConnections) {
    out.push({
      kind: 'jiraconn', key: `jiraconn:${c.id}`, id: c.id, usageKey: null, name: c.name, raw: c, meta: c.site,
      state: c.has_token ? ok : { label: 'falta token', tone: 'warn' }, draggable: false,
    });
  }
  for (const c of store.connections) {
    out.push({
      kind: 'conn', key: `conn:${c.id}`, id: c.id, usageKey: null, name: c.name, raw: c,
      meta: `${DB_LABELS[c.kind] || c.kind} · ${c.host}/${c.database}`,
      state: c.has_password ? ok : { label: 'sem senha', tone: 'warn' },
      draggable: false,
    });
  }
  for (const c of store.constants) {
    out.push({
      kind: 'const', key: `const:${c.name}`, id: c.name, usageKey: `const:${c.name}`, name: c.name, raw: c,
      meta: `${TYPES[c.type]} · ${showValue(c)}`, state: ok, draggable: false,
    });
  }
  return out;
}

/** "usada em 2 fluxos" ou "sem uso": o selo do cartão. */
export function usageText(source) {
  const n = usesOf(source).length;
  return n ? `usada em ${n} fluxo${n > 1 ? 's' : ''}` : 'sem uso';
}

export function matches(source, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return `${source.name} ${source.meta} ${source.raw?.description || ''}`.toLowerCase().includes(q)
    || usesOf(source).some((u) => u.workflow.toLowerCase().includes(q));
}
