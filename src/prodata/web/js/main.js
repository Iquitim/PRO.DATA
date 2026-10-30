// Ponto de entrada: carrega catálogo e fluxo, liga os módulos e os atalhos globais.

import { duplicateNode, removeContainer, removeEdge, removeNodes } from './actions.js';
import { api } from './api.js';
import {
  addContainerAtCenter, currentZoom, fitView, heldBy, initCanvas, NODE_W, pointerWorld, render as renderCanvas, zoomBy,
} from './canvas.js';
import { copySelection, cutSelection, paste } from './clipboard.js';
import { handleDashboardKey, initDashboard, render as renderDashboard } from './dashboard.js';
import { askExports } from './exports_ask.js';
import { refreshConnections, refreshQueries, renderConnectionsSection, renderQueriesSection } from './connections.js';
import { enableFileDropOnCanvas, refreshDatasets, renderDatasetsPanel } from './datasets.js';
import { basename, chooseOpenFile, chooseSaveFile, dirname } from './desktop.js';
import {
  activeIndex, anyDirty, dirtyTabs, findTab, openTab, persistTabs, removeTab, savedTabs, switchTab, tabCount, tabInfo,
} from './tabs.js';
import { $, button, debounce, fmt, h, isTyping, persist, storage } from './dom.js';
import { icon } from './icons.js';
import { initInsights } from './insights.js';
import { initInspector } from './inspector.js';
import { initLayout, openPanelsMenu, panelControls } from './layout.js';
import { renderPalette } from './palette.js';
import { initResults, showLog } from './results.js';
import {
  canRedo, canUndo, emit, inspect, markSaved, mutate, on, redo, select, selectedIds, selectMany, setExecution, store, undo,
} from './store.js';
import { confirmDialog, openDialog, showMenu, toast, toastError } from './ui.js';

const LAST_WORKFLOW = 'prodata.lastWorkflow'; // versões anteriores (antes das abas)
const RECENT_FILES = 'prodata.recentFiles';

// ------------------------------------------------------------------ execução

/**
 * Exportações em "Perguntar ao executar" com arquivo existente (spec 017): pergunta e devolve o fluxo a
 * executar (com a escolha só desta execução, ou gravada nas caixas), ou null se o usuário cancelar.
 */
async function resolveExports(targetNodeId) {
  const pending = await api.pendingExports(store.workflow, targetNodeId);
  if (!pending.length) return store.workflow;
  const answer = await askExports(pending);
  if (!answer) return null;
  if (answer.remember) {
    mutate((wf) => {
      for (const n of wf.nodes) if (answer.choices[n.id]) n.config.if_exists = answer.choices[n.id];
    });
    return store.workflow;
  }
  const once = structuredClone(store.workflow);
  for (const n of once.nodes) if (answer.choices[n.id]) n.config.if_exists = answer.choices[n.id];
  return once;
}

/**
 * Executa o fluxo. `auto`: execução que o usuário não pediu (abrir o programa ou um fluxo, trocar de aba):
 * exportações que precisariam perguntar ficam esperando o próximo "Executar".
 */
async function run(targetNodeId = null, { auto = false } = {}) {
  if (store.running || !store.workflow) return;
  let workflow = store.workflow;
  if (!auto) {
    try {
      workflow = await resolveExports(targetNodeId);
    } catch (err) {
      toastError(err, 'Não foi possível verificar os arquivos de saída');
      return;
    }
    if (!workflow) return; // cancelou: nada executa
  }
  store.running = true;
  emit('running');
  try {
    const report = await api.execute(workflow, targetNodeId, auto);
    setExecution(report, Object.keys(report.node_results));
    const errors = Object.values(report.node_results).filter((r) => r.status === 'error').length;
    if (errors) {
      toast(`${errors} nó(s) com erro`, { kind: 'error', detail: 'Veja os detalhes no nó ou no Log.' });
      showLog();
    }
    const focus = targetNodeId || store.inspect.nodeId || store.selection.nodeId;
    if (focus) inspect(focus, store.inspect.nodeId === focus ? store.inspect.anchor : null);
  } catch (err) {
    toastError(err, 'Falha ao executar o fluxo');
  } finally {
    store.running = false;
    emit('running');
  }
}

