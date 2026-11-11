// Campos da spec 033: escolher o fluxo de um Subflow e um arquivo do computador.

import { api } from './api.js';
import { saveDownload } from './desktop.js';
import { button, fmt, h } from './dom.js';
import { store } from './store.js';
import { confirmDialog, toast, toastError } from './ui.js';

const INTERFACE = ['flow.input', 'flow.output'];

/** Fluxos da biblioteca que podem ser subfluxo. O fluxo aberto fica de fora: ele não pode chamar a si mesmo. */
export function subflowField(field, value, set, _ctx, id) {
  const select = h('select', { id, class: 'input', onchange: (e) => set(e.target.value) },
    h('option', { value: value || '' }, value ? `${value} (carregando…)` : 'Carregando…'));
  const note = h('p', { class: 'field-help' });
  api.workflows().then(async (list) => {
    const others = list.filter((w) => w.id !== store.workflow?.id);
    // Só o resumo vem na lista: abre cada fluxo para saber se ele declara entrada e saída de subfluxo.
    const flows = await Promise.all(others.map((w) => api.workflow(w.id).catch(() => null)));
    const ready = others.filter((w, i) => flows[i]?.nodes.some((n) => INTERFACE.includes(n.type)));
    const known = ready.some((w) => w.id === value);
    select.replaceChildren(
      h('option', { value: '' }, ready.length ? 'Escolha um fluxo' : 'Nenhum fluxo com Subflow Input e Output'),
      ...(value && !known ? [h('option', { value, selected: true }, `${value} (não está na biblioteca daqui)`)] : []),
      ...ready.map((w) => h('option', { value: w.id, selected: w.id === value }, w.name)));
    note.textContent = ready.length
      ? ''
      : 'Num fluxo salvo, ponha as caixas Subflow Input e Subflow Output: ele passa a aparecer aqui.';
  }).catch(() => { note.textContent = 'Não foi possível listar os fluxos da biblioteca.'; });
  return h('div', { class: 'stack-xs' }, select, note);
}

/** Caminho completo de um arquivo. No programa instalado, o botão abre a janela de escolha do Windows. */
export function fileField(field, value, set, ctx, id) {
  const input = h('input', {
    id, class: 'input mono', value: value ?? '', placeholder: field.placeholder || 'Caminho completo do arquivo', spellcheck: false,
    oninput: (e) => set(e.target.value),
  });
  return h('div', { class: 'row' }, input,
    ctx.chooseFile ? button({
      icon: 'file', title: 'Escolher arquivo…',
      onClick: async () => {
        const chosen = await ctx.chooseFile(input.value);
        if (chosen) { input.value = chosen; set(chosen); }
      },
    }) : null,
    value ? button({ icon: 'x', title: 'Tirar', onClick: () => { input.value = ''; set(''); } }) : null);
}

