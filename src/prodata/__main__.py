"""``uv run prodata`` ou ``python -m prodata``: sobe o servidor web."""

from __future__ import annotations

import uvicorn

from prodata.config import Settings


def main() -> None:
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
