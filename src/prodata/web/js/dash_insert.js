// Inserir na página: textos, imagens, o logo e formas, escolhendo um lugar livre.

import { GRID, PAGE_W } from './dash_model.js';
import { overlaps } from './dash_snap.js';
import { commitLayout, dash, els, newId, page, ui } from './dash_state.js';
import { h } from './dom.js';
import { icon } from './icons.js';
import { store } from './store.js';
import { toastError } from './ui.js';

export function insertItems() {
  return [
    { label: 'Título', icon: 'edit', onSelect: () => insert({ kind: 'text', w: 800, h: 64, content: store.workflow.name || 'Título', format: { size: 30, bold: true } }, { header: true }) },
    { label: 'Texto', icon: 'list', onSelect: () => insert({ kind: 'text', w: 480, h: 120, content: 'Escreva aqui', format: {} }) },
    'separator',
    { label: 'Imagem…', icon: 'upload', onSelect: () => pickImage().then((img) => img && insert({ kind: 'image', ...fitBox(img, 360), content: img.data, format: {} })) },
    { label: 'Logo do Grupo Protege', icon: 'image', onSelect: () => logoImage().then((img) => insert({ kind: 'image', ...fitBox(img, 120), content: img.data, format: {} })) },
    'separator',
    { label: 'Retângulo (fundo de seção)', icon: 'group', onSelect: () => insert({ kind: 'shape', w: 760, h: 400, format: { shape: 'rect' } }, { back: true }) },
    { label: 'Linha divisória', icon: 'columns', onSelect: () => insert({ kind: 'shape', w: 1520, h: 16, format: { shape: 'line' } }) },
  ];
}

const fitBox = (img, max) => {
  const k = Math.min(1, max / Math.max(img.width, img.height));
  return { w: Math.max(48, Math.round((img.width * k) / GRID) * GRID), h: Math.max(48, Math.round((img.height * k) / GRID) * GRID) };
};

/** Primeiro espaço livre a partir de `top` (de cima para baixo, da esquerda para a direita). */
function freeSpot(w, h, top) {
  const taken = dash().items;
  const fits = (x, y) => !taken.some((o) => overlaps({ x: x - 16, y: y - 16, w: w + 32, h: h + 32 }, o));
  for (let y = top; y < top + 4000; y += GRID) {
    for (let x = 40; x + w <= PAGE_W - 40; x += GRID) if (fits(x, y)) return { x, y };
  }
  return { x: Math.round((PAGE_W - w) / 2 / GRID) * GRID, y: top };
}

/**
 * Novo item no primeiro espaço livre perto do topo visível, selecionado. Formas de fundo vão para trás,
 * no topo visível, porque costumam ficar atrás de outros itens. Um título (`header`) entra no topo
 * visível e empurra para baixo o que estiver dali em diante, abrindo espaço.
 */
function insert(item, { back = false, header = false } = {}) {
  const top = els.sheet ? Math.max(0, (page.root.getBoundingClientRect().top - els.sheet.getBoundingClientRect().top) / ui.scale) : 0;
  const start = Math.round((top + 40) / GRID) * GRID;
  const spot = back || header ? { x: 40, y: start } : freeSpot(item.w, item.h, start);
  const placed = { id: newId(), node_id: null, ...item, ...spot };
  commitLayout((d) => {
    if (header) for (const i of d.items) if (i.y + i.h > start) i.y += item.h + 16;
    if (back) d.items.unshift(placed); else d.items.push(placed);
  });
  ui.selected = new Set([placed.id]);
  page.render();
}

const SVG_FORBIDDEN = /<\s*script|<\s*foreignObject|<\s*iframe|<\s*object|<\s*embed|\son\w+\s*=|javascript:|(?:xlink:)?href\s*=\s*["']\s*(?!#|data:image\/)/i;

const readAsDataUrl = (blob) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(blob);
});

const naturalSize = (src) => new Promise((resolve) => {
  const img = new Image();
  img.onload = () => resolve({ width: img.naturalWidth || 320, height: img.naturalHeight || 240 });
  img.onerror = () => resolve({ width: 320, height: 240 });
  img.src = src;
});

/** Escolhe uma imagem do computador. Mesmas regras do servidor: PNG/JPG/SVG sem código, até 1 MB. */
export function pickImage() {
  return new Promise((resolve) => {
    const input = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/svg+xml', hidden: true });
    input.addEventListener('change', async () => {
      const file = input.files[0];
      input.remove();
      if (!file) { resolve(null); return; }
      try {
        if (!['image/png', 'image/jpeg', 'image/svg+xml'].includes(file.type)) throw new Error('Use uma imagem PNG, JPG ou SVG.');
        if (file.size > 1024 * 1024) throw new Error('A imagem passa de 1 MB. Reduza o tamanho antes de inserir.');
        if (file.type === 'image/svg+xml' && SVG_FORBIDDEN.test(await file.text())) throw new Error('O SVG contém scripts ou links externos e não pode ser usado.');
        const data = await readAsDataUrl(file);
        resolve({ data, ...(await naturalSize(data)) });
      } catch (err) {
        toastError(err, 'Imagem não aceita');
        resolve(null);
      }
    });
    document.body.append(input);
    input.click();
  });
}

export async function logoImage() {
  const blob = await (await fetch('/static/brand/protege-escudo.svg')).blob();
  const data = await readAsDataUrl(new Blob([blob], { type: 'image/svg+xml' }));
  return { data, width: 191, height: 241 };
}