/** Ponto de cache (spec 012): descarta o resultado guardado e executa de novo, relendo as entradas. */
async function refreshCache(nodeId) {
  try {
    await api.refreshCache(store.workflow.id, nodeId);
    await run();
  } catch (err) {
    toastError(err, 'Não foi possível atualizar o cache');
  }
}

// ------------------------------------------------------------------ arquivos de fluxo e abas (specs 009 e 010)

/** Fluxo com alterações: Salvar / Não salvar / Cancelar. Devolve 'save' | 'discard' | 'cancel'. */
function askSave(name, { many = 0 } = {}) {
  return new Promise((resolve) => {
    // Responde no clique (não depende do evento "close"); fechar pelo X ou Esc conta como Cancelar.
    const choose = (value) => { resolve(value); close(); };
    const { close } = openDialog({
      title: 'Alterações não salvas',
      size: 'sm',
      body: h('p', { class: 'dialog-text' }, many > 1
        ? `${many} fluxos têm alterações não salvas. O que deseja fazer?`
        : `"${name}" tem alterações não salvas. Deseja salvar antes de fechar?`),
      actions: [
        button({ label: 'Cancelar', onClick: () => choose('cancel') }),
        button({ label: many > 1 ? 'Fechar sem salvar' : 'Não salvar', variant: 'danger', onClick: () => choose('discard') }),
        button({ label: many > 1 ? 'Salvar tudo' : 'Salvar', icon: 'save', variant: 'primary', onClick: () => choose('save') }),
      ],
      onClose: () => resolve('cancel'),
    });
  });
}

/** Abre o fluxo numa aba (ou ativa a aba onde ele já está). */
async function open(workflow, { saved = true, autorun = true, filePath = null } = {}) {
  const existing = saved ? findTab(workflow.id, filePath) : -1;
  if (existing >= 0) {
    switchTab(existing);
    return;
  }
  // Completa configs antigas/parciais com os padrões atuais de cada ferramenta.
  for (const n of workflow.nodes) {
    n.config = { ...structuredClone(store.tools[n.type]?.default_config || {}), ...n.config };
  }
  openTab(workflow, { saved, filePath });
  if (saved && filePath) rememberRecent(filePath, workflow.name);
  if (autorun && workflow.nodes.length) await run(null, { auto: true });
}

/** Fluxos abertos/salvos fora da biblioteca, mais recentes primeiro (só neste computador). */
function rememberRecent(path, name) {
  const items = storage(RECENT_FILES, []).filter((r) => r.path.toLowerCase() !== path.toLowerCase());
  persist(RECENT_FILES, [{ path, name, at: new Date().toISOString() }, ...items].slice(0, 8));
}

/** Salva a aba ativa. Devolve true se salvou. */
async function save() {
  if (store.filePath) return saveToFile(store.filePath);
  try {
    const saved = await api.saveWorkflow(store.workflow);
    markSaved();
    persistTabs();
    emit('tabs');
    toast('Fluxo salvo', { kind: 'success', detail: `Biblioteca do PRO.DATA · ${saved.id}.prodata.json` });
    return true;
  } catch (err) {
    toastError(err, 'Não foi possível salvar');
    return false;
  }
}

async function saveToFile(path) {
  try {
    const res = await api.saveWorkflowFile(path, store.workflow);
    store.filePath = res.path;
    markSaved();
    rememberRecent(res.path, store.workflow.name);
    persistTabs();
    emit('file');
    emit('tabs');
    toast('Fluxo salvo', { kind: 'success', detail: res.path });
    return true;
  } catch (err) {
    toastError(err, 'Não foi possível salvar');
    return false;
  }
}

const fileSlug = (name) => (name || 'fluxo').normalize('NFKD').replace(/[^\w-]+/g, '_').replace(/^_+|_+$/g, '') || 'fluxo';

async function saveAs() {
  const path = await chooseSaveFile(`${fileSlug(store.workflow.name)}.prodata.json`, dirname(store.filePath));
  return path ? saveToFile(path) : false;
}

