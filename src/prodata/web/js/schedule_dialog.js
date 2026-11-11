// Execução sem clique (spec 033): mostra a linha de comando do fluxo aberto e o comando do Agendador do Windows.

import { button, h } from './dom.js';
import { isDirty, store } from './store.js';
import { openDialog, toast } from './ui.js';

function copyRow(label, text, help) {
  const code = h('code', { class: 'cli-line mono' }, text);
  return h('div', { class: 'field' },
    h('span', { class: 'field-label' }, label),
    h('div', { class: 'row' }, code, button({
      icon: 'copy', title: 'Copiar', onClick: async () => {
        try {
          await navigator.clipboard.writeText(text);
          toast('Copiado', { kind: 'success' });
        } catch {
          const range = document.createRange();
          range.selectNodeContents(code);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          toast('O comando está selecionado: use Ctrl+C para copiar.');
        }
      },
    })),
    help ? h('p', { class: 'field-help' }, help) : null);
}

export function openScheduleDialog() {
  const wf = store.workflow;
  if (!wf) return;
  const cli = store.catalog?.cli_command || 'prodata';
  // Arquivo de fora da biblioteca roda pelo caminho; o da biblioteca, pelo ID, que não muda com o nome.
  const target = store.filePath ? `"${store.filePath}"` : wf.id;
  const run = `${cli} run ${target}`;
  const task = `schtasks /Create /TN "PRO.DATA ${wf.name.replace(/"/g, '')}" /SC DAILY /ST 06:00 /TR "${run.replace(/"/g, '\\"')}"`;
  openDialog({
    title: 'Executar sem abrir o programa',
    size: 'lg',
    body: h('div', { class: 'form' },
      h('p', {}, 'O fluxo roda inteiro, grava as saídas e fecha. Serve para o Agendador do Windows deixar tudo pronto antes de você chegar.'),
      isDirty() ? h('p', { class: 'hint-box small' }, 'Salve antes: a linha de comando executa a versão salva, não a que está na tela.') : null,
      copyRow('Linha de comando deste fluxo', run, 'Termina com código 0 se tudo executou e 1 se alguma caixa falhou. O relatório de cada execução fica na pasta de dados, em logs/execucoes.'),
      copyRow('Agendar todo dia às 6h', task, 'Cole no Prompt de Comando. Para outro horário ou dia, mude /ST e /SC, ou edite a tarefa no Agendador de Tarefas.'),
      h('p', { class: 'field-help' }, 'Saída em "Perguntar ao executar" nunca sobrescreve sem alguém para responder: cria um arquivo novo com data e hora. Para manter sempre o mesmo nome, escolha "Substituir o arquivo" no Output Data.'),
      h('p', { class: 'field-help' }, 'Fluxo recebido de outra pessoa só executa por aqui depois de aberto e confiado no programa.')),
    actions: [],
  });
}