/** Modelo da biblioteca (Model Input): escolher, importar um arquivo .modelo, exportar ou tirar da biblioteca. */
export function modelField(field, value, set, ctx, id) {
  const select = h('select', { id, class: 'input', onchange: (e) => set(e.target.value) }, h('option', { value: value || '' }, value || 'Carregando…'));
  const note = h('p', { class: 'field-help' });
  const picker = h('input', { type: 'file', accept: '.modelo', hidden: true });
  const fill = (list, chosen) => {
    const known = list.some((m) => m.name === chosen);
    select.replaceChildren(
      h('option', { value: '' }, list.length ? 'Escolha um modelo' : 'A biblioteca está vazia'),
      ...(chosen && !known ? [h('option', { value: chosen, selected: true }, `${chosen} (não está na biblioteca daqui)`)] : []),
      ...list.map((m) => h('option', { value: m.name, selected: m.name === chosen }, `${m.name} · prevê ${m.target_column}`)));
    note.textContent = list.length ? '' : 'Num Model Trainer, preencha "Nome na biblioteca de modelos" e execute. Ou importe um arquivo .modelo.';
  };
  const load = (chosen = value) => api.models().then((list) => fill(list, chosen)).catch(() => { note.textContent = 'Não foi possível listar os modelos.'; });
  picker.addEventListener('change', async () => {
    const [file] = picker.files;
    picker.value = '';
    if (!file) return;
    try {
      const saved = await api.importModel(file);
      toast(`Modelo "${saved.name}" importado`, { kind: 'success', detail: `Prevê ${saved.target_column}.` });
      set(saved.name);
      await load(saved.name);
    } catch (err) {
      toastError(err, 'Não foi possível importar o modelo');
    }
  });
  const exportIt = async () => {
    try {
      const { blob, name } = await api.exportModel(select.value);
      const saved = await saveDownload(name, blob);
      if (saved) toast(`Salvo: ${saved}`, { kind: 'success' });
    } catch (err) {
      toastError(err, 'Não foi possível exportar o modelo');
    }
  };
  const remove = async () => {
    const name = select.value;
    if (!(await confirmDialog({ title: 'Tirar da biblioteca', message: `Tirar o modelo "${name}" da biblioteca deste computador? Os fluxos que usam este nome deixam de executar até ele voltar.`, confirm: 'Tirar', danger: true }))) return;
    try {
      await api.deleteModel(name);
      set('');
      await load('');
    } catch (err) {
      toastError(err, 'Não foi possível tirar o modelo');
    }
  };
  load();
  return h('div', { class: 'stack-xs' }, select, picker,
    h('div', { class: 'row' },
      button({ icon: 'upload', label: 'Importar arquivo…', size: 'sm', title: 'Trazer um arquivo .modelo exportado pelo PRO.DATA', onClick: () => picker.click() }),
      button({ icon: 'download', label: 'Exportar', size: 'sm', title: 'Salvar o arquivo .modelo para levar a outro computador', onClick: () => select.value && exportIt() }),
      button({ icon: 'trash', title: 'Tirar da biblioteca', size: 'sm', variant: 'ghost', onClick: () => select.value && remove() })),
    note);
}

/** Nome do modelo na biblioteca (Model Trainer), com o botão que salva o arquivo .modelo depois de treinar. */
export function modelSaveField(field, value, set, _ctx, id) {
  const input = h('input', { id, class: 'input', value: value ?? '', placeholder: field.placeholder || '', oninput: (e) => { set(e.target.value); note.textContent = hint(e.target.value); } });
  const hint = (name) => (name.trim() ? 'Execute a caixa para guardar o modelo com este nome. Depois, o botão salva o arquivo.' : 'Dê um nome para guardar o modelo na biblioteca e poder salvar o arquivo.');
  const note = h('p', { class: 'field-help' }, hint(value || ''));
  const save = async () => {
    const wanted = input.value.trim();
    if (!wanted) { toast('Dê um nome ao modelo e execute a caixa antes de salvar o arquivo.'); return; }
    try {
      // O nome guardado troca espaços por _ : procura pelo que a biblioteca tem de fato.
      const list = await api.models();
      const found = list.find((m) => m.name === wanted || m.name === wanted.replace(/ /g, '_'));
      if (!found) { toast('Este modelo ainda não está na biblioteca', { kind: 'info', detail: 'Execute a caixa: é o treino que guarda o modelo com o nome.' }); return; }
      const { blob, name } = await api.exportModel(found.name);
      const saved = await saveDownload(name, blob);
      if (saved) toast(`Salvo: ${saved}`, { kind: 'success' });
    } catch (err) {
      toastError(err, 'Não foi possível salvar o modelo');
    }
  };
  const remove = async () => {
    const wanted = input.value.trim();
    try {
      const list = await api.models();
      const found = wanted && list.find((m) => m.name === wanted || m.name === wanted.replace(/ /g, '_'));
      if (!found) { toast('Não há modelo com este nome na biblioteca.'); return; }
      const ok = await confirmDialog({
        title: 'Tirar da biblioteca',
        message: `Tirar o modelo "${found.name}" da biblioteca deste computador? As caixas Model Input que usam este nome deixam de executar. O modelo desta caixa continua guardado, e executar de novo com o nome preenchido põe ele de volta.`,
        confirm: 'Tirar', danger: true,
      });
      if (!ok) return;
      await api.deleteModel(found.name);
      toast(`Modelo "${found.name}" saiu da biblioteca`, { kind: 'success' });
    } catch (err) {
      toastError(err, 'Não foi possível tirar o modelo');
    }
  };
  return h('div', { class: 'stack-xs' },
    h('div', { class: 'row' }, input,
      button({ icon: 'download', label: 'Salvar arquivo…', size: 'sm', title: 'Salvar o modelo treinado num arquivo .modelo, para usar em outro computador', onClick: save }),
      button({ icon: 'trash', title: 'Tirar este modelo da biblioteca', size: 'sm', variant: 'ghost', onClick: remove })),
    note);
}

