// Fontes de API da aba Dados (spec 021). Segredos só saem do navegador ao testar ou salvar; o servidor guarda
// no cofre do sistema e nunca os devolve. Uma API salva vira uma fonte do Input Data (valor `api:<id>`).

import { addNode } from './actions.js';
import { api } from './api.js';
import { DND_DATASET, viewportCenter } from './canvas.js';
import { slug } from './connections.js';
import { previewTable } from './datasets.js';
import { button, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { API_PREFIX, commit, emit, on, store } from './store.js';
import { confirmDialog, openDialog, toast, toastError } from './ui.js';

const PLACEHOLDER = /\{([^{}"':\r\n]+)\}/g;
const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/i;

export async function refreshApis() {
  store.apis = await api.apis();
  emit('apis');
}

const blank = () => ({
  id: '', name: '', url: '', method: 'GET', params: [], headers: [], body: '', body_type: 'json',
  auth: { type: 'none', key_name: 'X-API-Key', key_in: 'header', username: '', token_url: '', client_id: '', scope: '' },
  format: 'auto', records_path: '', explode_path: '', flatten: true,
  pagination: { type: 'none', page_param: 'page', start_page: 1, size_param: '', page_size: 100, offset_param: 'offset', limit_param: 'limit', cursor_param: 'cursor', cursor_path: 'next_cursor', next_path: '', max_pages: 100 },
  timeout_s: 30, max_mb: 200, retries: 3, cache_results: false,
});

export function placeholdersOf(d) {
  const texts = [d.url, d.method === 'POST' ? d.body : '',
    ...[...d.params, ...d.headers].filter((p) => !p.secret).map((p) => p.value)];
  return [...new Set(texts.flatMap((t) => [...(t || '').matchAll(PLACEHOLDER)].map((m) => m[1])))];
}

export function addApiNode(saved) {
  const c = viewportCenter();
  if (placeholdersOf(saved).length) addNode('io.api_loop', c.x - 94, c.y - 28, { source: saved.id, __label: saved.name });
  else addNode('io.input_data', c.x - 94, c.y - 28, { dataset: `${API_PREFIX}${saved.id}`, __label: saved.name });
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
  const rows = list.map((p, i) => h('div', { class: 'api-pair' },
    text(p, 'name', { placeholder: 'Nome', 'aria-label': 'Nome' }),
    p.secret
      ? h('input', {
        class: 'input', type: 'password', autocomplete: 'new-password', 'aria-label': 'Valor sigiloso',
        value: state.secrets[`${kind}:${p.name}`] || '',
        placeholder: state.stored.includes(`${kind}:${p.name}`) ? 'Guardado no cofre' : 'Valor sigiloso',
        oninput: (e) => { state.secrets[`${kind}:${p.name}`] = e.target.value; },
      })
      : text(p, 'value', { placeholder: 'Valor, ou {coluna}', 'aria-label': 'Valor', oninput: () => state.onChange() }),
    h('label', { class: 'api-secret', title: 'Guarda o valor no cofre do sistema, fora do arquivo' },
      h('input', { type: 'checkbox', checked: p.secret, onchange: (e) => { p.secret = e.target.checked; redraw(); } }), icon('lock', 12)),
    button({ icon: 'trash', size: 'sm', variant: 'ghost', title: 'Remover', onClick: () => { list.splice(i, 1); redraw(); } })));
  return h('div', { class: 'stack-xs' }, rows,
    button({ icon: 'plus', label: 'Adicionar', size: 'sm', variant: 'ghost', onClick: () => { list.push({ name: '', value: '', secret: false }); redraw(); } }));
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

function answerPane(state) {
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

export function openApiEditor({ source = null, onSaved = null } = {}) {
  const state = { ...blank(), ...(source ? structuredClone(source) : {}), secrets: {}, stored: source?.set_secrets || [], onChange: () => {} };
  const samples = {};
  const meta = h('div', { class: 'preview-meta' }, h('span', { class: 'muted' }, 'Clique em Testar para ver as colunas.'));
  const grid = h('div', { class: 'preview-grid' });
  const notices = h('div', { class: 'stack-xs api-notices' });
  const pane = h('div', { class: 'api-pane' });
  let tab = 'params';

  const definition = () => {
    const { id, name, cache_results, secrets, stored, onChange, set_secrets, missing_secrets, ...d } = state;
    return d;
  };
  const drawNotices = () => {
    const url = state.url.trim();
    const needed = placeholdersOf(state);
    notices.replaceChildren(...[
      url.toLowerCase().startsWith('http://') && !LOCAL.test(url)
        ? h('p', { class: 'api-warn' }, icon('alert', 14), ' Endereço sem criptografia (http): credenciais e dados viajam abertos na rede.') : null,
      state.method === 'POST'
        ? h('p', { class: 'api-warn' }, icon('alert', 14), ' Um POST pode gravar dados no servidor. Ele não roda sozinho ao abrir o fluxo.') : null,
      needed.length
        ? h('div', { class: 'stack-xs' },
          h('p', { class: 'field-help' }, icon('repeat', 12), ` Esta API pede ${needed.map((n) => `{${n}}`).join(', ')}: entra no fluxo como API Loop, uma chamada por linha. Valores para o teste:`),
          ...needed.map((n) => h('label', { class: 'sheet-port' }, h('span', { class: 'ellipsis' }, n),
            h('input', { class: 'input input-sm', value: samples[n] || '', 'aria-label': `Valor de teste para ${n}`, oninput: (e) => { samples[n] = e.target.value; } }))))
        : null,
    ].filter(Boolean));
  };
  state.onChange = drawNotices;

  const tabs = h('div', { class: 'segmented small' });
  const drawTabs = () => {
    const list = [['params', 'Parâmetros'], ['headers', 'Cabeçalhos'], state.method === 'POST' ? ['body', 'Corpo'] : null,
      ['auth', 'Autenticação'], ['pages', 'Páginas'], ['answer', 'Resposta']].filter(Boolean);
    if (!list.some(([k]) => k === tab)) tab = 'params';
    tabs.replaceChildren(...list.map(([k, l]) => h('button', {
      type: 'button', class: 'segment', 'aria-selected': String(k === tab), dataset: { tab: k },
      onclick: () => { tab = k; drawTabs(); drawPane(); },
    }, l)));
  };
  const drawPane = () => {
    const redraw = () => { drawPane(); drawNotices(); };
    pane.replaceChildren({
      params: () => pairs(state, state.params, 'param', redraw),
      headers: () => pairs(state, state.headers, 'header', redraw),
      body: () => h('div', { class: 'stack-sm' },
        field('Tipo', choice(state, 'body_type', [['json', 'JSON'], ['text', 'Texto']])),
        field('Corpo', h('textarea', { class: 'input mono', rows: 8, spellcheck: false, oninput: (e) => { state.body = e.target.value; drawNotices(); } }, state.body),
          'Num JSON, escreva a coluna entre aspas: {"id": "{id}"}. O valor entra com o tipo certo.')),
      auth: () => authPane(state, redraw),
      pages: () => pagesPane(state, redraw),
      answer: () => answerPane(state),
    }[tab]());
  };

  const test = async () => {
    if (state.method === 'POST') {
      const ok = await confirmDialog({ title: 'Fazer o POST de teste?', message: 'A chamada é real: se esta API grava dados, o teste grava também.', confirm: 'Chamar' });
      if (!ok) return;
    }
    grid.classList.add('loading');
    meta.replaceChildren(h('span', { class: 'muted' }, 'Chamando…'));
    try {
      const secrets = Object.fromEntries(Object.entries(state.secrets).filter(([, v]) => v));
      const res = await api.previewApi({ definition: definition(), id: state.id, secrets, values: samples });
      if (res.needs_values) {
        meta.replaceChildren(h('span', { class: 'text-warning' }, icon('alert', 14), ` Preencha um valor de teste para: ${res.needs_values.join(', ')}.`));
        grid.replaceChildren();
        return;
      }
      meta.replaceChildren(h('span', { class: 'badge' }, icon('check', 12), 'Respondeu'),
        h('span', { class: 'muted' }, `${res.columns.length} colunas · ${fmt.int(res.total)} linhas nesta página${res.more_pages ? ' · há mais páginas' : ''}`));
      grid.replaceChildren(previewTable(res.columns, res.rows));
    } catch (err) {
      meta.replaceChildren(h('span', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
      grid.replaceChildren();
    } finally {
      grid.classList.remove('loading');
    }
  };

  const persist = async () => {
    if (!state.url.trim()) throw new Error('Informe o endereço da API.');
    let host = 'API';
    try { host = new URL(state.url.replace(/\{[^}]*\}/g, 'x')).hostname; } catch { /* a validação do servidor explica */ }
    const name = state.name.trim() || host;
    const secrets = Object.fromEntries(Object.entries(state.secrets).filter(([, v]) => v));
    const saved = await api.saveApi({ source: { ...definition(), name, cache_results: state.cache_results, id: state.id || slug(name) }, secrets });
    state.id = saved.id;
    await refreshApis();
    const users = (store.workflow?.nodes || []).filter((n) => n.config?.dataset === `${API_PREFIX}${saved.id}` || (n.type === 'io.api_loop' && n.config?.source === saved.id));
    if (users.length) commit({ affects: users.map((n) => n.id) });
    return saved;
  };
  const finish = async (addToFlow) => {
    try {
      const saved = await persist();
      close();
      if (onSaved) onSaved(saved);
      else if (addToFlow) addApiNode(saved);
      toast(`API "${saved.name}" salva`, { kind: 'success' });
    } catch (err) {
      toastError(err, 'Não foi possível salvar a API');
    }
  };

  const form = h('div', { class: 'api-form stack-sm' },
    field('Nome', text(state, 'name', { placeholder: 'Ex.: Clientes do CRM' })),
    h('div', { class: 'api-url' },
      choice(state, 'method', [['GET', 'GET'], ['POST', 'POST']], () => { drawTabs(); drawPane(); drawNotices(); }),
      text(state, 'url', { placeholder: 'https://api.exemplo.com/v1/clientes/{id}', 'aria-label': 'Endereço da API', class: 'input mono', oninput: drawNotices }),
      button({ label: 'Testar', icon: 'play', onClick: test })),
    notices, tabs, pane,
    h('label', { class: 'switch', title: 'Desligado: a API é chamada de novo a cada execução.' },
      h('input', { type: 'checkbox', checked: state.cache_results, onchange: (e) => { state.cache_results = e.target.checked; } }),
      h('span', { class: 'switch-track' }), h('span', {}, 'Reaproveitar resultado entre execuções')));

  drawTabs();
  drawPane();
  drawNotices();
  const { close } = openDialog({
    title: source ? `Editar API · ${source.name}` : 'Nova API',
    size: 'xl',
    body: h('div', { class: 'preview-layout api-layout' }, form, h('div', { class: 'preview-main' }, meta, grid)),
    actions: [
      button({ label: 'Cancelar', onClick: () => close() }),
      onSaved ? null : button({ label: 'Salvar', icon: 'save', onClick: () => finish(false) }),
      button({ label: onSaved ? 'Salvar' : 'Salvar e adicionar ao fluxo', icon: onSaved ? 'save' : 'plus', variant: 'primary', onClick: () => finish(true) }),
    ].filter(Boolean),
  });
}

async function removeApi(item) {
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

// ------------------------------------------------------------------ painel

function apiItem(item) {
  const looped = placeholdersOf(item).length > 0;
  let host = item.url;
  try { host = new URL(item.url.replace(/\{[^}]*\}/g, 'x')).hostname; } catch { /* mostra como está */ }
  const missing = item.missing_secrets?.length ? ' · falta segredo' : '';
  return h('div', {
    class: 'dataset-item query-item', draggable: looped ? 'false' : 'true',
    title: looped ? 'Use o botão + para criar um API Loop' : 'Arraste para o canvas para criar um Input Data',
    ondragstart: (e) => {
      e.dataTransfer.setData(DND_DATASET, `${API_PREFIX}${item.id}`);
      e.dataTransfer.effectAllowed = 'copy';
    },
  },
  h('span', { class: 'dataset-icon' }, icon(looped ? 'repeat' : 'globe', 16)),
  h('button', { type: 'button', class: 'dataset-main', onclick: () => openApiEditor({ source: item }), title: 'Editar e testar' },
    h('span', { class: 'dataset-name' }, item.name),
    h('span', { class: 'dataset-meta' }, `${item.method} · ${host}${missing}`)),
  h('div', { class: 'dataset-actions' },
    button({ icon: 'plus', title: looped ? 'Adicionar API Loop ao fluxo' : 'Adicionar ao fluxo', size: 'sm', variant: 'ghost', onClick: () => addApiNode(item) }),
    button({ icon: 'trash', title: 'Excluir API', size: 'sm', variant: 'ghost', onClick: () => removeApi(item) })));
}

export function renderApisSection(root) {
  const list = h('div', { class: 'dataset-list' });
  const draw = () => list.replaceChildren(...(store.apis.length
    ? store.apis.map(apiItem)
    : [h('p', { class: 'muted pad' }, 'Nenhuma API. Cadastre uma para ler dados da web no Input Data.')]));
  on('apis', draw);
  root.append(
    h('div', { class: 'panel-subtitle row space-between' }, 'APIs',
      button({ icon: 'plus', label: 'Nova', size: 'sm', variant: 'ghost', onClick: () => openApiEditor() })),
    list);
  draw();
}
