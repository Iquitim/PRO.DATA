// Cadastro de constantes (spec 028, RF-2848, RF-2849, RF-2855): o formulário, o aviso antes de mudar uma
// compartilhada usada em outros fluxos e o diálogo "Constantes do fluxo", aberto pela barra do canvas.

import { api } from './api.js';
import {
  flowRefs, knownConstants, markChanged, NAME_RE, refreshConstants, renameRefs, showValue, SYSTEM_CONSTANTS, TYPES, valueProblem,
} from './constants.js';
import { button, h } from './dom.js';
import { icon } from './icons.js';
import { mutate, store } from './store.js';
import { confirmDialog, openDialog, toast, toastError } from './ui.js';

const EXAMPLES = {
  date: (n) => ['IF ', ['col', '[data_venda]'], ' >= ', ['cst', `[#${n}]`], " THEN 'no mês' ELSE 'antes' ENDIF"],
  number: (n) => [['col', '[valor]'], ' * ', ['cst', `[#${n}]`]],
  text: (n) => [['col', '[uf]'], ' = ', ['cst', `[#${n}]`]],
};

/** A referência com a cor de constante, igual à do editor de fórmula. */
export const refChip = (name) => h('code', { class: 'fx-cst cst-chip' }, `[#${name}]`);

function example(type, name) {
  return h('pre', { class: 'cst-example mono', 'aria-label': 'Exemplo de fórmula' },
    EXAMPLES[type](name || 'nome').map((p) => (Array.isArray(p) ? h('span', { class: `fx-${p[0]}` }, p[1]) : p)));
}

function field(label, control, help) {
  return h('div', { class: 'field' }, h('label', { class: 'field-label' }, label), control,
    help ? h('p', { class: 'field-help' }, help) : null);
}

/** "Mudar mes_referencia em 3 fluxos?": lista as caixas que passam a calcular com o valor novo (RF-2849). */
export function confirmChange(name, before, after, uses) {
  return new Promise((resolve) => {
    let answer = false;
    const boxes = uses.flatMap((u) => u.readers.map((r) => ({ ...r, flow: u.workflow })));
    const { close } = openDialog({
      title: `Mudar ${name} em ${uses.length} fluxo${uses.length > 1 ? 's' : ''}?`,
      size: 'sm',
      body: h('div', { class: 'stack-sm' },
        h('p', { class: 'dialog-text' }, 'De ', h('b', {}, showValue(before)), ' para ', h('b', {}, showValue(after)),
          '. Estas caixas passam a calcular com o valor novo na próxima execução:'),
        h('ul', { class: 'cst-affected' }, boxes.map((b) => h('li', {},
          h('span', { class: 'cst-dot', style: { '--cat': `var(--cat-${store.tools[b.type]?.category || 'org'})` } }),
          h('b', {}, b.label || store.tools[b.type]?.name || b.type), h('span', { class: 'muted' }, b.flow))))),
      actions: [
        button({ label: 'Cancelar', onClick: () => close() }),
        button({ label: uses.length > 1 ? `Mudar nos ${uses.length} fluxos` : 'Mudar no fluxo', variant: 'primary', onClick: () => { answer = true; close(); } }),
      ],
      onClose: () => resolve(answer),
    });
  });
}

/** O que impede salvar, em português; vazio quando está tudo certo. */
function constantProblem(c, existing, scope) {
  if (!NAME_RE.test(c.name)) return 'O nome começa com letra e usa só letras, números e _ (sem espaço nem acento).';
  if (SYSTEM_CONSTANTS[c.name] && c.name !== existing?.name) return `[#${c.name}] é uma constante do sistema: escolha outro nome.`;
  const known = knownConstants().get(c.name);
  if (known && c.name !== existing?.name && (scope === 'flow' || known.scope !== 'flow')) {
    return known.scope === 'shared' && scope === 'flow'
      ? `Já existe uma constante compartilhada chamada ${c.name}: use a compartilhada ou escolha outro nome.`
      : `Já existe uma constante chamada ${c.name}.`;
  }
  return valueProblem(c.type, c.value);
}

