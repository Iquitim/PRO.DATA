# PyInstaller: aplicativo de desktop em pasta única (spec 008). Uso: uv run python packaging/build.py
# ruff: noqa
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

HERE = SPECPATH  # noqa: F821 (injetado pelo PyInstaller)

hiddenimports = (
    collect_submodules("prodata")  # ferramentas são registradas por import
    + collect_submodules("uvicorn")  # loops/protocolos escolhidos em tempo de execução
    + collect_submodules("webview")
    + collect_submodules("sklearn.ensemble")
    + collect_submodules("sklearn.linear_model")
    + ["keyring.backends.Windows", "sklearn.utils._typedefs", "sklearn.neighbors._partition_nodes"]
)

datas = (
    collect_data_files("prodata")  # interface web (HTML/CSS/JS/fontes)
    + collect_data_files("webview")
    + collect_data_files("sklearn")
    # Bibliotecas que leem a própria versão ou usam entry points (keyring acha o cofre do Windows assim).
    + [m for pkg in ("connectorx", "keyring", "polars", "duckdb", "fastexcel", "pywebview", "fastapi",
                     "uvicorn", "pydantic", "scikit-learn", "pyarrow", "xlsxwriter")
       for m in copy_metadata(pkg)]
)

a = Analysis(  # noqa: F821
    [f"{HERE}/launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "mypy", "ruff", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PRO.DATA",
    console=False,  # sem janela de terminal
    icon=f"{HERE}/prodata.ico",
    version=f"{HERE}/version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="PRO.DATA")  # noqa: F821
