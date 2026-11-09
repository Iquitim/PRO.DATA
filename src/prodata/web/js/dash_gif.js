// GIF de um gráfico (spec 030, RF-3071..3073 e RF-3075): nunca da página inteira, e sem executar o fluxo.

import { api } from './api.js';
import { frameMaker, saveDownload, stamp } from './dash_export.js';
import { withStrip } from './dash_png.js';
import { momentLabel } from './dash_replay.js';
import { dash, nodeLabel, page } from './dash_state.js';
import { button, fmt, h } from './dom.js';
import { encodeGif } from './gif_encoder.js';
import { store } from './store.js';
import { confirmDialog, openDialog, toast, toastError } from './ui.js';

const MAX_FRAMES = 240;
const MAX_BYTES = 40 * 1024 * 1024;
const BYTES_PER_PIXEL = 0.02; // medido em gráficos reais; o tamanho final depende de quanto muda entre quadros
const WIDTHS = [[360, 'Pequeno'], [560, 'Médio'], [800, 'Grande']];
const FPS = [[6, '6 por segundo'], [10, '10 por segundo'], [15, '15 por segundo']];
const STRIP = 40;

const size = (bytes) => (bytes >= 1048576 ? `${fmt.number(bytes / 1048576, 1)} MB` : `${fmt.int(Math.ceil(bytes / 1024))} KB`);
export const gifBlocked = () => (dash()?.confidentiality || 'interno') === 'restrito';

function optionsOf(list, value) {
  return list.map(([v, label]) => h('option', { value: v, selected: String(v) === String(value) }, label));
}

function dimensions(item, width) {
  const scale = width / item.w;
  return { scale, width, height: Math.round((item.h + STRIP) * scale) };
}

/** Só o gráfico daquele item, no momento pedido, com a faixa do rótulo e do período. */
function frameEl(item, widget, note) {
  const content = page.itemEl({ ...item, x: 0, y: 0 }, { [item.node_id]: widget }, { exporting: true });
  return withStrip(h('div', { class: 'dash-page dash-export', style: { width: `${item.w}px`, height: `${item.h}px`, backgroundColor: 'transparent' } }, content), item.w, item.h, note);
}

async function generate(item, replay, choice, ui) {
  const { from, to, seconds, fps, width, loop } = choice;
  const count = Math.max(2, Math.round(seconds * fps));
  const box = dimensions(item, width);
  const background = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim() || '#ffffff';
  const draw = await frameMaker(item.w, item.h + STRIP, { scale: box.scale, background });
  const step = replay.timeline.step;
  const widgetAt = (f) => {
    const place = from + ((to - from) * f) / (count - 1);
    const i = Math.min(to, Math.floor(place));
    return { widget: replay.between(i, place - i)[item.node_id], moment: replay.moments[i] };
  };
  const render = async (f) => {
    const { widget, moment } = widgetAt(f);
    return draw(frameEl(item, widget, `Período: ${momentLabel(moment, step)}`));
  };
  const samples = [await render(0), await render(Math.floor(count / 2)), await render(count - 1)];
  const blob = await encodeGif({
    width: box.width, height: box.height, count, delayCs: Math.max(2, Math.round(100 / fps)), loop, samples,
    next: async (f) => (ui.cancelled ? null : render(f)),
    progress: (done) => ui.progress(done, count),
  });
  if (!blob) return null;
  if (blob.size > MAX_BYTES) throw new Error(`O GIF daria ${size(blob.size)}, acima do limite de ${size(MAX_BYTES)}. Use menos duração ou um tamanho menor.`);
  return blob;
}

function logGif(file, label) {
  api.dashboardExportLog({ kind: 'GIF', file: String(file).split(/[\\/]/).pop(), label })
    .catch((err) => toastError(err, 'O GIF foi salvo, mas não entrou no registro de exportações'));
}

