// Ponte com o aplicativo de desktop (spec 009): diálogos nativos do Windows via window.pywebview.api.
// No navegador (modo servidor) não há diálogo nativo: o usuário digita o caminho.

import { button, h } from './dom.js';
import { openDialog, toastError } from './ui.js';

const native = () => window.pywebview?.api || null;

export const isDesktop = () => Boolean(native());

/** Pede um caminho por texto quando não há diálogo nativo. Devolve null se cancelado. */
function askPath({ title, label, value = '', placeholder = '' }) {
  return new Promise((resolve) => {
    let answer = null;
    const input = h('input', { class: 'input mono', value, placeholder, 'aria-label': label });
    const ok = () => { answer = input.value.trim() || null; resolve(answer); close(); };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
    const { close } = openDialog({
      title,
      size: 'sm',
      body: h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), input,
        h('p', { class: 'field-help' }, 'Caminho completo. No aplicativo de desktop, aqui abre o seletor do Windows.')),
      actions: [button({ label: 'Cancelar', onClick: () => close() }), button({ label: 'OK', variant: 'primary', onClick: ok })],
      onClose: () => resolve(answer),
    });
    input.focus();
    input.select();
  });
}

/** Chama a ponte nativa; qualquer falha vira mensagem visível em vez de sumir (spec 010, RF-1001). */
async function call(fn, ...args) {
  try {
    return await native()[fn](...args);
  } catch (err) {
    toastError(err, 'O diálogo do Windows não pôde ser aberto');
    return null;
  }
}

export async function chooseFolder(start = '') {
  if (native()) return call('choose_folder', start);
  return askPath({ title: 'Pasta de destino', label: 'Pasta', value: start, placeholder: 'D:\\Relatorios' });
}

export async function chooseSaveFile(suggested, start = '') {
  if (native()) return call('save_file', suggested, start);
  return askPath({ title: 'Salvar fluxo como', label: 'Arquivo', value: start ? `${start}\\${suggested}` : suggested, placeholder: 'D:\\Fluxos\\vendas.prodata.json' });
}

export async function chooseOpenFile(start = '') {
  if (native()) return call('open_file', start);
  return askPath({ title: 'Abrir fluxo de arquivo', label: 'Arquivo', placeholder: 'D:\\Fluxos\\vendas.prodata.json' });
}

/**
 * Salva um PNG (data URI). No desktop abre o "Salvar como" do Windows e devolve o caminho;
 * no navegador, baixa o arquivo. Devolve null se o usuário cancelar.
 */
export async function savePng(name, dataUrl) {
  if (native()) return call('save_png', name, dataUrl);
  const a = h('a', { href: dataUrl, download: `${name.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'dashboard'}.png` });
  document.body.append(a);
  a.click();
  a.remove();
  return a.download;
}

/** Mostra o arquivo no Explorer (só no desktop). */
export async function reveal(path) {
  return native() ? call('reveal', path) : false;
}

/** Pasta de um caminho do Windows ou POSIX. */
export const dirname = (path) => (path || '').replace(/[\\/][^\\/]*$/, '');
export const basename = (path) => (path || '').split(/[\\/]/).pop();
