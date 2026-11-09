// Detalhe de uma fonte na vista Dados (spec 028, RF-2803..2804, RF-2810): visão geral, cadastro, uso e explicação.

import { addJiraNode, jiraConnectionEditor, jiraQueryEditor, removeJiraConnection, removeJiraQuery } from './jira_ui.js';
import { tableSkeleton } from './skeleton.js';
import { api } from './api.js';
import { addApiNode, apiEditor, removeApi } from './apis.js';
import { addQueryNode, connectionEditor, queryEditor, removeConnection, removeQuery } from './connections.js';
import { refreshConstants } from './constants.js';
import { constantEditor } from './constants_ui.js';
import { KINDS, usageText, usesOf } from './data_sources.js';
import { usageMap } from './data_map.js';
import { addInputNode, openPreview, previewTable, removeDataset, uploadFiles } from './datasets.js';
import { button, fmt, h } from './dom.js';
import { icon } from './icons.js';

const TONES = { ok: 'check', warn: 'alert', err: 'alert', info: 'link' };

/** Desenho do caminho de cada tipo de fonte: o "Como funciona" (RF-2810). */
const HOW = {
  file: [['Arquivo', 'vendas.xlsx'], ['Tabela', 'linhas e colunas']],
  query: [['Banco', 'conexão'], ['Consulta', 'SELECT …'], ['Tabela', 'linhas e colunas']],
  jira: [['Jira', 'projetos e filtros'], ['Consulta', 'sem escrever JQL'], ['Tabela', 'só o que mudou']],
  jiraconn: [['Token', 'só leitura, no cofre'], ['Consultas', 'uma ou mais'], ['Fluxos', 'Input Data']],
  api: [['Pedido', 'GET /estados'], ['Resposta', '[{"sigla":"SP"…'], ['Tabela', 'linhas e colunas']],
  conn: [['Conexão', 'servidor e senha'], ['Consultas', 'uma ou mais'], ['Fluxos', 'Input Data']],
  const: [['Constante', '[#mes_referencia]'], ['Caixas', 'Formula, Filter…'], ['Execução', 'usa o valor de agora']],
};
const HOW_TEXT = {
  jira: 'A consulta lê demandas, histórico ou comentários do Jira, sem alterar nada, e vira uma tabela no Input Data. A primeira carga traz tudo; as seguintes, só o que mudou. Se cair no meio, continua de onde parou.',
  jiraconn: 'A conexão guarda o endereço do Jira e, no cofre do Windows, o e-mail e o token. O PRO.DATA só faz leituras, e o Jira só mostra o que a sua conta pode ver.',
  file: 'Um arquivo enviado vira uma cópia guardada no PRO.DATA. Um arquivo vinculado é lido onde está, sempre na versão mais nova.',
  query: 'A consulta pergunta ao banco, só para ler, e a resposta vira uma tabela no Input Data. A senha fica no cofre do Windows.',
  api: 'O PRO.DATA faz o pedido, recebe a resposta e transforma a lista que ela traz numa tabela. Com uma variável, como {sigla}, entra no fluxo como API Loop.',
  conn: 'A conexão guarda onde fica o banco e a senha, no cofre do Windows. As consultas usam a conexão; os fluxos usam as consultas.',
  const: 'Na execução, o PRO.DATA troca [#nome] pelo valor. Mudou o valor? Só as caixas que usam a constante são refeitas. Cada fluxo guarda o valor que usou, para rodar também num computador sem este cadastro.',
};

export function howItWorks(kind) {
  const color = KINDS[kind].color;
  return h('div', { class: 'stack-sm' },
    h('div', { class: 'dv-how', role: 'img', 'aria-label': HOW[kind].map(([a]) => a).join(', depois ') },
      HOW[kind].map(([title, sample], i) => h('span', { class: 'dv-step-wrap' },
        i ? h('span', { class: 'dv-link', style: { '--line': color }, 'aria-hidden': 'true' }) : null,
        h('span', { class: 'dv-how-box' }, h('b', {}, title), h('small', { class: 'mono' }, sample))))),
    h('p', { class: 'dv-how-text' }, HOW_TEXT[kind]));
}

function stat(label, value, hint = '') {
  return h('div', { class: 'dv-stat' }, h('span', {}, label), h('strong', {}, value), hint ? h('small', {}, hint) : null);
}

