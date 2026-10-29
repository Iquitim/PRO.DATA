# Distribuição: aplicativo de desktop (Windows)

Ver [spec 008](../specs/008-app-desktop/spec.md).

## Para quem usa

- **Instalador** `PRO.DATA-<versão>-setup.exe`: instala só para o usuário atual
  (sem administrador) em `%LOCALAPPDATA%\Programs\PRO.DATA`, cria atalho no Menu
  Iniciar (e, se marcado, na área de trabalho) e aparece em
  *Configurações → Aplicativos* para desinstalar.
- **Portátil** `PRO.DATA-<versão>-portable.zip`: descompacte e abra
  `PRO.DATA\PRO.DATA.exe`. Nada é instalado.

Nos dois casos os dados do usuário (fluxos, arquivos, conexões, cache, logs)
ficam em `%LOCALAPPDATA%\PRO.DATA` e **sobrevivem** a atualizações e à
desinstalação. Senhas de banco ficam no Gerenciador de Credenciais do Windows.

Requisitos: Windows 10/11 64 bits com o **WebView2 Runtime** (já vem no Windows
11 e nas versões atualizadas do Windows 10).

> Sem assinatura de código, o Windows SmartScreen mostra "Editor desconhecido"
> na primeira execução (*Mais informações → Executar assim mesmo*). Para
> distribuir em empresa, assine o `.exe` e o instalador com um certificado de
> assinatura de código (`signtool sign ...`).

## Para quem gera o build

Pré-requisitos (uma vez):

```powershell
uv sync --extra desktop --group build
winget install JRSoftware.InnoSetup        # só para gerar o instalador
```

Build:

```powershell
uv run python packaging/build.py            # ícone + app + .zip + instalador
uv run python packaging/build.py --no-setup # sem o instalador
```

Saídas em `dist/`. Para testar sem empacotar: `uv run prodata-desktop`.

| Arquivo | Papel |
|---------|-------|
| `src/prodata/desktop.py` | porta livre, servidor em thread, janela WebView2, log e caixa de erro |
| `packaging/prodata.spec` | PyInstaller (pasta única, sem console, metadados e dados embutidos) |
| `packaging/installer.iss` | Inno Setup (por usuário, atalhos, preserva dados) |
| `packaging/make_icon.py` | gera `prodata.ico` |
| `packaging/build.py` | orquestra tudo e mostra os tamanhos |

### Diagnóstico

Log do app: `%LOCALAPPDATA%\PRO.DATA\logs\prodata.log`. Se o app não abrir, ele
mostra uma caixa de mensagem com o motivo e o caminho do log.

Ao adicionar uma dependência que leia a própria versão (`importlib.metadata`) ou
use *entry points*, inclua-a em `copy_metadata` no `prodata.spec`, e **teste o
executável gerado** (não só `uv run prodata-desktop`): o PyInstaller só descobre
alguns desses problemas em tempo de execução.

### Números de referência (build 0.2.0)

| | |
|---|---|
| Instalador | 137 MB |
| Portátil (.zip) | 219 MB |
| App instalado | 600 MB (scikit-learn, Polars, DuckDB, PyArrow, .NET/WebView) |
| Abrir até o fluxo de demonstração executado | ~2,7 s |
| Fechar até o processo terminar | ~2,3 s |
