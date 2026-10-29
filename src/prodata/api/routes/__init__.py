from prodata.api.routes import catalog, connections, datasets, execution, files, queries, workflows

routers = [
    catalog.router,
    datasets.router,
    connections.router,
    queries.router,
    workflows.router,
    files.router,
    execution.router,
]
