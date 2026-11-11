"""Linha de comando (spec 033): ``prodata run <fluxo>`` executa sem servidor e sem janela.

Feito para o Agendador do Windows: o código de saída diz se deu certo, e o relatório fica na pasta de dados.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from prodata import __version__
from prodata.api.deps import Services
from prodata.config import Settings
from prodata.domain.execution import ExecutionReport
from prodata.domain.workflow import ID_PATTERN, Workflow
from prodata.errors import InvalidInputError, NotFoundError, ProdataError
from prodata.services.workflows import SUFFIX, load_from_file

OK, FAILED, REFUSED = 0, 1, 2
_STATUS = {
    "executed": "ok",
    "cached": "ok (cache)",
    "error": "ERRO",
    "skipped": "não executou",
    "disabled": "desativada",
}


def _services() -> Services:
    from prodata.main import build_services

    if getattr(sys, "frozen", False) and "PRODATA_STORAGE_DIR" not in os.environ:
        # O executável instalado usa a mesma pasta de dados do programa com janela.
        from prodata.desktop import user_data_dir

        os.environ["PRODATA_STORAGE_DIR"] = str(user_data_dir())
    return build_services(Settings())


def find_workflow(services: Services, name: str) -> Workflow:
    """Arquivo ``.prodata.json`` (caminho) ou fluxo da biblioteca (ID ou nome)."""
    as_path = Path(name)
    if name.lower().endswith(".json") or as_path.is_file():
        workflow, _ = load_from_file(str(as_path.resolve()))
        return workflow
    if re.fullmatch(ID_PATTERN, name) and services.workflows.exists(name):
        return services.workflows.get(name)
    matches = [s for s in services.workflows.list() if s.name.casefold() == name.casefold()]
    if len(matches) == 1:
        return services.workflows.get(matches[0].id)
    if len(matches) > 1:
        ids = ", ".join(m.id for m in matches)
        raise InvalidInputError(f"Há mais de um fluxo chamado '{name}'. Use o ID: {ids}")
    raise NotFoundError(
        f"Fluxo não encontrado: {name}. Use o caminho de um arquivo {SUFFIX}, ou veja os da biblioteca com 'prodata list'."
    )


def _save_report(folder: Path, workflow: Workflow, report: ExecutionReport) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%Hh%Mm%S")
    path = folder / f"{workflow.id}_{stamp}.json"
    path.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    return path


def _print_report(workflow: Workflow, report: ExecutionReport, quiet: bool) -> int:
    failed = 0
    for node_id, result in report.node_results.items():
        node = workflow.node(node_id)
        failed += result.status == "error"
        if quiet and result.status != "error":
            continue
        label = node.label or node.type
        line = f"  [{_STATUS.get(result.status, result.status)}] {label}"
        if result.status in ("error", "skipped") and result.error:
            line += f": {result.error}"
        elif exported := result.extra.get("exported_path") or result.extra.get("exported_file"):
            line += f" -> {exported}"
        print(line)
        for warning in result.extra.get("warnings") or []:
            print(f"      aviso: {warning}")
    return failed


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        services = _services()
        workflow = find_workflow(services, args.fluxo)
        # A mesma conferência da tela (spec 028): fluxo de fora só roda depois de aberto e confirmado no programa.
        if not services.trust.opened(workflow):
            print(
                f"Recusado: '{workflow.name}' veio de fora e ainda não foi conferido neste computador.\n"
                "Abra o fluxo no PRO.DATA, confira o que ele faz na faixa do topo e escolha Confiar e executar.",
                file=sys.stderr,
            )
            return REFUSED
        print(f"PRO.DATA {__version__} · {workflow.name} ({len(workflow.nodes)} caixas)")
        report = services.runner.run(workflow, args.ate)
    except ProdataError as exc:
        print(f"Erro: {exc.message}", file=sys.stderr)
        return REFUSED
    except (OSError, ValueError, KeyError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return REFUSED
    failed = _print_report(workflow, report, args.silencioso)
    saved = _save_report(services.settings.storage_dir / "logs" / "execucoes", workflow, report)
    if args.relatorio:
        target = Path(args.relatorio).resolve()
        if target.suffix.lower() != ".json" or not target.parent.is_dir():
            print(
                f"Relatório não gravado: {target} precisa ser um .json numa pasta existente.", file=sys.stderr
            )
        else:
            target.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    seconds = f"{report.total_elapsed_ms / 1000:.1f}".replace(".", ",")
    print(f"{'FALHOU' if failed else 'Concluído'} em {seconds} s · {failed} erro(s) · relatório: {saved}")
    return FAILED if failed else OK


def list_workflows(_args: argparse.Namespace) -> int:
    services = _services()
    for summary in services.workflows.list():
        print(f"{summary.id}\t{summary.name}\t{summary.node_count} caixas")
    return OK


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="prodata",
        description="PRO.DATA: sem comando, abre o servidor web. 'run' executa um fluxo e sai.",
    )
    root.add_argument("--version", action="version", version=f"PRO.DATA {__version__}")
    commands = root.add_subparsers(dest="command")
    run_cmd = commands.add_parser("run", help="Executa um fluxo e sai (para o Agendador do Windows).")
    run_cmd.add_argument("fluxo", help=f"Arquivo {SUFFIX}, ou ID ou nome de um fluxo da biblioteca.")
    run_cmd.add_argument("--ate", metavar="CAIXA", help="Executa só até esta caixa (ID).")
    run_cmd.add_argument(
        "--relatorio", metavar="ARQUIVO.json", help="Grava o relatório também neste arquivo."
    )
    run_cmd.add_argument("--silencioso", action="store_true", help="Mostra só os erros e o resumo.")
    run_cmd.set_defaults(handler=run)
    list_cmd = commands.add_parser("list", help="Lista os fluxos da biblioteca.")
    list_cmd.set_defaults(handler=list_workflows)
    commands.add_parser("serve", help="Abre o servidor web (o mesmo que não passar comando).")
    return root


def main(argv: list[str] | None = None) -> int | None:
    """Devolve o código de saída, ou None quando o pedido é abrir o servidor."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")  # acentos no console do Windows
    args = parser().parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        return None
    code: int = handler(args)
    return code


def cli_only() -> None:
    """Ponto de entrada do ``prodata-cli.exe``: nunca abre servidor."""
    code = main(sys.argv[1:] or ["--help"])
    sys.exit(OK if code is None else code)


if __name__ == "__main__":
    cli_only()