/** Grava uma compartilhada, depois de avisar quem a usa (RF-2849). Devolve false quando a pessoa desiste. */
async function saveShared(constant, existing, uses) {
  if (existing && uses.length) {
    const changed = existing.value !== constant.value || existing.type !== constant.type;
    if (changed && !await confirmChange(existing.name, existing, constant, uses)) return false;
    if (existing.name !== constant.name && !await confirmDialog({
      title: `Renomear ${existing.name}?`,
      message: `${uses.length} fluxo(s) usam [#${existing.name}]. Eles passam a avisar que a constante não está cadastrada até você trocar a referência para [#${constant.name}].`,
      confirm: 'Renomear', danger: true,
    })) return false;
  }
  await api.saveConstant(constant, existing?.name || null);
  await refreshConstants();
  markChanged(constant.name, existing?.name);
  toast(`Constante ${constant.name} salva`, { kind: 'success', detail: 'Os fluxos que a usam calculam com este valor na próxima execução.' });
  return true;
}

/**
 * Formulário de uma constante. `scope`: 'shared' (vista Dados) ou 'flow' (diálogo do fluxo).
 * `uses`: onde a compartilhada é usada (de /api/usage), para o aviso antes de mudar.
 * `onSave(constant, previous)`: no escopo do fluxo, quem chama grava no fluxo; no compartilhado, já vai ao servidor.
 */
export function constantEditor(existing, { scope = 'shared', uses = [], onSave, onSaved } = {}, host) {
  const c = existing ? { ...existing } : { name: '', type: 'date', value: '', description: '' };
  const problem = h('p', { class: 'text-error small', role: 'alert', hidden: true });
  const exampleBox = h('div', {});
  const valueBox = h('div', {});
  const name = h('input', {
    class: 'input mono', value: c.name, placeholder: 'mes_referencia', spellcheck: false, 'aria-label': 'Nome da constante',
    oninput: (e) => { c.name = e.target.value.trim(); exampleBox.replaceChildren(example(c.type, c.name)); },
  });
  const drawValue = () => {
    const input = h('input', {
      class: 'input', type: c.type === 'date' ? 'date' : 'text', value: c.value, 'aria-label': 'Valor',
      inputmode: c.type === 'number' ? 'decimal' : undefined, placeholder: c.type === 'number' ? 'Ex.: 0,15' : c.type === 'text' ? 'Ex.: SP' : '',
      oninput: (e) => { c.value = e.target.value; before.hidden = !changed(); },
    });
    // "Antes" só aparece quando o valor muda: é a lembrança do que os fluxos usam hoje.
    const changed = () => Boolean(existing) && (c.value !== existing.value || c.type !== existing.type);
    const before = h('p', { class: 'field-help', hidden: !changed() }, 'Antes: ', h('b', {}, existing ? showValue(existing) : ''));
    valueBox.replaceChildren(input, before);
  };
  const types = h('div', { class: 'segmented small', role: 'radiogroup', 'aria-label': 'Tipo' });
  const drawTypes = () => types.replaceChildren(...Object.entries(TYPES).map(([k, label]) => h('button', {
    type: 'button', class: 'segment', role: 'radio', 'aria-checked': String(c.type === k), 'aria-selected': String(c.type === k),
    onclick: () => { if (c.type !== k) c.value = ''; c.type = k; drawTypes(); drawValue(); exampleBox.replaceChildren(example(c.type, c.name)); },
  }, label)));
  drawTypes();
  drawValue();
  exampleBox.replaceChildren(example(c.type, c.name));

  const save = async () => {
    const err = constantProblem(c, existing, scope);
    problem.hidden = !err;
    problem.textContent = err;
    if (err) return;
    const constant = { name: c.name, type: c.type, value: String(c.value).trim(), description: (c.description || '').trim() };
    try {
      if (scope === 'flow') onSave?.(constant, existing?.name || null);
      else if (!await saveShared(constant, existing, uses)) return;
      host.close();
      onSaved?.(constant);
    } catch (e) {
      toastError(e, 'Não foi possível salvar a constante');
    }
  };

  return {
    title: existing ? `Editar constante · ${existing.name}` : scope === 'flow' ? 'Nova constante do fluxo' : 'Nova constante compartilhada',
    body: h('div', { class: 'form cst-form' },
      h('p', { class: 'cst-lead' }, icon('hash', 14),
        ' Uma constante é um valor com nome, como o mês de referência, que você troca num lugar só. ',
        scope === 'flow' ? 'Esta fica no arquivo do fluxo e vale só nele.' : 'Esta vale para todos os fluxos deste computador.'),
      h('div', { class: 'cst-grid' },
        field('Nome', name, 'Na fórmula, escreva entre [# e ].'),
        field('Tipo', types)),
      field('Valor', valueBox),
      field('Descrição', h('textarea', {
        class: 'input', rows: 2, maxlength: 300, placeholder: 'Ex.: primeiro dia do mês que os relatórios fecham.',
        oninput: (e) => { c.description = e.target.value; },
      }, c.description || ''), 'Opcional: ajuda quem abrir o fluxo depois.'),
      problem,
      h('section', { class: 'cst-how' },
        h('strong', {}, 'Como usar numa fórmula'),
        h('p', { class: 'field-help' }, 'No editor de fórmula, o botão Constante insere a referência. Ela tem cor própria, para nunca parecer uma coluna.'),
        exampleBox,
        h('p', { class: 'field-help' }, 'Também vale no valor do Filter básico, no nome do arquivo do Output Data e nos parâmetros fixos de uma API.'))),
    actions: [
      button({ label: 'Cancelar', onClick: () => host.close() }),
      button({ label: 'Salvar', icon: 'save', variant: 'primary', onClick: save }),
    ],
  };
}

