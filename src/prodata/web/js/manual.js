// Manual dentro do programa (spec 029, RF-2983..2989): o guia, ao lado do trabalho, com busca e links que agem na tela.
// O conteúdo vem de manual.json, gerado a partir de docs/guia/guia.html: é texto nosso, instalado com o programa.

import { h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { revealPanel } from './layout.js';
import { CONTEXT, TARGETS } from './manual_targets.js';
import { node, on, store, toolOf } from './store.js';
import { toast, toastError } from './ui.js';

const fold = (text) => String(text ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const RESULTS = 30;
const RING_MS = 6000;
const WIDTH_KEY = 'prodata.manual.largura';
const EXPANDED_KEY = 'prodata.manual.expandido';
const MIN_WIDTH = 340;
const EXPANDED_WIDTH = 1000;
const ROOM_FOR_WORK = 320; // o que sobra para o trabalho, por menor que seja a janela

let data = null;
let root = null;
let actions = {};
let current = null; // capítulo aberto; null é o sumário
let query = '';

let width = storage(WIDTH_KEY, null);
let expanded = storage(EXPANDED_KEY, false);

/** Largura do Manual: a padrão, a que a pessoa arrastou ou a expandida. */
function applyWidth() {
  const wanted = expanded ? EXPANDED_WIDTH : width;
  const style = document.documentElement.style;
  if (wanted) style.setProperty('--manual-w', `min(${wanted}px, calc(100vw - ${ROOM_FOR_WORK}px))`);
  else style.removeProperty('--manual-w');
  const button = root?.querySelector('.manual-expand');
  if (button) {
    button.title = expanded ? 'Voltar à largura normal' : 'Expandir o Manual';
    button.setAttribute('aria-pressed', String(expanded));
    button.replaceChildren(icon(expanded ? 'minimize' : 'maximize', 15));
  }
  window.dispatchEvent(new Event('resize'));
}

function toggleExpanded() {
  expanded = !expanded;
  persist(EXPANDED_KEY, expanded);
  applyWidth();
}

/** Arrastar a borda esquerda ajusta a largura, e ela fica lembrada. */
function startResize(e) {
  e.preventDefault();
  document.body.classList.add('resizing');
  const move = (ev) => {
    expanded = false;
    width = Math.round(Math.max(MIN_WIDTH, Math.min(innerWidth - ROOM_FOR_WORK, innerWidth - ev.clientX)));
    applyWidth();
  };
  const stop = () => {
    document.body.classList.remove('resizing');
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', stop);
    persist(WIDTH_KEY, width);
    persist(EXPANDED_KEY, expanded);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', stop);
}

const chapterTitle = (c) => (c.number ? `Capítulo ${c.number} · ${c.title}` : c.title);
const isDark = () => (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';

async function ensureData() {
  if (!data) data = await fetch('/static/manual/manual.json').then((r) => r.json());
  return data;
}

// ------------------------------------------------------------------ imagens no tema

function setImage(img) {
  const name = img.dataset.img;
  const light = `/static/manual/img/${name}`;
  img.onerror = () => { img.onerror = null; img.src = light; }; // captura ainda sem versão escura
  img.src = isDark() ? `/static/manual/img-escuro/${name}` : light;
}

const refreshImages = () => root?.querySelectorAll('img[data-img]').forEach(setImage);

// ------------------------------------------------------------------ mostrar onde fica

let ring = null;
function clearRing() {
  ring?.forEach((el) => el.remove());
  ring = null;
}

/** Acha o alvo, leva até a tela certa e acende (RF-2985). */
export function showTarget(key) {
  const target = TARGETS[key];
  if (!target) return false;
  clearRing();
  if (target.view && store.view !== target.view) actions.setView(target.view);
  if (target.panel) revealPanel(target.panel);
  requestAnimationFrame(() => setTimeout(() => {
    const el = [...document.querySelectorAll(target.sel)].find((e) => e.offsetParent && (!target.text || e.textContent.includes(target.text)));
    if (!el) { toast('Isso não está à vista agora', { detail: 'Abra um fluxo ou a tela citada no texto e tente de novo.' }); return; }
    highlight(el, target.tip);
  }, 60));
  return true;
}

function highlight(el, tip) {
  el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  const r = el.getBoundingClientRect();
  const box = h('div', { class: 'manual-ring', style: { left: `${r.left - 4}px`, top: `${r.top - 4}px`, width: `${r.width + 8}px`, height: `${r.height + 8}px` } });
  const label = h('div', { class: 'manual-ring-tip', role: 'status' }, tip);
  document.body.append(box, label);
  const tr = label.getBoundingClientRect();
  const above = r.top - tr.height - 12;
  label.style.left = `${Math.max(8, Math.min(r.left, innerWidth - tr.width - 8))}px`;
  label.style.top = `${above > 8 ? above : r.bottom + 12}px`;
  const mine = [box, label];
  ring = mine;
  // Só apaga o próprio destaque: o temporizador de um antigo não pode apagar o que veio depois.
  const stop = () => { if (ring === mine) clearRing(); document.removeEventListener('pointerdown', stop, true); };
  document.addEventListener('pointerdown', stop, true);
  setTimeout(stop, RING_MS);
}

/** Link de ferramenta: mostra a ferramenta na lista, já filtrada pelo nome (RF-2987). */
function showTool(type) {
  const tool = store.tools[type];
  if (!tool) return;
  actions.setView('designer');
  revealPanel('explorer');
  document.querySelector('#leftPanel .tab[data-tab=tools]')?.click();
  const search = document.querySelector("#leftPanel input[placeholder='Buscar ferramenta']");
  if (search) { search.value = tool.name; search.dispatchEvent(new Event('input', { bubbles: true })); }
  setTimeout(() => {
    const el = [...document.querySelectorAll('#leftPanel .tool-item')].find((e) => e.querySelector('.tool-name')?.textContent === tool.name);
    if (el) highlight(el, tool.description.split('.')[0]);
  }, 80);
}

async function tryExample(name) {
  try {
    const workflow = await fetch(`/static/manual/exemplos/${name}.json`).then((r) => r.json());
    await actions.openExample(workflow);
  } catch (err) {
    toastError(err, 'Não foi possível abrir o exemplo');
  }
}

// ------------------------------------------------------------------ desenho

/** O capítulo que combina com o que a pessoa está fazendo agora (RF-2988). */
function suggested() {
  const selected = node(store.selection?.nodeId);
  const title = CONTEXT.views[store.view]
    || (selected ? CONTEXT.tools[selected.type] || CONTEXT.selected : CONTEXT.idle);
  const where = store.view === 'designer'
    ? (selected ? `Você está no Designer, com a caixa ${selected.label || toolOf(selected)?.name}` : 'Você está no Designer')
    : `Você está na vista ${{ data: 'Dados', dashboard: 'Dashboard', sql: 'SQL' }[store.view]}`;
  return { chapter: data.chapters.find((c) => c.title === title), where };
}

function chapterRow(c) {
  return h('button', { type: 'button', class: 'manual-chapter', onclick: () => openChapter(c) },
    h('i', {}, c.number || '·'), h('span', {}, c.title));
}

function homeView() {
  const { chapter, where } = suggested();
  return [
    chapter ? h('button', { type: 'button', class: 'manual-here', onclick: () => openChapter(chapter) }, h('small', {}, where), h('b', {}, chapter.title)) : null,
    ...data.chapters.map(chapterRow),
  ].filter(Boolean);
}

function searchSections(text) {
  const words = fold(text).split(/\s+/).filter(Boolean);
  const hits = [];
  for (const c of data.chapters) {
    for (const s of c.sections) {
      const title = fold(`${c.title} ${s.title}`);
      const body = fold(s.text);
      if (!words.every((w) => title.includes(w) || body.includes(w))) continue;
      const score = words.filter((w) => fold(s.title || c.title).includes(w)).length;
      hits.push({ c, s, score, at: Math.max(0, body.indexOf(words[0]) - 40) });
    }
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, RESULTS);
}

function searchView() {
  const hits = searchSections(query);
  if (!hits.length) return [h('p', { class: 'manual-none' }, 'Nada encontrado. Tente outra palavra.')];
  return hits.map(({ c, s, at }) => h('button', { type: 'button', class: 'manual-hit', onclick: () => openChapter(c, s.id) },
    h('b', {}, s.title || c.title), h('small', {}, chapterTitle(c)), h('span', {}, `${at ? '…' : ''}${s.text.slice(at, at + 130)}…`)));
}

function chapterView(c) {
  const article = h('article', { class: 'manual-text' });
  article.innerHTML = c.html; // conteúdo nosso: gerado do guia e instalado com o programa
  for (const b of article.querySelectorAll('[data-show]')) b.prepend(icon('target', 13));
  for (const b of article.querySelectorAll('[data-try]')) b.prepend(icon('play', 13));
  return [h('div', { class: 'manual-crumb' }, c.label || 'Visão geral'), h('h2', {}, c.title), article];
}

function draw(sectionId = '') {
  if (!root || !data) return;
  const searching = query.trim().length > 1;
  const body = root.querySelector('.manual-body');
  body.replaceChildren(...(searching ? searchView() : current ? chapterView(current) : homeView()));
  root.querySelector('.manual-back').hidden = !current || searching;
  refreshImages();
  if (sectionId) body.querySelector(`#${sectionId}`)?.scrollIntoView({ block: 'start' });
  else body.scrollTop = 0;
}

function openChapter(c, sectionId = '') {
  current = c;
  query = '';
  root.querySelector('.manual-find').value = '';
  draw(sectionId);
}

function build() {
  root = h('aside', { class: 'manual', 'aria-label': 'Manual', hidden: true },
    h('div', { class: 'manual-resize', title: 'Arraste para ajustar a largura', onpointerdown: startResize }),
    h('header', { class: 'manual-head' },
      h('button', { type: 'button', class: 'manual-back btn btn-ghost btn-icon btn-sm', title: 'Voltar ao sumário', hidden: true, onclick: () => { current = null; draw(); } }, icon('chevron-left', 15)),
      h('b', {}, 'Manual'),
      h('button', { type: 'button', class: 'btn btn-ghost btn-icon btn-sm manual-expand', onclick: toggleExpanded }),
      h('button', { type: 'button', class: 'btn btn-ghost btn-icon btn-sm manual-close', title: 'Fechar (F1)', onclick: () => closeManual() }, icon('x', 15))),
    h('div', { class: 'manual-search' }, h('input', {
      class: 'input input-search manual-find', type: 'search', placeholder: 'Buscar no manual…', 'aria-label': 'Buscar no manual',
      oninput: (e) => { query = e.target.value; draw(); },
    })),
    h('div', { class: 'manual-body' }));
  root.addEventListener('click', (e) => {
    const show = e.target.closest('[data-show]');
    const example = e.target.closest('[data-try]');
    const tool = e.target.closest('[data-tool]');
    if (show) showTarget(show.dataset.show);
    else if (example) tryExample(example.dataset.try);
    else if (tool) showTool(tool.dataset.tool);
  });
  document.body.append(root);
  applyWidth();
  new MutationObserver(refreshImages).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', refreshImages);
}

export const manualIsOpen = () => Boolean(root && !root.hidden);

export function closeManual() {
  if (!root) return;
  root.hidden = true;
  clearRing();
  document.body.classList.remove('manual-open');
  window.dispatchEvent(new Event('resize'));
}

export async function openManual() {
  try {
    await ensureData();
  } catch (err) {
    toastError(err, 'Não foi possível abrir o manual');
    return;
  }
  root.hidden = false;
  document.body.classList.add('manual-open');
  window.dispatchEvent(new Event('resize'));
  draw();
}

/** Abre no sumário, com a sugestão da tela atual; se já está aberto, fecha. */
export function toggleManual() {
  if (manualIsOpen()) closeManual();
  else { current = null; query = ''; if (root) root.querySelector('.manual-find').value = ''; openManual(); }
}

/** Abre num capítulo, vindo da busca de comandos. */
async function openAt(chapterId, sectionId) {
  await openManual();
  const c = data.chapters.find((x) => x.id === chapterId);
  if (c) openChapter(c, sectionId);
}

/** Capítulos e seções na busca de comandos (Ctrl+K). */
export function manualEntries() {
  if (!data) return [];
  return data.chapters.flatMap((c) => c.sections.filter((s) => s.title || c.sections[0] === s).map((s) => ({
    group: 'Manual', icon: 'book', name: s.title || c.title, detail: chapterTitle(c), end: 'abrir', keywords: s.title ? '' : c.label,
    run: () => openAt(c.id, s.id),
  })));
}

/** `a`: { setView, openExample(workflow) }. */
export function initManual(a) {
  actions = a;
  build();
  ensureData().catch(() => {}); // a busca de comandos já acha os capítulos
  on('selection', () => { if (manualIsOpen() && !current && !query) draw(); });
}
