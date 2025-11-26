import datetime as dt
from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.clients.eu import EUClient
from lawgraph.pipelines.eu_law import EULawPipeline


def main() -> None:
    load_dotenv()
    eu_client = EUClient()
    store = ArangoStore()
    pipeline = EULawPipeline(eu_client, store)

    since = dt.date(2019, 1, 1)
    pipeline.run_since(since)
