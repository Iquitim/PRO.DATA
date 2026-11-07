// Fontes de API da aba Dados (spec 021). Segredos só saem do navegador ao testar ou salvar; o servidor guarda
// no cofre do sistema e nunca os devolve. Uma API salva vira uma fonte do Input Data (valor `api:<id>`).

import { addNode } from './actions.js';
import { api } from './api.js';
import { viewportCenter } from './canvas.js';
import { slug } from './connections.js';
import { previewTable } from './datasets.js';
import { button, fmt, h } from './dom.js';
import { openLink } from './desktop.js';
import { arrow, linkHover, mini } from './explainers.js';
import { icon } from './icons.js';
import { API_PREFIX, commit, emit, placeholdersOf, store } from './store.js';
import { confirmDialog, openDialog, toast, toastError } from './ui.js';

const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i;

export async function refreshApis() {
  store.apis = await api.apis();
  emit('apis');
}

const blank = () => ({
  id: '', name: '', url: '', method: 'GET', params: [], headers: [], body: '', body_type: 'json',
  auth: { type: 'none', key_name: 'X-API-Key', key_in: 'header', username: '', token_url: '', client_id: '', scope: '' },
  format: 'auto', records_path: '', explode_path: '', flatten: true, docs_url: '',
  pagination: { type: 'none', page_param: 'page', start_page: 1, size_param: '', page_size: 100, offset_param: 'offset', limit_param: 'limit', cursor_param: 'cursor', cursor_path: 'next_cursor', next_path: '', max_pages: 100 },
  timeout_s: 30, max_mb: 200, retries: 3, cache_results: false, hold_on_open: false,
});

export { placeholdersOf };

export function addApiNode(saved) {
  const c = viewportCenter();
  if (placeholdersOf(saved).length) addNode('io.api_loop', c.x - 94, c.y - 28, { source: saved.id, __label: saved.name });
  else addNode('io.input_data', c.x - 94, c.y - 28, { dataset: `${API_PREFIX}${saved.id}`, __label: saved.name });
}

// ------------------------------------------------------------------ esquemas (spec 022)

/** Quadro "Como funciona" dentro de uma aba do editor. */
function how(...children) {
  return h('div', { class: 'api-how' }, icon('info', 13), h('div', { class: 'api-how-body' }, children));
}

