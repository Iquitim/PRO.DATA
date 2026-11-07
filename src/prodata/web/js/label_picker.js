// Seletor de rótulo de confidencialidade (spec 026): cada nível com ícone e cor, e uma dica por cima que diz o
// que vai acontecer na exportação. A dica existe porque o efeito muda com o tipo de arquivo: o HTML pede senha,
// a imagem e o Excel não têm como pedir.

import { h } from './dom.js';
import { icon } from './icons.js';

export const LABELS = { publico: 'Público', interno: 'Interno', confidencial: 'Confidencial', restrito: 'Restrito' };
export const passwordRequired = (level) => ['confidencial', 'restrito'].includes(level);

const LEVELS = {
  publico: { icon: 'globe', text: 'Pode circular fora da empresa' },
  interno: { icon: 'building', text: 'Só para quem trabalha na empresa' },
  confidencial: { icon: 'lock', text: 'Só para quem precisa ver' },
  restrito: { icon: 'shield', text: 'Poucas pessoas autorizadas' },
};

const COACH_MS = 7000;

/**
 * O que acontece com este rótulo, só na saída de onde a dica foi aberta: o HTML só aparece no HTML.
 * `place`: dash (rótulo da página e imagem), image, html ou file (Output Data).
 */
function effects(level, place) {
  const name = LABELS[level];
  const strict = passwordRequired(level);
  if (place === 'file') {
    return strict
      ? [['table', 'No Excel: vai nas propriedades, na impressão e na cor da aba. O arquivo não recebe senha.'],
        ['file', `Nos outros formatos: "${name}" entra no nome do arquivo.`]]
      : [['table', 'No Excel: vai nas propriedades, na impressão e na cor da aba.']];
  }
  if (place === 'html') {
    return [strict
      ? ['lock', 'O HTML vai pedir senha: sem ela, não dá para salvar. Os dados ficam cifrados.']
      : ['globe', 'O HTML pode ter senha, se você quiser.']];
  }
  return [strict
    ? ['alert', `A imagem não tem como levar senha: sai com a faixa "${name}". Cuidado com quem recebe.`]
    : ['image', 'A imagem sai com a faixa do rótulo.']];
}

let tipEl = null;
let tipTimer = 0;

export function hideLabelTip() {
  clearTimeout(tipTimer);
  tipEl?.remove();
  tipEl = null;
  document.removeEventListener('pointerdown', hideLabelTip, true);
}

/** Dica por cima da tela. `ms`: some sozinha depois disso (ao escolher o rótulo); sem ela, some ao sair o mouse. */
export function showLabelTip(anchor, level, place, { ms = 0 } = {}) {
  hideLabelTip();
  if (!anchor?.isConnected) return;
  tipEl = h('div', { class: ['label-tip', `label-tone-${level}`], role: 'tooltip' },
    h('div', { class: 'label-tip-head' }, icon(LEVELS[level].icon, 15), h('strong', {}, LABELS[level])),
    effects(level, place).map(([name, text]) => h('p', {}, icon(name, 14), h('span', {}, text))));
  // Dentro de um diálogo modal, só o que está no próprio diálogo aparece por cima dele.
  (anchor.closest('dialog') || document.body).append(tipEl);
  const r = anchor.getBoundingClientRect();
  const below = r.bottom + tipEl.offsetHeight + 12 < window.innerHeight;
  tipEl.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - tipEl.offsetWidth - 8))}px`;
  tipEl.style.top = `${below ? r.bottom + 8 : Math.max(8, r.top - tipEl.offsetHeight - 8)}px`;
  if (ms) {
    tipTimer = setTimeout(hideLabelTip, ms);
    document.addEventListener('pointerdown', hideLabelTip, true); // clicar em qualquer lugar dispensa
  }
}

/** Liga a dica a um elemento: aparece ao passar o mouse ou com o foco do teclado. */
export function withLabelTip(el, level, place) {
  el.addEventListener('mouseenter', () => showLabelTip(el, level(), place));
  el.addEventListener('mouseleave', hideLabelTip);
  el.addEventListener('focus', () => showLabelTip(el, level(), place));
  el.addEventListener('blur', hideLabelTip);
  return el;
}

/** Selo no botão de exportar: mostra de longe que aquela saída tem cuidado especial. */
export function guardBadge(level, kind) {
  if (!passwordRequired(level)) return null;
  return h('span', { class: ['label-guard', `label-tone-${level}`], title: null }, icon(kind === 'html' ? 'lock' : 'alert', 12),
    kind === 'html' ? 'Com senha' : 'Sem senha');
}

let openPop = null;

function closePop() {
  openPop?.remove();
  openPop = null;
  document.removeEventListener('pointerdown', closeOutside, true);
}

function closeOutside(e) {
  if (openPop && !openPop.contains(e.target)) closePop();
}

/** `value` e `onChange(nível)`; `place` decide o texto da dica: dash, html ou file. */
export function labelPicker({ value, onChange, place = 'dash', id = null }) {
  let current = LABELS[value] ? value : 'interno';
  const root = h('div', { class: 'label-pick', dataset: { place } });
  const draw = () => {
    const trigger = h('button', {
      type: 'button', id, class: ['label-pick-btn', `label-tone-${current}`], 'aria-haspopup': 'listbox', 'aria-label': `Rótulo de confidencialidade: ${LABELS[current]}`,
      onclick: (e) => { const same = Boolean(openPop); closePop(); hideLabelTip(); if (!same) openList(e.currentTarget); },
    }, icon(LEVELS[current].icon, 15), h('span', {}, LABELS[current]), icon('chevron-down', 13));
    withLabelTip(trigger, () => current, place);
    root.replaceChildren(trigger);
    return trigger;
  };
  const choose = (level) => {
    closePop();
    current = level;
    onChange(level);
    // Quem desenha pode refazer a tela ao mudar o rótulo: procura o botão de novo antes de mostrar a dica.
    const shown = draw();
    if (!passwordRequired(level)) return;
    requestAnimationFrame(() => {
      const anchor = shown.isConnected ? shown : document.querySelector(`.label-pick[data-place="${place}"] .label-pick-btn`);
      showLabelTip(anchor, level, place, { ms: COACH_MS });
    });
  };
  const openList = (anchor) => {
    const list = h('div', { class: 'label-pick-list', role: 'listbox', 'aria-label': 'Rótulos de confidencialidade' },
      Object.entries(LABELS).map(([level, name]) => h('button', {
        type: 'button', role: 'option', 'aria-selected': level === current ? 'true' : 'false',
        class: ['label-pick-item', `label-tone-${level}`, level === current && 'active'], dataset: { level },
        onclick: () => choose(level),
      }, h('span', { class: 'label-pick-mark' }, icon(LEVELS[level].icon, 15)),
      h('span', { class: 'label-pick-text' }, h('b', {}, name), h('small', {}, LEVELS[level].text)))));
    list.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePop(); anchor.focus(); }
      const items = [...list.querySelectorAll('button')];
      const at = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1) % items.length].focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length].focus(); }
    });
    (anchor.closest('dialog') || document.body).append(list);
    const r = anchor.getBoundingClientRect();
    list.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - list.offsetWidth - 8))}px`;
    list.style.top = `${r.bottom + list.offsetHeight + 8 < window.innerHeight ? r.bottom + 4 : Math.max(8, r.top - list.offsetHeight - 4)}px`;
    openPop = list;
    document.addEventListener('pointerdown', closeOutside, true);
    list.querySelector('.active')?.focus();
  };
  draw();
  return root;
}
