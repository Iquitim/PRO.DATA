"""``uv run prodata`` ou ``python -m prodata``: sem comando, sobe o servidor web; ``run`` executa um fluxo e sai."""

from __future__ import annotations

import sys

import uvicorn

from prodata import cli
from prodata.config import Settings


def main() -> None:
    code = cli.main(sys.argv[1:])
    if code is not None:
        sys.exit(code)
    settings = Settings()
    uvicorn.run(
        "prodata.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