/** Texto com {coluna} destacado. */
function marked(text, cls = '') {
  const out = [];
  let last = 0;
  for (const m of (text || '').matchAll(/\{([^{}"':\r\n]+)\}/g)) {
    out.push(text.slice(last, m.index), h('span', { class: 'req-col', title: `Variável: muda a cada chamada. No API Loop, você escolhe a coluna que preenche ${m[1]}` }, m[0]));
    last = m.index + m[0].length;
  }
  out.push((text || '').slice(last));
  return h('span', { class: cls }, out);
}

const DOTS = '••••••';

// Outras formas de escrever uma variável, comuns em documentações e ao copiar da barra do navegador.
const LOOSE_FORMS = [
  /\{\{\s*([^{}"':\r\n]+?)\s*\}\}/g,
  /%7B(.+?)%7D/gi,
  /<([^<>/?&#\s]+)>/g,
  /(?<=\/):([A-Za-z_][\w-]*)(?=[/?#]|$)/g,
  /(?<==):([A-Za-z_][\w-]*)(?=[&#]|$)/g,
];

/** O que no endereço parece uma variável fora do formato {nome}. Só sugere: quem decide é a pessoa. */
export function looseVariables(url) {
  const found = new Map();
  for (const form of LOOSE_FORMS) {
    for (const m of (url || '').matchAll(form)) {
      let name = m[1];
      try { name = decodeURIComponent(name); } catch { /* fica como está */ }
      if (name.trim() && !/[{}"':\r\n]/.test(name)) found.set(m[0], name.trim());
    }
  }
  return [...found].map(([text, name]) => ({ text, name }));
}

function authLines(state) {
  const a = state.auth;
  return {
    bearer: [['Authorization', `Bearer ${DOTS}`]],
    basic: [['Authorization', `Basic ${DOTS}`]],
    oauth2: [['Authorization', `Bearer ${DOTS}`]],
    api_key: a.key_in === 'header' ? [[a.key_name, DOTS]] : [],
  }[a.type] || [];
}

/** O pedido montado (RF-2222): muda enquanto se digita e nunca mostra uma credencial. */
function requestPreview(state) {
  const url = state.url.trim();
  if (!url) return h('p', { class: 'field-help' }, 'Digite o endereço para ver o pedido sendo montado.');
  const m = /^(https?:\/\/[^/?#]*)([^?#]*)(\?[^#]*)?/i.exec(url);
  const host = m ? m[1] : '';
  const path = m ? m[2] : url;
  const inline = m?.[3] || '';
  const query = [...state.params.filter((p) => p.name).map((p) => [p.name, p.secret ? DOTS : p.value])];
  if (state.auth.type === 'api_key' && state.auth.key_in === 'query') query.push([state.auth.key_name, DOTS]);
  const pager = state.pagination;
  if (pager.type === 'page') {
    query.push([pager.page_param, String(pager.start_page)]);
    if (pager.size_param) query.push([pager.size_param, String(pager.page_size)]);
  } else if (pager.type === 'offset') query.push([pager.offset_param, '0'], [pager.limit_param, String(pager.page_size)]);
  const headers = [...state.headers.filter((p) => p.name).map((p) => [p.name, p.secret ? DOTS : p.value]), ...authLines(state)];
  return h('div', { class: 'req' },
    h('div', { class: 'req-line' }, h('span', { class: 'req-method' }, state.method),
      h('span', { class: 'req-url' }, h('span', { class: 'req-host' }, host), marked(path, 'req-path'), inline ? marked(inline, 'req-param') : null,
        query.map(([k, v], i) => h('span', { class: 'req-param' }, `${i || inline ? '&' : '?'}${k}=`, marked(v))))),
    headers.length ? h('div', { class: 'req-headers' }, headers.map(([k, v]) => h('div', {}, h('span', { class: 'req-key' }, `${k}: `), marked(v)))) : null,
    state.method === 'POST' && state.body.trim() ? h('div', { class: 'req-headers' }, marked(state.body.length > 160 ? `${state.body.slice(0, 160)}…` : state.body)) : null,
    h('div', { class: 'req-legend' },
      h('span', { class: 'req-host' }, 'servidor'), h('span', { class: 'req-path' }, 'caminho'), h('span', { class: 'req-param' }, 'parâmetros fixos'),
      h('span', { class: 'req-col' }, '{variável}')));
}

/** Sequência de pedidos da paginação, com os nomes configurados (RF-2223). */
function pagesScheme(p) {
  const chip = (text) => h('span', { class: 'page-chip' }, text);
  const go = h('span', { class: 'page-arrow' }, '→');
  const size = p.size_param ? `&${p.size_param}=${p.page_size}` : '';
  const flows = {
    page: [[chip(`?${p.page_param}=${p.start_page}${size}`), go.cloneNode(true), chip(`?${p.page_param}=${p.start_page + 1}${size}`), go.cloneNode(true), chip(`?${p.page_param}=${p.start_page + 2}${size}`)],
      p.size_param ? `Para quando uma página vier com menos de ${p.page_size} linhas.` : 'Para quando uma página vier vazia ou igual à anterior.'],
    offset: [[chip(`?${p.offset_param}=0&${p.limit_param}=${p.page_size}`), go.cloneNode(true), chip(`?${p.offset_param}=${p.page_size}&${p.limit_param}=${p.page_size}`), go.cloneNode(true), chip(`?${p.offset_param}=${p.page_size * 2}&${p.limit_param}=${p.page_size}`)],
      `Pula as linhas já lidas. Para quando vierem menos de ${p.page_size} linhas.`],
    cursor: [[chip('1º pedido'), go.cloneNode(true), chip(`resposta traz ${p.cursor_path}: "abc"`), go.cloneNode(true), chip(`?${p.cursor_param}=abc`)],
      'Cada resposta diz onde continuar. Para quando o cursor vier vazio.'],
    next_link: [[chip('1º pedido'), go.cloneNode(true), chip(p.next_path ? `resposta traz ${p.next_path}` : 'cabeçalho Link: rel="next"'), go.cloneNode(true), chip('abre esse link')],
      'A própria resposta traz o link da próxima página. As credenciais só vão para o mesmo servidor.'],
  }[p.type];
  if (!flows) return how('A API devolve tudo de uma vez. Escolha outro tipo se a resposta trouxer só uma parte dos dados, com algo como "page" ou "next".');
  return how(h('div', { class: 'page-flow' }, flows[0]), h('p', {}, flows[1]));
}

function authScheme(state) {
  const a = state.auth;
  const code = (text) => h('code', { class: 'auth-code' }, text);
  return {
    none: () => how('A API é aberta: nada de credencial no pedido. É o caso de muitas APIs públicas, como a do IBGE.'),
    bearer: () => how('O token vai em todo pedido, neste cabeçalho:', code(`Authorization: Bearer ${DOTS}`)),
    api_key: () => how('A chave vai em todo pedido:', code(a.key_in === 'header' ? `${a.key_name}: ${DOTS}` : `…?${a.key_name}=${DOTS}`),
      a.key_in === 'query' ? h('p', {}, 'No endereço, a chave pode aparecer em registros de servidores. Prefira o cabeçalho, se a API aceitar.') : null),
    basic: () => how('Usuário e senha vão codificados em todo pedido:', code(`Authorization: Basic ${DOTS}`)),
    oauth2: () => how(h('div', { class: 'page-flow' }, h('span', { class: 'page-chip' }, 'ID + segredo'), h('span', { class: 'page-arrow' }, '→'), h('span', { class: 'page-chip' }, 'servidor do token'), h('span', { class: 'page-arrow' }, '→'), h('span', { class: 'page-chip' }, 'token'), h('span', { class: 'page-arrow' }, '→'), h('span', { class: 'page-chip' }, 'chamada')),
      h('p', {}, 'O PRO.DATA pede o token sozinho e renova quando vence.')),
  }[a.type]();
}

/** Resposta real em árvore: listas dizem quantos itens têm e podem virar as linhas da tabela (RF-2225). */
function responseTree(sample, state, { onPick, onExplode }) {
  const recordsPrefix = state.records_path ? `${state.records_path}.*.` : '*.';
  const leafLink = (path) => {
    if (!path) return null;
    if (path.startsWith(recordsPrefix)) return `c:${path.slice(recordsPrefix.length).replace(/\.\*\./g, '.')}`;
    return null;
  };
  const scalar = (v) => (v === null ? 'null' : typeof v === 'string' ? `"${v}"` : String(v));
  const walk = (node, key) => {
    const label = key === null ? null : h('span', { class: 'tree-key' }, `${key}: `);
    if (node.kind === 'value') {
      const link = leafLink(node.path);
      return h('div', { class: 'tree-row', dataset: link ? { link } : undefined }, label, h('span', { class: `tree-v tree-${node.value === null ? 'null' : typeof node.value}` }, scalar(node.value)));
    }
    if (node.kind === 'more') return h('div', { class: 'tree-row muted' }, label, node.text);
    if (node.kind === 'object') {
      return h('div', {}, key === null ? null : h('div', { class: 'tree-row' }, label, h('span', { class: 'muted' }, 'objeto')),
        h('div', { class: key === null ? null : 'tree-kids' }, node.fields.map(([k, v]) => walk(v, k)),
          node.hidden ? h('div', { class: 'tree-row muted' }, `e mais ${node.hidden} campos`) : null));
    }
    const isRecords = node.path === state.records_path || (!state.records_path && !node.path);
    const nested = node.path.startsWith(recordsPrefix);
    const relative = nested ? node.path.slice(recordsPrefix.length) : '';
    let action = null;
    if (!node.path.includes('*') && !isRecords) {
      action = button({ label: 'Usar como linhas', size: 'sm', variant: 'ghost', title: `Cada item de "${node.path}" vira uma linha`, onClick: () => onPick(node.path) });
    } else if (nested && !relative.includes('*')) {
      const on_ = state.explode_path === relative;
      action = button({ label: on_ ? 'Não abrir em linhas' : 'Abrir em linhas', size: 'sm', variant: 'ghost', title: 'Uma linha por item, repetindo os outros campos', onClick: () => onExplode(on_ ? '' : relative) });
    }
    return h('div', { class: ['tree-list', isRecords && 'is-records'] },
      h('div', { class: 'tree-row' }, label, h('span', { class: 'tree-badge' }, `lista · ${fmt.int(node.total)} ${node.total === 1 ? 'item' : 'itens'}`),
        isRecords ? h('span', { class: 'tree-here' }, icon('check', 11), 'linhas da tabela') : null, action),
      h('div', { class: 'tree-kids' }, node.items.map((item, i) => h('div', { class: 'tree-item' }, h('span', { class: 'tree-index' }, `item ${i + 1}`), walk(item, null))),
        node.total > node.items.length ? h('div', { class: 'tree-row muted' }, `e mais ${fmt.int(node.total - node.items.length)} itens`) : null));
  };
  return h('div', { class: 'tree' }, walk(sample, null));
}

/** Antes de testar: o caminho do pedido até a tabela, com um exemplo (RF-2224). */
function howItWorks() {
  const stage = (n, title, body) => h('div', { class: 'api-stage' }, h('div', { class: 'x-title' }, `${n}. ${title}`), body);
  const answer = h('pre', { class: 'api-json' }, '[\n  { "sigla": "SP",\n    "nome": "São Paulo",\n    "regiao": { "nome": "Sudeste" } },\n  { "sigla": "RJ",\n    "nome": "Rio de Janeiro",\n    "regiao": { "nome": "Sudeste" } }\n]');
  return h('div', { class: 'api-intro' },
    h('p', { class: 'api-intro-lead' }, 'Uma API responde a um endereço com dados. O PRO.DATA transforma a resposta em tabela:'),
    stage(1, 'O pedido', h('div', { class: 'req' }, h('div', { class: 'req-line' }, h('span', { class: 'req-method' }, 'GET'), h('span', { class: 'req-url' }, h('span', { class: 'req-host' }, 'https://servicodados.ibge.gov.br'), h('span', { class: 'req-path' }, '/api/v1/localidades/estados'))))),
    arrow('a API responde'),
    stage(2, 'A resposta', answer),
    arrow('cada item vira uma linha'),
    stage(3, 'A tabela', mini('', [{ text: 'sigla', kind: 'to' }, { text: 'nome', kind: 'to' }, { text: 'regiao.nome', kind: 'to' }],
      [['SP', 'São Paulo', 'Sudeste'], ['RJ', 'Rio de Janeiro', 'Sudeste']].map((r) => r.map((text) => ({ text }))))),
    h('p', { class: 'field-help' }, 'Nesta figura, os dados são de exemplo. Clique em Testar para ver a resposta da sua API.'));
}

// ------------------------------------------------------------------ pedaços do formulário

function field(label, control, help) {
  return h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control,
    help ? h('p', { class: 'field-help' }, help) : null);
}

function text(obj, key, attrs = {}) {
  return h('input', { class: 'input', value: obj[key] ?? '', spellcheck: false, ...attrs, oninput: (e) => { obj[key] = e.target.value; attrs.oninput?.(e); } });
}

function number(obj, key, attrs = {}) {
  return h('input', { class: 'input', type: 'number', value: obj[key], ...attrs, onchange: (e) => { obj[key] = Number(e.target.value); } });
}

function choice(obj, key, options, onChange) {
  return h('select', { class: 'input', onchange: (e) => { obj[key] = e.target.value; onChange?.(); } },
    options.map(([value, label]) => h('option', { value, selected: obj[key] === value }, label)));
}

/** Campo de segredo: mostra que há valor guardado, sem nunca trazê-lo de volta. */
function secretField(state, slot, label, help) {
  const stored = state.stored.includes(slot);
  return field(label, h('input', {
    class: 'input', type: 'password', autocomplete: 'new-password', value: state.secrets[slot] || '',
    placeholder: stored ? 'Guardado no cofre do sistema (digite para trocar)' : '',
    oninput: (e) => { state.secrets[slot] = e.target.value; },
  }), help);
}

function pairs(state, list, kind, redraw) {
  const rows = list.map((p, i) => h('div', { class: 'api-pair-box' }, h('div', { class: 'api-pair' },
    text(p, 'name', { placeholder: 'Nome', 'aria-label': 'Nome' }),
    p.secret
      ? h('input', {
        class: 'input', type: 'password', autocomplete: 'new-password', 'aria-label': 'Valor sigiloso',
        value: state.secrets[`${kind}:${p.name}`] || '',
        placeholder: state.stored.includes(`${kind}:${p.name}`) ? 'Guardado no cofre' : 'Valor sigiloso',
        oninput: (e) => { state.secrets[`${kind}:${p.name}`] = e.target.value; },
      })
      : text(p, 'value', { placeholder: 'Valor', 'aria-label': 'Valor', oninput: () => state.onChange() }),
    h('label', { class: 'api-secret', title: 'Guarda o valor no cofre do sistema, fora do arquivo' },
      h('input', { type: 'checkbox', checked: p.secret, onchange: (e) => { p.secret = e.target.checked; redraw(); } }), icon('lock', 12)),
    button({ icon: 'trash', size: 'sm', variant: 'ghost', title: 'Remover', onClick: () => { list.splice(i, 1); redraw(); } })),
  text(p, 'note', { class: 'input input-sm api-note', placeholder: 'Para que serve (opcional)', 'aria-label': `Para que serve ${p.name || 'este item'}`, maxlength: 300 })));
  return h('div', { class: 'stack-xs' }, rows,
    button({ icon: 'plus', label: 'Adicionar', size: 'sm', variant: 'ghost', onClick: () => { list.push({ name: '', value: '', secret: false, note: '' }); redraw(); } }));
}

function authPane(state, redraw) {
  const a = state.auth;
  const kind = field('Tipo', choice(a, 'type', [['none', 'Sem autenticação'], ['bearer', 'Token (Bearer)'], ['api_key', 'Chave de API'], ['basic', 'Usuário e senha'], ['oauth2', 'OAuth 2 (credenciais do cliente)']], redraw));
  const rest = {
    none: [],
    bearer: [secretField(state, 'token', 'Token')],
    api_key: [field('Nome', text(a, 'key_name')),
      field('Enviar em', choice(a, 'key_in', [['header', 'Cabeçalho'], ['query', 'Parâmetro do endereço']])),
      secretField(state, 'token', 'Chave')],
    basic: [field('Usuário', text(a, 'username')), secretField(state, 'password', 'Senha')],
    oauth2: [field('Endereço do token', text(a, 'token_url', { placeholder: 'https://…/oauth/token' })),
      field('ID do cliente', text(a, 'client_id')),
      secretField(state, 'client_secret', 'Segredo do cliente'),
      field('Escopo', text(a, 'scope'), 'Opcional.')],
  }[a.type];
  return h('div', { class: 'stack-sm' }, kind, ...rest,
    h('p', { class: 'field-help' }, icon('lock', 12), ' Tokens e senhas ficam no cofre do sistema, nunca no fluxo ou em arquivos.'));
}

function pagesPane(state, redraw) {
  const p = state.pagination;
  const kind = field('Como a API divide os dados', choice(p, 'type', [['none', 'Uma resposta só'], ['page', 'Número de página'], ['offset', 'Deslocamento (offset e limit)'], ['cursor', 'Cursor na resposta'], ['next_link', 'Link para a próxima página']], redraw));
  const rest = {
    none: [],
    page: [field('Parâmetro da página', text(p, 'page_param')), field('Primeira página', number(p, 'start_page', { min: 0 })),
      field('Parâmetro do tamanho', text(p, 'size_param'), 'Opcional. Com ele, uma página menor que o tamanho encerra a leitura.'),
      field('Linhas por página', number(p, 'page_size', { min: 1 }))],
    offset: [field('Parâmetro do deslocamento', text(p, 'offset_param')), field('Parâmetro do limite', text(p, 'limit_param')),
      field('Linhas por página', number(p, 'page_size', { min: 1 }))],
    cursor: [field('Parâmetro do cursor', text(p, 'cursor_param')), field('Onde está o próximo cursor', text(p, 'cursor_path'), 'Caminho na resposta, como meta.next.')],
    next_link: [field('Onde está o link', text(p, 'next_path', { placeholder: 'Cabeçalho Link' }), 'Caminho na resposta, como links.next. Vazio = cabeçalho Link.')],
  }[p.type];
  return h('div', { class: 'stack-sm' }, kind, ...rest,
    p.type === 'none' ? null : field('Limite de páginas', number(p, 'max_pages', { min: 1 }), 'Se chegar aqui e ainda houver dados, a caixa avisa.'));
}

function answerPane(state, _redraw) {
  return h('div', { class: 'stack-sm' },
    field('Formato', choice(state, 'format', [['auto', 'Detectar'], ['json', 'JSON'], ['csv', 'CSV'], ['xml', 'XML']])),
    field('Onde estão as linhas', text(state, 'records_path', { placeholder: 'data.itens' }), 'Vazio: usa a lista da resposta, se houver só uma.'),
    field('Lista para abrir em linhas', text(state, 'explode_path', { placeholder: 'itens' }), 'Opcional: uma linha por item, repetindo os outros campos.'),
    h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: state.flatten, onchange: (e) => { state.flatten = e.target.checked; } }),
      h('span', { class: 'switch-track' }), h('span', {}, 'Abrir campos aninhados em colunas (dono.nome)')),
    field('Tempo limite (s)', number(state, 'timeout_s', { min: 1, max: 600 })),
    field('Tamanho máximo da resposta (MB)', number(state, 'max_mb', { min: 1 })),
    field('Novas tentativas (429 e falhas temporárias)', number(state, 'retries', { min: 0, max: 10 })));
}

// ------------------------------------------------------------------ editor

const apiDefinition = (state) => {
  const { id, name, cache_results, hold_on_open, secrets, stored, onChange, set_secrets, missing_secrets, ...d } = state;
  return d;
};
const filledSecrets = (state) => Object.fromEntries(Object.entries(state.secrets).filter(([, v]) => v));

/** Avisos abaixo do endereço: variável escrita de outro jeito, http sem criptografia, POST e o tipo de chamada. */
function apiNotices(state) {
  const ctx = { el: h('div', { class: 'stack-xs api-notices' }), urlInput: null };
  const notVariables = new Set();
  const looseHint = ({ text: found, name }) => h('div', { class: 'api-loose' },
    h('p', {}, h('code', {}, found), ' parece uma variável escrita de outro jeito. Aqui, ela é escrita entre chaves.'),
    h('div', { class: 'row' },
      button({ label: `Converter para {${name}}`, size: 'sm', onClick: () => {
        state.url = state.url.split(found).join(`{${name}}`);
        if (ctx.urlInput) ctx.urlInput.value = state.url;
        state.onChange();
      } }),
      button({ label: 'Não é variável', size: 'sm', variant: 'ghost', onClick: () => { notVariables.add(found); state.onChange(); } })));
  ctx.draw = () => {
    const url = state.url.trim();
    const needed = placeholdersOf(state);
    ctx.el.replaceChildren(...[
      ...looseVariables(url).filter((v) => !notVariables.has(v.text)).map(looseHint),
      url.toLowerCase().startsWith('http://') && !LOCAL.test(url)
        ? h('p', { class: 'api-warn' }, icon('alert', 14), ' Endereço sem criptografia (http): os dados viajam abertos na rede, e o PRO.DATA não envia credenciais por ele.') : null,
      state.method === 'POST'
        ? h('p', { class: 'api-warn' }, icon('alert', 14), ' Um POST pode gravar dados no servidor. Ele não roda sozinho ao abrir o fluxo.') : null,
      needed.length
        ? h('div', { class: 'api-kind is-param' },
          h('strong', {}, icon('repeat', 14), ` Com variável: pede ${needed.map((n) => `{${n}}`).join(', ')}`),
          h('p', {}, 'O endereço tem um espaço a preencher, diferente a cada chamada. Entra no fluxo como API Loop: lá você escolhe de qual coluna da tabela vem o valor.'))
        : url ? h('div', { class: 'api-kind' },
          h('strong', {}, icon('globe', 14), ' Chamada direta: o endereço é sempre o mesmo'),
          h('p', {}, 'A API devolve os dados de uma vez e vira uma tabela no Input Data. Para o endereço mudar a cada chamada, crie uma variável na aba Parâmetros.')) : null,
    ].filter(Boolean));
  };
  return ctx;
}

/** Na aba Parâmetros, o que muda a cada chamada aparece junto do que é fixo, com um valor só para testar. */
function apiVariables(state, samples) {
  const el = h('div', { class: 'api-section api-vars' });
  const whereIs = (name) => {
    const mark = `{${name}}`;
    if (state.url.includes(mark)) return 'no endereço';
    const param = state.params.find((p) => !p.secret && p.value?.includes(mark));
    if (param) return `no parâmetro ${param.name || 'sem nome'}`;
    const header = state.headers.find((p) => !p.secret && p.value?.includes(mark));
    return header ? `no cabeçalho ${header.name || 'sem nome'}` : 'no corpo';
  };
  const draw = () => {
    const needed = placeholdersOf(state);
    el.replaceChildren(
      h('div', { class: 'api-section-title' }, 'Variáveis: mudam a cada chamada'),
      needed.length
        ? h('p', { class: 'field-help' }, 'No fluxo, o valor vem de uma coluna da tabela, no API Loop. Aqui, digite um valor só para testar.')
        : h('p', { class: 'field-help' }, 'Nenhuma. Para o endereço mudar a cada chamada, escreva o nome entre chaves nele, como …/estados/', h('code', { class: 'req-col' }, '{sigla}'), '/municipios.'),
      ...needed.map((n) => h('label', { class: 'api-var' },
        h('code', { class: 'req-col' }, `{${n}}`),
        h('span', { class: 'ellipsis muted' }, whereIs(n)),
        h('input', { class: 'input input-sm', value: samples[n] || '', placeholder: 'Valor de teste', 'aria-label': `Valor de teste para ${n}`, oninput: (e) => { samples[n] = e.target.value; } }))));
  };
  return { el, draw };
}

const docsAction = (state) => (/^https?:\/\//i.test(state.docs_url.trim())
  ? button({ icon: 'link', label: 'Abrir a documentação da API', size: 'sm', onClick: () => openLink(state.docs_url.trim()) })
  : h('p', { class: 'field-help' }, 'Guarde o link no campo "Documentação da API", acima, para consultar depois.'));

/** O conteúdo de cada aba do pedido. `redraw` refaz a aba e o resumo do que será enviado. */
function apiPane(tab, state, vars, redraw) {
  return {
    params: () => h('div', { class: 'stack-sm' },
      vars.el,
      h('div', { class: 'api-section' }, h('div', { class: 'api-section-title' }, 'Parâmetros fixos: sempre iguais'),
        h('p', { class: 'field-help' }, 'Opções que entram no fim do endereço como ', h('code', {}, '?nome=valor'), ', em toda chamada. Cada API tem as suas, quase sempre opcionais: a lista está na documentação dela.'),
        docsAction(state),
        pairs(state, state.params, 'param', redraw))),
    headers: () => h('div', { class: 'stack-sm' },
      how('Informações que acompanham o pedido, fora do endereço. A credencial tem aba própria: use o cadeado para qualquer outro valor sigiloso.'),
      pairs(state, state.headers, 'header', redraw)),
    body: () => h('div', { class: 'stack-sm' },
      field('Tipo', choice(state, 'body_type', [['json', 'JSON'], ['text', 'Texto']])),
      field('Corpo', h('textarea', { class: 'input mono', rows: 8, spellcheck: false, oninput: (e) => { state.body = e.target.value; state.onChange(); } }, state.body),
        'Num JSON, escreva a variável entre aspas: {"id": "{id}"}. O valor entra com o tipo certo.')),
    auth: () => h('div', { class: 'stack-sm' }, authScheme(state), authPane(state, redraw)),
    pages: () => h('div', { class: 'stack-sm' }, pagesScheme(state.pagination), pagesPane(state, redraw)),
    answer: () => h('div', { class: 'stack-sm' },
      how('Depois de testar, a resposta aparece ao lado: clique numa lista dela para escolher de onde vêm as linhas, sem precisar digitar o caminho.'),
      answerPane(state, redraw)),
  }[tab]();
}

/** Abas do pedido: parâmetros, cabeçalhos, corpo (só no POST), autenticação, páginas e resposta. */
function apiTabs(state, vars, onRedraw) {
  const ctx = { tab: 'params', el: h('div', { class: 'segmented small' }), pane: h('div', { class: 'api-pane' }) };
  ctx.drawTabs = () => {
    const list = [['params', 'Parâmetros'], ['headers', 'Cabeçalhos'], state.method === 'POST' ? ['body', 'Corpo'] : null,
      ['auth', 'Autenticação'], ['pages', 'Páginas'], ['answer', 'Resposta']].filter(Boolean);
    if (!list.some(([k]) => k === ctx.tab)) ctx.tab = 'params';
    ctx.el.replaceChildren(...list.map(([k, l]) => h('button', {
      type: 'button', class: 'segment', 'aria-selected': String(k === ctx.tab), dataset: { tab: k },
      onclick: () => ctx.show(k),
    }, l)));
  };
  ctx.drawPane = () => ctx.pane.replaceChildren(apiPane(ctx.tab, state, vars, () => { ctx.drawPane(); onRedraw(); }));
  ctx.show = (tab) => { ctx.tab = tab; ctx.drawTabs(); ctx.drawPane(); };
  return ctx;
}

/** A resposta real ao lado da tabela que ela gerou; passar o mouse num campo acende a coluna. */
function answerFlow(res, state, retest) {
  const cols = res.columns.slice(0, 5).map((c) => c.name);
  const table = mini(`A tabela: ${res.columns.length} colunas`, cols.map((c) => ({ text: c, kind: 'to', link: `c:${c}` })),
    res.rows.slice(0, 3).map((r) => cols.map((c) => ({ text: r[c] === null || r[c] === undefined ? '—' : String(r[c]), link: `c:${c}` }))));
  const tree = res.sample
    ? responseTree(res.sample, state, {
      onPick: (path) => { state.records_path = path; state.explode_path = ''; retest(); },
      onExplode: (path) => { state.explode_path = path; retest(); },
    })
    : h('p', { class: 'field-help' }, 'Resposta em CSV ou XML: cada linha ou elemento repetido vira uma linha da tabela.');
  return [
    h('div', { class: 'api-stage' }, h('div', { class: 'x-title' }, 'A resposta da API (amostra)'), tree),
    arrow('vira'),
    h('div', { class: 'api-stage' }, table),
  ];
}

/** Testar: chama a API de verdade e mostra a resposta, a tabela e as colunas. */
async function testApi(state, samples, view, again) {
  const { meta, grid, flow, tabs, vars } = view;
  if (state.method === 'POST') {
    const ok = await confirmDialog({ title: 'Fazer o POST de teste?', message: 'A chamada é real: se esta API grava dados, o teste grava também.', confirm: 'Chamar' });
    if (!ok) return;
  }
  const retest = () => {
    tabs.drawPane();
    if (state.method === 'GET') again();
    else meta.replaceChildren(h('span', { class: 'muted' }, 'Clique em Testar para ver o resultado: um POST não é repetido sozinho.'));
  };
  grid.classList.add('loading');
  meta.replaceChildren(h('span', { class: 'muted' }, 'Chamando…'));
  try {
    const res = await api.previewApi({ definition: apiDefinition(state), id: state.id, secrets: filledSecrets(state), values: samples });
    if (res.needs_values) {
      meta.replaceChildren(h('span', { class: 'text-warning' }, icon('alert', 14), ` Preencha um valor de teste para ${res.needs_values.map((n) => `{${n}}`).join(', ')}, na aba Parâmetros.`));
      tabs.show('params');
      vars.el.querySelector('input')?.focus();
      grid.replaceChildren();
      return;
    }
    meta.replaceChildren(h('span', { class: 'badge' }, icon('check', 12), 'Respondeu'),
      h('span', { class: 'muted' }, `${res.columns.length} colunas · ${fmt.int(res.total)} linhas nesta página${res.more_pages ? ' · há mais páginas' : ''}`));
    flow.replaceChildren(...answerFlow(res, state, retest));
    grid.replaceChildren(previewTable(res.columns, res.rows));
  } catch (err) {
    meta.replaceChildren(h('span', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
    flow.replaceChildren(howItWorks());
    grid.replaceChildren();
  } finally {
    grid.classList.remove('loading');
  }
}

/** Grava a API e marca como pendentes as caixas do fluxo aberto que a usam. */
async function saveApiSource(state) {
  if (!state.url.trim()) throw new Error('Informe o endereço da API.');
  let hostname = 'API';
  try { hostname = new URL(state.url.replace(/\{[^}]*\}/g, 'x')).hostname; } catch { /* a validação do servidor explica */ }
  const name = state.name.trim() || hostname;
  const source = { ...apiDefinition(state), name, cache_results: state.cache_results, hold_on_open: state.hold_on_open, id: state.id || slug(name) };
  const saved = await api.saveApi({ source, secrets: filledSecrets(state) });
  state.id = saved.id;
  await refreshApis();
  const users = (store.workflow?.nodes || []).filter((n) => n.config?.dataset === `${API_PREFIX}${saved.id}` || (n.type === 'io.api_loop' && n.config?.source === saved.id));
  if (users.length) commit({ affects: users.map((n) => n.id) });
  return saved;
}

/** Exemplos prontos, só para uma API nova: cada um reabre o formulário já preenchido. */
function apiExamples(host, onSaved) {
  const box = h('div', { class: 'api-examples' }, h('div', { class: 'x-title' }, 'Começar de um exemplo'));
  api.apiExamples().then((list) => box.append(h('div', { class: 'api-example-list' }, list.map((ex) => h('button', {
    type: 'button', class: 'api-example', title: ex.what,
    onclick: () => host.reopen({ preset: ex.source, values: ex.values, onSaved }),
  }, h('strong', {}, ex.title), h('span', {}, ex.source.name), h('em', { class: 'api-example-kind' }, placeholdersOf(ex.source).length ? 'com variável' : 'direta')))))).catch(() => box.remove());
  return box;
}

function apiForm(state, view, { examples, test }) {
  const { tabs, notices } = view;
  const toggle = (key, label, title) => h('label', { class: 'switch', title },
    h('input', { type: 'checkbox', checked: state[key], onchange: (e) => { state[key] = e.target.checked; } }),
    h('span', { class: 'switch-track' }), h('span', {}, label));
  notices.urlInput = text(state, 'url', { placeholder: 'https://api.exemplo.com/v1/clientes/{id}', 'aria-label': 'Endereço da API', class: 'input mono', oninput: () => state.onChange() });
  return h('div', { class: 'api-form stack-sm' },
    examples,
    field('Nome', text(state, 'name', { placeholder: 'Ex.: Clientes do CRM' })),
    field('Documentação da API (opcional)', h('div', { class: 'row' },
      text(state, 'docs_url', { placeholder: 'https://… onde a API explica o que aceita', 'aria-label': 'Endereço da documentação', oninput: () => { if (tabs.tab === 'params') tabs.drawPane(); } }),
      button({ icon: 'link', title: 'Abrir a documentação', onClick: () => openLink(state.docs_url.trim()) }))),
    h('div', { class: 'api-url' },
      choice(state, 'method', [['GET', 'GET'], ['POST', 'POST']], () => { tabs.drawTabs(); tabs.drawPane(); state.onChange(); }),
      notices.urlInput,
      button({ label: 'Testar', icon: 'play', onClick: test })),
    view.requestBox, notices.el, tabs.el, tabs.pane,
    toggle('hold_on_open', 'Só chamar quando eu clicar em Executar', 'Ligado: abrir um fluxo não chama esta API. Ela espera o clique em Executar.'),
    toggle('cache_results', 'Reaproveitar resultado entre execuções', 'Desligado: a API é chamada de novo a cada execução.'));
}

/**
 * Formulário de cadastro de API, para um diálogo ou para a vista Dados (spec 028). `host.close()` fecha ou volta;
 * `host.reopen(opts)` abre de novo com outro ponto de partida (um exemplo pronto).
 */
export function apiEditor({ source = null, onSaved = null, preset = null, values = {} } = {}, host) {
  const state = { ...blank(), ...(source ? structuredClone(source) : {}), ...(preset ? structuredClone(preset) : {}), secrets: {}, stored: source?.set_secrets || [], onChange: () => {} };
  if (preset) state.id = '';
  const samples = { ...values };
  const view = {
    meta: h('div', { class: 'preview-meta' }, h('span', { class: 'muted' }, 'Clique em Testar para ver as colunas.')),
    grid: h('div', { class: 'preview-grid' }),
    flow: linkHover(h('div', { class: 'api-flow' }, howItWorks())),
    requestBox: h('div', { class: 'api-request' }),
    notices: apiNotices(state),
    vars: apiVariables(state, samples),
  };
  const drawRequest = () => view.requestBox.replaceChildren(h('div', { class: 'x-title' }, 'O que será enviado'), requestPreview(state));
  view.tabs = apiTabs(state, view.vars, () => { view.notices.draw(); drawRequest(); });
  state.onChange = () => { view.notices.draw(); drawRequest(); view.vars.draw(); };
  const test = () => testApi(state, samples, view, test);
  const finish = async (addToFlow) => {
    try {
      const saved = await saveApiSource(state);
      host.close();
      if (onSaved) onSaved(saved);
      else if (addToFlow) addApiNode(saved);
      toast(`API "${saved.name}" salva`, { kind: 'success' });
    } catch (err) {
      toastError(err, 'Não foi possível salvar a API');
    }
  };
  const form = apiForm(state, view, { examples: source || preset ? null : apiExamples(host, onSaved), test });
  view.tabs.drawTabs();
  view.tabs.drawPane();
  state.onChange();
  return {
    title: source ? `Editar API · ${source.name}` : 'Nova API',
    body: h('div', { class: 'preview-layout api-layout' }, form, h('div', { class: 'preview-main api-main' }, view.meta, view.flow, view.grid)),
    actions: [
      button({ label: 'Cancelar', onClick: () => host.close() }),
      onSaved ? null : button({ label: 'Salvar', icon: 'save', onClick: () => finish(false) }),
      button({ label: onSaved ? 'Salvar' : 'Salvar e adicionar ao fluxo', icon: onSaved ? 'save' : 'plus', variant: 'primary', onClick: () => finish(true) }),
    ].filter(Boolean),
  };
}

/** O mesmo formulário num diálogo: usado pelos atalhos do Configurar. */
export function openApiEditor(opts = {}) {
  const host = { close: () => {}, reopen: (next) => { host.close(); openApiEditor(next); } };
  const editor = apiEditor(opts, host);
  const { close } = openDialog({ title: editor.title, size: 'xl', body: editor.body, actions: editor.actions });
  host.close = close;
}

export async function removeApi(item) {
  const used = store.workflow?.nodes.some((n) => n.config?.dataset === `${API_PREFIX}${item.id}` || n.config?.source === item.id);
  const ok = await confirmDialog({
    title: 'Excluir API',
    message: `Excluir a API "${item.name}" e os segredos dela?${used ? ' Este fluxo usa a API e deixará de funcionar.' : ''}`,
    confirm: 'Excluir',
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteApi(item.id);
    await refreshApis();
  } catch (err) {
    toastError(err, 'Não foi possível excluir');
  }
}
