// História do dashboard (spec 030, RF-3061..3064): sequência de cenas em tela cheia.
// A mesma apresentação no programa e no HTML exportado; o programa soma o caminho até a origem.

import { button, h } from './dom.js';

const AUTO_MS = 7000;
const PADDING = 32;

/**
 * `render(scene)` devolve a página da cena no tamanho real; `size` é {width, height} dela.
 * `trace(scene, close)` devolve botões extras, ou nada.
 */
export function openStory({ scenes, render, size, trace, label = '' }) {
  let index = 0;
  let timer = 0;
  let playing = false;
  const stage = h('div', { class: 'story-stage' });
  const title = h('h2', { class: 'story-title' });
  const note = h('p', { class: 'story-note' });
  const counter = h('span', { class: 'story-count' });
  const extras = h('div', { class: 'story-extra' });
  const close = () => {
    clearTimeout(timer);
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', draw);
    root.remove();
  };
  const go = (next) => {
    index = (next + scenes.length) % scenes.length;
    draw();
    if (playing) arm();
  };
  const arm = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (index === scenes.length - 1) { playing = false; drawNav(); return; }
      go(index + 1);
    }, AUTO_MS);
  };
  const toggle = () => {
    playing = !playing;
    drawNav();
    if (playing) arm(); else clearTimeout(timer);
  };
  const nav = h('div', { class: 'story-nav' });
  function drawNav() {
    nav.replaceChildren(
      button({ icon: 'chevron-left', label: 'Anterior', disabled: index === 0, onClick: () => go(index - 1) }),
      button({ icon: playing ? 'pause' : 'play', label: playing ? 'Pausar' : 'Reproduzir', onClick: toggle }),
      button({ icon: 'chevron-right', label: 'Próxima', variant: 'primary', disabled: index === scenes.length - 1, onClick: () => go(index + 1) }),
      counter,
      button({ icon: 'x', label: 'Sair', variant: 'ghost', onClick: close }));
  }
  function draw() {
    const scene = scenes[index];
    title.textContent = scene.title || `Cena ${index + 1}`;
    note.textContent = scene.note || '';
    counter.textContent = `${index + 1} de ${scenes.length}`;
    extras.replaceChildren(...(trace?.(scene, close) || []));
    drawNav();
    const page = render(scene);
    const fit = Math.min(Math.max(120, stage.clientWidth - PADDING) / size.width, Math.max(120, stage.clientHeight - PADDING) / size.height, 1.5);
    page.style.transform = `scale(${fit})`;
    stage.replaceChildren(h('div', { class: 'dash-sheet story-sheet', style: { width: `${size.width * fit}px`, height: `${size.height * fit}px` } }, page));
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'ArrowRight' && index < scenes.length - 1) { e.preventDefault(); go(index + 1); }
    else if (e.key === 'ArrowLeft' && index > 0) { e.preventDefault(); go(index - 1); }
  }
  const root = h('div', { class: 'story', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Apresentação da história' },
    label ? h('div', { class: ['label-bar', `label-${label.level}`] }, `Classificação: ${label.name}`) : null,
    stage,
    h('footer', { class: 'story-foot' }, h('div', { class: 'story-text' }, title, note, extras), nav));
  document.body.append(root);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('resize', draw);
  requestAnimationFrame(draw);
  return close;
}
