from prodata.api.routes import (
    apis,
    catalog,
    connections,
    dashboard,
    datasets,
    execution,
    files,
    queries,
    sql,
    workflows,
)

routers = [
    catalog.router,
    datasets.router,
    connections.router,
    queries.router,
    apis.router,
    workflows.router,
    files.router,
    execution.router,
    dashboard.router,
    sql.router,
]
