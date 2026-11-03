// Aba SQL (spec 020): o fluxo escrito em SQL, por saída. A trilha à esquerda é o seletor; o código fica sempre limpo e a
// explicação de cada etapa mora na trilha. Só leitura: nada aqui altera o fluxo.

import { api } from './api.js';
import { NODE_W, nodeHeight } from './canvas.js';
import { saveDownload } from './desktop.js';
import { button, debounce, fmt, h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { node, on, store, toolOf } from './store.js';
import { showMenu, toast, toastError } from './ui.js';

const ROW = 54;
const GAP = 6;
const X0 = 14;
const LANE = 15;
const MAX_LANES = 5;
const POLL_MS = 600;

const ui = {
  root: null,
  data: null,
  selection: null, // saídas escolhidas (null = o servidor decide)
  temporary: null, // caixa da saída temporária
  showVisuals: false,
  preview: null,
  current: null,
  mapOpen: false,
  searchOpen: false,
  searchText: '',
  matches: [],
  match: -1,
  verifyAllowed: true,
  verifying: false,
  seq: 0,
  goTo: null, // caixa para a qual o código deve rolar uma vez, depois de desenhado
  codeKey: '',
};
const els = {};

const selectionKey = () => `prodata.sql.saidas.${store.workflow?.id}`;
const visible = () => store.view === 'sql' && store.workflow;

// ---------------------------------------------------------------- dados

async function refresh() {
  if (!visible()) return;
  const seq = ++ui.seq;
  try {
    const data = await api.sqlGenerate(store.workflow, ui.selection || [], ui.temporary);
    if (seq !== ui.seq) return; // chegou uma versão mais nova do fluxo
    ui.data = data;
    draw();
    startVerification();
  } catch (err) {
    if (seq === ui.seq) drawError(err);
  }
}
const refreshSoon = debounce(refresh, 300);

async function startVerification() {
  if (!ui.verifyAllowed || ui.verifying || store.running || !store.execution || store.pending.size || !ui.data?.ok_blocks) return;
  ui.verifyAllowed = false;
  ui.verifying = true;
  const workflow = store.workflow;
  try {
    await api.sqlVerify(workflow);
    drawHead();
    for (;;) {
      await new Promise((resolve) => { setTimeout(resolve, POLL_MS); });
      if (store.workflow?.id !== workflow.id) return;
      const status = await api.sqlVerifyStatus(workflow.id);
      if (!status.running) {
        if (status.error) toast('Não foi possível conferir o SQL', { kind: 'error', detail: status.error });
        break;
      }
    }
  } catch (err) {
    toastError(err, 'Não foi possível conferir o SQL');
  } finally {
    ui.verifying = false;
  }
  refresh();
}

const selectedViews = () => (ui.data ? ui.data.selected_views : []);
const blockById = () => Object.fromEntries((ui.data?.blocks || []).map((b) => [b.id, b]));

function usage() {
  const used = {};
  for (const output of selectedViews()) for (const step of output.steps) used[step] = (used[step] || 0) + 1;
  return used;
}

function remember() {
  if (ui.selection) persist(selectionKey(), ui.selection);
}

function selectOne(id) {
  ui.temporary = null;
  ui.selection = [id];
  remember();
  ui.current = null;
  refresh();
}

function toggle(id) {
  const now = new Set(ui.temporary ? [] : ui.data.selection);
  if (now.has(id) && now.size > 1) now.delete(id);
  else now.add(id);
  ui.temporary = null;
  ui.selection = [...now];
  remember();
  refresh();
}

/** Abre a aba no caminho de uma caixa: a saída dela, ou o código até ela. Usado por "Ver SQL". */
export function showNode(nodeId) {
  const own = ui.data?.outputs.find((o) => o.node_id === nodeId);
  ui.temporary = own ? null : nodeId;
  if (own) ui.selection = [own.id];
  ui.current = nodeId;
  ui.goTo = nodeId;
}

/** Ao chegar à aba, a seleção do Designer indica a saída mais próxima daquela caixa (RF-2017). */
function nearestToSelection() {
  const nodeId = store.selection.nodeId;
  const outputs = ui.data?.outputs || [];
  if (!nodeId) return null;
  // A caixa já faz parte do que está na tela: a escolha do usuário fica como está.
  if (selectedViews().some((o) => o.steps.some((s) => s.startsWith(`${nodeId}|`)))) return null;
  const owning = outputs.filter((o) => o.steps.some((s) => s.startsWith(`${nodeId}|`)));
  owning.sort((a, b) => (a.kind === b.kind ? a.steps.length - b.steps.length : a.kind === 'table' ? -1 : 1));
  return owning[0]?.id || null;
}

// ---------------------------------------------------------------- saídas

function drawOutputs() {
  const { outputs, selection, temporary } = ui.data;
  const tables = outputs.filter((o) => o.kind === 'table');
  const visuals = outputs.filter((o) => o.kind === 'visual');
  // Sem tabelas, os visuais aparecem direto. Com uma saída só, o seletor nem aparece (RF-2011, RF-2012).
  const list = tables.length ? [...tables, ...(ui.showVisuals ? visuals : [])] : visuals;
  const single = outputs.length <= 1 && !temporary;
  els.outputsTitle.hidden = single;
  els.outputs.hidden = single && !temporary;
  els.allBtn.hidden = tables.length < 2;
  const rows = list.map((o) => {
    const on_ = !temporary && selection.includes(o.id);
    return h('div', {
      class: ['sql-out', on_ && 'on'],
      onmouseenter: () => { ui.preview = o.id; drawTrail(); },
      onmouseleave: () => { ui.preview = null; drawTrail(); },
    },
    h('input', {
      type: 'checkbox', checked: on_, 'aria-label': `Somar ${o.name} ao código`, title: 'Somar ao código',
      onchange: () => toggle(o.id),
    }),
    h('button', { type: 'button', class: 'sql-out-pick', onclick: () => selectOne(o.id) },
      h('span', { class: 'sql-out-name ellipsis' }, o.name),
      h('span', { class: 'sql-out-sub ellipsis' }, outputSub(o))),
    h('span', { class: ['sql-dot', o.state.state], title: o.state.label, role: 'img', 'aria-label': o.state.label }));
  });
  els.outputs.replaceChildren(...[
    temporary ? h('div', { class: 'sql-temp' }, h('span', { class: 'ellipsis' }, 'Até a caixa ', h('strong', {}, temporary.name)),
      button({ icon: 'x', title: 'Voltar às saídas', size: 'sm', variant: 'ghost', onClick: () => { ui.temporary = null; refresh(); } })) : null,
    ...rows,
    tables.length && visuals.length
      ? h('button', { type: 'button', class: 'sql-more', onclick: () => { ui.showVisuals = !ui.showVisuals; draw(); } },
        ui.showVisuals ? 'Ocultar visuais' : `Mostrar visuais (${visuals.length})`)
      : null,
  ].filter(Boolean));
}

function outputSub(o) {
  const bits = [];
  if (o.export_file) bits.push(o.export_file);
  else bits.push(o.kind === 'visual' ? 'Visual' : 'Tabela');
  if (o.rows !== null && o.rows !== undefined) bits.push(`${fmt.int(o.rows)} linhas`);
  if (o.stop) bits.push('depende de etapa sem SQL');
  return bits.join(' · ');
}

// ---------------------------------------------------------------- trilha

function trailNodes(lit, previewed) {
  const seen = new Set();
  const list = [];
  const visuals = new Set(ui.data.outputs.filter((o) => o.kind === 'visual').map((o) => o.node_id));
  for (const block of ui.data.blocks) {
    if (seen.has(block.node_id)) continue;
    seen.add(block.node_id);
    const n = node(block.node_id);
    if (!n) continue;
    if (visuals.has(n.id) && !ui.showVisuals && !lit.has(n.id) && !previewed.has(n.id)) continue;
    list.push(n);
  }
  return list;
}

/** Faixas das linhas, como num gráfico de ramificações: a caixa segue na faixa do pai quando ela está livre. */
function assignLanes(nodes, parentsOf) {
  const row = new Map(nodes.map((n, i) => [n.id, i]));
  const lanes = new Map();
  const busy = [];
  nodes.forEach((n, i) => {
    const parents = parentsOf(n.id).filter((p) => row.has(p)).sort((a, b) => row.get(a) - row.get(b));
    const start = parents.length ? row.get(parents[0]) : i;
    let lane = parents.map((p) => lanes.get(p)).find((l) => busy[l] === row.get(parents.find((p) => lanes.get(p) === l)));
    if (lane === undefined) {
      lane = 0;
      while (lane < MAX_LANES - 1 && busy[lane] !== undefined && busy[lane] >= start) lane += 1;
    }
    lanes.set(n.id, lane);
    busy[lane] = i;
    for (const p of parents) if (lanes.get(p) !== lane) busy[lanes.get(p)] = Math.max(busy[lanes.get(p)] ?? -1, i);
  });
  return lanes;
}

const STATUS_TAGS = { no_sql: ['sem SQL', 'nosql'], error: ['revisar', 'problem'], disabled: ['desligada', 'muted'], not_ready: ['execute', 'problem'] };

function drawTrail() {
  if (!ui.data) return;
  const blocks = blockById();
  const used = usage();
  const steps = new Set(Object.keys(used));
  const lit = new Set([...steps].map((s) => blocks[s]?.node_id));
  const previewOut = ui.data.outputs.find((o) => o.id === ui.preview);
  const previewSteps = new Set(previewOut?.steps || []);
  const previewed = new Set([...previewSteps].map((s) => blocks[s]?.node_id));
  const nodes = trailNodes(lit, previewed);
  const links = [];
  for (const b of ui.data.blocks) for (const d of b.deps) if (blocks[d]) links.push({ from: blocks[d].node_id, to: b.node_id, fromBlock: d, toBlock: b.id });
  const parentsOf = (id) => [...new Set(links.filter((l) => l.to === id).map((l) => l.from))];
  const lanes = assignLanes(nodes, parentsOf);
  const maxLane = Math.max(0, ...lanes.values());
  const pad = X0 + (maxLane + 1) * LANE;
  const pos = new Map(nodes.map((n, i) => [n.id, { y: 4 + i * (ROW + GAP), cy: 4 + i * (ROW + GAP) + ROW / 2, cx: X0 + lanes.get(n.id) * LANE }]));
  const height = 8 + nodes.length * (ROW + GAP);

  const paths = [];
  const drawn = new Set();
  const ordered = [...links].sort((a, b) => (steps.has(a.toBlock) ? 1 : 0) - (steps.has(b.toBlock) ? 1 : 0));
  for (const link of ordered) {
    const a = pos.get(link.from);
    const b = pos.get(link.to);
    const key = `${link.from}>${link.to}`;
    if (!a || !b || (drawn.has(key) && !steps.has(link.toBlock))) continue;
    drawn.add(key);
    const onPath = steps.has(link.fromBlock) && steps.has(link.toBlock);
    const inPreview = !onPath && previewSteps.has(link.fromBlock) && previewSteps.has(link.toBlock);
    const stops = blocks[link.toBlock]?.status === 'no_sql';
    let d;
    if (a.cx === b.cx) d = `M${a.cx} ${a.cy}L${b.cx} ${b.cy}`;
    else if (b.cx > a.cx) d = `M${a.cx} ${a.cy}C${a.cx} ${a.cy + 22},${b.cx} ${a.cy + 8},${b.cx} ${a.cy + 30}L${b.cx} ${b.cy}`;
    else d = `M${a.cx} ${a.cy}L${a.cx} ${b.cy - 30}C${a.cx} ${b.cy - 8},${b.cx} ${b.cy - 22},${b.cx} ${b.cy}`;
    paths.push(`<path class="${onPath && stops ? 'nosql' : onPath ? 'on' : inPreview ? 'preview' : ''}" d="${d}"/>`);
  }
  const outputNodes = new Set(ui.data.outputs.map((o) => o.node_id));
  // Fora do caminho, a caixa mostra a saída que o fluxo usa: num Join, o J conectado, e não o L solto.
  const usedByFlow = new Set(links.map((l) => l.fromBlock));
  const statusOf = (id) => {
    const own = ui.data.blocks.filter((b) => b.node_id === id);
    return own.find((b) => steps.has(b.id)) || own.find((b) => usedByFlow.has(b.id)) || own[0];
  };
  const dots = nodes.map((n) => {
    const b = statusOf(n.id);
    const p = pos.get(n.id);
    const cls = [b.status === 'no_sql' ? 'nosql' : lit.has(n.id) ? 'on' : '', outputNodes.has(n.id) ? 'out-mark' : ''].join(' ');
    return `<circle class="${cls}" cx="${p.cx}" cy="${p.cy}" r="${outputNodes.has(n.id) ? 5.5 : 4}"/>`;
  });
  const svg = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${pad}" height="${height}" aria-hidden="true">${paths.join('')}${dots.join('')}</svg>`, 'image/svg+xml').documentElement;

  const rows = nodes.map((n) => {
    const block = statusOf(n.id);
    const on_ = lit.has(n.id);
    const spec = toolOf(n);
    const tag = STATUS_TAGS[block.status];
    const count = Object.entries(used).filter(([id]) => blocks[id]?.node_id === n.id).reduce((m, [, c]) => Math.max(m, c), 0);
    const caption = block.status === 'ok' ? block.explain : block.reason;
    const label = n.label || spec?.name || n.type;
    const differs = block.check?.state === 'different';
    const notes = on_ ? block.notes || [] : [];
    const row = h('button', {
      type: 'button',
      class: ['sql-row', !on_ && 'off', previewed.has(n.id) && !on_ && 'preview', ui.current === n.id && 'current', tag && tag[1], differs && 'differs'],
      dataset: { node: n.id, category: spec?.category || 'prep' },
      style: { top: `${pos.get(n.id).y}px`, height: `${ROW}px`, paddingLeft: `${pad}px` },
      title: on_ ? [caption, differs ? block.check.detail : null, ...notes].filter(Boolean).join('\n') : `Ver o código até ${label}`,
      onclick: () => clickNode(n.id, block, on_),
      onmouseenter: () => linkBlock(n.id, true),
      onmouseleave: () => linkBlock(n.id, false),
    },
    h('span', { class: 'sql-card' },
      h('span', { class: 'sql-icon' }, icon(spec?.icon || 'workflow', 15)),
      h('span', { class: 'sql-card-text' }, h('span', { class: 'sql-label ellipsis' }, label), h('span', { class: 'sql-cap ellipsis' }, caption || spec?.name || '')),
      h('span', { class: 'sql-tags' },
        tag ? h('span', { class: ['sql-tag', tag[1]] }, tag[0]) : null,
        differs ? h('span', { class: 'sql-tag differs' }, 'não bate') : null,
        notes.length && !differs ? h('span', { class: 'sql-tag note' }, 'ressalva') : null,
        block.rows !== null && block.rows !== undefined ? h('span', { class: 'sql-rows' }, fmt.int(block.rows)) : null,
        on_ && count > 1 ? h('span', { class: 'sql-tag shared' }, `usada por ${count}`) : null)));
    return row;
  });
  const top = els.trailWrap.scrollTop;
  els.trail.style.height = `${height}px`;
  els.trail.replaceChildren(svg, ...rows);
  els.trailWrap.scrollTop = top;
}

function clickNode(nodeId, block, onPath) {
  const output = ui.data.outputs.find((o) => o.node_id === nodeId);
  if (block.status === 'no_sql') { toast(block.reason || 'Esta caixa não tem equivalente em SQL.', { detail: 'O código para na etapa anterior.' }); return; }
  if (output && !onPath) { selectOne(output.id); return; }
  if (onPath && block.status === 'ok') { goToBlock(nodeId); return; }
  if (block.status !== 'ok') { toast(block.reason || 'Esta etapa ainda não virou SQL.'); return; }
  ui.temporary = nodeId;
  ui.current = nodeId;
  ui.goTo = nodeId;
  refresh();
}

function linkBlock(nodeId, active) {
  els.code.querySelectorAll(`[data-node="${CSS.escape(nodeId)}"]`).forEach((el) => el.classList.toggle('hot', active));
  els.trail.querySelector(`.sql-row[data-node="${CSS.escape(nodeId)}"]`)?.classList.toggle('hot', active);
}

function goToBlock(nodeId) {
  const el = els.code.querySelector(`[data-node="${CSS.escape(nodeId)}"]`);
  if (!el) return;
  const smooth = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ block: 'center', behavior: smooth ? 'smooth' : 'auto' });
  el.classList.remove('flash');
  void el.offsetWidth; // reinicia a animação
  el.classList.add('flash');
  ui.current = nodeId;
  drawTrail();
}

