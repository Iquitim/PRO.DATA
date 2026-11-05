# Spec 024 — Versão 0.5.8: documentação e anotações da API

Status: Implementada · Criada: 2026-11-05 · Versão alvo: 0.5.8

## Contexto

Dúvida em uso: como saber quais parâmetros fixos existem? Não há lista única: cada API define os seus, e a API não informa o que aceita. A tela só dizia "veja a documentação da API", sem levar a ela e sem lugar para anotar o que cada parâmetro faz. As APIs serão passadas a outras pessoas do time.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-2401 | O cadastro tem o campo opcional **Documentação da API**, com o endereço da página da API, e um botão que abre essa página fora do programa. |
| RF-2402 | A aba Parâmetros explica que os parâmetros são próprios de cada API e oferece abrir a documentação, ou indica onde guardar o link. |
| RF-2403 | Cada parâmetro e cabeçalho tem um campo opcional **Para que serve**, salvo no cadastro. |
| RF-2404 | Link e anotações nunca vão no pedido, e editá-los não invalida resultados guardados nem provoca nova chamada. |
| RF-2405 | Só abrem páginas `http` e `https`, sem credenciais no endereço. Nada de arquivos ou programas. O programa nunca acessa o link sozinho. |
| RF-2406 | Os exemplos prontos vêm com o link e, onde há parâmetro fixo, a explicação dele. As APIs de exemplo já cadastradas recebem isso sem perder o que o usuário alterou, e uma API de exemplo excluída não volta. |

## Critérios de aceite

- Link e anotação ficam salvos e não aparecem no pedido (teste).
- Editar link ou anotação não muda a assinatura da fonte (teste).
- `javascript:`, `file:` e caminhos locais são recusados (teste).
- Botão abre a página certa, no navegador (teste no navegador).

## Fora de escopo

Ler a documentação para listar os parâmetros automaticamente.