/** Barras de qualidade por coluna, na amostra lida: verde preenchido, âmbar texto vazio, vermelho sem valor. */
function columnQuality(preview) {
  const total = preview.rows.length || 1;
  return h('section', { class: 'dv-card stack-sm' },
    h('h3', {}, 'Qualidade das colunas'),
    h('p', { class: 'field-help' }, `Nas primeiras ${fmt.int(preview.rows.length)} linhas · verde: preenchido · âmbar: texto vazio · vermelho: sem valor`),
    preview.columns.slice(0, 14).map((c) => {
      const values = preview.rows.map((r) => r[c.name]);
      const nul = values.filter((v) => v === null || v === undefined).length;
      const empty = values.filter((v) => typeof v === 'string' && !v.trim()).length;
      const pct = (n) => `${(n / total) * 100}%`;
      return h('div', { class: 'dv-quality' },
        h('span', { class: 'mono ellipsis', title: c.name }, c.name),
        h('span', { class: 'dv-quality-bar', title: `${nul} sem valor · ${empty} texto vazio` },
          h('span', { class: 'q-ok', style: { width: pct(total - nul - empty) } }),
          h('span', { class: 'q-empty', style: { width: pct(empty) } }),
          h('span', { class: 'q-null', style: { width: pct(nul) } })),
        h('span', { class: 'muted' }, `${Math.round(((total - nul - empty) / total) * 100)}%`));
    }));
}