async function openFile(path = null) {
  const chosen = path || await chooseOpenFile(dirname(store.filePath || storage(RECENT_FILES, [])[0]?.path));
  if (!chosen) return;
  try {
    const res = await api.openWorkflowFile(chosen);
    await open(res.workflow, { filePath: res.path });
  } catch (err) {
    toastError(err, 'Não foi possível abrir o arquivo');
  }
}

const emptyWorkflow = () => ({
  id: `fluxo_${Date.now().toString(36)}`, name: 'Novo fluxo', description: '', containers: [], nodes: [], edges: [],
});

function newWorkflow() {
  open(emptyWorkflow(), { saved: false, autorun: false });
}

/** Fecha a aba perguntando o que fazer com as alterações (RF-1012). */
async function closeTab(i) {
  if (store.running) {
    toast('Aguarde a execução terminar', { kind: 'info' });
    return false;
  }
  const info = tabInfo(i);
  if (info.dirty) {
    switchTab(i);
    const answer = await askSave(info.name);
    if (answer === 'cancel') return false;
    if (answer === 'save' && !(await save())) return false;
  }
  if (tabCount() > 1) removeTab(i);
  else openTab(emptyWorkflow(), { saved: false }); // a última aba vira um fluxo novo
  // A aba fechada não deve voltar ao reabrir: a lista salva acompanha as abas que restaram.
  persistTabs();
  return true;
}

/** Fechar a janela do desktop com alterações (RF-1013): chamado pelo Python. */
window.prodataConfirmClose = async () => {
  const dirty = dirtyTabs();
  if (!dirty.length) { window.pywebview?.api?.close_app(); return; }
  const answer = await askSave(tabInfo(dirty[0]).name, { many: dirty.length });
  if (answer === 'cancel') return;
  if (answer === 'save') {
    for (const i of dirty) {
      switchTab(i);
      if (!(await save())) return; // falhou: mantém o programa aberto para o usuário resolver
    }
  }
  window.pywebview?.api?.close_app();
};

/** O desktop precisa saber se há algo não salvo antes de fechar a janela. */
function reportDirty() {
  try { window.pywebview?.api?.set_dirty(anyDirty()); } catch { /* ponte ainda não pronta */ }
}

function buildTabs() {
  const bar = $('#wfTabs');
  const draw = () => {
    bar.replaceChildren(
      ...Array.from({ length: tabCount() }, (_, i) => {
        const info = tabInfo(i);
        return h('div', {
          class: ['wf-tab', i === activeIndex() && 'active', info.dirty && 'dirty'], role: 'tab',
          'aria-selected': String(i === activeIndex()), title: info.filePath || `${info.name} · biblioteca do PRO.DATA`,
          onclick: () => {
            if (store.running && i !== activeIndex()) { toast('Aguarde a execução terminar', { kind: 'info' }); return; }
            switchTab(i);
            if (!store.execution && store.workflow.nodes.length) run(null, { auto: true });
          },
          onauxclick: (e) => { if (e.button === 1) closeTab(i); },
        },
        icon(info.filePath ? 'file' : 'workflow', 13),
        h('span', { class: 'wf-tab-name' }, info.name),
        h('span', { class: 'wf-tab-dot', title: 'Alterações não salvas' }),
        h('button', {
          type: 'button', class: 'wf-tab-close', title: 'Fechar aba', 'aria-label': `Fechar ${info.name}`,
          onclick: (e) => { e.stopPropagation(); closeTab(i); },
        }, icon('x', 12)));
      }),
      button({ icon: 'plus', title: 'Novo fluxo em outra aba', size: 'sm', variant: 'ghost', class: 'btn btn-ghost btn-sm btn-icon wf-tab-new', onClick: newWorkflow }));
    reportDirty();
  };
  on('tabs', draw);
  on('dirty', draw);
  on('workflow:changed', draw);
  window.addEventListener('pywebviewready', reportDirty);
}

