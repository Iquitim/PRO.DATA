// Lições guiadas (spec 030, RF-3081..3083): passo a passo dentro do programa, num fluxo só da lição.
// Cada passo diz onde agir e avança sozinho quando a ação acontece. Nada aqui mexe no fluxo da pessoa.

import { h, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { revealPanel } from './layout.js';
import { store } from './store.js';
import { toast } from './ui.js';

const DONE_KEY = 'prodata.licoes.concluidas';
const POLL_MS = 250;
const CLIENTES = 'clientes_enterprise.csv';
const VENDAS = 'transacoes_vendas.csv';

const nodeOf = (type) => store.workflow?.nodes.find((n) => n.type === type) || null;
const linked = (fromType, toType, handle = null) => {
  const from = nodeOf(fromType);
  const to = nodeOf(toType);
  return Boolean(from && to && store.workflow.edges.some((e) => e.source === from.id && e.target === to.id && (!handle || e.targetHandle === handle)));
};
const ran = (type) => {
  const n = nodeOf(type);
  return Boolean(n && store.execution?.node_results?.[n.id]?.status === 'executed' && !store.running);
};

const toolEl = (type) => () => {
  const name = store.tools[type]?.name;
  return [...document.querySelectorAll('#leftPanel .tool-item')].find((e) => e.querySelector('.tool-name')?.textContent === name) || null;
};
const nodeEl = (type) => () => {
  const n = nodeOf(type);
  return n ? document.querySelector(`.node[data-id="${CSS.escape(n.id)}"]`) : null;
};
const runEl = () => [...document.querySelectorAll('#topActions button')].find((b) => b.textContent.includes('Executar')) || null;
const viewEl = (view) => () => document.querySelector(`#viewSwitch .segment[data-view=${view}]`);

const addStep = (type, what) => ({ tool: type, text: `Arraste ${store.tools[type]?.name || 'a ferramenta'} da lista à esquerda para o canvas. ${what}`, target: toolEl(type), done: () => Boolean(nodeOf(type)) });
const linkStep = (from, to, text, handle = null) => ({ text, target: nodeEl(to), done: () => linked(from, to, handle) });
const runStep = (type, text) => ({ text, target: runEl, done: () => ran(type) });

const input = (id, label, dataset, y) => ({ id, type: 'io.input_data', label, x: 80, y, config: { dataset } });
const flow = (id, name, nodes = [], edges = []) => ({ id: `licao_${id}`, name: `Lição: ${name}`, description: 'Fluxo da lição. Mexa à vontade: nada aqui altera os seus fluxos.', containers: [], nodes, edges });

export const LESSONS = [
  {
    id: 'primeiro',
    title: 'Seu primeiro fluxo',
    about: 'Trazer um arquivo, filtrar e ver o resultado.',
    start: () => flow('primeiro', 'Seu primeiro fluxo'),
    steps: () => [
      addStep('io.input_data', 'É ela que traz os dados.'),
      { text: `Clique na caixa e, no painel à direita, escolha o arquivo ${CLIENTES}.`, target: nodeEl('io.input_data'), done: () => Boolean(nodeOf('io.input_data')?.config.dataset) },
      addStep('prep.filter', 'Ela separa as linhas.'),
      linkStep('io.input_data', 'prep.filter', 'Ligue a saída do Input Data à entrada do Filter: arraste de um círculo ao outro.'),
      { text: 'Clique no Filter e escolha uma coluna e um valor. Por exemplo, uf igual a SP.', target: nodeEl('prep.filter'), done: () => { const c = nodeOf('prep.filter')?.config; return Boolean(c && ((c.column && c.value) || c.expression)); } },
      runStep('prep.filter', 'Agora clique em Executar. Depois, clique na caixa para ver a tabela.'),
    ],
  },
  {
    id: 'juntar',
    title: 'Juntar duas tabelas',
    about: 'Combinar clientes e vendas por uma coluna em comum.',
    start: () => flow('juntar', 'Juntar duas tabelas', [input('a', 'Clientes', CLIENTES, 60), input('b', 'Vendas', VENDAS, 240)]),
    steps: () => [
      addStep('transform.join', 'Ele casa as linhas das duas tabelas.'),
      { text: 'Ligue Clientes à entrada L do Join.', target: nodeEl('transform.join'), done: () => store.workflow.edges.some((e) => e.source === 'a' && e.target === nodeOf('transform.join')?.id && e.targetHandle === 'L') },
      { text: 'Ligue Vendas à entrada R do Join.', target: nodeEl('transform.join'), done: () => store.workflow.edges.some((e) => e.source === 'b' && e.target === nodeOf('transform.join')?.id && e.targetHandle === 'R') },
      { text: 'Clique no Join e escolha id_cliente nos dois lados da chave.', target: nodeEl('transform.join'), done: () => { const k = nodeOf('transform.join')?.config.keys?.[0]; return Boolean(k?.left && k?.right); } },
      runStep('transform.join', 'Clique em Executar. A saída J traz o que casou; L e R, o que sobrou de cada lado.'),
    ],
  },
  {
    id: 'qualidade',
    title: 'Conferir a qualidade',
    about: 'Criar uma regra e separar o que passou do que falhou.',
    start: () => flow('qualidade', 'Conferir a qualidade', [input('a', 'Clientes', CLIENTES, 120)]),
    steps: () => [
      addStep('prep.data_quality', 'Ela confere cada linha.'),
      linkStep('io.input_data', 'prep.data_quality', 'Ligue Clientes à entrada da caixa Data Quality.'),
      { text: 'Clique em Data Quality e adicione uma regra. Por exemplo, setor não pode ficar vazio.', target: nodeEl('prep.data_quality'), done: () => (nodeOf('prep.data_quality')?.config.rules || []).some((r) => r.column) },
      runStep('prep.data_quality', 'Clique em Executar. A saída P traz o que passou; F, o que falhou e o motivo.'),
    ],
  },
  {
    id: 'dashboard',
    title: 'Montar um dashboard',
    about: 'Criar um gráfico e ver a página pronta.',
    start: () => flow('dashboard', 'Montar um dashboard', [input('a', 'Clientes', CLIENTES, 120)]),
    steps: () => [
      addStep('bi.chart', 'Cada gráfico é uma caixa do fluxo.'),
      linkStep('io.input_data', 'bi.chart', 'Ligue Clientes à entrada do Chart.'),
      { text: 'Clique no Chart, escolha uf em Categoria e Contagem em Agregação.', target: nodeEl('bi.chart'), done: () => { const c = nodeOf('bi.chart')?.config; return Boolean(c?.x_column && (c.agg === 'count' || c.y_column)); } },
      runStep('bi.chart', 'Clique em Executar para gerar o gráfico.'),
      { text: 'Abra a vista Dashboard no topo. A página já vem montada.', target: viewEl('dashboard'), done: () => store.view === 'dashboard' },
    ],
  },
];

export const finishedLessons = () => storage(DONE_KEY, []);

let session = null;

function stop() {
  if (!session) return;
  clearInterval(session.timer);
  session.card.remove();
  session.ring.remove();
  session = null;
}

function revealTool(type, setView) {
  setView('designer');
  revealPanel('explorer');
  document.querySelector('#leftPanel .tab[data-tab=tools]')?.click();
  const search = document.querySelector("#leftPanel input[placeholder='Buscar ferramenta']");
  if (search) {
    search.value = store.tools[type]?.name || '';
    search.dispatchEvent(new Event('input', { bubbles: true }));
  }
}

function placeRing() {
  const { steps, index, ring } = session;
  const el = steps[index]?.target?.();
  if (!el || !el.offsetParent) { ring.hidden = true; return; }
  const r = el.getBoundingClientRect();
  ring.hidden = false;
  Object.assign(ring.style, { left: `${r.left - 4}px`, top: `${r.top - 4}px`, width: `${r.width + 8}px`, height: `${r.height + 8}px` });
}

function finish() {
  const { lesson, body } = session;
  persist(DONE_KEY, [...new Set([...finishedLessons(), lesson.id])]);
  clearInterval(session.timer);
  session.ring.hidden = true;
  body.replaceChildren(h('strong', {}, icon('check-circle', 15), ' Lição concluída'),
    h('p', {}, 'O fluxo da lição fica aberto para você explorar. Ele não é salvo sozinho.'),
    h('div', { class: 'lesson-actions' }, h('button', { type: 'button', class: 'btn btn-primary btn-sm', onclick: stop }, 'Fechar')));
}

function drawStep(setView) {
  const { steps, index, body, lesson } = session;
  const step = steps[index];
  if (step.tool) revealTool(step.tool, setView);
  body.replaceChildren(
    h('small', { class: 'lesson-count' }, `${lesson.title} · passo ${index + 1} de ${steps.length}`),
    h('p', { class: 'lesson-text' }, step.text),
    h('div', { class: 'lesson-actions' },
      h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: () => advance(setView) }, 'Pular'),
      h('button', { type: 'button', class: 'btn btn-sm', onclick: stop }, 'Sair')));
}

function advance(setView) {
  session.index += 1;
  if (session.index >= session.steps.length) finish();
  else drawStep(setView);
}

/** `actions`: { setView, openExample(workflow) }. A lição abre numa aba própria e o fluxo da pessoa continua aberto. */
export async function startLesson(id, actions) {
  stop();
  const lesson = LESSONS.find((l) => l.id === id);
  if (!lesson) return;
  try {
    await actions.openExample(lesson.start());
  } catch (err) {
    toast(err.message, { kind: 'error' });
    return;
  }
  const body = h('div', { class: 'lesson-body' });
  const card = h('section', { class: 'lesson-card', role: 'status', 'aria-label': 'Lição guiada' }, body);
  const ring = h('div', { class: 'lesson-ring', hidden: true });
  document.body.append(card, ring);
  session = { lesson, steps: lesson.steps(), index: 0, body, card, ring, timer: 0 };
  drawStep(actions.setView);
  session.timer = setInterval(() => {
    if (store.workflow?.id !== `licao_${lesson.id}`) return; // a pessoa foi para outra aba: a lição espera
    if (session.steps[session.index].done()) advance(actions.setView);
    if (session) placeRing();
  }, POLL_MS);
}

export const lessonRunning = () => Boolean(session);
