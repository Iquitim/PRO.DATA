"""Aplicativo de desktop: servidor local + janela nativa (WebView2 no Windows). Ver spec 008.

``prodata-desktop`` (ou o executável empacotado) sobe o servidor numa porta livre de
127.0.0.1, abre a janela e encerra tudo quando a janela é fechada.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

APP_NAME = "PRO.DATA"
log = logging.getLogger("prodata.desktop")


def user_data_dir() -> Path:
    """Dados do usuário fora da pasta do programa (RF-802)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def _setup_logging(data_dir: Path) -> Path:
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_file = logs / "prodata.log"
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # Executável sem console: stdout/stderr são None e quebrariam bibliotecas que escrevem neles.
    if sys.stdout is None:
        sys.stdout = Path(os.devnull).open("w", encoding="utf-8")  # noqa: SIM115 (vive até o fim do processo)
    if sys.stderr is None:
        sys.stderr = Path(os.devnull).open("w", encoding="utf-8")  # noqa: SIM115
    return log_file


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_ready(url: str, server_thread: threading.Thread, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not server_thread.is_alive():
            raise RuntimeError("O servidor interno parou durante a inicialização. Veja o log.")
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as res:
                if res.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"O servidor interno não respondeu em {timeout:.0f} s.")


def _error_box(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)  # MB_ICONERROR
    else:
        print(message, file=sys.stderr)


class DesktopApi:
    """Funções nativas expostas à página como ``window.pywebview.api`` (spec 009).

    Só diálogos do Windows e "mostrar no Explorer": a página nunca recebe acesso livre ao disco.
    """

    def __init__(self) -> None:
        # Atributos privados: o pywebview expõe à página tudo o que é público.
        self._window: Any = None
        self._dirty = False
        self._force_close = False

    def _dialog(self, kind: Any, **kwargs: Any) -> str | None:
        result = self._window.create_file_dialog(kind, **kwargs)
        if not result:
            return None
        return str(result if isinstance(result, str) else result[0])

    def choose_folder(self, start: str = "") -> str | None:
        import webview

        return self._dialog(webview.FileDialog.FOLDER, directory=start if Path(start).is_dir() else "")

    def save_file(self, suggested: str = "fluxo.prodata.json", start: str = "") -> str | None:
        import webview

        return self._dialog(
            webview.FileDialog.SAVE,
            directory=start if Path(start).is_dir() else "",
            save_filename=suggested,
            file_types=(_WORKFLOW_FILTER,),
        )

    def open_file(self, start: str = "") -> str | None:
        import webview

        return self._dialog(
            webview.FileDialog.OPEN,
            directory=start if Path(start).is_dir() else "",
            file_types=(_WORKFLOW_FILTER, "Todos os arquivos (*.*)"),
        )

    def save_png(self, suggested: str, data: str) -> str | None:
        """Imagem do dashboard (spec 014, RF-1452): "Salvar como" do Windows e grava o PNG escolhido."""
        import webview

        chosen = self._dialog(
            webview.FileDialog.SAVE, save_filename=png_name(suggested), file_types=(_PNG_FILTER,)
        )
        if not chosen:
            return None
        path = write_png(chosen, data)
        log.info("Imagem do dashboard salva em %s", path)
        return str(path)

    def set_dirty(self, dirty: bool) -> None:
        """A página avisa se há abas com alterações não salvas (usado ao fechar a janela)."""
        self._dirty = bool(dirty)

    def close_app(self) -> None:
        """Fecha a janela depois que a página resolveu as alterações pendentes."""
        self._force_close = True
        self._window.destroy()

    def _on_closing(self) -> bool:
        if not self._dirty or self._force_close:
            return True
        # Pergunta na própria página (Salvar tudo / Fechar sem salvar / Cancelar). Numa thread:
        # o evento roda na thread da interface, e evaluate_js esperaria por ela.
        threading.Thread(
            target=self._window.evaluate_js, args=("window.prodataConfirmClose?.()",), daemon=True
        ).start()
        return False

    def reveal(self, path: str) -> bool:
        """Abre o Explorer com o arquivo selecionado (ou a pasta, se for uma)."""
        target = Path(path)
        if not target.exists():
            return False
        if sys.platform == "win32":
            args = ["explorer", str(target)] if target.is_dir() else ["explorer", f"/select,{target}"]
            subprocess.Popen(args)  # caminho existente, sem shell
        return True