async function openDialogList() {
  let items;
  try {
    items = await api.workflows();
  } catch (err) {
    toastError(err, 'Não foi possível listar os fluxos');
    return;
  }
  const list = h('div', { class: 'wf-list' });
  const draw = () => list.replaceChildren(...(items.length ? items.map((w) => h('div', { class: ['wf-item', w.id === store.workflow?.id && 'current'] },
    h('button', {
      type: 'button', class: 'wf-main',
      onclick: async () => {
        dlg.close();
        try { await open(await api.workflow(w.id)); } catch (err) { toastError(err, 'Não foi possível abrir'); }
      },
    }, icon('workflow', 16), h('span', { class: 'grow' }, h('strong', {}, w.name), h('small', { class: 'muted' }, ` · ${w.node_count} nós · ${fmt.date(w.modified_at)}`),
      w.description ? h('span', { class: 'wf-desc' }, w.description) : null)),
    button({
      icon: 'trash', title: 'Excluir fluxo', size: 'sm', variant: 'ghost',
      onClick: async () => {
        if (!(await confirmDialog({ title: 'Excluir fluxo', message: `Excluir "${w.name}"?`, confirm: 'Excluir', danger: true }))) return;
        try {
          await api.deleteWorkflow(w.id);
          items = items.filter((x) => x.id !== w.id);
          draw();
        } catch (err) { toastError(err, 'Não foi possível excluir'); }
      },
    }))) : [h('p', { class: 'muted' }, 'Nenhum fluxo salvo.')]));
  draw();
  const recents = storage(RECENT_FILES, []);
  const recentList = recents.length ? h('div', { class: 'stack-xs' },
    h('div', { class: 'panel-subtitle' }, 'Arquivos recentes (fora da biblioteca)'),
    h('div', { class: 'wf-list' }, recents.map((r) => h('div', { class: ['wf-item', r.path === store.filePath && 'current'] },
      h('button', { type: 'button', class: 'wf-main', title: r.path, onclick: () => { dlg.close(); openFile(r.path); } },
        icon('file', 16), h('span', { class: 'grow' }, h('strong', {}, r.name || basename(r.path)),
          h('span', { class: 'wf-desc mono' }, r.path))),
      button({
        icon: 'x', title: 'Remover da lista (não apaga o arquivo)', size: 'sm', variant: 'ghost',
        onClick: (e) => { persist(RECENT_FILES, storage(RECENT_FILES, []).filter((x) => x.path !== r.path)); e.currentTarget.closest('.wf-item').remove(); },
      }))))) : null;
  const dlg = openDialog({
    title: 'Abrir fluxo',
    body: h('div', { class: 'stack-sm' }, h('p', { class: 'muted small' }, 'O fluxo abre numa nova aba.'),
      h('div', { class: 'panel-subtitle' }, 'Biblioteca do PRO.DATA'), list, recentList),
    actions: [
      button({ label: 'Abrir arquivo…', icon: 'folder', onClick: () => { dlg.close(); openFile(); } }),
      button({ label: 'Fluxo de demonstração', icon: 'refresh', onClick: async () => {
        dlg.close();
        await open(await api.demoWorkflow(), { saved: false });
      } }),
      button({ label: 'Novo fluxo', icon: 'file-plus', variant: 'primary', onClick: () => { dlg.close(); newWorkflow(); } }),
    ],
  });
}

const SHORTCUTS = [
  ['Ctrl + Enter', 'Executar o fluxo'], ['Ctrl + Shift + Enter', 'Executar até o nó selecionado'],
  ['Ctrl + S', 'Salvar'], ['Ctrl + Shift + S', 'Salvar como (escolher pasta)'], ['Ctrl + O', 'Abrir fluxo'],
  ['Ctrl + Z / Ctrl + Shift + Z', 'Desfazer / refazer'],
  ['Ctrl + C / Ctrl + X / Ctrl + V', 'Copiar / recortar / colar caixa ou etapa'],
  ['Ctrl + D', 'Duplicar nó'], ['Delete', 'Excluir nó, conexão ou etapa selecionada'], ['G', 'Nova etapa (contêiner)'], ['F', 'Ajustar à tela'],
  ['Shift + clique / Ctrl + clique', 'Adicionar ou tirar caixa da seleção'],
  ['Shift + arrastar no vazio', 'Selecionar várias caixas com um retângulo'], ['Ctrl + A', 'Selecionar todas'],
  ['+ / −', 'Zoom'], ['Duplo clique no canvas', 'Adicionar ferramenta'],
  ['Esc', 'Limpar seleção'],
];

