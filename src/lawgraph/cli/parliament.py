import datetime as dt
from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.clients.tk import TKClient
from lawgraph.pipelines.parliament import ParliamentPipeline


def main() -> None:
    load_dotenv()
    tk_client = TKClient()
    store = ArangoStore()
    pipeline = ParliamentPipeline(tk_client, store)

    since = dt.datetime.now() - dt.timedelta(days=1)
    pipeline.run_since(since)