function fileOverview(source) {
  const box = h('div', { class: 'stack-md' }, tableSkeleton(8));
  if (source.raw.missing) {
    box.replaceChildren(h('p', { class: 'api-warn' }, icon('alert', 14), ` O arquivo vinculado não foi encontrado em ${source.raw.linked_path}.`));
    return box;
  }
  api.previewDataset(source.id, {}, 100).then((preview) => {
    box.replaceChildren(
      h('div', { class: 'dv-stats' },
        stat('Linhas', preview.row_count === null ? '—' : fmt.int(preview.row_count)),
        stat('Colunas', fmt.int(preview.columns.length)),
        stat('Tamanho', fmt.bytes(preview.info.size_bytes)),
        stat('Atualizado', preview.info.modified_at ? new Date(preview.info.modified_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '—',
          source.raw.linked_path ? 'lido onde está' : 'cópia no PRO.DATA')),
      h('div', { class: 'dv-split' },
        h('section', { class: 'dv-card dv-grow stack-sm' },
          h('div', { class: 'row space-between' }, h('h3', {}, 'Prévia: primeiras linhas'),
            button({ icon: 'settings', label: 'Opções de leitura', size: 'sm', variant: 'ghost', onClick: () => openPreview(source.id) })),
          previewTable(preview.columns, preview.rows.slice(0, 12))),
        columnQuality(preview)));
  }).catch((err) => box.replaceChildren(h('p', { class: 'text-error' }, icon('alert', 14), ` ${err.message}`)));
  return box;
}

/** Cadastro dentro da vista: o mesmo formulário dos atalhos, com os botões no rodapé. */
function editorPane(source, ctx) {
  const host = { close: () => ctx.refresh(), reopen: (opts) => ctx.mountEditor(source.kind, opts) };
  const done = (saved) => ctx.afterSave(source.kind, saved);
  const editor = source.kind === 'api' ? apiEditor({ source: source.raw, onSaved: done }, host)
    : source.kind === 'jira' ? jiraQueryEditor({ query: source.raw, onSaved: done }, host)
    : source.kind === 'jiraconn' ? jiraConnectionEditor(source.raw, { onSaved: done }, host)
    : source.kind === 'query' ? queryEditor({ query: source.raw, onSaved: done }, host)
      : source.kind === 'const' ? constantEditor(source.raw, { uses: usesOf(source), onSaved: done }, host)
        : connectionEditor(source.raw, { onSaved: done }, host);
  return h('div', { class: 'dv-editor' }, editor.body, h('footer', { class: 'dv-editor-actions' }, editor.actions));
}

function actionsFor(source, ctx) {
  const add = (fn) => () => { fn(); ctx.showDesigner(); };
  const replace = h('input', { type: 'file', hidden: true,
    onchange: (e) => { uploadFiles([...e.target.files], { overwrite: true }).then(ctx.refresh); e.target.value = ''; } });
  const list = {
    file: [
      button({ icon: 'plus', label: 'Adicionar ao fluxo', disabled: source.raw.missing, onClick: add(() => addInputNode(source.id)) }),
      source.raw.linked_path ? null : button({ icon: 'upload', label: 'Enviar nova versão', onClick: () => replace.click() }),
      button({ icon: 'trash', label: source.raw.linked_path ? 'Remover vínculo' : 'Excluir', variant: 'ghost', onClick: () => ctx.remove(source, () => removeDataset(source.raw)) }),
      replace,
    ],
    query: [
      button({ icon: 'plus', label: 'Adicionar ao fluxo', onClick: add(() => addQueryNode(source.raw)) }),
      button({ icon: 'trash', label: 'Excluir', variant: 'ghost', onClick: () => ctx.remove(source, () => removeQuery(source.raw)) }),
    ],
    api: [
      button({ icon: 'plus', label: source.loop ? 'Adicionar API Loop ao fluxo' : 'Adicionar ao fluxo', onClick: add(() => addApiNode(source.raw)) }),
      button({ icon: 'trash', label: 'Excluir', variant: 'ghost', onClick: () => ctx.remove(source, () => removeApi(source.raw)) }),
    ],
    const: [
      button({ icon: 'trash', label: 'Excluir', variant: 'ghost',
        onClick: () => ctx.remove(source, async () => { await api.deleteConstant(source.id); await refreshConstants(); }) }),
    ],
    jira: [
      button({ icon: 'plus', label: 'Adicionar ao fluxo', onClick: add(() => addJiraNode(source.raw)) }),
      button({ icon: 'trash', label: 'Excluir', variant: 'ghost', onClick: () => ctx.remove(source, () => removeJiraQuery(source.raw)) }),
    ],
    jiraconn: [
      button({ icon: 'plus', label: 'Nova consulta', onClick: () => ctx.newSource('jira', { connectionId: source.id }) }),
      button({ icon: 'trash', label: 'Excluir', variant: 'ghost', onClick: () => ctx.remove(source, () => removeJiraConnection(source.raw)) }),
    ],
    conn: [
      button({ icon: 'plus', label: 'Nova consulta', onClick: () => ctx.newSource('query', { connectionId: source.id }) }),
      button({ icon: 'trash', label: 'Excluir', variant: 'ghost', onClick: () => ctx.remove(source, () => removeConnection(source.raw)) }),
    ],
  };
  return list[source.kind].filter(Boolean);
}

/** `ctx`: tab, setTab, refresh, mountEditor, afterSave, remove, newSource, openFlow, showDesigner. */
export function sourceDetail(source, ctx) {
  const kind = KINDS[source.kind];
  const uses = usesOf(source);
  const tabs = source.kind === 'file'
    ? [['overview', 'Visão geral'], ['usage', 'Onde é usada'], ['how', 'Como funciona']]
    : [['overview', 'Cadastro'], ['usage', 'Onde é usada'], ['how', 'Como funciona']];
  const tab = tabs.some(([k]) => k === ctx.tab) ? ctx.tab : 'overview';
  const content = {
    overview: () => (source.kind === 'file' ? fileOverview(source) : editorPane(source, ctx)),
    usage: () => usageMap(source, uses, ctx.openFlow),
    how: () => howItWorks(source.kind),
  }[tab]();
  return h('div', { class: 'dv-detail' },
    h('header', { class: 'dv-head' },
      h('span', { class: 'dv-head-icon', style: { '--kind': kind.color } }, icon(kind.icon, 22)),
      h('div', { class: 'dv-head-text' }, h('h2', {}, source.name), h('p', {}, `${kind.one[0].toUpperCase()}${kind.one.slice(1)} · ${source.meta}`)),
      h('span', { class: ['dv-chip', `tone-${source.state.tone}`] }, icon(TONES[source.state.tone], 12), source.state.label),
      h('button', { type: 'button', class: ['dv-chip', 'dv-chip-use', !uses.length && 'none'], onclick: () => ctx.setTab('usage') }, usageText(source)),
      h('div', { class: 'dv-head-actions' }, actionsFor(source, ctx))),
    h('nav', { class: 'dv-tabs', role: 'tablist', 'aria-label': 'Seções da fonte' }, tabs.map(([k, label]) => h('button', {
      type: 'button', role: 'tab', class: 'dv-tab', 'aria-selected': String(k === tab), dataset: { tab: k },
      onclick: () => ctx.setTab(k),
    }, label))),
    h('div', { class: 'dv-body' }, content));
}