function shortcutsDialog() {
  openDialog({
    title: 'Atalhos de teclado',
    size: 'sm',
    body: h('dl', { class: 'shortcuts' }, SHORTCUTS.map(([k, v]) => h('div', {}, h('dt', {}, k.split(' / ').map((part, i) => [i ? ' / ' : '',
      part.split(' + ').map((key, j) => [j ? '+' : '', h('kbd', {}, key)])])), h('dd', {}, v)))),
  });
}

// ------------------------------------------------------------------ chrome

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function resolvedTheme() {
  return document.documentElement.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}

function setView(view) {
  store.view = view;
  document.body.dataset.view = view;
  for (const b of document.querySelectorAll('#viewSwitch .segment')) b.setAttribute('aria-selected', String(b.dataset.view === view));
  if (view === 'dashboard') renderDashboard();
  else renderCanvas();
}

function buildTopbar() {
  const name = $('#wfName');
  name.addEventListener('input', () => mutate((wf) => { wf.name = name.value; }, { key: 'wf:name' }));
  on('workflow:loaded', () => { name.value = store.workflow.name; });
  const showFile = () => {
    name.title = store.filePath ? `Arquivo: ${store.filePath}` : 'Biblioteca do PRO.DATA';
    $('#fileBadge').hidden = !store.filePath;
    $('#fileBadge').textContent = store.filePath ? basename(store.filePath) : '';
    $('#fileBadge').title = store.filePath || '';
  };
  on('workflow:loaded', showFile);
  on('file', showFile);
  on('workflow:changed', () => { if (document.activeElement !== name) name.value = store.workflow.name; });
  on('dirty', (dirty) => { $('#dirtyBadge').hidden = !dirty; });

  $('#viewSwitch').addEventListener('click', (e) => {
    const b = e.target.closest('.segment');
    if (b) setView(b.dataset.view);
  });

  const runBtn = button({ icon: 'play', label: 'Executar', variant: 'primary', title: 'Executar fluxo (Ctrl+Enter)', onClick: () => run() });
  const themeBtn = button({ icon: resolvedTheme() === 'dark' ? 'sun' : 'moon', title: 'Alternar tema', variant: 'ghost', onClick: () => {
    const next = resolvedTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    persist('prodata.theme', next);
    themeBtn.replaceChildren(icon(next === 'dark' ? 'sun' : 'moon', 16));
    if (store.view === 'dashboard') renderDashboard();
  } });
  $('#topActions').replaceChildren(
    button({ icon: 'file-plus', title: 'Novo fluxo', variant: 'ghost', onClick: newWorkflow }),
    button({ icon: 'folder', title: 'Abrir fluxo (Ctrl+O)', variant: 'ghost', onClick: openDialogList }),
    button({ icon: 'save', title: 'Salvar (Ctrl+S)', variant: 'ghost', onClick: save }),
    button({
      icon: 'chevron-down', title: 'Mais opções de salvar e abrir', variant: 'ghost', class: 'btn btn-ghost btn-icon btn-caret',
      onClick: (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        showMenu(r.left, r.bottom + 4, [
          { label: 'Salvar', icon: 'save', shortcut: 'Ctrl+S', onSelect: save },
          { label: 'Salvar como…', icon: 'directory', shortcut: 'Ctrl+Shift+S', onSelect: saveAs },
          'separator',
          { label: 'Abrir da biblioteca…', icon: 'folder', shortcut: 'Ctrl+O', onSelect: openDialogList },
          { label: 'Abrir arquivo…', icon: 'file', onSelect: () => openFile() },
        ]);
      },
    }),
    button({ icon: 'panel', title: 'Painéis: mostrar, ocultar e restaurar', variant: 'ghost', onClick: (e) => openPanelsMenu(e.currentTarget) }),
    button({ icon: 'keyboard', title: 'Atalhos (?)', variant: 'ghost', onClick: shortcutsDialog }),
    themeBtn,
    runBtn,
  );
  on('running', () => {
    runBtn.disabled = store.running;
    runBtn.classList.toggle('busy', store.running);
    runBtn.querySelector('span').textContent = store.running ? 'Executando…' : 'Executar';
  });
}