// ---------------------------------------------------------------- código

const SQL_TOKENS = /(--[^\n]*)|('(?:[^']|'')*')|("(?:[^"]|"")*")|\b(WITH|AS|SELECT|FROM|WHERE|GROUP BY|ORDER BY|INNER JOIN|CROSS JOIN|ON|AND|OR|NOT|CASE|WHEN|THEN|ELSE|END|CAST|TRY_CAST|CREATE OR REPLACE TEMP VIEW|CREATE OR REPLACE TEMPORARY MACRO|DISTINCT|DESC|ASC|NULLS LAST|OVER|PARTITION BY|IN|DOUBLE|VARCHAR|BIGINT|BOOLEAN|DATE|INTEGER|EXISTS|LIMIT|QUALIFY|REPLACE|EXCLUDE|UNION ALL BY NAME|UNION ALL|USING SAMPLE|VALUES|FILTER|NULL|TRUE|FALSE|IS|lambda)\b|\b([A-Za-z_]\w*)(?=\()|\b(\d+(?:\.\d+)?)\b/g;
const SQL_CLASSES = ['c', 's', 'i', 'k', 'f', 'n'];

function highlighted(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(SQL_TOKENS)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const group = m.slice(1).findIndex(Boolean);
    out.push(h('span', { class: `sql-t-${SQL_CLASSES[group]}` }, m[0]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function drawCode() {
  const blocks = blockById();
  const parts = ui.data.parts.map((p) => {
    const nodeId = p.block ? blocks[p.block]?.node_id : null;
    return h('div', {
      class: ['sql-part', p.kind, nodeId && 'linked'],
      dataset: nodeId ? { node: nodeId } : undefined,
      onmouseenter: nodeId ? () => linkBlock(nodeId, true) : null,
      onmouseleave: nodeId ? () => linkBlock(nodeId, false) : null,
    }, highlighted(p.text));
  });
  // A conferência terminar não pode tirar o leitor do lugar: o topo é só para quando o código muda de assunto.
  const key = `${ui.data.selection.join(',')}|${ui.temporary || ''}`;
  const top = key === ui.codeKey ? els.code.scrollTop : 0;
  ui.codeKey = key;
  els.code.replaceChildren(...parts);
  els.code.scrollTop = top;
  applySearch();
  if (ui.goTo) {
    const nodeId = ui.goTo;
    ui.goTo = null;
    requestAnimationFrame(() => goToBlock(nodeId));
  }
}

function drawHead() {
  if (!ui.data) return;
  const views = selectedViews();
  const order = ['mismatch', 'partial', 'pending', 'ready_notes', 'ready'];
  const worst = [...views].sort((a, b) => order.indexOf(a.state.state) - order.indexOf(b.state.state))[0];
  const state = ui.verifying && worst?.state.state === 'pending' ? { state: 'pending', label: 'Conferindo…' } : worst?.state || { state: 'pending', label: 'Sem saídas' };
  els.state.className = `sql-state ${state.state}`;
  els.state.replaceChildren(h('span', { class: ['sql-dot', state.state], 'aria-hidden': 'true' }), state.label);
  const used = usage();
  const blocks = blockById();
  const stepCount = Object.keys(used).filter((s) => blocks[s]?.status === 'ok').length;
  const shared = Object.keys(used).filter((s) => used[s] > 1 && blocks[s]?.status === 'ok').length;
  const checked = views.reduce((n, v) => n + (v.state.checked || 0), 0);
  const total = views.reduce((n, v) => n + (v.state.total || 0), 0);
  const steps = `${stepCount} etapa${stepCount === 1 ? '' : 's'}`;
  const bits = [views.length > 1 ? `${views.length} saídas, ${steps}${shared ? `, ${shared} compartilhada${shared === 1 ? '' : 's'}` : ''}` : steps];
  if (total && views.length === 1) bits.push(`${checked} de ${total} ${total === 1 ? 'transformação conferida' : 'transformações conferidas'}`);
  const stop = views.find((v) => v.stop);
  if (stop) bits.push(`para em ${blocks[stop.stop]?.name}`);
  if (worst?.state.state === 'pending' && !ui.verifying) bits.push(store.execution ? (worst.state.detail || 'execute o fluxo para conferir') : 'execute o fluxo para conferir');
  els.sub.textContent = bits.join(' · ');
  const notes = [...new Set(views.flatMap((v) => v.state.notes || []))];
  const mismatch = views.find((v) => v.state.state === 'mismatch');
  const problem = mismatch?.state.detail;
  const stopReasons = [...new Set(views.filter((v) => v.stop).map((v) => blocks[v.stop]?.reason))].filter(Boolean);
  els.notes.replaceChildren(...[
    problem ? h('p', { class: 'sql-note bad' }, icon('alert', 14), problem) : null,
    mismatch?.state.examples?.length ? diffTable(mismatch.state.examples) : null,
    ...stopReasons.map((r) => h('p', { class: 'sql-note bad' }, icon('alert', 14), r)),
    notes.length ? h('details', { class: 'sql-notes-more' }, h('summary', {}, `${notes.length} ressalva${notes.length > 1 ? 's' : ''}`), h('ul', {}, notes.map((n) => h('li', {}, n)))) : null,
  ].filter(Boolean));
  els.notes.hidden = !els.notes.childElementCount;
}

/** Exemplos do que difere (RF-2023): uma tabela curta, com rolagem própria. */
function diffTable(examples) {
  const columns = Object.keys(examples[0]);
  return h('div', { class: 'sql-diff' }, h('table', {},
    h('thead', {}, h('tr', {}, columns.map((c) => h('th', {}, c === 'lado' ? 'Onde' : c)))),
    h('tbody', {}, examples.map((row) => h('tr', {}, columns.map((c) => h('td', {}, row[c] ?? '∅')))))));
}

function draw() {
  if (!ui.data) return;
  const empty = !ui.data.outputs.length && !ui.data.temporary;
  els.view.classList.toggle('is-empty', empty);
  if (empty) {
    els.code.replaceChildren(h('div', { class: 'empty big' }, icon('terminal', 28), h('strong', {}, 'O fluxo ainda não tem saídas'),
      h('span', {}, 'Adicione caixas no Designer: o código aparece aqui.')));
    els.trail.replaceChildren();
    els.outputs.replaceChildren();
    els.outputs.hidden = true;
    els.outputsTitle.hidden = true;
    els.state.className = 'sql-state';
    els.state.replaceChildren();
    els.sub.textContent = '';
    els.notes.hidden = true;
    return;
  }
  drawOutputs();
  drawTrail();
  drawCode();
  drawHead();
  if (ui.mapOpen) drawMap();
}

function drawError(err) {
  els.code.replaceChildren(h('div', { class: 'empty big' }, icon('alert', 28), h('strong', {}, 'Não foi possível gerar o SQL'), h('span', {}, err.message)));
}

// ---------------------------------------------------------------- busca

function clearMarks() {
  for (const mark of els.code.querySelectorAll('mark.sql-mark')) mark.replaceWith(mark.textContent);
  els.code.normalize();
}

function applySearch() {
  ui.matches = [];
  ui.match = -1;
  const text = ui.searchOpen ? ui.searchText.toLowerCase() : '';
  if (text) {
    clearMarks();
    const walker = document.createTreeWalker(els.code, NodeFilter.SHOW_TEXT);
    const found = [];
    while (walker.nextNode()) found.push(walker.currentNode);
    for (const textNode of found) {
      let rest = textNode;
      let at = rest.data.toLowerCase().indexOf(text);
      while (at >= 0) {
        const hit = rest.splitText(at);
        rest = hit.splitText(text.length);
        const mark = h('mark', { class: 'sql-mark' }, hit.data);
        hit.replaceWith(mark);
        ui.matches.push(mark);
        at = rest.data.toLowerCase().indexOf(text);
      }
    }
  } else {
    clearMarks();
  }
  els.searchCount.textContent = text ? `${fmt.int(ui.matches.length)} resultado${ui.matches.length === 1 ? '' : 's'}` : '';
  if (ui.matches.length) stepSearch(1);
}

function stepSearch(direction) {
  if (!ui.matches.length) return;
  ui.matches[ui.match]?.classList.remove('now');
  ui.match = (ui.match + direction + ui.matches.length) % ui.matches.length;
  const mark = ui.matches[ui.match];
  mark.classList.add('now');
  mark.scrollIntoView({ block: 'center' });
}

function openSearch() {
  ui.searchOpen = true;
  els.search.hidden = false;
  els.searchInput.focus();
  els.searchInput.select();
  applySearch();
}

function closeSearch() {
  ui.searchOpen = false;
  els.search.hidden = true;
  applySearch();
}

/** Atalhos da aba. Delete, Ctrl+D e afins não valem aqui: nada nesta tela altera o fluxo. */
export function handleSqlKey(e) {
  if (document.querySelector('dialog[open]')) return false;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === 'f') { e.preventDefault(); openSearch(); return true; }
  if (e.key === 'Escape' && ui.mapOpen) { closeMap(); return true; }
  if (e.key === 'Escape' && ui.searchOpen) { closeSearch(); return true; }
  return false;
}

// ---------------------------------------------------------------- entregar

async function copyCode() {
  const text = ui.data?.text || '';
  try {
    await navigator.clipboard.writeText(text);
    toast('SQL copiado.', { kind: 'success' });
  } catch {
    const range = document.createRange();
    range.selectNodeContents(els.code);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    toast('O código está selecionado: use Ctrl+C para copiar.');
  }
}

async function download(mode) {
  try {
    const { blob, name } = await api.sqlDownload(store.workflow, ui.data.selection, ui.temporary, mode);
    const saved = await saveDownload(name, blob);
    if (saved) toast(`Salvo: ${saved}`, { kind: 'success' });
  } catch (err) {
    toastError(err, 'Não foi possível salvar o arquivo');
  }
}

function downloadMenu(e) {
  const r = e.currentTarget.getBoundingClientRect();
  const tables = ui.data.outputs.filter((o) => o.kind === 'table').length;
  const many = ui.data.selection.length > 1;
  showMenu(r.left, r.bottom + 4, [
    { label: many ? 'A seleção, num arquivo .sql' : 'Esta saída (.sql)', icon: 'file', onSelect: () => download('selection') },
    { label: 'Um .sql por saída, mais o unificado (.zip)', icon: 'folder', disabled: tables < 2, onSelect: () => download('zip') },
  ]);
}

// ---------------------------------------------------------------- fluxo completo

function drawMap() {
  const wf = store.workflow;
  const blocks = blockById();
  const used = usage();
  const lit = new Set(Object.keys(used).map((s) => blocks[s]?.node_id));
  const boxes = wf.nodes.map((n) => ({ n, w: NODE_W, h: nodeHeight(n) }));
  const containers = wf.containers || [];
  const xs = [...boxes.map((b) => b.n.x), ...containers.map((c) => c.x)];
  const ys = [...boxes.map((b) => b.n.y), ...containers.map((c) => c.y)];
  const minX = Math.min(...xs) - 20;
  const minY = Math.min(...ys) - 20;
  const width = Math.max(...boxes.map((b) => b.n.x + b.w), ...containers.map((c) => c.x + c.width)) - minX + 20;
  const height = Math.max(...boxes.map((b) => b.n.y + b.h), ...containers.map((c) => c.y + c.height)) - minY + 20;
  const body = els.mapBody.getBoundingClientRect();
  // A mesma escala nos dois eixos: o desenho inteiro cabe, centralizado, sem distorcer (RF-2016).
  const scale = Math.min(1, (body.width - 32) / width, (body.height - 32) / height);
  els.mapStage.style.cssText = `width:${width}px;height:${height}px;transform:scale(${scale});left:${Math.max(0, (body.width - width * scale) / 2)}px;top:${Math.max(0, (body.height - height * scale) / 2)}px`;
  const place = (x, y) => ({ left: `${x - minX}px`, top: `${y - minY}px` });
  const boxOf = new Map(boxes.map((b) => [b.n.id, b]));
  const paths = wf.edges.map((e) => {
    const a = boxOf.get(e.source);
    const b = boxOf.get(e.target);
    if (!a || !b) return '';
    const x1 = a.n.x + a.w - minX;
    const y1 = a.n.y + a.h / 2 - minY;
    const x2 = b.n.x - minX;
    const y2 = b.n.y + b.h / 2 - minY;
    const k = Math.max(30, Math.abs(x2 - x1) / 2);
    const onPath = used[`${e.source}|${e.sourceHandle}`] && lit.has(e.target);
    const stops = blocks[`${e.target}|${(toolOf(node(e.target))?.outputs[0] || {}).id}`]?.status === 'no_sql';
    return `<path class="${onPath && stops ? 'nosql' : onPath ? 'lit' : ''}" d="M${x1} ${y1}C${x1 + k} ${y1},${x2 - k} ${y2},${x2} ${y2}"/>`;
  });
  const svg = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" aria-hidden="true">${paths.join('')}</svg>`, 'image/svg+xml').documentElement;
  const nodes = boxes.map(({ n, h: hgt }) => {
    const spec = toolOf(n);
    const block = ui.data.blocks.find((b) => b.node_id === n.id);
    const noSql = block?.status === 'no_sql';
    return h('button', {
      type: 'button',
      class: ['sql-map-node', lit.has(n.id) ? 'lit' : 'dim', noSql && 'nosql'],
      dataset: { category: spec?.category || 'prep' },
      style: { ...place(n.x, n.y), width: `${NODE_W}px`, height: `${hgt}px` },
      onclick: () => {
        closeMap();
        if (noSql) { toast(block.reason); return; }
        clickNode(n.id, block, lit.has(n.id));
      },
    },
    h('span', { class: 'sql-icon' }, icon(spec?.icon || 'workflow', 15)),
    h('span', { class: 'sql-card-text' }, h('span', { class: 'sql-label ellipsis' }, n.label || spec?.name || n.type),
      h('span', { class: 'sql-cap ellipsis' }, noSql ? 'sem SQL' : block?.explain || '')));
  });
  const areas = containers.map((c) => h('div', {
    class: 'sql-map-box',
    style: { ...place(c.x, c.y), width: `${c.width}px`, height: `${c.height}px`, '--mc': c.color },
  }, c.title));
  els.mapStage.replaceChildren(...areas, svg, ...nodes);
}

function openMap() {
  ui.mapOpen = true;
  els.map.hidden = false;
  drawMap();
  els.mapClose.focus();
}

function closeMap() {
  ui.mapOpen = false;
  els.map.hidden = true;
}

// ---------------------------------------------------------------- montagem

export function initSqlView(root) {
  els.view = root;
  els.outputsTitle = h('div', { class: 'sql-panel-title' }, 'Saídas');
  els.allBtn = h('button', {
    type: 'button', class: 'sql-all',
    onclick: () => {
      ui.temporary = null;
      ui.selection = ui.data.outputs.filter((o) => o.kind === 'table').map((o) => o.id);
      remember();
      refresh();
    },
  }, 'Todas as tabelas');
  els.outputsTitle.append(els.allBtn);
  els.outputs = h('div', { class: 'sql-outs' });
  els.trail = h('div', { class: 'sql-trail' });
  els.trailWrap = h('div', { class: 'sql-trail-wrap' }, els.trail);
  const left = h('aside', { class: 'sql-left', 'aria-label': 'Saídas e caminho no fluxo' },
    els.outputsTitle, els.outputs, h('div', { class: 'sql-panel-title' }, 'Caminho no fluxo'), els.trailWrap);

  els.state = h('span', { class: 'sql-state', role: 'status' });
  els.sub = h('span', { class: 'sql-sub' });
  const actions = h('div', { class: 'sql-actions' },
    button({ icon: 'search', title: 'Buscar no código (Ctrl+F)', variant: 'ghost', onClick: openSearch }),
    button({ icon: 'workflow', label: 'Fluxo completo', onClick: openMap }),
    button({ icon: 'download', label: 'Baixar', onClick: downloadMenu }),
    button({ icon: 'copy', label: 'Copiar SQL', variant: 'primary', onClick: copyCode }));
  const dialect = h('span', { class: 'sql-dialect', title: 'O código é do DuckDB. Para o Microsoft Fabric, é preciso adaptar a leitura de arquivos e as funções próprias do DuckDB.' }, 'DuckDB');
  const head = h('div', { class: 'sql-head' }, els.state, els.sub, dialect, actions);
  els.notes = h('div', { class: 'sql-notes', hidden: true });
  els.searchInput = h('input', {
    class: 'input input-sm', type: 'search', placeholder: 'Buscar no código', 'aria-label': 'Buscar no código',
    oninput: (e) => { ui.searchText = e.target.value; applySearch(); },
    onkeydown: (e) => {
      if (e.key === 'Enter') { e.preventDefault(); stepSearch(e.shiftKey ? -1 : 1); }
      if (e.key === 'Escape') { e.stopPropagation(); closeSearch(); }
    },
  });
  els.searchCount = h('span', { class: 'sql-sub' });
  els.search = h('div', { class: 'sql-search', hidden: true }, els.searchInput, els.searchCount,
    button({ icon: 'x', title: 'Fechar a busca', size: 'sm', variant: 'ghost', onClick: closeSearch }));
  els.code = h('div', { class: 'sql-code', tabindex: '0', 'aria-label': 'Código SQL gerado' });

  els.mapStage = h('div', { class: 'sql-map-stage' });
  els.mapBody = h('div', { class: 'sql-map-body' }, els.mapStage);
  els.mapClose = button({ label: 'Voltar ao código', onClick: closeMap });
  els.map = h('div', { class: 'sql-map', hidden: true },
    h('div', { class: 'sql-map-head' }, h('strong', {}, 'Fluxo completo'),
      h('span', { class: 'sql-sub' }, 'Só leitura. O caminho da seleção fica aceso.'), els.mapClose),
    els.mapBody);

  const main = h('section', { class: 'sql-main', 'aria-label': 'Código SQL' }, head, els.notes, els.search, els.code);
  root.replaceChildren(left, main, els.map);

  on('workflow:changed', () => { ui.verifyAllowed = true; if (visible()) refreshSoon(); });
  on('workflow:loaded', () => {
    ui.selection = storage(selectionKey(), null);
    ui.temporary = null;
    ui.data = null;
    ui.verifyAllowed = true;
    if (visible()) refresh();
  });
  on('execution', () => { ui.verifyAllowed = true; if (visible()) refreshSoon(); });
  window.addEventListener('resize', () => { if (ui.mapOpen && visible()) drawMap(); });
}

/** Chegou à aba. `pendingNode`: caixa pedida pelo "Ver SQL". */
export async function renderSqlView(pendingNode = null) {
  if (!visible()) return;
  if (!ui.selection && !pendingNode) ui.selection = storage(selectionKey(), null);
  if (!ui.data) await refresh();
  if (pendingNode) showNode(pendingNode);
  else {
    const nearest = nearestToSelection();
    if (nearest && !ui.data?.selection.includes(nearest)) { ui.temporary = null; ui.selection = [nearest]; }
  }
  refresh();
}