/** Diálogo: duração, tamanho, quadros, período e repetição, com a estimativa antes de gerar. */
export async function openGif(item, replay) {
  const level = dash().confidentiality || 'interno';
  if (level === 'restrito') {
    toast('GIF não tem senha: fica bloqueado em dashboards com rótulo Restrito.', { kind: 'error' });
    return;
  }
  if (level === 'confidencial') {
    const ok = await confirmDialog({
      title: 'Gerar GIF de dado confidencial?',
      message: 'O GIF não tem senha: quem receber o arquivo vê os dados. Ele sai com a faixa do rótulo.',
      confirm: 'Gerar assim mesmo',
    });
    if (!ok) return;
  }
  const last = replay.moments.length - 1;
  const moments = replay.moments.map((m, i) => [i, momentLabel(m, replay.timeline.step)]);
  const choice = { from: 0, to: last, seconds: Math.min(15, Math.max(4, Math.ceil(last * 0.8))), fps: 10, width: 560, loop: true };
  const estimate = h('p', { class: 'field-help', 'aria-live': 'polite' });
  const progress = h('p', { class: 'muted' });
  const save = button({ icon: 'download', label: 'Gerar GIF', variant: 'primary', onClick: () => start() });
  const refresh = () => {
    const box = dimensions(item, choice.width);
    const frames = Math.round(choice.seconds * choice.fps);
    const bytes = frames * box.width * box.height * BYTES_PER_PIXEL;
    const tooMany = frames > MAX_FRAMES;
    const tooBig = bytes > MAX_BYTES;
    const invalid = choice.to <= choice.from;
    save.disabled = tooMany || tooBig || invalid;
    estimate.textContent = invalid ? 'Escolha um período com mais de um momento.'
      : tooMany ? `São ${frames} quadros, acima do limite de ${MAX_FRAMES}. Reduza a duração ou os quadros por segundo.`
        : tooBig ? `Daria cerca de ${size(bytes)}, acima do limite de ${size(MAX_BYTES)}. Reduza o tamanho ou a duração.`
          : `${frames} quadros, ${box.width} × ${box.height} px, cerca de ${size(bytes)}.`;
  };
  const row = (label, control) => h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control);
  const pick = (key, list, parse = Number) => h('select', { class: 'input', 'aria-label': key, onchange: (e) => { choice[key] = parse(e.target.value); refresh(); } }, optionsOf(list, choice[key]));
  const body = h('div', { class: 'stack-sm' },
    h('p', {}, 'Só este gráfico, com a faixa do rótulo. O GIF usa os dados já calculados e não tem senha.'),
    h('div', { class: 'replay-gif-grid' },
      row('De', pick('from', moments)),
      row('Até', pick('to', moments)),
      row('Duração (segundos)', h('input', { class: 'input', type: 'number', min: 1, max: 40, value: choice.seconds, 'aria-label': 'Duração', oninput: (e) => { choice.seconds = Math.max(1, Number(e.target.value) || 1); refresh(); } })),
      row('Quadros', pick('fps', FPS)),
      row('Tamanho', pick('width', WIDTHS)),
      row('Repetição', h('select', { class: 'input', 'aria-label': 'Repetição', onchange: (e) => { choice.loop = e.target.value === '1'; } }, h('option', { value: '1' }, 'Repetir sempre'), h('option', { value: '0' }, 'Tocar uma vez')))),
    estimate, progress);
  const ui = { cancelled: false, progress: (done, total) => { progress.textContent = `Gerando o quadro ${done} de ${total}…`; } };
  const dialog = openDialog({
    title: 'Baixar GIF deste gráfico',
    size: 'md',
    body,
    actions: [button({ label: 'Cancelar', onClick: () => { ui.cancelled = true; dialog.close(); } }), save],
    onClose: () => { ui.cancelled = true; },
  });
  refresh();
  const start = async () => {
    save.disabled = true;
    progress.textContent = 'Preparando…';
    try {
      const blob = await generate(item, replay, choice, ui);
      if (!blob) return;
      const name = `${page.shownWidgets()[item.node_id]?.title || nodeLabel(item.node_id)} - ${stamp()}.gif`;
      const saved = await saveDownload(name, blob);
      if (!saved) { refresh(); progress.textContent = ''; return; }
      logGif(saved, level);
      toast(`GIF salvo: ${saved}`, { kind: 'success', detail: size(blob.size) });
      dialog.close();
    } catch (err) {
      progress.textContent = '';
      refresh();
      toastError(err, 'Não foi possível gerar o GIF');
    }
  };
  return store.workflow;
}