function buildStatusbar() {
  const left = h('div', { class: 'status-left' });
  const zoom = h('span', {});
  const right = h('div', { class: 'status-right' }, zoom, h('span', {}, `v${store.catalog.version}`));
  $('#statusbar').replaceChildren(left, right);
  const draw = () => {
    const ex = store.execution;
    const results = Object.values(ex?.node_results || {});
    const errors = results.filter((r) => r.status === 'error').length;
    const stale = store.pending.size > 0 && ex && !store.running;
    const skipped = ex ? heldBy().size : 0;
    left.replaceChildren(...[
      h('span', { class: ['status-dot', store.running ? 'busy' : errors ? 'error' : ex ? 'ok' : ''] }),
      store.running ? 'Executando…'
        : ex ? `${results.length} nós · ${fmt.ms(ex.total_elapsed_ms)}${errors ? ` · ${errors} com erro` : ''}` : 'Pronto',
      stale ? h('span', { class: 'muted' }, `· ${store.pending.size} alterado(s) desde a execução`) : null,
      skipped && !store.running ? h('span', { class: 'status-held', title: 'Caixas antes de um ponto de cache: não precisaram executar' },
        `· ${skipped} pulada(s) pelo cache`) : null,
    ].filter(Boolean));
  };
  on('running', draw);
  on('execution', draw);
  on('workflow:changed', draw);
  on('workflow:loaded', draw);
  on('zoom', (z) => { zoom.textContent = `${Math.round(z * 100)}%`; });
  zoom.textContent = `${Math.round(currentZoom() * 100)}%`;
  draw();
}

function buildCanvasToolbar() {
  const undoBtn = button({ icon: 'undo', title: 'Desfazer (Ctrl+Z)', variant: 'ghost', onClick: undo });
  const redoBtn = button({ icon: 'redo', title: 'Refazer (Ctrl+Shift+Z)', variant: 'ghost', onClick: redo });
  const sync = () => { undoBtn.disabled = !canUndo(); redoBtn.disabled = !canRedo(); };
  on('workflow:changed', sync);
  on('workflow:loaded', sync);
  sync();
  $('#canvasToolbar').replaceChildren(
    undoBtn, redoBtn, h('div', { class: 'divider-v' }),
    button({ icon: 'zoom-out', title: 'Diminuir zoom (−)', variant: 'ghost', onClick: () => zoomBy(1 / 1.2) }),
    button({ icon: 'zoom-in', title: 'Aumentar zoom (+)', variant: 'ghost', onClick: () => zoomBy(1.2) }),
    button({ icon: 'fit', title: 'Ajustar à tela (F)', variant: 'ghost', onClick: fitView }),
    h('div', { class: 'divider-v' }),
    button({ icon: 'group', label: 'Etapa', title: 'Nova etapa / contêiner (G)', variant: 'ghost', onClick: addContainerAtCenter }),
  );
}

/** Painel esquerdo: Ferramentas, Dados e Configurar (abre sozinho ao selecionar um nó). */
function buildLeftPanel() {
  const panes = {
    tools: h('div', { class: 'panel-pane', role: 'tabpanel' }),
    data: h('div', { class: 'panel-pane', role: 'tabpanel', hidden: true }),
    config: h('div', { class: 'panel-pane', role: 'tabpanel', hidden: true }),
  };
  const show = (id) => {
    for (const t of tabs.querySelectorAll('.tab')) t.setAttribute('aria-selected', String(t.dataset.tab === id));
    for (const [key, pane] of Object.entries(panes)) pane.hidden = key !== id;
  };
  const tabs = h('div', { class: 'tabs full', role: 'tablist' },
    [['tools', 'Ferramentas'], ['data', 'Dados'], ['config', 'Configurar']].map(([id, label]) => h('button', {
      type: 'button', role: 'tab', class: 'tab', dataset: { tab: id }, 'aria-selected': String(id === 'tools'),
      onclick: () => show(id),
    }, label)));
  tabs.append(panelControls('explorer'));
  $('#leftPanel').replaceChildren(tabs, ...Object.values(panes));
  renderPalette(panes.tools);
  renderDatasetsPanel(panes.data);
  renderQueriesSection(panes.data);
  renderConnectionsSection(panes.data);
  initInspector(panes.config, { runTo: (id) => run(id), run: () => run(), refreshCache });
  on('selection', () => { if (store.selection.nodeId || store.selection.containerId || selectedIds().length > 1) show('config'); });
}