# O pywebview só aceita letras, dígitos e espaços na descrição do filtro: "PRO.DATA" quebrava o diálogo.
_WORKFLOW_FILTER = "Fluxos PRODATA (*.prodata.json)"
_PNG_FILTER = "Imagem PNG (*.png)"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_MAX_BYTES = 64 * 1024 * 1024


def png_name(name: str) -> str:
    """Nome de arquivo saneado, sempre terminando em .png (constituição IV)."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", Path(name.replace("\\", "/")).name)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    stem = re.sub(r"\.png$", "", stem, flags=re.IGNORECASE).strip(" .")[:120]
    return f"{stem or 'dashboard'}.png"


def write_png(raw_path: str, data: str) -> Path:
    """Grava o PNG no destino escolhido: caminho absoluto, pasta existente, extensão fixa."""
    path = Path(raw_path)
    if not path.is_absolute():
        raise ValueError("Escolha a pasta e o nome da imagem.")
    path = path.with_name(png_name(path.name))
    if not path.parent.is_dir():
        raise ValueError(f"A pasta não existe: {path.parent}")
    raw = base64.b64decode(data.split(",", 1)[-1], validate=True)
    if not raw.startswith(_PNG_SIGNATURE) or len(raw) > _PNG_MAX_BYTES:
        raise ValueError("A imagem gerada é inválida.")
    path.write_bytes(raw)
    return path


def main() -> None:
    data_dir = Path(os.environ.setdefault("PRODATA_STORAGE_DIR", str(user_data_dir())))
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = _setup_logging(data_dir)
    try:
        run(data_dir)
    except Exception as exc:
        log.exception("Falha ao iniciar o %s", APP_NAME)
        _error_box(f"Não foi possível iniciar o {APP_NAME}.\n\n{exc}\n\nDetalhes em:\n{log_file}")
        raise SystemExit(1) from exc
    log.info("Encerrado")
    logging.shutdown()
    # Servidor e janela já foram fechados e o log gravado. A finalização normal do Python
    # (runtime .NET do pythonnet, pools de threads) levava ~5 s sem fazer nada útil.
    os._exit(0)


def run(data_dir: Path) -> None:
    import uvicorn
    import webview

    from prodata import __version__
    from prodata.config import Settings
    from prodata.main import create_app

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    settings = Settings(host="127.0.0.1", port=port, cors_origins=[url])
    log.info("%s %s iniciando em %s (dados: %s)", APP_NAME, __version__, url, data_dir)

    # log_config=None: o padrão do uvicorn escreve no console, que não existe no executável.
    config = uvicorn.Config(
        create_app(settings),
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
        # A WebView mantém conexões abertas: sem limite, fechar o app esperava ~6 s.
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="prodata-server", daemon=True)
    thread.start()
    _wait_until_ready(url, thread)

    webview.settings["ALLOW_DOWNLOADS"] = True  # exportações do Output Data
    api = DesktopApi()
    api._window = webview.create_window(
        f"{APP_NAME} {__version__} · Grupo Protege",
        url,
        width=1440,
        height=900,
        min_size=(1024, 680),
        text_select=True,
        js_api=api,
    )
    api._window.events.closing += api._on_closing
    # private_mode=False: mantém preferências do usuário (tema, painéis) entre sessões.
    webview.start(private_mode=False, storage_path=str(data_dir / "webview"))

    log.info("Janela fechada; encerrando servidor")
    server.should_exit = True
    thread.join(timeout=10)


if __name__ == "__main__":
    main()
