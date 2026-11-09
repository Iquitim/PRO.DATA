// A linha do tempo dentro do programa (spec 030): carrega as tabelas uma vez por execução e cuida da barra.

import { api } from './api.js';
import { previewTable } from './datasets.js';
import { openGif } from './dash_gif.js';
import { PAGE_W, pageHeight } from './dash_model.js';
import { createReplay, makeTables, momentLabel, momentsOf } from './dash_replay.js';
import { commitLayout, dash, newId, nodeLabel, page, ui } from './dash_state.js';
import { openStory } from './dash_story.js';
import { barButton, stillBadge, timelineBar } from './dash_timeline.js';
import { button, fmt, h } from './dom.js';
import { LABELS } from './label_picker.js';
import { store } from './store.js';
import { confirmDialog, openDialog, showMenu, toast } from './ui.js';

const RECORDS = 200;
const app = { key: '', filtersKey: '', data: null, tables: null, replay: null, bar: null, timeline: null, problem: '' };
let env = { redraw: () => {}, patch: () => {}, columns: () => [], goToNode: () => {} };

export const initReplay = (next) => { env = { ...env, ...next }; };
export const replay = () => app.replay;
export const replayWidgets = () => (app.replay && ui.mode === 'view' ? app.replay.widgets() : {});
/** Visual cuja tabela não tem a coluna: nem vem nos dados da linha do tempo, ou vem sem ela. */
export const isStill = (nodeId) => Boolean(app.replay) && !(app.timeline.column in (app.tables[nodeId]?.columns || {}));
const pageVisuals = () => dash().items.filter((i) => i.kind === 'visual').map((i) => i.node_id);
export const stillMark = (nodeId) => (isStill(nodeId) ? stillBadge(app.timeline.column) : null);
export const momentNote = () => (app.replay ? `Momento: ${momentLabel(app.replay.moment, app.timeline.step)}` : '');
export const animates = (nodeId) => dash()?.items.find((i) => i.node_id === nodeId)?.format?.animate !== false;

function clear() {
  app.replay?.pause();
  Object.assign(app, { key: '', filtersKey: '', data: null, tables: null, replay: null, bar: null, timeline: null, problem: '' });
}

function buildBar() {
  const stillCount = pageVisuals().filter(isStill).length;
  app.bar = timelineBar(app.replay, {
    stillCount,
    onMode: (mode) => commitLayout((d) => { d.timeline.mode = mode; }),
    onSpeed: (speed) => commitLayout((d) => { d.timeline.speed = speed; }),
    extra: [
      barButton({ icon: 'table', title: 'Ver os registros deste momento', onClick: recordsMenu }),
      barButton({ icon: 'flag', label: 'Guardar cena', title: 'Guardar este momento, os filtros e um destaque como cena da história', onClick: () => editScene() }),
      barButton({ icon: 'book', label: `Cenas (${(dash().scenes || []).length})`, title: 'Ver, reordenar e apresentar a história', onClick: openScenes }),
      barButton({ icon: 'settings', title: 'Ajustar a linha do tempo', variant: 'ghost', onClick: openTimelineSetup }),
    ],
  });
}

async function load(key) {
  try {
    const res = await api.dashboardExportData(store.workflow);
    if (key !== app.key) return;
    if (res.too_large) { app.problem = 'A linha do tempo precisa de dados demais para rodar aqui. Filtre as tabelas no fluxo.'; env.redraw(); return; }
    const tables = makeTables(res);
    const timeline = { ...dash().timeline };
    const { moments, tooMany } = momentsOf(tables, timeline.column, timeline.step);
    if (tooMany) { app.problem = 'Períodos demais nesse passo. Escolha um passo maior em Ajustar.'; env.redraw(); return; }
    if (!moments.length) { app.problem = `A coluna ${timeline.column} não tem datas nas tabelas dos visuais.`; env.redraw(); return; }
    Object.assign(app, { data: res, tables, timeline, problem: '' });
    app.replay = createReplay({
      data: res, tables, timeline, moments, animates,
      getFilters: () => dash()?.filters || [],
      draw: (widgets) => { if (store.view !== 'dashboard') app.replay?.pause(); else env.patch(widgets); },
      changed: () => app.bar?.update(),
    });
    buildBar();
    env.redraw();
  } catch (err) {
    if (key === app.key) { app.problem = err.message; env.redraw(); }
  }
}

