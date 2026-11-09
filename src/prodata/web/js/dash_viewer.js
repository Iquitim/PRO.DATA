// Página do HTML exportado (spec 021): mostra o dashboard e recalcula os visuais quando um filtro muda.
// Roda sozinha, sem servidor: tudo o que precisa está no próprio arquivo. Com senha (spec 026), os dados
// só existem cifrados até a pessoa digitá-la.

import { chartChrome, freeEl, placeItem, setCardEnv, visualCard } from './dash_cards.js';
import { computeWidget, applyFilters } from './dash_compute.js';
import { decryptText } from './dash_crypt.js';
import { activeFiltersText, clickedValues, filterBar, filtersFor, isFilterActive, noFilterBadge, selectedIn } from './dash_filters.js';
import { createReplay, makeTables, momentsOf } from './dash_replay.js';
import { openStory } from './dash_story.js';
import { stillBadge, timelineBar } from './dash_timeline.js';
import { h } from './dom.js';

const PAGE_W = 1600;
const root = document.getElementById('prodata-pagina');

const labelBar = (level, name) => (name ? h('div', { class: ['label-bar', `label-${level}`] }, `Classificação: ${name}`) : null);

function start(data) {
  const filters = (data.filters || []).map((f) => ({ ...f }));

  const tables = makeTables(data);
  const timeline = data.timeline ? { ...data.timeline } : null;
  const span = timeline ? momentsOf(tables, timeline.column, timeline.step) : { moments: [] };
  const animates = (id) => data.items.find((i) => i.node_id === id)?.format?.animate !== false;
  const replay = span.moments.length ? createReplay({
    data, tables, timeline, moments: span.moments, animates, getFilters: () => filters,
    draw: (w) => patch(w), changed: () => bar?.update(),
  }) : null;
  const isStill = (id) => Boolean(replay) && !(timeline.column in (tables[id]?.columns || {}));
  let bar = null;

  const widgets = () => {
    const out = { ...data.widgets };
    const missing = {};
    for (const [id, node] of Object.entries(data.nodes || {})) {
      const { table, missing: absent } = applyFilters(tables[id], filtersFor(node.config, filters));
      if (absent.length) missing[id] = absent;
      try {
        out[id] = { ...computeWidget(node.tool, node.config, table), node_id: id };
      } catch (err) {
        out[id] = { widget_type: 'message', title: node.title, message: err.message, node_id: id };
      }
    }
    for (const item of data.items) {
      if (item.kind !== 'visual' || data.nodes?.[item.node_id]) continue;
      const absent = filters.filter(isFilterActive).map((f) => f.column);
      if (absent.length) missing[item.node_id] = [...new Set(absent)];
    }
    if (replay) Object.assign(out, replay.widgets());
    return { out, missing };
  };

  const page = () => {
    const { out, missing } = widgets();
    return h('div', {
      class: 'dash-page dash-viewer-page',
      style: { width: `${PAGE_W}px`, height: `${data.height}px`, backgroundColor: data.page.background || null },
    }, data.items.map((item) => itemNode(item, out, missing)));
  };

  const itemNode = (item, out, missing = {}) => {
    const f = item.format || {};
    const w = out[item.node_id];
    if (item.kind === 'visual' && !w) return null;
    const content = item.kind === 'visual'
      ? visualCard(w, { width: item.w, height: Math.max(80, item.h - chartChrome(f)), className: 'fill', fmt: f, cross: true })
      : freeEl(item, { editing: false });
    if (!content) return null;
    return placeItem(item, content, [
      missing[item.node_id] ? noFilterBadge(missing[item.node_id]) : null,
      item.kind === 'visual' && isStill(item.node_id) ? stillBadge(timeline.column) : null,
    ]);
  };

  /** Durante a reprodução, só os visuais que mudaram. */
  const patch = (widgets) => {
    for (const item of data.items) {
      if (item.kind !== 'visual' || !widgets[item.node_id]) continue;
      const old = root.querySelector(`.dash-item[data-id="${CSS.escape(item.id)}"]`);
      const next = old && itemNode(item, widgets);
      if (next) old.replaceWith(next);
    }
  };

  const present = () => {
    const { out } = widgets();
    openStory({
      scenes: data.scenes,
      size: { width: PAGE_W, height: data.height },
      label: data.label_name ? { level: data.label, name: data.label_name } : '',
      render: (scene) => {
        const current = { ...out, ...replay.snapshot(scene.filters || [], scene.moment || replay.moment) };
        return h('div', {
          class: ['dash-page', 'dash-viewer-page', scene.item_id && 'has-spot'],
          style: { width: `${PAGE_W}px`, height: `${data.height}px`, backgroundColor: data.page.background || null },
        }, data.items.map((item) => {
          const el = itemNode(item, current);
          if (el && item.id === scene.item_id) el.classList.add('spot');
          return el;
        }).filter(Boolean));
      },
    });
  };

  const buildBar = () => {
    bar = timelineBar(replay, {
      stillCount: data.items.filter((i) => i.kind === 'visual' && isStill(i.node_id)).length,
      onMode: (mode) => { timeline.mode = mode; replay.invalidate(); buildBar(); schedule(); },
      onSpeed: (speed) => { timeline.speed = speed; },
      extra: data.scenes?.length ? [h('button', { type: 'button', class: 'btn btn-sm', onclick: present }, 'Ver história')] : [],
    });
  };

  let pending = 0;
  let pulse = false;
  const schedule = () => {
    pulse = true;
    replay?.invalidate();
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(draw);
  };

  function draw() {
    const available = Math.max(320, document.documentElement.clientWidth - 32);
    const scale = Math.min(available / PAGE_W, 1.5);
    const sheet = h('div', { class: 'dash-sheet', style: { width: `${PAGE_W * scale}px`, height: `${data.height * scale}px` } }, page());
    sheet.firstChild.style.transform = `scale(${scale})`;
    if (pulse) sheet.firstChild.classList.add('dash-refresh');
    pulse = false;
    const note = data.fixed_filters ? h('p', { class: 'dash-viewer-fixed' }, `Recorte aplicado ao gerar este arquivo: ${data.fixed_filters}`) : null;
    const filtersEl = filterBar({
      filters,
      options: data.options,
      onChange: (id, patch) => { Object.assign(filters.find((f) => f.id === id), patch); schedule(); },
      onClear: () => { for (const f of filters) { f.selected = []; f.min = null; f.max = null; } schedule(); },
    });
    const head = h('header', { class: 'dash-head' }, h('div', { class: 'dash-brand' },
      data.logo ? h('img', { class: 'dash-logo', src: data.logo, alt: 'Grupo Protege' }) : null,
      h('div', {}, h('div', { class: 'dash-org' }, 'Grupo Protege'), h('h1', {}, data.name),
        h('p', { class: 'muted' }, `Dados de ${data.exported_at} · ${activeFiltersText(filters) || 'sem filtros aplicados'}`))));
    if (replay && !bar) buildBar();
    root.replaceChildren(...[labelBar(data.label, data.label_name), head, note, filtersEl, bar?.el, sheet].filter(Boolean));
  }

  setCardEnv({
    open: null,
    clickable: () => false,
    // O arquivo só leva as colunas dos filtros: sem filtro naquela coluna, não há como recalcular.
    canFilter: (w) => filters.some((f) => f.kind === 'list' && f.column === w.x_column),
    selectedFor: (w) => selectedIn([...filters, ...(data.frozen_filters || [])], w.x_column),
    onCategory: (w, value, adding) => {
      const f = filters.find((x) => x.kind === 'list' && x.column === w.x_column);
      f.selected = clickedValues(f.selected, value, adding);
      schedule();
    },
  });
  let resizing = 0;
  window.addEventListener('resize', () => { clearTimeout(resizing); resizing = setTimeout(draw, 120); });
  document.title = data.name;
  draw();
}

/** Tela de senha: nada dos dados existe em claro até aqui. */
function gate(box) {
  const input = h('input', { class: 'input', type: 'password', autocomplete: 'off', 'aria-label': 'Senha do arquivo', placeholder: 'Senha' });
  const message = h('p', { class: 'dash-gate-error', role: 'alert' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, 'Abrir');
  const form = h('form', {
    class: 'dash-gate',
    onsubmit: async (e) => {
      e.preventDefault();
      message.textContent = '';
      submit.disabled = true;
      try {
        const text = await decryptText(box, input.value);
        start(JSON.parse(text));
      } catch {
        message.textContent = 'Senha incorreta.';
        submit.disabled = false;
        input.select();
      }
    },
  },
  labelBar(box.label, box.label_name),
  h('div', { class: 'dash-gate-body' },
    h('h1', {}, 'Documento protegido'),
    h('p', { class: 'muted' }, 'Digite a senha informada por quem enviou este arquivo.'),
    input, submit, message));
  root.replaceChildren(form);
  input.focus();
}

const open = document.getElementById('prodata-dados');
if (open) start(JSON.parse(open.textContent));
else gate(JSON.parse(document.getElementById('prodata-cifrado').textContent));
