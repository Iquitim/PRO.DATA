// Vista Dados (spec 028, RF-2801..2810): todas as fontes num lugar só, com detalhe, cadastro e onde são usadas.
// Gerenciar acontece só aqui; o painel lateral do Designer fica com busca e arrasto.

import { apiEditor, refreshApis } from './apis.js';
import { connectionEditor, queryEditor, refreshConnections, refreshQueries } from './connections.js';
import { refreshConstants } from './constants.js';
import { constantEditor } from './constants_ui.js';
import { sourceDetail } from './data_detail.js';
import { allSources, KINDS, matches, refreshUsage, usageText, usesOf } from './data_sources.js';
import { accept, linkFile, refreshDatasets, uploadFiles } from './datasets.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';
import { on, store } from './store.js';
import { confirmDialog, showMenu } from './ui.js';

const ui = { key: null, tab: 'overview', search: '', creating: null };
let root = null;
let handlers = { openFlow: async () => {}, showDesigner: () => {} };
const fileInput = h('input', { type: 'file', multiple: true, hidden: true,
  onchange: (e) => { uploadFiles([...e.target.files]).then(afterChange); e.target.value = ''; } });

const sourceByKey = (key) => allSources().find((s) => s.key === key) || null;

async function afterChange() {
  await Promise.all([refreshDatasets(), refreshQueries(), refreshApis(), refreshConnections(), refreshConstants(), refreshUsage()]).catch(() => {});
  renderDataView();
}

/** Abre a vista numa fonte: o atalho "Abrir em Dados" do painel lateral. */
export function openInData(key, tab = 'overview') {
  ui.key = key;
  ui.tab = tab;
  ui.creating = null;
}

function newSource(kind, opts = {}) {
  ui.creating = { kind, opts };
  ui.key = null;
  renderDataView();
}

function addMenu(e) {
  const r = e.currentTarget.getBoundingClientRect();
  showMenu(r.left, r.bottom + 4, [
    { label: 'Enviar arquivo', icon: 'upload', onSelect: () => { fileInput.accept = accept(); fileInput.click(); } },
    { label: 'Vincular arquivo (lido onde está)', icon: 'link', onSelect: () => linkFile().then(afterChange) },
    'separator',
    { label: 'Nova conexão com banco', icon: 'database', onSelect: () => newSource('conn') },
    { label: 'Nova consulta de banco', icon: 'server', disabled: !store.connections.length, onSelect: () => newSource('query') },
    { label: 'Nova API', icon: 'globe', onSelect: () => newSource('api') },
    'separator',
    { label: 'Nova constante compartilhada', icon: 'hash', onSelect: () => newSource('const') },
  ]);
}

function card(source) {
  const kind = KINDS[source.kind];
  const n = usesOf(source).length;
  return h('button', {
    type: 'button', class: ['dv-card-item', ui.key === source.key && 'active'], dataset: { key: source.key },
    onclick: () => { openInData(source.key, ui.key === source.key ? ui.tab : 'overview'); renderDataView(); },
  },
  h('span', { class: 'dv-card-icon', style: { '--kind': kind.color } }, icon(kind.icon, 17)),
  h('strong', { class: 'ellipsis', title: source.name }, source.name),
  h('span', { class: ['dv-state', `tone-${source.state.tone}`] }, source.state.label),
  h('span', { class: 'dv-card-meta ellipsis', title: source.meta }, source.meta),
  h('span', { class: ['dv-card-use', !n && 'none'] }, usageText(source)));
}

function listPane() {
  const search = h('input', {
    type: 'search', class: 'input input-search', placeholder: 'Buscar fonte ou fluxo', 'aria-label': 'Buscar fontes', value: ui.search,
    oninput: (e) => { ui.search = e.target.value; drawList(); },
  });
  const groups = h('div', { class: 'dv-groups' });
  const drawList = () => {
    const sources = allSources().filter((s) => matches(s, ui.search));
    groups.replaceChildren(...Object.entries(KINDS).map(([kind, meta]) => {
      const items = sources.filter((s) => s.kind === kind);
      if (!items.length) return null;
      return h('section', { class: 'dv-group' },
        h('div', { class: 'dv-group-title', style: { '--kind': meta.color } }, meta.title, h('span', {}, String(items.length))),
        items.map(card));
    }).filter(Boolean), ...(sources.length ? [] : [h('p', { class: 'muted pad' }, 'Nenhuma fonte encontrada.')]));
  };
  drawList();
  return h('aside', { class: 'dv-list' },
    h('div', { class: 'dv-list-head' },
      h('div', {}, h('h1', {}, 'Seus dados'), h('p', {}, 'Valem para todos os fluxos deste computador')),
      button({ icon: 'plus', label: 'Adicionar', variant: 'primary', onClick: addMenu })),
    search, groups, fileInput);
}