/** Chamado a cada desenho da página: é aqui que a barra acompanha execução, filtros, modo e velocidade. */
export function syncReplay() {
  const d = dash();
  const tl = d?.timeline;
  if (!tl?.column || !store.execution) { if (app.key) clear(); return; }
  const key = JSON.stringify([tl.column, tl.step, store.execution.total_elapsed_ms, store.workflow.id]);
  if (key !== app.key) {
    clear();
    app.key = key;
    load(key);
    return;
  }
  if (!app.replay) return;
  const filtersKey = JSON.stringify(d.filters || []);
  const modeChanged = app.timeline.mode !== tl.mode;
  const scenesChanged = app.scenes !== (d.scenes || []).length;
  if (filtersKey !== app.filtersKey || modeChanged) {
    if (app.filtersKey !== '' || modeChanged) app.replay.invalidate();
    app.filtersKey = filtersKey;
    app.timeline.mode = tl.mode;
    buildBar();
  } else if (scenesChanged) {
    buildBar();
  }
  app.scenes = (d.scenes || []).length;
  app.timeline.speed = tl.speed;
}

export function replaySlot() {
  if (ui.mode !== 'view') return null;
  if (app.problem) return h('p', { class: 'replay-problem' }, app.problem, ' ', button({ label: 'Ajustar', size: 'sm', onClick: openTimelineSetup }));
  return app.bar?.el || null;
}

/** Só no modo Visualizar: GIF de um gráfico que acompanha o tempo. */
export function gifAction(item, w) {
  if (!app.replay || !app.data.nodes[item.node_id] || isStill(item.node_id) || w?.widget_type !== 'chart') return null;
  return button({ icon: 'film', title: 'Baixar GIF deste gráfico', size: 'sm', variant: 'ghost', onClick: () => openGif(item, app.replay) });
}

// ------------------------------------------------------------------ registros (RF-3046)

function recordsMenu(e) {
  const r = e.currentTarget.getBoundingClientRect();
  const visuals = Object.keys(app.data.nodes).filter((id) => !isStill(id));
  showMenu(r.left, r.bottom + 4, visuals.map((id) => ({ label: app.data.nodes[id].title, icon: 'table', onSelect: () => showRecords(id) })));
}

function showRecords(id) {
  const { columns, rows, total } = app.replay.rows(id, RECORDS);
  const box = openDialog({
    title: `Registros de ${app.data.nodes[id].title}`,
    size: 'lg',
    body: h('div', { class: 'stack-sm' },
      h('p', { class: 'muted' }, `${momentNote()}, ${app.timeline.mode === 'period' ? 'só naquele período' : 'acumulado até ali'}. ${fmt.int(total)} linhas${total > RECORDS ? `, mostrando ${RECORDS}` : ''}. Só as colunas que o visual e os filtros usam.`),
      h('div', { class: 'replay-records' }, previewTable(columns, rows))),
    actions: [button({ icon: 'workflow', label: 'Ir para a caixa', onClick: () => { box.close(); env.goToNode(id); } }), button({ label: 'Fechar', variant: 'primary', onClick: () => box.close() })],
  });
}

// ------------------------------------------------------------------ ajustes

const isDateOption = (o) => o.kind === 'date' || o.date_like;

function sampleOf(o) {
  if (o.kind === 'list') return (o.values || []).filter((v) => v !== '(vazio)').slice(0, 3).join(', ');
  if (o.min === null || o.min === undefined) return '';
  return o.kind === 'number' ? `${fmt.number(o.min)} a ${fmt.number(o.max)}` : `${o.min} a ${o.max}`;
}

/** O que acontece com a coluna escolhida: exemplos dos valores e quem acompanha o tempo. */
function columnNote(option) {
  if (!option) return h('p', { class: 'field-help' }, 'Escolha a coluna que diz quando cada linha aconteceu.');
  const sample = sampleOf(option);
  if (!isDateOption(option)) {
    return h('p', { class: 'field-warn' }, `Esta coluna não tem datas${sample ? ` (valores como ${sample})` : ''}. Use uma coluna de data ou texto como 2026-05 e 29/10/2026. Para converter, inclua no fluxo uma caixa Formula com o tipo Data.`);
  }
  const follow = new Set(option.node_ids || []);
  const names = (list) => list.map(nodeLabel).join(', ');
  const visuals = pageVisuals();
  const moving = visuals.filter((id) => follow.has(id));
  const still = visuals.filter((id) => !follow.has(id));
  return h('div', { class: 'stack-xs' },
    sample ? h('p', { class: 'field-help' }, `Valores como ${sample}.`) : null,
    h('p', { class: 'field-help' }, h('b', {}, 'Acompanham: '), names(moving) || 'nenhum visual'),
    still.length ? h('p', { class: 'field-help' }, h('b', {}, 'Ficam parados: '), names(still), '. A tabela deles não tem esta coluna.') : null);
}

