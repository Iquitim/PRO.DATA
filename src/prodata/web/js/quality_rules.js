// Data Quality (spec 028, RF-2832..2838): as regras e as contas que o esquema "Como funciona" usa na amostra.
// O motor é quem decide de verdade; aqui as contas só ilustram, como nos outros esquemas.

export const RULES = [
  { kind: 'not_empty', name: 'Não vazio', icon: 'edit', pass: '"Ana"', fail: 'vazio ou só espaços' },
  { kind: 'unique', name: 'Sem duplicados', icon: 'copy', pass: 'cada id uma vez', fail: 'o mesmo id duas vezes' },
  { kind: 'cpf', name: 'CPF válido', icon: 'fingerprint', pass: '529.982.247-25', fail: '111.111.111-11' },
  { kind: 'cnpj', name: 'CNPJ válido', icon: 'server', pass: '11.222.333/0001-81', fail: '11.222.333/0001-80' },
  { kind: 'email', name: 'E-mail válido', icon: 'globe', pass: 'ana@empresa.com', fail: 'ana@empresa' },
  { kind: 'number_range', name: 'Número na faixa', icon: 'hash', pass: '35 (de 0 a 120)', fail: '-4' },
  { kind: 'date', name: 'Data válida', icon: 'clock', pass: '12/03/2025', fail: '31/02/2025' },
  { kind: 'allowed', name: 'Valor permitido', icon: 'list', pass: 'SP, da lista', fail: 'XX' },
  { kind: 'formula', name: 'Fórmula livre', icon: 'function', pass: 'a sua regra', fail: 'opcional' },
];

export const ruleOf = (kind) => RULES.find((r) => r.kind === kind) || RULES[0];

const NUMBERS = ['Int64', 'Float64'];
/** Que colunas cada regra aceita: número só para números, data para datas e textos com data. */
export function fits(kind, type) {
  if (kind === 'number_range') return NUMBERS.includes(type);
  if (kind === 'date') return ['Date', 'Datetime', 'String'].includes(type);
  return true;
}

const digits = (s) => String(s).replace(/\D/g, '');
const filled = (v) => v !== null && v !== undefined && String(v).trim() !== '';

export function validCpf(text) {
  const d = digits(text);
  if (d.length !== 11 || new Set(d).size === 1 || /[^\d.\-\s]/.test(String(text))) return false;
  for (const size of [9, 10]) {
    let total = 0;
    for (let i = 0; i < size; i++) total += Number(d[i]) * (size + 1 - i);
    if (((total * 10) % 11) % 10 !== Number(d[size])) return false;
  }
  return true;
}

export function validCnpj(text) {
  const raw = String(text).trim().toUpperCase().replace(/[.\-/\s]/g, '');
  if (!/^[A-Z0-9]{12}\d{2}$/.test(raw) || new Set(raw).size === 1) return false;
  const values = [...raw].map((c) => c.charCodeAt(0) - 48);
  for (const size of [12, 13]) {
    const weights = size === 12 ? [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] : [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const rest = weights.reduce((acc, w, i) => acc + values[i] * w, 0) % 11;
    if ((rest < 2 ? 0 : 11 - rest) !== values[size]) return false;
  }
  return true;
}

function asDate(v) {
  if (!filled(v)) return null;
  const s = String(v).trim();
  const br = s.match(/^(\d{2})[/-](\d{2})[/-](\d{4})$/);
  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  const [y, m, d] = br ? [br[3], br[2], br[1]] : iso ? [iso[1], iso[2], iso[3]] : [];
  if (!y) return null;
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
  return date.getUTCDate() === Number(d) && date.getUTCMonth() === Number(m) - 1 ? date.toISOString().slice(0, 10) : null;
}

/** Para cada linha da amostra, as regras que ela reprova. A fórmula livre só o motor sabe: fica de fora. */
export function sampleFailures(rows, rules) {
  const today = new Date().toISOString().slice(0, 10);
  return rows.map((row, i) => rules.map((rule) => {
    const v = row[rule.column];
    switch (rule.kind) {
      case 'not_empty': return !filled(v);
      case 'unique': {
        const key = (r) => JSON.stringify([rule.column, ...(rule.also || [])].map((c) => r[c]));
        return rows.some((other, j) => j !== i && key(other) === key(row));
      }
      case 'cpf': return filled(v) && !validCpf(v);
      case 'cnpj': return filled(v) && !validCnpj(v);
      case 'email': return filled(v) && !/^[^@\s]+@[^@\s]+\.[^@\s.]+$/.test(String(v).trim());
      case 'number_range': return typeof v === 'number' && ((rule.min !== null && rule.min !== undefined && v < rule.min) || (rule.max !== null && rule.max !== undefined && v > rule.max));
      case 'date': {
        const d = asDate(v);
        if (filled(v) && !d) return true;
        return Boolean(d && ((rule.date_min && d < rule.date_min) || (rule.date_max && d > rule.date_max) || (rule.not_future && d > today)));
      }
      case 'allowed': {
        if (rule.values_from === 'table') return false; // a lista da entrada L é conferida ao executar
        const norm = (x) => (rule.ignore_case ? String(x).trim().toLowerCase() : String(x).trim());
        return filled(v) && !(rule.values || []).map(norm).includes(norm(v));
      }
      default: return false;
    }
  }));
}