// ------------------------------------------------------------------ diálogo do fluxo (RF-2855)

function saveFlowConstant(constant, previous) {
  const refs = flowRefs();
  const affects = [...(refs.get(constant.name) || []), ...(previous ? refs.get(previous) || [] : [])].map((n) => n.id);
  mutate((wf) => {
    const list = (wf.constants || []).filter((x) => x.name !== (previous || constant.name));
    wf.constants = [...list, constant].sort((a, b) => a.name.localeCompare(b.name));
    if (previous && previous !== constant.name) renameRefs(wf, previous, constant.name);
  }, { affects });
}

async function removeFlowConstant(constant, users) {
  if (users.length && !await confirmDialog({
    title: `Excluir ${constant.name}?`,
    message: `${users.length} caixa(s) deste fluxo usam [#${constant.name}] e passam a dar erro: ${users.map((n) => n.label || store.tools[n.type]?.name || n.type).join(', ')}.`,
    confirm: 'Excluir', danger: true,
  })) return false;
  mutate((wf) => { wf.constants = (wf.constants || []).filter((x) => x.name !== constant.name); }, { affects: users.map((n) => n.id) });
  return true;
}

const usedText = (users) => (users.length ? `em ${users.length} caixa${users.length > 1 ? 's' : ''}` : 'sem uso');

function row(c, users, actions, tone = '') {
  return h('div', { class: ['cst-row', tone && `tone-${tone}`] },
    refChip(c.name),
    h('span', { class: 'cst-type' }, TYPES[c.type] || c.type || ''),
    h('b', { class: 'cst-value ellipsis', title: c.value }, c.value === undefined ? '—' : showValue(c)),
    h('span', { class: ['cst-use', !users.length && 'none'] }, usedText(users)),
    c.description ? h('span', { class: 'cst-desc muted ellipsis', title: c.description }, c.description) : null,
    h('span', { class: 'cst-actions' }, actions));
}