/** Na própria aba Dashboard: qual coluna é a data, o passo e como contar. Fica salvo no fluxo. */
export function openTimelineSetup() {
  const d = dash();
  const current = d.timeline || {};
  const columns = [...env.columns()].sort((a, b) => Number(isDateOption(b)) - Number(isDateOption(a)));
  const firstDate = columns.find(isDateOption)?.column || '';
  const draft = { step: 'month', mode: 'cumulative', speed: 1, ...current, column: current.column || firstDate };
  const row = (label, control, help) => h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control, help ? h('p', { class: 'field-help' }, help) : null);
  const choose = (key, list) => h('select', { class: 'input', 'aria-label': key, onchange: (e) => { draft[key] = e.target.value; } },
    list.map(([value, text]) => h('option', { value, selected: value === draft[key] }, text)));
  const note = h('div', { 'aria-live': 'polite' });
  const apply = button({ label: 'Aplicar', variant: 'primary', onClick: () => { commitLayout((dd) => { dd.timeline = { ...dd.timeline, ...draft }; }); box.close(); } });
  const refresh = () => {
    const option = columns.find((o) => o.column === draft.column);
    note.replaceChildren(columnNote(option));
    apply.disabled = !option || !isDateOption(option);
  };
  const group = (label, list) => (list.length ? h('optgroup', { label }, list.map((o) => h('option', { value: o.column, selected: o.column === draft.column }, o.column))) : null);
  const picker = h('select', { class: 'input', 'aria-label': 'Coluna de data', onchange: (e) => { draft.column = e.target.value; refresh(); } },
    draft.column ? null : h('option', { value: '', selected: true }, 'Escolha uma coluna'),
    group('Datas', columns.filter(isDateOption)),
    group('Outras colunas', columns.filter((o) => !isDateOption(o))));
  const empty = store.execution ? 'Nenhuma coluna chegou aos visuais desta página. Confira se há visuais na página e execute o fluxo.' : 'Execute o fluxo para listar as colunas dos visuais.';
  const body = columns.length ? h('div', { class: 'stack-sm' },
    row('Qual coluna é a data?', picker),
    note,
    row('Passo', choose('step', [['day', 'Dia'], ['week', 'Semana'], ['month', 'Mês']])),
    row('Como contar', choose('mode', [['cumulative', 'Acumulado até o momento'], ['period', 'Só naquele período']]), 'Use "só naquele período" em tabelas de fotos, como as da caixa Estado por período.'))
    : h('p', {}, empty);
  const box = openDialog({
    title: 'Linha do tempo',
    size: 'sm',
    body,
    actions: [
      current.column ? button({ icon: 'trash', label: 'Tirar', variant: 'ghost', onClick: () => { commitLayout((dd) => { dd.timeline = { ...dd.timeline, column: '' }; }); box.close(); } }) : null,
      button({ label: 'Cancelar', onClick: () => box.close() }),
      columns.length ? apply : null,
    ].filter(Boolean),
  });
  refresh();
}

// ------------------------------------------------------------------ história (RF-3061..3064)

const visualsOnPage = () => dash().items.filter((i) => i.kind === 'visual');

