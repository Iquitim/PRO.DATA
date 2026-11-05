# Spec 023 — Versão 0.5.7: API com e sem parâmetro

Status: Implementada · Criada: 2026-11-05 · Versão alvo: 0.5.7

## Contexto (o que foi verificado no código)

Relato de uso da 0.5.6: há dois tipos de API, e a tela não os diferencia; na caixa do API Loop, não há onde configurar de onde vêm os estados usados na busca.

| Ponto | Situação encontrada |
|-------|---------------------|
| Vínculo do parâmetro | Implícito: `{sigla}` só funciona se a tabela tiver uma coluna com exatamente esse nome. Não há campo na caixa, e uma coluna `uf` não pode ser usada sem renomear. |
| Tipos de API | Lista única na aba Dados. Só um ícone e um aviso discreto no cadastro indicam o tipo. |
| Vocabulário | A tela chama de `{coluna}` o que para a API é um parâmetro. |

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-2301 | O API Loop mostra uma linha por parâmetro da API escolhida, com uma lista das colunas da tabela de entrada: `{sigla}` ← coluna. |
| RF-2302 | Sem escolha, vale a coluna de mesmo nome, como nos fluxos já salvos. Sem coluna de mesmo nome, a caixa pede a escolha, e a execução explica o que falta antes de fazer qualquer chamada. |
| RF-2303 | A coluna escolhida define as chamadas, a junção com as respostas e as linhas da saída E. O nome da coluna não muda. |
| RF-2304 | A aba Dados separa as APIs em **Chamada direta** (viram tabela no Input Data) e **Com parâmetro** (entram como API Loop), e mostra o que cada uma pede. |
| RF-2305 | O cadastro diz, enquanto se digita, de que tipo é a API, o que isso significa e como passar de um tipo ao outro. Os exemplos indicam o tipo. |
| RF-2306 | O esquema "Como funciona" do API Loop mostra o vínculo entre parâmetro e coluna. A tela passa a dizer `{parâmetro}` em vez de `{coluna}`. |

## Critérios de aceite

- Uma coluna `uf` alimenta `{sigla}`, com as colunas de origem preservadas na saída (teste).
- Fluxos salvos sem o vínculo continuam iguais (teste).
- Coluna inexistente ou não escolhida: erro claro, sem nenhuma chamada (teste).
- Na tela, escolher a coluna muda as chamadas do esquema e o resultado da execução (teste no navegador, com o IBGE).

## Fora de escopo

Valor fixo digitado na caixa para um parâmetro: quem precisar pode usar um Text Input com uma linha, ligado ao API Loop.
