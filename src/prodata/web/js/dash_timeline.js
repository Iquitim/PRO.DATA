// Barra da linha do tempo (spec 030): a mesma no programa e no HTML exportado.

import { momentLabel } from './dash_replay.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';

const SPEEDS = [[0.5, '0,5×'], [1, '1×'], [2, '2×'], [4, '4×']];
const MODE_TEXT = {
  cumulative: 'Acumulado: cada momento soma tudo o que veio antes dele.',
  period: 'Só naquele período: cada momento mostra só o que aconteceu nele. É o certo para fotos, como as do Estado por período.',
};

/** Selo do visual que fica parado na linha do tempo (RF-3043). */
export function stillBadge(column) {
  return h('span', { class: 'dash-nofilter', title: `Este visual não tem a coluna ${column}: fica parado na linha do tempo.` },
    icon('clock', 11), 'Parado');
}

function modeSwitch(timeline, onMode) {
  const choice = (mode, label) => h('button', {
    type: 'button', class: ['replay-mode', timeline.mode === mode && 'on'], 'aria-pressed': String(timeline.mode === mode), dataset: { mode },
    onclick: () => onMode(mode),
  }, label);
  return h('div', { class: 'replay-modes', role: 'group', 'aria-label': 'Como contar' }, choice('cumulative', 'Acumulado'), choice('period', 'Só no período'));
}

function speedPicker(timeline, onSpeed) {
  return h('select', { class: 'input replay-speed', 'aria-label': 'Velocidade', onchange: (e) => onSpeed(Number(e.target.value)) },
    SPEEDS.map(([value, label]) => h('option', { value, selected: timeline.speed === value }, label)));
}

/** `extra`: botões que só existem no programa. Devolve o elemento e `update()`, que não refaz a barra. */
export function timelineBar(replay, { onMode, onSpeed, extra = [], stillCount = 0 }) {
  const { moments, timeline } = replay;
  const playIcon = h('span', { class: 'replay-play-icon' });
  const play = h('button', { type: 'button', class: 'btn btn-primary replay-play', onclick: () => replay.toggle() }, playIcon);
  const label = h('strong', { class: 'replay-now', 'aria-live': 'off' });
  const slider = h('input', {
    type: 'range', class: 'replay-slider', min: 0, max: moments.length - 1, step: 1, 'aria-label': 'Momento',
    oninput: (e) => { if (replay.playing) replay.pause(); replay.seek(Number(e.target.value)); },
  });
  const pins = h('div', { class: 'replay-pins' });
  const about = h('p', { class: 'replay-about' });
  const baseAbout = `${MODE_TEXT[timeline.mode]}${stillCount ? ` ${stillCount === 1 ? '1 visual fica parado' : `${stillCount} visuais ficam parados`}: sem a coluna ${timeline.column}.` : ''}`;
  let shown = null;
  const showNote = (mark) => {
    shown = mark;
    about.textContent = mark ? `${momentLabel(moments[mark.index], timeline.step)} · ${mark.kind}: ${mark.text}.` : baseAbout;
    about.classList.toggle('on', Boolean(mark));
  };
  const place = () => {
    const { title, marks } = replay.highlights();
    const span = Math.max(1, moments.length - 1);
    pins.replaceChildren(...marks.map((mark) => h('button', {
      type: 'button', class: ['replay-pin', `kind-${mark.kind.replace(/\s/g, '-').replace('ê', 'e')}`], style: { left: `${(mark.index / span) * 100}%` },
      title: `${mark.kind}: ${mark.text} (${title})`, 'aria-label': `${mark.kind} em ${momentLabel(moments[mark.index], timeline.step)}`,
      onclick: () => { if (replay.playing) replay.pause(); replay.seek(mark.index); showNote(mark); },
    }, h('span', {}))));
  };
  const update = () => {
    const name = replay.playing ? 'pause' : 'play';
    if (play.dataset.icon !== name) {
      play.dataset.icon = name;
      playIcon.replaceChildren(icon(name, 14));
      play.title = replay.playing ? 'Pausar' : 'Reproduzir';
      play.setAttribute('aria-label', play.title);
    }
    slider.value = String(replay.index);
    label.textContent = momentLabel(replay.moment, timeline.step);
    if (shown && shown.index !== replay.index) showNote(null);
  };
  const el = h('section', { class: 'replay-bar', 'aria-label': 'Linha do tempo' },
    h('div', { class: 'replay-row' },
      play, label,
      h('div', { class: 'replay-track' }, slider, pins),
      modeSwitch(timeline, onMode),
      speedPicker(timeline, onSpeed),
      extra),
    about);
  showNote(null);
  place();
  update();
  return { el, update, place };
}

/** Botão comum da barra, para os dois lugares terem a mesma cara. */
export const barButton = (props) => button({ size: 'sm', ...props });
