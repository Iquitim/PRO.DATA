# Spec 008 — Aplicativo de desktop instalável (Windows)

Status: Implementada · Criada: 2026-10-29

## Contexto

Hoje o PRO.DATA exige `uv`, terminal e navegador. Para usuários de negócio ele
precisa ser um programa comum: instalar, clicar no ícone, usar.

## Decisões do usuário

- Abre em **janela própria** (não no navegador).
- Entrega em **instalador .exe** e **pasta portátil .zip**, gerados do mesmo build.

## Requisitos funcionais

| ID | Requisito |
|----|-----------|
| RF-801 | Comando `prodata-desktop`: sobe o servidor numa porta livre de `127.0.0.1`, espera ficar pronto e abre uma janela nativa (WebView2) com título, ícone, tamanho inicial e mínimo. Fechar a janela encerra o servidor. |
| RF-802 | No app de desktop os dados do usuário (datasets, fluxos, cache, exportações, conexões) ficam em `%LOCALAPPDATA%\PRO.DATA`, nunca na pasta do programa. `PRODATA_STORAGE_DIR` continua tendo precedência. |
| RF-803 | Erro ao iniciar (porta, WebView2 ausente, falha no servidor) mostra uma caixa de mensagem com o motivo e grava log em `%LOCALAPPDATA%\PRO.DATA\logs\prodata.log`. |
| RF-804 | Build reprodutível: `uv run python packaging/build.py` gera `dist/PRO.DATA/` (PyInstaller, pasta única), `dist/PRO.DATA-<versão>-portable.zip` e, se o Inno Setup estiver instalado, `dist/PRO.DATA-<versão>-setup.exe`. |
| RF-805 | Instalador: instala por usuário (sem exigir administrador), cria atalhos no Menu Iniciar e (opcional) na área de trabalho, aparece em "Aplicativos" com desinstalador, e não apaga os dados do usuário ao desinstalar. |
| RF-806 | O app empacotado funciona offline (fontes e recursos embutidos) e não abre console. |

## Critérios de aceite

- Em uma máquina sem Python, o `.exe` abre a janela com o fluxo de demonstração
  executado.
- Fechar a janela não deixa processo do PRO.DATA rodando.
- Desinstalar remove o programa e mantém `%LOCALAPPDATA%\PRO.DATA`.

## Fora do escopo

- Assinatura de código (exige certificado pago); sem ela o Windows SmartScreen
  avisa "editor desconhecido" na primeira execução.
- Atualização automática e builds para macOS/Linux.