/** `openData(key)`: leva à vista Dados (quem chama é o main.js, que troca a vista). */
export function openFlowConstants({ create = false, openData = () => {} } = {}) {
  if (!store.workflow) return;
  const editor = (existing) => {
    const host = { close: () => { dlg.close(); openFlowConstants({ openData }); } };
    let dlg = null;
    const ed = constantEditor(existing, { scope: 'flow', onSave: saveFlowConstant }, host);
    dlg = openDialog({ title: ed.title, body: ed.body, actions: ed.actions, size: 'md' });
  };
  if (create) { editor(null); return; }
  const refs = flowRefs();
  const own = store.workflow.constants || [];
  const sharedNames = [...refs.keys()].filter((n) => !own.some((c) => c.name === n)).sort();
  const saved = store.workflow.shared_constants || {};
  let dlg = null;
  const ownRows = own.map((c) => row(c, refs.get(c.name) || [], [
    button({ icon: 'edit', title: 'Editar', size: 'sm', variant: 'ghost', onClick: () => { dlg.close(); editor(c); } }),
    button({ icon: 'trash', title: 'Excluir', size: 'sm', variant: 'ghost', onClick: async () => {
      if (await removeFlowConstant(c, refs.get(c.name) || [])) { dlg.close(); openFlowConstants({ openData }); }
    } }),
  ], store.constants.some((s) => s.name === c.name) ? 'err' : ''));
  const sharedRows = sharedNames.map((n) => {
    const reg = store.constants.find((s) => s.name === n);
    if (!reg && SYSTEM_CONSTANTS[n]) {
      return row(SYSTEM_CONSTANTS[n](), refs.get(n) || [], [h('span', { class: 'cst-flag' }, icon('clock', 12), ' do sistema, sem cadastro')], '');
    }
    const c = reg || (saved[n] ? { name: n, ...saved[n] } : { name: n });
    const tone = reg ? '' : saved[n] ? 'warn' : 'err';
    return row(c, refs.get(n) || [], [
      reg ? button({ label: 'Abrir em Dados', size: 'sm', variant: 'ghost', onClick: () => { dlg.close(); openData(`const:${n}`); } })
        : h('span', { class: `cst-flag tone-${tone}` }, icon('alert', 12), saved[n] ? ' não cadastrada aqui: usa o valor salvo' : ' não existe'),
    ], tone);
  });
  dlg = openDialog({
    title: 'Constantes do fluxo',
    size: 'lg',
    body: h('div', { class: 'stack-md cst-dialog' },
      h('p', { class: 'cst-lead' }, icon('hash', 14),
        ' Valores com nome que as caixas usam, como ', refChip('mes_referencia'), '. Troque aqui e só as caixas que usam a constante são refeitas.'),
      h('section', { class: 'stack-sm' },
        h('div', { class: 'row space-between' }, h('h3', {}, 'Deste fluxo'),
          button({ icon: 'plus', label: 'Nova constante do fluxo', size: 'sm', onClick: () => { dlg.close(); editor(null); } })),
        h('p', { class: 'field-help' }, 'Ficam no arquivo do fluxo e vão junto quando você o envia a alguém.'),
        ownRows.length ? h('div', { class: 'cst-list' }, ownRows) : h('p', { class: 'muted small' }, 'Nenhuma ainda.')),
      h('section', { class: 'stack-sm' },
        h('div', { class: 'row space-between' }, h('h3', {}, 'Compartilhadas usadas aqui'),
          button({ icon: 'database', label: 'Ver todas na vista Dados', size: 'sm', variant: 'ghost', onClick: () => { dlg.close(); openData(null); } })),
        h('p', { class: 'field-help' }, 'Cadastradas na vista Dados, valem para todos os fluxos. O fluxo guarda o valor de cada uma, para rodar em outro computador.'),
        sharedRows.length ? h('div', { class: 'cst-list' }, sharedRows)
          : h('p', { class: 'muted small' }, store.constants.length
            ? `Nenhuma caixa usa as ${store.constants.length} compartilhada(s) ainda. No editor de fórmula, use o botão Constante.`
            : 'Nenhuma compartilhada cadastrada.'))),
    actions: [button({ label: 'Fechar', variant: 'primary', onClick: () => dlg.close() })],
  });
}
