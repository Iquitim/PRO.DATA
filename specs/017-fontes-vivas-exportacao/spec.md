# Spec 017 — Fontes que se atualizam, exportação que pergunta e Venn com colunas grandes

Status: Implementada · Criada: 2026-10-30 · Versão alvo: 0.3.7

## Contexto

1. Venn: escolher como "grupo" uma coluna com milhares de valores (ex.: id do cliente) lista
   tudo, sem aviso.
2. Só o Excel tem opção para quando o arquivo já existe; os demais formatos sobrescrevem sem
   perguntar.
3. Fluxos rodados todo dia sobre fontes que se atualizam:
   - arquivos da aba Dados são **cópias** enviadas ao PRO.DATA: atualizar a planilha original (pasta
     da rede, OneDrive) não muda o que o fluxo lê;
   - o ponto de cache só considera mudanças de configuração: pode servir dados de ontem;
   - consultas de banco já são refeitas a cada execução (sem "reaproveitar resultado").

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-1701 | Venn: com mais de 50 valores distintos na coluna do grupo, aviso de que ela parece um identificador e não um grupo; a lista mostra só os 15 mais frequentes e a busca consulta o servidor (funciona com qualquer número de valores). |
| RF-1702 | Output Data (todos os formatos): "Se o arquivo já existir" = **Perguntar ao executar** (padrão para caixas novas), Substituir, Criar um novo arquivo (data e hora no nome) ou Adicionar/atualizar planilha (só Excel). |
| RF-1703 | Ao executar pelo programa, se alguma caixa em "Perguntar" for gravar num arquivo que já existe, uma janela lista esses arquivos e pergunta, para cada um, substituir, criar novo ou adicionar planilha (Excel), com a opção de lembrar a escolha na caixa. Cancelar não executa. |
| RF-1704 | Sem ninguém para perguntar (execução pela API), "Perguntar" cria um novo arquivo: o PRO.DATA nunca sobrescreve em silêncio. |
| RF-1705 | **Vincular arquivo** na aba Dados: em vez de copiar, guarda o caminho de um arquivo escolhido pelo usuário e lê sempre a versão atual dele. Mostra o caminho, a data da última modificação e avisa se o arquivo sumiu (movido ou renomeado). Remover o vínculo não apaga o arquivo. |
| RF-1706 | A cada execução, uma fonte em arquivo (enviado ou vinculado) que mudou desde a última leitura é relida, e só o que depende dela executa de novo. O Configurar do Input Data mostra quando o arquivo foi modificado. |
| RF-1707 | O ponto de cache é invalidado quando um arquivo de origem antes dele muda (data ou tamanho), além das mudanças de configuração. |
| RF-1708 | O ponto de cache tem "Renovar": só quando algo antes mudar (padrão), também todo dia (o primeiro uso em cada dia relê) ou também a cada hora — para fontes de banco, cujas mudanças não são visíveis sem consultar. |

## Constituição

Emenda 1.4.0 no princípio IV: arquivos de **origem vinculados** escolhidos explicitamente pelo
usuário podem ser lidos fora do diretório de dados — caminho absoluto, arquivo existente no momento
do vínculo, extensão da lista permitida, somente leitura.

## Critérios de aceite

- Vincular um CSV, executar, alterar o CSV no disco e executar de novo: o resultado muda e só as
  caixas que dependem dele executam (teste).
- Ponto de cache depois de uma fonte vinculada: alterar o arquivo invalida o cache (teste).
- Ponto de cache com "todo dia": um instantâneo de ontem não vale hoje (teste).
- Output Data em "Perguntar" com arquivo existente, executado pela API: cria
  `nome AAAA-MM-DD HHhMM.ext` e o original fica intacto (teste).
- Venn com "id_cliente" como grupo: aviso, 15 valores e busca por "CLI-14" encontra os do servidor.
