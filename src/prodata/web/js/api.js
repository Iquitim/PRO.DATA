// Cliente da API REST. Erros viram ApiError com a mensagem enviada pelo servidor.

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, url, body) {
  const init = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError('Servidor indisponível. Verifique se o PRO.DATA está em execução.', 0, 'network');
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(describe(data) || `Erro ${res.status}`, res.status, data?.code);
  }
  return data;
}

function describe(data) {
  if (!data) return '';
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  }
  return '';
}

const enc = encodeURIComponent;

export const api = {
  catalog: () => request('GET', '/api/catalog'),

  datasets: () => request('GET', '/api/datasets'),
  previewDataset: (name, options = {}, rows = 100) =>
    request('POST', `/api/datasets/${enc(name)}/preview?rows=${rows}`, options),
  deleteDataset: (name) => request('DELETE', `/api/datasets/${enc(name)}`),
  linkDataset: (path, name = null) => request('POST', '/api/datasets/link', { path, name }),

  /** Upload com progresso (fetch não expõe progresso de envio). */
  uploadDataset(file, { overwrite = false, onProgress } = {}) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append('file', file);
      form.append('overwrite', String(overwrite));
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/datasets');
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        const data = JSON.parse(xhr.responseText || 'null');
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new ApiError(describe(data) || `Erro ${xhr.status}`, xhr.status, data?.code));
      };
      xhr.onerror = () => reject(new ApiError('Falha de rede durante o envio.', 0, 'network'));
      xhr.send(form);
    });
  },

  connections: () => request('GET', '/api/connections'),
  saveConnection: (connection, password) =>
    request('PUT', `/api/connections/${enc(connection.id)}`, { connection, password }),
  deleteConnection: (id) => request('DELETE', `/api/connections/${enc(id)}`),
  testConnection: (id) => request('POST', `/api/connections/${enc(id)}/test`),
  connectionTables: (id) => request('GET', `/api/connections/${enc(id)}/tables`),
  previewConnection: (id, body, rows = 100) => request('POST', `/api/connections/${enc(id)}/preview?rows=${rows}`, body),

  queries: () => request('GET', '/api/queries'),
  saveQuery: (query) => request('PUT', `/api/queries/${enc(query.id)}`, query),
  deleteQuery: (id) => request('DELETE', `/api/queries/${enc(id)}`),
  previewQuery: (definition, rows = 100) => request('POST', `/api/queries/preview?rows=${rows}`, definition),

  saveWorkflowFile: (path, workflow) => request('POST', '/api/files/workflow/save', { path, workflow }),
  openWorkflowFile: (path) => request('POST', '/api/files/workflow/open', { path }),

  refreshCache: (wfId, nodeId) => request('DELETE', `/api/cache/${enc(wfId)}/${enc(nodeId)}`),

  workflows: () => request('GET', '/api/workflows'),
  workflow: (id) => request('GET', `/api/workflows/${enc(id)}`),
  demoWorkflow: () => request('GET', '/api/workflows/demo'),
  saveWorkflow: (wf) => request('PUT', `/api/workflows/${enc(wf.id)}`, wf),
  deleteWorkflow: (id) => request('DELETE', `/api/workflows/${enc(id)}`),

  execute: (workflow, targetNodeId = null, holdExports = false) =>
    request('POST', '/api/execute', { workflow, target_node_id: targetNodeId, hold_exports: holdExports }),
  pendingExports: (workflow, targetNodeId = null) =>
    request('POST', '/api/exports/pending', { workflow, target_node_id: targetNodeId }),
  columnValues: (wfId, nodeId, anchor, column, limit = 500, search = '') =>
    request('GET', `/api/results/${enc(wfId)}/${enc(nodeId)}/${enc(anchor)}/values?${new URLSearchParams({ column, limit, search })}`),
  results: (wfId, nodeId, anchor, params) =>
    request('GET', `/api/results/${enc(wfId)}/${enc(nodeId)}/${enc(anchor)}?${new URLSearchParams(params)}`),
  validateFormula: (expression, columns) => request('POST', '/api/formula/validate', { expression, columns }),

  arrangeDashboard: (body) => request('POST', '/api/dashboard/arrange', body),
  placeDashboard: (body) => request('POST', '/api/dashboard/place', body),
  dashboardFormats: () => request('GET', '/api/dashboard/formats'),
};
