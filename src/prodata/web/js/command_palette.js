// Busca de comandos (spec 029, RF-2982): Ctrl+K acha ferramentas, caixas do fluxo, ações, fontes e capítulos.

import { addNode } from './actions.js';
import { revealNode, viewportCenter } from './canvas.js';
import { allSources, KINDS } from './data_sources.js';
import { openInData } from './data_view.js';
import { h } from './dom.js';
import { icon } from './icons.js';
import { inspect, select, store, toolOf } from './store.js';

// O que as pessoas digitam quando não lembram o nome em inglês da ferramenta.
const SYNONYMS = {
  'transform.join': 'juntar unir combinar cruzar procv tabelas chave',
  'transform.union': 'empilhar unir anexar linhas',
  'transform.append': 'acrescentar colunas cruzar todas',
  'transform.summarize': 'somar agrupar resumir totalizar media contar',
  'transform.crosstab': 'pivot dinamica cruzada',
  'transform.transpose': 'unpivot despivotar girar',
  'transform.running_total': 'acumulado soma',
  'transform.sql_query': 'consulta select',
  'prep.filter': 'filtrar condicao separar',
  'prep.formula': 'calcular coluna nova conta',
  'prep.multirow': 'linha anterior acumular',
  'prep.select': 'colunas renomear escolher tirar',
  'prep.sort': 'ordenar classificar',
  'prep.regex': 'expressao regular extrair padrao texto',
  'prep.multi_field': 'varias colunas formula de uma vez',
  'prep.mask': 'mascarar anonimizar lgpd cpf cnpj email dados pessoais',
  'io.input_folder': 'pasta varios arquivos empilhar mes',
  'io.generate_rows': 'calendario datas sequencia gerar linhas',
  'transform.fuzzy_match': 'aproximado parecido razao social endereco procv',
  'control.reconcile': 'conciliar conferir totais fechar bater',
  'control.compare_runs': 'comparar anterior mes passado o que mudou diferenca',
  'flow.subflow': 'macro reutilizar etapa outro fluxo',
  'ml.model_input': 'importar modelo salvo pickle treinado biblioteca',
  'flow.input': 'macro entrada subfluxo',
  'flow.output': 'macro saida subfluxo',
  'prep.unique': 'duplicados repetidos distintos',
  'prep.sample': 'amostra primeiras linhas',
  'prep.cleanse': 'limpar espacos nulos padronizar',
  'prep.data_quality': 'qualidade validar conferir cpf cnpj regras',
  'prep.text_to_columns': 'dividir separar quebrar',
  'prep.record_id': 'numerar sequencia',
  'io.input_data': 'ler abrir arquivo planilha',
  'io.output_data': 'gravar salvar exportar excel',
  'io.text_input': 'digitar tabela de-para',
  'io.api_loop': 'chamar repetir',
  'bi.chart': 'grafico barras linha pizza',
  'bi.kpi_card': 'indicador numero meta',
  'ml.automl_trainer': 'treinar modelo previsao',
  'ml.predictor': 'prever pontuar score',
};
const GROUP_LIMIT = 5;
const fold = (text) => String(text ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const stem = (word) => (word.length > 4 ? word.replace(/(ando|endo|indo|ar|er|ir|s)$/, '') : word);

let handlers = {};
let openDialogEl = null;

function toolEntries() {
  return store.catalog.tools.filter((t) => !t.hidden).map((t) => ({
    group: 'Ferramentas', icon: t.icon, name: t.name, detail: t.description, end: 'adicionar ao fluxo', keywords: SYNONYMS[t.type] || '',
    run: () => {
      handlers.setView('designer');
      const c = viewportCenter();
      const added = addNode(t.type, c.x - 80, c.y - 28);
      if (added) { select(added.id); inspect(added.id); }
    },
  }));
}

function boxEntries() {
  return (store.workflow?.nodes || []).map((n) => {
    const tool = toolOf(n);
    return {
      group: 'Caixas deste fluxo', icon: tool?.icon || 'info', name: n.label || tool?.name || n.id, detail: tool?.name, end: 'selecionar',
      run: () => { handlers.setView('designer'); select(n.id); inspect(n.id); revealNode(n.id); },
    };
  });
}

function sourceEntries() {
  return allSources().map((s) => ({
    group: 'Fontes', icon: KINDS[s.kind]?.icon || 'file', name: s.name, detail: KINDS[s.kind]?.one, end: 'abrir em Dados',
    run: () => { openInData(s.key); handlers.setView('data'); },
  }));
}

function allEntries() {
  const actions = handlers.commands().map((c) => ({ ...c, group: 'Ações' }));
  return [...toolEntries(), ...boxEntries(), ...actions, ...sourceEntries(), ...(handlers.manualEntries?.() || [])]
    .map((e) => ({ ...e, nameKey: fold(e.name), wordsKey: fold(e.keywords || ''), textKey: fold(`${e.name} ${e.detail || ''} ${e.keywords || ''}`) }));
}

/** 0: o nome começa com o que foi digitado; 1: o nome contém; 2: é um sinônimo; 3: só aparece na descrição. */
function rank(entry, query, words) {
  if (!words.every((w) => entry.textKey.includes(w) || entry.textKey.includes(stem(w)))) return null;
  if (entry.nameKey.startsWith(query)) return 0;
  if (entry.nameKey.includes(query)) return 1;
  return words.every((w) => entry.wordsKey.includes(w)) ? 2 : 3;
}

/** Quantas palavras aparecem inteiras no nome: desempata "clientes vendas" a favor de "Clientes × vendas". */
const nameHits = (entry, words) => words.filter((w) => entry.nameKey.includes(w)).length;

/** As linhas da lista, na ordem em que aparecem. Sem texto, só as ações. */
function searchCommands(entries, text) {
  const query = fold(text).trim();
  if (!query) return entries.filter((e) => e.group === 'Ações');
  const words = query.split(/\s+/);
  const groups = new Map();
  for (const entry of entries) {
    const r = rank(entry, query, words);
    if (r === null) continue;
    if (!groups.has(entry.group)) groups.set(entry.group, []);
    groups.get(entry.group).push({ ...entry, rank: r, hits: nameHits(entry, words) });
  }
  const sorted = [...groups.values()].map((list) => list.sort((a, b) => a.rank - b.rank || b.hits - a.hits).slice(0, GROUP_LIMIT));
  return sorted.sort((a, b) => a[0].rank - b[0].rank || b[0].hits - a[0].hits).flat(); // sort estável: empate mantém a ordem dos grupos
}

function openPalette() {
  const entries = allEntries();
  const input = h('input', { class: 'cmd-input', type: 'text', placeholder: 'O que você quer fazer? Ex.: juntar duas tabelas', 'aria-label': 'Buscar comando', spellcheck: false, autocomplete: 'off' });
  const list = h('div', { class: 'cmd-list', role: 'listbox' });
  let shown = [];
  let active = 0;
  const dialog = h('dialog', { class: 'cmd-dialog', 'aria-label': 'Busca de comandos' },
    h('div', { class: 'cmd-head' }, icon('search', 18), input, h('kbd', {}, 'Esc')),
    list,
    h('div', { class: 'cmd-foot' }, h('span', {}, '↑↓ navegar'), h('span', {}, 'Enter escolher'), h('span', {}, 'Esc fechar')));
  const choose = (entry) => { dialog.close(); entry.run(); };
  const mark = () => {
    for (const row of list.querySelectorAll('.cmd-row')) {
      const on = Number(row.dataset.i) === active;
      row.classList.toggle('active', on);
      if (on) row.scrollIntoView({ block: 'nearest' });
    }
  };
  const draw = () => {
    shown = searchCommands(entries, input.value);
    active = 0;
    let group = '';
    const rows = [];
    shown.forEach((e, i) => {
      if (e.group !== group) { group = e.group; rows.push(h('div', { class: 'cmd-group' }, group)); }
      rows.push(h('button', {
        type: 'button', class: 'cmd-row', role: 'option', tabindex: -1, dataset: { i },
        onmousemove: () => { if (active !== i) { active = i; mark(); } },
        onclick: () => choose(e),
      }, h('span', { class: 'cmd-icon' }, icon(e.icon, 15)),
      h('span', { class: 'cmd-text' }, h('b', {}, e.name), e.detail ? h('small', {}, e.detail) : null),
      e.end ? h('span', { class: 'cmd-end' }, e.end) : null));
    });
    list.replaceChildren(...(rows.length ? rows : [h('p', { class: 'cmd-none' }, 'Nada encontrado. Tente outra palavra.')]));
    mark();
  };
  input.addEventListener('input', draw);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active - 1); mark(); }
    else if (e.key === 'Enter' && shown[active]) { e.preventDefault(); choose(shown[active]); }
  });
  dialog.addEventListener('mousedown', (e) => { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => { dialog.remove(); openDialogEl = null; });
  document.body.append(dialog);
  openDialogEl = dialog;
  dialog.showModal();
  draw();
}

export function togglePalette() {
  if (openDialogEl) openDialogEl.close();
  else if (!document.querySelector('dialog[open]')) openPalette();
}

/** `a`: { setView, commands(), manualEntries() }. */
export function initCommandPalette(a) {
  handlers = a;
}
