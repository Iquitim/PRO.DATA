"""Build do aplicativo de desktop (spec 008).

    uv run python packaging/build.py            # ícone + executável + zip + instalador (se houver Inno Setup)
    uv run python packaging/build.py --no-setup # sem o instalador

Saídas em dist/: PRO.DATA/ (pasta do app), PRO.DATA-<versão>-portable.zip e
PRO.DATA-<versão>-setup.exe.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
APP_DIR = DIST / "PRO.DATA"

ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
]


def version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def write_version_info(ver: str) -> None:
    """Metadados do .exe (Propriedades > Detalhes no Windows Explorer)."""
    parts = [*map(int, ver.split(".")), 0, 0, 0][:4]
    tup = ", ".join(map(str, parts))
    (PACKAGING / "version_info.txt").write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup})),
  kids=[StringFileInfo([StringTable('041604B0', [
    StringStruct('CompanyName', 'Grupo Protege'),
    StringStruct('FileDescription', 'PRO.DATA - pipelines de dados visuais'),
    StringStruct('FileVersion', '{ver}'),
    StringStruct('ProductName', 'PRO.DATA'),
    StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])]
)
""",
        encoding="utf-8",
    )


def build_exe() -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(PACKAGING / "prodata.spec"),
         "--noconfirm", "--clean", "--distpath", str(DIST), "--workpath", str(ROOT / "build")],
        check=True,
    )  # fmt: skip


def build_zip(ver: str) -> Path:
    base = DIST / f"PRO.DATA-{ver}-portable"
    return Path(shutil.make_archive(str(base), "zip", root_dir=DIST, base_dir="PRO.DATA"))


def build_setup(ver: str) -> Path | None:
    iscc = next((p for p in ISCC_CANDIDATES if p.is_file()), None) or shutil.which("ISCC")
    if not iscc:
        print(
            "Inno Setup não encontrado (instale com: winget install JRSoftware.InnoSetup). Pulando o instalador."
        )
        return None
    subprocess.run(
        [str(iscc), f"/DAppVersion={ver}", f"/DSourceDir={APP_DIR}", str(PACKAGING / "installer.iss")],
        check=True,
    )
    return DIST / f"PRO.DATA-{ver}-setup.exe"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--no-setup", action="store_true", help="não gerar o instalador")
    args = parser.parse_args()

    ver = version()
    step("Ícone e metadados")
    subprocess.run([sys.executable, str(PACKAGING / "make_icon.py")], check=True)
    write_version_info(ver)

    step("Executável (PyInstaller)")
    shutil.rmtree(APP_DIR, ignore_errors=True)
    build_exe()

    step("Pacote portátil (.zip)")
    zip_path = build_zip(ver)

    setup_path = None
    if not args.no_setup:
        step("Instalador (Inno Setup)")
        setup_path = build_setup(ver)

    size = sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file()) / 2**20
    step("Pronto")
    print(f"App:         {APP_DIR}  ({size:.0f} MB)")
    print(f"Portátil:    {zip_path}  ({zip_path.stat().st_size / 2**20:.0f} MB)")
    if setup_path:
        print(f"Instalador:  {setup_path}  ({setup_path.stat().st_size / 2**20:.0f} MB)")


if __name__ == "__main__":
    main()
