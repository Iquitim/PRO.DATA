// Constantes (spec 028, RF-2841..2850): um valor com nome, escrito [#nome], trocado num lugar só.
// Do fluxo: ficam no arquivo do fluxo. Compartilhadas: cadastradas na vista Dados, valem para todos os fluxos.
// Este módulo só tem os dados; o cadastro e os diálogos ficam em constants_ui.js.

import { api } from './api.js';
import { API_PREFIX, commit, emit, store } from './store.js';

export const TYPES = { date: 'Data', number: 'Número', text: 'Texto' };
export const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const REF = /\[#([A-Za-z_][A-Za-z0-9_]{0,63})\]/g;
const LITERAL = /'(?:[^']|'')*'|"(?:[^"]|"")*"/g;
// Campos de texto que aceitam constante além das fórmulas (iguais aos do servidor, engine/constants.py).
const RAW_FIELDS = new Set(['prep.filter:value', 'io.output_data:filename']);

export async function refreshConstants() {
  store.constants = await api.constants();
  emit('constants');
}

/** Constantes que este fluxo enxerga: as compartilhadas e as dele (as dele aparecem com `scope: 'flow'`). */
/** Constantes do sistema (spec 029, RF-2995): sempre disponíveis, sem cadastro; o nome é reservado. */
const localDay = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
export const SYSTEM_CONSTANTS = {
  hoje: () => ({ name: 'hoje', type: 'date', value: localDay(), scope: 'system', description: 'A data de hoje. Muda sozinha a cada dia.' }),
};

export function knownConstants() {
  const out = new Map(Object.entries(SYSTEM_CONSTANTS).map(([name, make]) => [name, make()]));
  // Um fluxo antigo com uma constante própria chamada "hoje" continua usando a dele (o motor avisa).
  for (const c of store.constants || []) out.set(c.name, { ...c, scope: 'shared' });
  for (const c of store.workflow?.constants || []) {
    out.set(c.name, { ...c, scope: out.get(c.name)?.scope === 'shared' ? 'conflict' : 'flow' });
  }
  return out;
}

const refsIn = (text, formula) => {
  const clean = formula ? text.replace(LITERAL, '') : text; // '[#x]' entre aspas é texto, não constante
  return [...clean.matchAll(REF)].map((m) => m[1]);
};

function apiTexts(node) {
  const id = node.type === 'io.api_loop' ? node.config?.source
    : node.type === 'io.input_data' && String(node.config?.dataset || '').startsWith(API_PREFIX)
      ? node.config.dataset.slice(API_PREFIX.length) : null;
  const a = id ? store.apis.find((x) => x.id === id) : null;
  if (!a) return [];
  return [a.url, ...a.params.filter((p) => !p.secret).map((p) => p.value), ...a.headers.filter((p) => !p.secret).map((p) => p.value)];
}

/** Nomes citados por uma caixa: nas fórmulas, no valor do Filter, no nome do arquivo de saída e na API dela. */
export function nodeRefs(node) {
  const found = new Set();
  const walk = (obj) => {
    if (Array.isArray(obj)) { obj.forEach(walk); return; }
    if (!obj || typeof obj !== 'object') return;
    for (const [key, value] of Object.entries(obj)) {
      if (typeof value === 'string' && (key === 'expression' || RAW_FIELDS.has(`${node.type}:${key}`))) {
        for (const name of refsIn(value, key === 'expression')) found.add(name);
      } else {
        walk(value);
      }
    }
  };
  walk(node.config);
  for (const text of apiTexts(node)) for (const name of refsIn(text || '', false)) found.add(name);
  return found;
}

/** Caixas do fluxo aberto que usam cada constante: `Map(nome → [caixa])`. */
export function flowRefs(workflow = store.workflow) {
  const out = new Map();
  for (const node of workflow?.nodes || []) {
    for (const name of nodeRefs(node)) out.set(name, [...(out.get(name) || []), node]);
  }
  return out;
}

/** Uma constante mudou: as caixas que a usam (e as de depois) ficam pendentes no fluxo aberto. */
export function markChanged(...names) {
  const refs = flowRefs();
  const ids = names.flatMap((n) => (refs.get(n) || []).map((node) => node.id));
  if (ids.length) commit({ affects: ids });
}

/** Problema do valor para o tipo, em português; vazio quando está certo. */
export function valueProblem(type, value) {
  const v = String(value ?? '').trim();
  if (type === 'number' && !/^-?\d+([.,]\d+)?$/.test(v)) return 'Use um número, como 1500 ou 0,15.';
  if (type === 'date') {
    const ok = /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(`${v}T00:00:00Z`))
      && new Date(`${v}T00:00:00Z`).toISOString().startsWith(v);
    if (!ok) return 'Escolha uma data válida.';
  }
  return '';
}

/** O valor como aparece para a pessoa: data em dd/mm/aaaa, o resto como está. */
export function showValue(c) {
  if (c.type === 'date' && /^\d{4}-\d{2}-\d{2}$/.test(c.value)) return c.value.split('-').reverse().join('/');
  return c.value === '' ? '(vazio)' : c.value;
}

/** Troca [#antigo] por [#novo] nas caixas do fluxo, ao renomear uma constante do fluxo. */
export function renameRefs(workflow, from, to) {
  const swap = (text) => text.split(`[#${from}]`).join(`[#${to}]`);
  const walk = (node, obj) => {
    if (Array.isArray(obj)) { obj.forEach((v) => walk(node, v)); return; }
    if (!obj || typeof obj !== 'object') return;
    for (const [key, value] of Object.entries(obj)) {
      if (typeof value === 'string' && (key === 'expression' || RAW_FIELDS.has(`${node.type}:${key}`))) obj[key] = swap(value);
      else walk(node, value);
    }
  };
  for (const node of workflow.nodes) walk(node, node.config);
}
