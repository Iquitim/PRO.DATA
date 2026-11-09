// Manual (spec 029, RF-2985 e RF-2988): o que "Mostrar onde fica" acende e qual capítulo combina com cada tela.
// Um teste confere que cada marcação do guia existe aqui e que cada alvo existe na tela (RF-2989).

export const TARGETS = {
  executar: { sel: '#topActions .btn-primary', tip: 'Roda o fluxo. Atalho: Ctrl+Enter' },
  tema: { sel: "#topActions button[title^='Alternar tema']", tip: 'Troca entre o tema claro e o escuro' },
  exibir: { sel: '.top-menu', text: 'Exibir', tip: 'Mostrar e esconder painéis' },
  vista_dados: { sel: '#viewSwitch .segment[data-view=data]', tip: 'Todas as fontes, para todos os fluxos' },
  vista_sql: { sel: '#viewSwitch .segment[data-view=sql]', tip: 'O código SQL do fluxo' },
  tab_ferramentas: { view: 'designer', panel: 'explorer', sel: '#leftPanel .tab[data-tab=tools]', tip: 'Todas as ferramentas, para arrastar ao canvas' },
  tab_fontes: { view: 'designer', panel: 'explorer', sel: '#leftPanel .tab[data-tab=data]', tip: 'Suas fontes, para arrastar ao canvas' },
  tab_configurar: { view: 'designer', panel: 'explorer', sel: '#leftPanel .tab[data-tab=config]', tip: 'A configuração da caixa selecionada' },
  aba_resultado: { view: 'designer', panel: 'results', sel: '#results .tab[data-tab=data]', tip: 'A tabela da caixa selecionada' },
  filtros_resultado: { view: 'designer', panel: 'results', sel: '#results button', text: 'Filtros', tip: 'Filtra a tabela sem mudar o fluxo' },
  constantes: { view: 'designer', sel: '#canvasToolbar button', text: 'Constantes', tip: 'As constantes do fluxo ficam aqui' },
  etapa: { view: 'designer', sel: '#canvasToolbar button', text: 'Etapa', tip: 'Cria uma etapa. Atalho: G' },
  foco: { view: 'designer', sel: '.canvas-focus', tip: 'Só o fluxo na tela. Atalho: F11' },
  adicionar_fonte: { view: 'data', sel: '.data-view button', text: 'Adicionar', tip: 'Arquivo, banco, API ou constante' },
  editar_layout: { view: 'dashboard', sel: '.dash-actions button', text: 'Editar layout', tip: 'Mover, redimensionar e formatar' },
  baixar: { view: 'dashboard', sel: '.dash-download', tip: 'Imagem ou HTML' },
  filtros_dash: { view: 'dashboard', sel: '.dash-filters button', text: 'Adicionar filtro', tip: 'Filtros da página' },
};

/** Capítulo sugerido, pelo título. A tela e a caixa selecionada decidem; um teste confere que os títulos existem. */
export const CONTEXT = {
  views: { data: 'Trazendo dados', dashboard: 'Montando o dashboard', sql: 'Levando a lógica para o banco' },
  tools: {
    'prep.data_quality': 'Dados que dá para confiar',
    'io.api_loop': 'Dados de APIs, sem programar',
    'io.input_data': 'Trazendo dados',
    'transform.period_state': 'Dados do Jira, sem escrever JQL',
    'bi.chart': 'Indicadores e visuais',
    'bi.kpi_card': 'Indicadores e visuais',
    'bi.venn': 'Indicadores e visuais',
  },
  selected: 'Montando o fluxo',
  idle: 'Conhecendo a tela',
};
