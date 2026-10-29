// Imagem PNG do dashboard ou de um visual (spec 014, RF-1450..RF-1452), sem biblioteca externa:
// o HTML vira um SVG com <foreignObject>, com o CSS e as fontes embutidos, desenhado num <canvas> 2×.

import { savePng } from './desktop.js';

const inlined = new Map(); // url → data URI (fontes e imagens do CSS)

async function toDataUri(url) {
  if (!inlined.has(url)) {
    inlined.set(url, fetch(url).then((r) => (r.ok ? r.blob() : null)).then((blob) => (blob ? new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    }) : null)).catch(() => null));
  }
  return inlined.get(url);
}

/** CSS da página com url(...) trocadas por data URI: dentro de uma imagem SVG o navegador não busca nada. */
async function collectCss() {
  const parts = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules;
    } catch {
      continue; // folha de outra origem: não há nenhuma no app
    }
    let text = [...rules].map((r) => r.cssText).join('\n');
    const urls = [...text.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map((m) => m[1]).filter((u) => !u.startsWith('data:'));
    for (const u of new Set(urls)) {
      const data = await toDataUri(new URL(u, sheet.href || location.href).href);
      if (data) text = text.split(u).join(data);
    }
    parts.push(text);
  }
  return parts.join('\n');
}

/** Variáveis do tema atual (claro ou escuro), aplicadas no contêiner da imagem. */
function themeVars() {
  const computed = getComputedStyle(document.documentElement);
  const out = [];
  for (const prop of computed) if (prop.startsWith('--')) out.push(`${prop}:${computed.getPropertyValue(prop)}`);
  const body = getComputedStyle(document.body);
  // Altura de linha como proporção (13px/1.45 no CSS): em px fixo, textos maiores (valor do KPI) seriam cortados.
  const ratio = parseFloat(body.lineHeight) / parseFloat(body.fontSize);
  out.push(`font-family:${body.fontFamily}`, `font-size:${body.fontSize}`, `color:${body.color}`,
    `line-height:${Number.isFinite(ratio) ? ratio.toFixed(3) : 'normal'}`);
  return out.join(';');
}

const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

/**
 * Desenha `el` (montado fora da tela, no tamanho real) e devolve um data URI PNG.
 * `background`: cor de fundo da imagem (a página ou o cartão).
 */
export async function renderPng(el, width, height, { scale = 2, background = '' } = {}) {
  const host = document.createElement('div');
  host.style.cssText = `position:fixed;left:-100000px;top:0;width:${width}px;height:${height}px;overflow:hidden;`;
  host.append(el);
  document.body.append(host);
  try {
    await document.fonts.ready;
    await nextFrame();
    const css = await collectCss();
    const html = new XMLSerializer().serializeToString(el);
    const svgText = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">`
      + `<style>${css.replace(/<\/style/gi, '')}</style>`
      + `<foreignObject x="0" y="0" width="${width}" height="${height}">`
      + `<div xmlns="http://www.w3.org/1999/xhtml" style="${themeVars().replace(/"/g, "'")};width:${width}px;height:${height}px;background:${background}">${html}</div>`
      + '</foreignObject></svg>';
    const img = new Image();
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0, width, height);
    return canvas.toDataURL('image/png');
  } finally {
    host.remove();
  }
}

export const stamp = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}h${p(d.getMinutes())}`;
};

export { savePng };
