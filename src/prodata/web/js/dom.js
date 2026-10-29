// Utilitários de DOM e formatação.

import { icon } from './icons.js';

/**
 * Cria um elemento. Atributos `on*` viram listeners; `class` aceita string ou array;
 * filhos podem ser strings, nós, arrays ou null.
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'class') {
      el.className = Array.isArray(value) ? value.filter(Boolean).join(' ') : value;
    } else if (key === 'style' && typeof value === 'object') {
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith('--')) el.style.setProperty(prop, v);
        else el.style[prop] = v;
      }
    } else if (key === 'dataset') {
      Object.assign(el.dataset, value);
    } else if (key in el && typeof value !== 'string') {
      el[key] = value;
    } else {
      el.setAttribute(key, value === true ? '' : value);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Botão com ícone. `label` vira texto visível; `title` vira tooltip e aria-label. */
export function button({ icon: iconName, label, title, variant = '', size = '', onClick, ...rest } = {}) {
  return h(
    'button',
    {
      type: 'button',
      class: ['btn', variant && `btn-${variant}`, size && `btn-${size}`, !label && 'btn-icon'],
      title: title || label,
      'aria-label': title || label,
      onclick: onClick,
      ...rest,
    },
    iconName ? icon(iconName, size === 'sm' ? 14 : 16) : null,
    label ? h('span', {}, label) : null,
  );
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

const NUMBER = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
const COMPACT = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });

export const fmt = {
  number: (v, digits) => (v === null || v === undefined || Number.isNaN(v) ? '—'
    : digits === undefined ? NUMBER.format(v)
      : new Intl.NumberFormat('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)),
  compact: (v) => COMPACT.format(v),
  int: (v) => NUMBER.format(Math.round(v ?? 0)),
  bytes(n) {
    if (n < 1024) return `${n} B`;
    const units = ['KB', 'MB', 'GB'];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${NUMBER.format(Number(v.toFixed(1)))} ${units[i]}`;
  },
  date: (iso) => new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }),
  ms: (v) => (v >= 1000 ? `${NUMBER.format(v / 1000)} s` : `${NUMBER.format(v)} ms`),
};

export function debounce(fn, wait = 250) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

export const uid = (prefix = 'n') => `${prefix}_${Math.random().toString(36).slice(2, 8)}`;

export function storage(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}

export function persist(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* modo privado ou armazenamento bloqueado: preferência só não é lembrada */
  }
}

export function isTyping(target = document.activeElement) {
  const tag = target?.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable;
}