/** Alças de redimensionamento persistidas em CSS custom properties. */
function setupResizers() {
  const rootStyle = document.documentElement.style;
  const sizes = storage('prodata.layout.v2', { left: 300, right: 460, dock: 280 });
  // Cada tamanho vale para a janela em que foi escolhido (vw × vh; o padrão foi pensado para 1600 × 900).
  // Numa janela menor, os painéis encolhem na mesma proporção e o canvas não fica espremido (spec 016);
  // a preferência salva não muda e volta inteira numa tela maior.
  const fitted = () => {
    const kw = Math.min(1, innerWidth / (sizes.vw || 1600));
    const kh = Math.min(1, innerHeight / (sizes.vh || 900));
    return {
      left: Math.max(220, Math.round(sizes.left * kw)),
      right: Math.max(260, Math.round(sizes.right * kw)),
      dock: Math.max(130, Math.round(sizes.dock * kh)),
    };
  };
  const apply = () => {
    const s = fitted();
    rootStyle.setProperty('--left-w', `${s.left}px`);
    rootStyle.setProperty('--right-w', `${s.right}px`);
    rootStyle.setProperty('--dock-h', `${s.dock}px`);
  };
  apply();
  window.addEventListener('resize', debounce(apply, 80));
  for (const handle of document.querySelectorAll('[data-resize]')) {
    handle.addEventListener('pointerdown', (e) => {
      const key = handle.dataset.resize;
      // Arrastar parte do tamanho que está na tela e passa a valer para a janela atual.
      Object.assign(sizes, fitted(), { vw: innerWidth, vh: innerHeight });
      const start = { x: e.clientX, y: e.clientY, value: sizes[key] };
      handle.setPointerCapture(e.pointerId);
      document.body.classList.add('resizing');
      const move = (ev) => {
        const limits = { left: [260, 480], right: [320, 900], dock: [140, innerHeight - 260] }[key];
        const delta = key === 'left' ? ev.clientX - start.x : key === 'right' ? start.x - ev.clientX : start.y - ev.clientY;
        sizes[key] = Math.min(limits[1], Math.max(limits[0], start.value + delta));
        apply();
      };
      const up = () => {
        handle.removeEventListener('pointermove', move);
        document.body.classList.remove('resizing');
        persist('prodata.layout.v2', sizes);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up, { once: true });
    });
  }
}

