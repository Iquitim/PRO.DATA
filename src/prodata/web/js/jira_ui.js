// Jira na vista Dados (spec 030): conexão com token guiado. A consulta fica em jira_query.js.

import { addNode } from './actions.js';
import { api } from './api.js';
import { viewportCenter } from './canvas.js';
import { openLink } from './desktop.js';
import { button, fmt, h } from './dom.js';
import { icon } from './icons.js';
import { emit, JIRA_PREFIX, store } from './store.js';
import { toast, toastError } from './ui.js';

const TOKEN_PAGE = 'https://id.atlassian.com/manage-profile/security/api-tokens';
export const newId = (prefix) => `${prefix}_${Date.now().toString(36)}`;

export async function refreshJira() {
  const [connections, queries] = await Promise.all([api.jiraConnections(), api.jiraQueries()]);
  store.jiraConnections = connections;
  store.jiraQueries = queries;
  emit('jira');
}

export function addJiraNode(query) {
  const c = viewportCenter();
  addNode('io.input_data', c.x - 94, c.y - 28, { dataset: `${JIRA_PREFIX}${query.id}`, __label: query.name });
}

export async function removeJiraQuery(query) {
  await api.deleteJiraQuery(query.id);
  await refreshJira();
}

export async function removeJiraConnection(conn) {
  await api.deleteJiraConnection(conn.id);
  await refreshJira();
}

export const field = (label, control, help) => h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control, help ? h('p', { class: 'field-help' }, help) : null);

export function step(n, title, body) {
  return h('li', { class: 'jira-step' }, h('b', {}, String(n)), h('div', {}, h('strong', {}, title), body));
}

function testMessage(res) {
  const scoped = res.token_kind === 'com escopo';
  return h('div', { class: 'stack-xs' },
    h('div', { class: 'jira-ok' }, icon('check', 14), ` Conectado como ${res.display_name} · ${fmt.int(res.projects)} projeto${res.projects === 1 ? '' : 's'}`),
    scoped ? null : h('p', { class: 'field-warn' }, icon('alert', 13),
      ' Este é um token comum, que também poderia alterar dados. O PRO.DATA só lê, mas o mais seguro é criar um token com escopo só de leitura.'));
}

/** Conexão: endereço, token criado no navegador, teste na hora. O token não volta para a tela. */
export function jiraConnectionEditor(existing, { onSaved }, host) {
  const state = { name: existing?.name || 'Jira', site: existing?.site || '', email: existing?.email || '', token: '' };
  const result = h('div', { class: 'jira-result', 'aria-live': 'polite' });
  const input = (key, attrs = {}) => h('input', { class: 'input', value: state[key], oninput: (e) => { state[key] = e.target.value; }, ...attrs });
  const request = () => ({ site: state.site, email: state.email, token: state.token, id: existing?.id || '' });
  const test = async () => {
    result.replaceChildren(h('p', { class: 'muted' }, 'Testando…'));
    try {
      const res = await api.testJira(request());
      result.replaceChildren(testMessage(res));
      return res;
    } catch (err) {
      result.replaceChildren(h('p', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`));
      return null;
    }
  };
  const save = async () => {
    const res = await test();
    if (!res) return;
    try {
      const saved = await api.saveJiraConnection({
        connection: { id: existing?.id || newId('jira'), name: state.name.trim() || 'Jira', site: res.site },
        email: state.email || null, token: state.token || null,
      });
      await refreshJira();
      toast(`Conexão ${saved.name} salva`, { kind: 'success' });
      host.close();
      onSaved?.(saved);
    } catch (err) {
      toastError(err, 'Não foi possível salvar a conexão');
    }
  };
  const body = h('div', { class: 'stack-md jira-form' },
    h('ol', { class: 'jira-steps' },
      step(1, 'Diga qual é o seu Jira', h('div', { class: 'stack-xs' },
        input('site', { placeholder: 'empresa.atlassian.net', 'aria-label': 'Endereço do Jira' }),
        h('p', { class: 'field-help' }, 'Pode colar o endereço de qualquer página do Jira.'))),
      step(2, 'Crie um token de leitura', h('div', { class: 'stack-xs' },
        button({ icon: 'globe', label: 'Criar meu token', onClick: () => openLink(TOKEN_PAGE) }),
        h('p', { class: 'field-help' }, 'Abre a página da Atlassian no navegador. Escolha ', h('b', {}, 'criar token com escopos'), ', selecione Jira e marque só as permissões de leitura, como ', h('code', {}, 'read:jira-work'), ' e ', h('code', {}, 'read:jira-user'), '.'))),
      step(3, 'Cole aqui', h('div', { class: 'stack-xs' },
        field('E-mail da sua conta Atlassian', input('email', { type: 'email', autocomplete: 'off' })),
        field('Token', input('token', { type: 'password', autocomplete: 'off', placeholder: existing?.has_token ? 'Guardado no cofre. Cole outro para trocar.' : '', 'aria-label': 'Token' }), 'Fica no cofre do Windows e nunca vai para fluxos, arquivos ou registros.')))),
    field('Nome da conexão', input('name')),
    result);
  return {
    title: existing ? `Editar conexão · ${existing.name}` : 'Conectar ao Jira',
    body,
    actions: [
      button({ label: 'Cancelar', onClick: () => host.close() }),
      button({ label: 'Testar', onClick: test }),
      button({ label: 'Salvar', variant: 'primary', onClick: save }),
    ],
  };
}