/** Versão do modelo (Model Trainer): o número em uso e a lista das versões guardadas, com usar e apagar. */
export function modelVersionsField(field, value, set, _ctx, id, values) {
  // Em "Treinar sempre", a versão em uso é sempre a mais nova: não há número para escolher.
  const always = values?.training === 'always';
  const nodeId = store.selection.nodeId;
  const input = h('input', { id, class: 'input', type: 'number', min: 1, max: 9999, step: 1, value: Number(value) || 1, hidden: always, onchange: (e) => set(Math.max(1, Math.round(Number(e.target.value) || 1))) });
  const list = h('div', { class: 'model-versions' });
  const quality = (m) => (m.task === 'classification' ? `acurácia ${fmt.number(m.accuracy_pct)}%` : m.r2 !== undefined ? `R² ${fmt.number(m.r2, 3)}` : '');
  const draw = async () => {
    const versions = nodeId ? await api.modelVersions(store.workflow.id, nodeId).catch(() => []) : [];
    if (!versions.length) {
      list.replaceChildren(h('p', { class: 'field-help' }, always ? 'Nenhuma versão guardada ainda: a primeira execução treina e guarda a v1.' : 'Nenhuma versão guardada ainda: a primeira execução treina e guarda esta versão.'));
      return;
    }
    const current = always ? versions[0].version : Number(value) || 1;
    const next = Math.max(current, ...versions.map((v) => v.version)) + 1;
    list.replaceChildren(
      h('div', { class: 'x-title' }, always ? 'Versões guardadas (as 10 últimas)' : 'Versões guardadas'),
      ...versions.map((v) => {
        const using = v.version === current;
        return h('div', { class: ['model-version', using && 'using'] },
          h('b', {}, `v${v.version}`),
          h('span', {}, [v.trained_at ? new Date(v.trained_at).toLocaleDateString('pt-BR') : '', v.rows ? `${fmt.int(v.rows)} linhas` : '', quality(v.metrics)].filter(Boolean).join(' · ')),
          using ? h('span', { class: 'model-version-tag' }, 'em uso')
            : always ? h('span', {}) : button({ label: 'Usar', size: 'sm', title: `Voltar a usar a versão ${v.version}`, onClick: () => set(v.version) }),
          button({
            icon: 'trash', size: 'sm', variant: 'ghost', disabled: using,
            title: using ? 'A versão em uso não pode ser apagada' : `Apagar a versão ${v.version}`,
            onClick: async () => {
              if (!(await confirmDialog({ title: `Apagar a versão ${v.version}`, message: `Apagar o modelo v${v.version} guardado por esta caixa? Não dá para desfazer.`, confirm: 'Apagar', danger: true }))) return;
              try { await api.deleteModelVersion(store.workflow.id, nodeId, v.version, current); await draw(); } catch (err) { toastError(err, 'Não foi possível apagar a versão'); }
            },
          }));
      }),
      always ? h('p', { class: 'field-help' }, 'Cada mudança nos dados treina uma versão nova. A mais nova é a que vale, e ficam guardadas as 10 últimas.')
        : button({ icon: 'plus', label: `Treinar a v${next} com os dados de agora`, size: 'sm', title: 'Muda a Versão; a próxima execução treina e guarda', onClick: () => set(next) }));
  };
  draw();
  return h('div', { class: 'stack-xs' }, input, list);
}
