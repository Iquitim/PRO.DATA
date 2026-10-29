"""Leitura de arquivos tabulares com detecção automática de formato, encoding e delimitador."""

from prodata.ingestion.datasets import DatasetInfo, DatasetStore
from prodata.ingestion.options import ReadOptions
from prodata.ingestion.readers import inspect_file, read_table

__all__ = ["DatasetInfo", "DatasetStore", "ReadOptions", "inspect_file", "read_table"]
