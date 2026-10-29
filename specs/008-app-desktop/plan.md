# Plano 008

## Execução (`src/prodata/desktop.py`)

1. Define `PRODATA_STORAGE_DIR` = `%LOCALAPPDATA%\PRO.DATA` se não definido.
2. Escolhe porta livre (`socket.bind(("127.0.0.1", 0))`).
3. `uvicorn.Server` numa thread (sem reload, sem sinais), `create_app` com CORS
   para a origem local.
4. Espera `/api/health` (timeout 30 s).
5. `webview.create_window(...)` + `webview.start()` (bloqueia até fechar).
6. `server.should_exit = True` e espera a thread.
7. Exceções → log em arquivo + `MessageBoxW` (ctypes).

## Empacotamento (`packaging/`)

| Arquivo | Papel |
|---------|-------|
| `prodata.spec` | PyInstaller: pasta única, `console=False`, ícone, dados `prodata/web`, coleta de `sklearn`, `polars`, `duckdb`, `pyarrow`, `fastexcel`, `connectorx`, `webview`, backends do `keyring`, `uvicorn` |
| `make_icon.py` | gera `prodata.ico` (16–256 px) a partir da marca, com Pillow |
| `installer.iss` | Inno Setup: instalação por usuário, atalhos, desinstalador, preserva dados |
| `build.py` | orquestra ícone → PyInstaller → zip → Inno Setup (se `ISCC.exe` existir) |

Dependências só de build ficam no grupo `build` do `pyproject.toml`
(`pyinstaller`, `pillow`); `pywebview` é dependência opcional `desktop`.