/** Primeira vez, ou nenhuma fonte escolhida: explica os tipos de fonte e leva a cada um (RF-2809). */
function welcome() {
  const kinds = [
    ['file', 'Arquivo', 'Excel, CSV, Parquet ou JSON do seu computador', [['vendas.xlsx', '3 planilhas'], ['Tabela', '1.800 linhas']],
      'Envie uma cópia ou vincule o arquivo onde ele está, para ler sempre a versão mais nova.',
      button({ icon: 'upload', label: 'Enviar arquivo', variant: 'primary', onClick: () => { fileInput.accept = accept(); fileInput.click(); } }),
      button({ label: 'ou vincular um arquivo', variant: 'ghost', onClick: () => linkFile().then(afterChange) })],
    ['conn', 'Banco de dados', 'PostgreSQL e SQL Server, só para leitura', [['ERP', 'conexão'], ['Consulta', 'SELECT …'], ['Tabela', '512 linhas']],
      'Cadastre a conexão uma vez, com a senha no cofre do Windows, e depois as consultas que os fluxos usam.',
      button({ icon: 'database', label: 'Conectar a um banco', variant: 'primary', onClick: () => newSource('conn') }), null],
    ['api', 'API', 'Serviços na internet, como o IBGE, e sistemas da empresa', [['Pedido', 'GET /estados'], ['Resposta', '[{"sigla"…'], ['Tabela', '27 linhas']],
      'Cole o endereço e teste na hora. APIs públicas funcionam sem configuração; as internas, com a lista da TI.',
      button({ icon: 'globe', label: 'Cadastrar API', variant: 'primary', onClick: () => newSource('api') }), null],
  ];
  return h('div', { class: 'dv-welcome' },
    h('span', { class: 'dv-eyebrow' }, 'Comece por aqui'),
    h('h2', {}, 'De onde vêm os seus dados?'),
    h('p', { class: 'dv-lead' }, 'Tudo o que um fluxo lê fica nesta vista: você cadastra uma vez e usa em quantos fluxos quiser.'),
    h('div', { class: 'dv-kinds' }, kinds.map(([kind, title, when, steps, text, main, extra]) => h('section', { class: 'dv-card dv-kind', style: { '--kind': KINDS[kind].color } },
      h('div', { class: 'dv-kind-head' }, h('span', { class: 'dv-head-icon' }, icon(KINDS[kind].icon, 20)),
        h('div', {}, h('h3', {}, title), h('p', {}, when))),
      h('div', { class: 'dv-how', role: 'img', 'aria-label': steps.map(([a]) => a).join(', depois ') }, steps.map(([a, b], i) => h('span', { class: 'dv-step-wrap' },
        i ? h('span', { class: 'dv-link', 'aria-hidden': 'true' }) : null, h('span', { class: 'dv-how-box' }, h('b', {}, a), h('small', { class: 'mono' }, b))))),
      h('p', { class: 'dv-how-text' }, text),
      h('div', { class: 'row' }, main, extra)))),
    h('section', { class: 'dv-card dv-const-hint', style: { '--kind': KINDS.const.color } },
      h('span', { class: 'dv-head-icon' }, icon('hash', 18)),
      h('div', {}, h('strong', {}, 'Um valor que se repete em vários fluxos?'),
        h('p', {}, 'Como o mês de referência ou a meta do trimestre: cadastre uma constante e troque num lugar só.')),
      button({ icon: 'plus', label: 'Nova constante', onClick: () => newSource('const') })),
    h('p', { class: 'field-help' }, icon('upload', 12), ' Já está no Designer? Arraste um arquivo direto para o canvas: ele entra aqui sozinho.'));
}

function creatingPane() {
  const { kind, opts } = ui.creating;
  const host = { close: () => { ui.creating = null; renderDataView(); }, reopen: (next) => newSource(kind, next) };
  const done = (saved) => afterSave(kind, saved);
  const editor = kind === 'api' ? apiEditor({ ...opts, onSaved: done }, host)
    : kind === 'query' ? queryEditor({ ...opts, onSaved: done }, host)
      : kind === 'const' ? constantEditor(null, { onSaved: done }, host)
        : connectionEditor(null, { onSaved: done }, host);
  return h('div', { class: 'dv-detail' },
    h('header', { class: 'dv-head' },
      h('span', { class: 'dv-head-icon', style: { '--kind': KINDS[kind].color } }, icon(KINDS[kind].icon, 22)),
      h('div', { class: 'dv-head-text' }, h('h2', {}, editor.title))),
    h('div', { class: 'dv-body' }, h('div', { class: 'dv-editor' }, editor.body, h('footer', { class: 'dv-editor-actions' }, editor.actions))));
}

async function afterSave(kind, saved) {
  ui.creating = null;
  ui.key = `${kind}:${saved.id ?? saved.name}`;
  await afterChange();
}

async function removeSource(source, action) {
  const uses = usesOf(source);
  if (uses.length) {
    const ok = await confirmDialog({
      title: `Esta fonte é usada em ${uses.length} fluxo(s)`,
      message: `Ao excluir, deixam de funcionar: ${uses.map((u) => `${u.workflow} (${u.readers.map((r) => r.label || r.type).join(', ')})`).join('; ')}.`,
      confirm: 'Continuar', danger: true,
    });
    if (!ok) return;
  }
  await action();
  ui.key = null;
  await afterChange();
}

export function renderDataView() {
  if (!root || store.view !== 'data') return;
  const selected = ui.key ? sourceByKey(ui.key) : null;
  const ctx = {
    tab: ui.tab,
    setTab: (tab) => { ui.tab = tab; renderDataView(); },
    refresh: () => afterChange(),
    mountEditor: (kind, opts) => newSource(kind, opts),
    afterSave,
    remove: removeSource,
    newSource,
    openFlow: (workflowId, nodeId) => handlers.openFlow(workflowId, nodeId),
    showDesigner: () => handlers.showDesigner(),
  };
  const main = ui.creating ? creatingPane() : selected ? sourceDetail(selected, ctx) : welcome();
  root.replaceChildren(listPane(), h('main', { class: 'dv-main' }, main));
}

export function initDataView(el, opts) {
  root = el;
  handlers = { ...handlers, ...opts };
  for (const event of ['datasets', 'queries', 'apis', 'connections', 'constants']) on(event, () => renderDataView());
}

/** Ao entrar na vista: dados de uso frescos, porque outro fluxo pode ter sido salvo. */
export async function showDataView() {
  renderDataView();
  await refreshUsage();
  renderDataView();
}
