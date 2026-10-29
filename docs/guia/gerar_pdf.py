"""Gera docs/guia/PRO.DATA-Guia-do-Produto.pdf a partir de guia.html usando o Chrome/Edge headless.

    uv run python docs/guia/gerar_pdf.py

As capturas em img/ vêm do app rodando com o fluxo de demonstração.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "guia.html"
OUTPUT = HERE / "PRO.DATA-Guia-do-Produto.pdf"
BROWSERS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def main() -> None:
    browser = next((b for b in BROWSERS if b.is_file()), None) or shutil.which("chrome") or shutil.which("msedge")
    if not browser:
        sys.exit("Chrome ou Edge não encontrado.")
    with tempfile.TemporaryDirectory(prefix="prodata-guia-") as tmp:
        # O Chrome grava num diretório temporário e o arquivo é movido depois: falha de
        # escrita do navegador vira erro explícito em vez de deixar um PDF antigo no lugar.
        target = Path(tmp) / OUTPUT.name
        subprocess.run(
            [
                str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
                f"--user-data-dir={Path(tmp) / 'profile'}", "--no-pdf-header-footer", "--virtual-time-budget=5000",
                f"--print-to-pdf={target}", SOURCE.as_uri(),
            ],
            check=True, capture_output=True,
        )  # fmt: skip
        if not target.is_file():
            sys.exit("O navegador não gerou o PDF.")
        shutil.move(target, OUTPUT)
    print(f"PDF gerado: {OUTPUT} ({OUTPUT.stat().st_size / 2**20:.1f} MB)")


if __name__ == "__main__":
    main()
