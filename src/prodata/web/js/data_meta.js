// Cabeçalho organizável do detalhe de uma fonte (spec 034, RF-3410..3420): nome de exibição editável no título,
// pasta, fixar e a descrição com responsável. Tudo é texto puro: nada aqui vira HTML.

import { button, h } from './dom.js';
import { icon } from './icons.js';
import { changeSources, colorOf, folderOf, moveItems } from './organization.js';
import { showMenu } from './ui.js';

/** Como a fonte é chamada nos fluxos e fórmulas: o nome original, que nunca muda por aqui. */
export const originalOf = (source) => (source.kind === 'const' ? `[#${source.name}]` : source.name);

/** Título que vira campo ao clicar. Vazio ou igual ao original volta ao nome original (RF-3413). */
export function titleEditor(source, { editing = false } = {}) {
  const wrap = h('div', { class: 'org-title' });
  const save = (value) => {
    const text = value.trim();
    const label = text === source.name ? '' : text;
    if (label !== source.info.label) changeSources([source.key], { label });
    else show();
  };
  const show = () => wrap.replaceChildren(
    h('button', { type: 'button', class: 'org-title-btn', title: 'Clique para dar um nome de exibição', onclick: edit },
      h('h2', {}, source.title), h('span', { class: 'org-title-pen' }, icon('edit', 14))));
  function edit() {
    const input = h('input', {
      class: 'input org-title-input', value: source.title, maxlength: 120, 'aria-label': 'Nome de exibição',
      placeholder: source.name,
      onkeydown: (e) => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { e.preventDefault(); input.dataset.cancel = '1'; input.blur(); }
      },
      onblur: () => (input.dataset.cancel ? show() : save(input.value)),
    });
    wrap.replaceChildren(input,
      h('p', { class: 'org-title-help' }, icon('info', 12),
        ' Só muda como a fonte aparece na tela. Os fluxos continuam usando ', h('span', { class: 'mono' }, originalOf(source)),
        '. Deixe vazio para voltar ao nome original.'));
    input.focus();
    input.select();
  }
  editing ? queueMicrotask(edit) : show();
  return wrap;
}

/** "Nome original: …", quando a fonte tem nome de exibição. */
export function originalLine(source) {
  if (!source.info.label) return null;
  return h('span', { class: 'org-original-line' }, 'nome original ', h('span', { class: 'mono' }, originalOf(source)));
}

/** Pasta da fonte, num chip colorido que abre o "Mover para", e o botão de fixar. */
export function orgChips(source) {
  const folder = folderOf(source.info.folder);
  const pinned = source.info.pinned;
  return [
    h('button', {
      type: 'button', class: ['dv-chip', 'org-folder-chip', !folder && 'none'], style: { '--folder': colorOf(folder) },
      title: 'Mover para outra pasta',
      onclick: (e) => { const r = e.currentTarget.getBoundingClientRect(); showMenu(r.left, r.bottom + 4, moveItems([source.key], source.info.folder)); },
    }, icon('folder-closed', 12), folder ? folder.name : 'Sem pasta', icon('chevron-down', 11)),
    h('button', {
      type: 'button', class: ['dv-chip', 'org-pin', pinned && 'on'], 'aria-pressed': String(pinned),
      title: pinned ? 'Desafixar do topo da lista' : 'Fixar no topo da lista',
      onclick: () => changeSources([source.key], { pinned: !pinned }),
    }, icon('star', 12), pinned ? 'Fixada' : 'Fixar'),
  ];
}

/** Descrição e responsável. Vazia, convida a escrever com um exemplo; preenchida, mostra o texto (RF-3420). */
export function aboutBlock(source) {
  const box = h('section', { class: 'org-about' });
  const { description, owner } = source.info;
  const edit = () => {
    const text = h('textarea', {
      class: 'input', rows: 3, maxlength: 1000, value: description, 'aria-label': 'Descrição da fonte',
      placeholder: 'Ex.: Extrato diário da conta movimento, baixado do banco pela Tesouraria às 9h. Uma linha por lançamento.',
    });
    const who = h('input', { class: 'input', maxlength: 120, value: owner, 'aria-label': 'Responsável', placeholder: 'Ex.: Ana, da Tesouraria' });
    const save = async () => {
      if (await changeSources([source.key], { description: text.value, owner: who.value })) return;
      text.focus();
    };
    box.classList.add('editing');
    box.replaceChildren(
      h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'O que é esta fonte'), text),
      h('label', { class: 'field' }, h('span', { class: 'field-label' }, icon('user', 12), ' Responsável'), who),
      h('div', { class: 'row' },
        button({ label: 'Salvar', variant: 'primary', size: 'sm', onClick: save }),
        button({ label: 'Cancelar', variant: 'ghost', size: 'sm', onClick: () => box.replaceWith(aboutBlock(source)) })));
    text.focus();
  };
  if (!description && !owner) {
    box.classList.add('empty');
    box.append(h('button', { type: 'button', class: 'org-about-invite', onclick: edit },
      h('span', { class: 'org-about-plus' }, icon('plus', 14)),
      h('span', {}, h('strong', {}, 'Descrever esta fonte'),
        h('small', {}, 'O que contém, de onde vem, quando atualiza e quem cuida. Ajuda quem abrir o fluxo depois.'))));
    return box;
  }
  box.append(
    h('div', { class: 'org-about-text' }, description ? h('p', {}, description) : h('p', { class: 'muted' }, 'Sem descrição.'),
      owner ? h('span', { class: 'org-owner' }, icon('user', 12), owner) : null),
    button({ icon: 'edit', title: 'Editar descrição e responsável', size: 'sm', variant: 'ghost', onClick: edit }));
  return box;
}