function setupShortcuts() {
  window.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const key = e.key.toLowerCase();
    if (mod && key === 'enter') { e.preventDefault(); run(e.shiftKey ? store.selection.nodeId : null); return; }
    if (mod && key === 's') { e.preventDefault(); if (e.shiftKey) saveAs(); else save(); return; }
    if (mod && key === 'o') { e.preventDefault(); openDialogList(); return; }
    if (isTyping(e.target) || document.querySelector('dialog[open]')) return;
    // No dashboard, as teclas mexem no layout (spec 014); atalhos do fluxo (Delete, Ctrl+D...) não valem.
    if (store.view === 'dashboard') {
      if (handleDashboardKey(e)) { e.preventDefault(); return; }
      if (!(mod && (key === 'z' || key === 'y'))) return;
    }
    if (mod && key === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && key === 'y') { e.preventDefault(); redo(); return; }
    if (mod && key === 'a' && store.view === 'designer') { e.preventDefault(); selectMany(store.workflow.nodes.map((n) => n.id)); return; }
    if (mod && key === 'd' && store.selection.nodeId) { e.preventDefault(); duplicateNode(store.selection.nodeId); return; }
    // Copiar/colar caixas só no Designer e quando não há texto selecionado (ex.: células da tabela).
    const textSelected = Boolean(window.getSelection()?.toString());
    if (mod && store.view === 'designer' && !textSelected) {
      if (key === 'c' && copySelection({ nodeWidth: NODE_W })) { e.preventDefault(); return; }
      if (key === 'x' && cutSelection({ nodeWidth: NODE_W })) { e.preventDefault(); return; }
      if (key === 'v') { e.preventDefault(); paste(pointerWorld()); return; }
    }
    if (mod) return;
    if (key === 'delete' || key === 'backspace') {
      if (selectedIds().length) removeNodes(selectedIds());
      else if (store.selection.edgeId) removeEdge(store.selection.edgeId);
      else if (store.selection.containerId) removeContainer(store.selection.containerId);
    } else if (key === 'g' && store.view === 'designer') addContainerAtCenter();
    else if (key === 'f' && store.view === 'designer') fitView();
    else if (key === '+' || key === '=') zoomBy(1.2);
    else if (key === '-') zoomBy(1 / 1.2);
    else if (key === '?') shortcutsDialog();
    else if (key === 'escape') select(null);
  });
  window.addEventListener('beforeunload', (e) => {
    if (anyDirty()) e.preventDefault();
  });
}

// ------------------------------------------------------------------ bootstrap

async function boot() {
  applyTheme(storage('prodata.theme', null));
  try {
    store.catalog = await api.catalog();
  } catch (err) {
    document.body.replaceChildren(h('div', { class: 'empty big' }, icon('alert', 28),
      h('strong', {}, 'Não foi possível conectar ao servidor'), h('span', {}, err.message)));
    return;
  }
  store.tools = Object.fromEntries(store.catalog.tools.map((t) => [t.type, t]));

  setupResizers();
  initLayout();
  buildTopbar();
  buildCanvasToolbar();
  buildStatusbar();
  initCanvas($('#canvas'), { runTo: (id) => run(id), run: () => run(), refreshCache });
  enableFileDropOnCanvas($('#canvas'));
  buildLeftPanel();
  initResults($('#results'));
  initInsights($('#insights'), { openDashboard: () => setView('dashboard') });
  initDashboard($('#dashboard'), { run: () => run(), showDesigner: () => setView('designer') });
  setupShortcuts();
  setView('designer');

  await Promise.all([
    refreshDatasets().catch((err) => toastError(err, 'Não foi possível listar os datasets')),
    refreshConnections().catch((err) => toastError(err, 'Não foi possível listar as conexões')),
    refreshQueries().catch((err) => toastError(err, 'Não foi possível listar as consultas')),
  ]);

  await restoreTabs();
  buildTabs();
  emit('tabs');
  if (store.workflow.nodes.length) await run(null, { auto: true });
  if (!store.inspect.nodeId && store.workflow.nodes.length) inspect(store.workflow.nodes[0].id);
}

/** Reabre as abas da sessão anterior (RF-1004); sem nenhuma, o último fluxo ou a demonstração. */
async function restoreTabs() {
  const saved = savedTabs();
  const items = saved?.items || [{ kind: 'library', id: storage(LAST_WORKFLOW, 'demo_pipeline_360') }];
  let activeTab = 0;
  for (const [i, item] of items.entries()) {
    try {
      if (item.kind === 'file') {
        const res = await api.openWorkflowFile(item.path);
        await open(res.workflow, { filePath: res.path, autorun: false });
      } else {
        await open(await api.workflow(item.id), { autorun: false });
      }
      if (i === saved?.active) activeTab = tabCount() - 1;
    } catch {
      /* arquivo movido ou fluxo excluído desde a última sessão: a aba não volta */
    }
  }
  if (!tabCount()) await open(await api.demoWorkflow(), { saved: false, autorun: false });
  switchTab(Math.min(activeTab, tabCount() - 1));
  persistTabs();
}

boot();