function editScene(scene = null) {
  const d = dash();
  const draft = scene ? { ...scene } : { id: newId(), title: '', note: '', moment: app.replay.moment, filters: structuredClone(d.filters || []), item_id: null };
  const title = h('input', { class: 'input', value: draft.title, maxlength: 200, 'aria-label': 'Título da cena', placeholder: 'Ex.: Backlog dobrou em março' });
  const note = h('textarea', { class: 'input', rows: 3, maxlength: 2000, 'aria-label': 'Anotação' }, draft.note);
  const spot = h('select', { class: 'input', 'aria-label': 'Visual em destaque' },
    h('option', { value: '' }, 'Nenhum'),
    visualsOnPage().map((i) => h('option', { value: i.id, selected: i.id === draft.item_id }, nodeLabel(i.node_id))));
  const save = () => {
    const out = { ...draft, title: title.value.trim(), note: note.value.trim(), item_id: spot.value || null };
    if (!out.title) { toast('Dê um título à cena', { kind: 'error' }); return; }
    commitLayout((dd) => {
      const at = (dd.scenes || []).findIndex((s) => s.id === out.id);
      dd.scenes = dd.scenes || [];
      if (at >= 0) dd.scenes[at] = out; else dd.scenes.push(out);
    });
    box.close();
    toast('Cena guardada', { kind: 'success' });
  };
  const box = openDialog({
    title: scene ? 'Editar cena' : 'Guardar cena',
    size: 'sm',
    body: h('div', { class: 'stack-sm' },
      h('p', { class: 'muted' }, `${momentLabel(draft.moment, app.timeline.step)}${draft.filters.some((f) => f.selected?.length || f.min || f.max) ? ', com os filtros de agora' : ''}.`),
      h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Título'), title),
      h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Anotação'), note),
      h('div', { class: 'field' }, h('label', { class: 'field-label' }, 'Visual em destaque'), spot)),
    actions: [button({ label: 'Cancelar', onClick: () => box.close() }), button({ label: 'Salvar', variant: 'primary', onClick: save })],
  });
  title.focus();
}

function sceneRow(scene, i, list, redraw) {
  const move = (delta) => { commitLayout((d) => { const [s] = d.scenes.splice(i, 1); d.scenes.splice(i + delta, 0, s); }); redraw(); };
  const remove = async () => {
    if (!await confirmDialog({ title: 'Apagar cena?', message: scene.title, confirm: 'Apagar', danger: true })) return;
    commitLayout((d) => { d.scenes.splice(i, 1); });
    redraw();
  };
  return h('li', { class: 'story-row' },
    h('div', {}, h('strong', {}, scene.title), h('small', { class: 'muted' }, momentLabel(scene.moment, app.timeline.step))),
    h('div', { class: 'row' },
      button({ icon: 'chevron-up', title: 'Subir', size: 'sm', variant: 'ghost', disabled: i === 0, onClick: () => move(-1) }),
      button({ icon: 'chevron-down', title: 'Descer', size: 'sm', variant: 'ghost', disabled: i === list.length - 1, onClick: () => move(1) }),
      button({ icon: 'edit', title: 'Editar', size: 'sm', variant: 'ghost', onClick: () => editScene(scene) }),
      button({ icon: 'trash', title: 'Apagar', size: 'sm', variant: 'ghost', onClick: remove })));
}

function openScenes() {
  const list = h('ul', { class: 'story-list' });
  const draw = () => {
    const scenes = dash().scenes || [];
    list.replaceChildren(...(scenes.length ? scenes.map((s, i) => sceneRow(s, i, scenes, draw)) : [h('li', { class: 'muted' }, 'Nenhuma cena ainda. Pare num momento e use Guardar cena.')]));
  };
  draw();
  const box = openDialog({
    title: 'História',
    size: 'md',
    body: list,
    actions: [button({ label: 'Fechar', onClick: () => box.close() }), button({ icon: 'play', label: 'Apresentar', variant: 'primary', onClick: () => { box.close(); presentStory(); } })],
  });
}

export function presentStory() {
  const d = dash();
  if (!d.scenes?.length) { toast('Guarde ao menos uma cena'); return; }
  const base = page.shownWidgets();
  const render = (scene) => {
    const widgets = { ...base, ...app.replay.snapshot(scene.filters || [], scene.moment || app.replay.moment) };
    return h('div', {
      class: ['dash-page', 'dash-export', scene.item_id && 'has-spot'],
      style: { width: `${PAGE_W}px`, height: `${pageHeight(d.page)}px`, backgroundColor: d.page.background || null },
    }, d.items.map((item) => {
      const el = page.itemEl(item, widgets, { exporting: true });
      if (el && item.id === scene.item_id) el.classList.add('spot');
      return el;
    }).filter(Boolean));
  };
  const trace = (scene, close) => {
    const item = d.items.find((i) => i.id === scene.item_id) || visualsOnPage()[0];
    if (!item) return [];
    return [button({ icon: 'workflow', label: 'Ver a caixa de origem', size: 'sm', variant: 'ghost', onClick: () => { close(); env.goToNode(item.node_id); } })];
  };
  const level = d.confidentiality || 'interno';
  openStory({ scenes: d.scenes, render, size: { width: PAGE_W, height: pageHeight(d.page) }, trace, label: { level, name: LABELS[level] } });
}
