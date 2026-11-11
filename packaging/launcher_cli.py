"""Ponto de entrada do ``prodata-cli.exe`` (spec 033): linha de comando, com console, sem abrir janela."""

from prodata.cli import cli_only

if __name__ == "__main__":
    cli_only()
