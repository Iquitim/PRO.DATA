// Data Quality, regra "Valor permitido" (spec 028, RF-2840): a lista digitada, com as etiquetas de como ela
// foi entendida, e o botão que traz os valores que aparecem na coluna para a pessoa só tirar os errados.

import { button, fmt, h } from './dom.js';
import { icon } from './icons.js';

const MAX_BROUGHT = 200;

/**
 * Texto → valores. Uma linha é um valor (como ao colar uma coluna do Excel); tabulação e ponto e vírgula
 * sempre separam; a vírgula separa só quando tudo está numa linha, para "São Paulo, SP" caber numa linha só.
 */
export function parseValues(text) {
  const lines = String(text).split(/\r?\n/);
  const pieces = lines.length > 1 ? lines.flatMap((l) => l.split(/[\t;]/)) : lines[0].split(/[\t;,]/);
  const seen = new Set();
  const values = [];
  const repeated = [];
  for (const raw of pieces) {
    const v = raw.trim();
    if (!v) continue;
    if (seen.has(v)) { if (!repeated.includes(v)) repeated.push(v); continue; }
    seen.add(v);
    values.push(v);
  }
  return { values, repeated };
}

/** Widget `allowed_values`. `rule` é a regra inteira: dela vem a coluna para "Trazer os valores". */
export function allowedValuesField(field, value, set, ctx, id, rule) {
  let current = Array.isArray(value) ? [...value] : [];
  const area = h('textarea', {
    id, class: 'input mono dq-values-input', rows: 5, spellcheck: 'false',
    placeholder: 'SP\nRJ\nMG', 'aria-describedby': `${id}_help`,
  }, current.join('\n'));
  const summary = h('div', { class: 'dq-values-summary', 'aria-live': 'polite' });
  const note = h('p', { class: 'field-help' });

  const draw = (repeated = []) => {
    const commaInLines = area.value.includes('\n') && area.value.includes(',');
    summary.replaceChildren(...[ // replaceChildren() nativo escreveria "null" para os itens ausentes
      h('span', { class: 'dq-values-count' }, current.length
        ? `${fmt.int(current.length)} ${current.length === 1 ? 'valor permitido' : 'valores permitidos'}`
        : 'Nenhum valor ainda'),
      current.length ? h('div', { class: 'chips' }, current.slice(0, 60).map((v) => h('span', { class: 'chip' },
        h('span', { class: 'mono' }, v),
        h('button', { type: 'button', class: 'chip-x', 'aria-label': `Tirar ${v}`, onclick: () => replace(current.filter((x) => x !== v)) },
          icon('x', 12))))) : null,
      current.length > 60 ? h('span', { class: 'muted' }, `e mais ${fmt.int(current.length - 60)}`) : null,
      repeated.length ? h('p', { class: 'field-warn' }, icon('alert', 13), ` Repetido, contou uma vez: ${repeated.join(', ')}`) : null,
      commaInLines ? h('p', { class: 'field-help' }, 'Com um valor por linha, a vírgula fica dentro do valor.') : null,
    ].filter(Boolean)
    );
  };
  const replace = (values) => {
    current = values;
    area.value = values.join('\n');
    set(values);
    draw();
  };
  area.addEventListener('input', () => {
    const parsed = parseValues(area.value);
    current = parsed.values;
    set(current);
    draw(parsed.repeated);
  });

  const bring = rule?.column && ctx.values
    ? button({
      label: `Trazer os valores de [${rule.column}]`, icon: 'download', size: 'sm', variant: 'ghost',
      onClick: () => ctx.values(rule.column, 'in')
        .then((data) => {
          const found = data.values.map((v) => v.value).filter((v) => v !== null && String(v).trim() !== '');
          if (data.distinct > MAX_BROUGHT) {
            note.textContent = `[${rule.column}] tem ${fmt.int(data.distinct)} valores diferentes: é mais fácil usar uma tabela com a lista (entrada L).`;
            return;
          }
          const added = found.filter((v) => !current.includes(v));
          replace([...current, ...added]);
          note.textContent = added.length
            ? `Vieram ${fmt.int(added.length)} valor(es) de [${rule.column}]. Tire os que não valem.`
            : `Todos os valores de [${rule.column}] já estão na lista.`;
        })
        .catch(() => { note.textContent = 'Execute o fluxo para trazer os valores da coluna.'; }),
    })
    : null;
  draw();
  return h('div', { class: 'stack-xs dq-values' },
    area,
    h('p', { class: 'field-help', id: `${id}_help` },
      'Um valor por linha, ou separados por vírgula ou ponto e vírgula. Dá para colar uma coluna do Excel.'),
    summary,
    bring ? h('div', { class: 'row' }, bring) : null,
    note);
}
