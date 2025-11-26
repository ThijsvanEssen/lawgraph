import datetime as dt
from dotenv import load_dotenv

from lawgraph.db import ArangoStore
from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.pipelines.case_law import CaseLawPipeline


def main() -> None:
    load_dotenv()
    rs_client = RechtspraakClient()
    store = ArangoStore()
    pipeline = CaseLawPipeline(rs_client, store)

    since = dt.date.today() - dt.timedelta(days=1)
    pipeline.run_since(since)
