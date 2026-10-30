// Antes de executar (spec 017, RF-1703): exportações em "Perguntar ao executar" que vão encontrar o arquivo
// já existente perguntam o que fazer — substituir, criar um novo com data e hora, ou adicionar a planilha.

import { button, h } from './dom.js';
import { icon } from './icons.js';
import { openDialog } from './ui.js';

const CHOICES = [
  ['new_file', 'Criar um novo arquivo', 'Mesmo nome com data e hora; o atual fica intacto'],
  ['replace', 'Substituir o arquivo', 'O conteúdo atual é apagado'],
  ['add_sheet', 'Adicionar ou atualizar a planilha', 'Mantém as outras planilhas do arquivo'],
];

/**
 * Pergunta o que fazer com cada arquivo. Devolve `{ choices: {nó: modo}, remember: bool }`
 * ou `null` se o usuário cancelar (aí nada executa).
 */
export function askExports(pending) {
  return new Promise((resolve) => {
    let answer = null;
    const choices = Object.fromEntries(pending.map((p) => [p.node_id, 'new_file']));
    const remember = h('input', { type: 'checkbox', id: 'exports-remember' });
    const rows = pending.map((p) => h('fieldset', { class: 'export-ask' },
      h('legend', {}, icon('file', 14), h('strong', {}, p.file), p.label ? h('span', { class: 'muted' }, ` · ${p.label}`) : null),
      h('p', { class: 'muted mono export-path', title: p.path }, p.path),
      CHOICES.filter(([value]) => value !== 'add_sheet' || p.format === 'excel').map(([value, label, help]) => h('label', { class: 'export-choice' },
        h('input', {
          type: 'radio', name: `exp-${p.node_id}`, value, checked: value === 'new_file',
          onchange: () => { choices[p.node_id] = value; },
        }),
        h('span', {}, h('strong', {}, label), h('small', { class: 'muted' }, help))))));
    const { close } = openDialog({
      title: pending.length === 1 ? 'O arquivo já existe' : `${pending.length} arquivos já existem`,
      body: h('div', { class: 'stack-sm' },
        h('p', {}, 'Antes de executar, escolha o que fazer com cada arquivo de saída.'),
        ...rows,
        h('label', { class: 'switch-line', for: 'exports-remember' }, remember,
          h('span', {}, 'Lembrar a escolha nas caixas (não perguntar de novo)'))),
      actions: [
        button({ label: 'Cancelar', onClick: () => close() }),
        button({ icon: 'play', label: 'Executar', variant: 'primary', onClick: () => {
          answer = { choices, remember: remember.checked };
          resolve(answer);
          close();
        } }),
      ],
      onClose: () => resolve(answer),
    });
  });
}
