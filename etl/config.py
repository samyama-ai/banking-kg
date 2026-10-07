"""Every setting banking-kg uses, in one place.

Nothing else in the package hard-codes a URL, port, timeout, batch size or quota: modules import the names
below, and command-line flags default to them. Settings a deployment is likely to change can be overridden
with an environment variable (named in each comment); the rest are facts about the sources or the engine.

    BANKING_KG_URL=http://localhost:8080 BANKING_KG_GRAPH=bankingkg python -m etl.loader
"""

import os
import pathlib
import re
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- deployment (environment-overridable)
ENGINE_URL = os.environ.get("BANKING_KG_URL", "http://localhost:8081")  # engine HTTP API
GRAPH = os.environ.get("BANKING_KG_GRAPH", "bankingkg")  # tenant id
DATA_DIR = pathlib.Path(os.environ.get("BANKING_KG_DATA", ROOT.parent / "data" / "banking-kg"))
BANK_DIR_NAME = "bank_v1"  # the bank's request tables, under DATA_DIR
AUDIENCE_DIR_NAME = "audiences"  # audience CSVs written by the loader, under DATA_DIR
STATE = os.environ.get("BANKING_KG_STATE", "DC")  # market scope (spec D4)
YEAR = int(os.environ.get("BANKING_KG_YEAR", "2023"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")  # Ollama as seen from here
ENGINE_OLLAMA_URL = os.environ.get("BANKING_KG_ENGINE_OLLAMA", "http://host.docker.internal:11434")  # ... from the engine

# ---------------------------------------------------------------- engine client
TIMEOUT_QUERY_S = 600  # one Cypher statement (a 200-node CREATE batch is the slowest)
TIMEOUT_STATUS_S = 10
TIMEOUT_TENANTS_S = 30
TIMEOUT_SNAPSHOT_S = 1800  # export of the full graph
TIMEOUT_REBUILD_S = 900  # vector-index rebuild
NODE_BATCH = 200  # nodes per CREATE
EDGE_BATCH = 100  # edges per MATCH ... CREATE (each adds two index lookups)
ERROR_SNIPPET = 400  # characters of an engine error kept in the raised message
CYPHER_SNIPPET = 300  # characters of the failing statement kept in the raised message
GIB = 1 << 30
TENANT_QUOTAS = {  # a new tenant; the full graph is ~75K nodes / ~241K edges
    "max_connections": 100,
    "max_edges": 10_000_000,
    "max_memory_bytes": 4 * GIB,
    "max_nodes": 2_000_000,
    "max_query_time_ms": 120_000,
    "max_storage_bytes": 10 * GIB,
}

# ---------------------------------------------------------------- embeddings (etl.embed)
EMBED_MODEL = os.environ.get("BANKING_KG_EMBED_MODEL", "all-minilm")
EMBED_DIMS = 384  # all-minilm's output size
EMBED_CHUNK_SIZE = 512  # engine embed_config: text chunking for server-side search embedding
EMBED_CHUNK_OVERLAP = 50
EMBED_BATCH = 64  # texts per Ollama request
EMBED_SET_BATCH = 16  # vectors per SET statement
TIMEOUT_OLLAMA_S = 300

# ---------------------------------------------------------------- public sources (etl.fetch)
USER_AGENT = "Mozilla/5.0 (banking-kg fetch)"
HMDA_CSV_URL = "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years={year}&states={state}"
HMDA_FILERS_URL = "https://ffiec.cfpb.gov/v2/data-browser-api/view/filers?years={year}&states={state}"
GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
GLEIF_BATCH = 100  # LEIs per request (GLEIF's page-size maximum)
GLEIF_PAUSE_S = 0.5  # between GLEIF requests, to stay under its rate limit
FDIC_INSTITUTIONS_URL = (
    "https://banks.data.fdic.gov/api/institutions?filters=ACTIVE:1&fields=NAME,CERT,FED_RSSD,ASSET,CITY,STALP,BKCLASS&limit={limit}&format=json"
)
FDIC_FINANCIALS_URL = "https://banks.data.fdic.gov/api/financials"
FDIC_FINANCIAL_FIELDS = "CERT,REPDTE,NAME,ASSET,DEP,LNLSNET,LNRE,LNRERES,LNCI,LNCON,LNATRES,NTLNLS"
FDIC_LIMIT = 10_000  # FDIC API page-size maximum
FDIC_CERT_BATCH = 40  # certificates per financials query (keeps the filter URL short)
SBA_DATASET_PAGE = "https://data.sba.gov/dataset/7a-504-foia"
SBA_LINK_RX = r'https://data\.sba\.gov/sites/default/files/uploaded_resources/FOIA_[^"]+\.csv'
SBA_FILES = (("FOIA_7a_FY2020_Present", "sba_7a_fy2020_present.csv"), ("FOIA_504_FY2010_Present", "sba_504_fy2010_present.csv"))
TIMEOUT_FETCH_S = 300
TIMEOUT_SBA_DOWNLOAD_S = 1800  # the 7(a) file is ~200 MB

ALLOWED_SCHEMES = ("http", "https")
STATE_RX = re.compile(r"^[A-Z]{2}$")  # USPS state or territory code


def check_url(url: str) -> str:
    """Return url unchanged if it is http(s) with a host; raise ValueError otherwise.

    urllib.request.urlopen also opens file:// and other schemes, so every URL taken from a flag or an
    environment variable goes through here before it is used."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ALLOWED_SCHEMES or not p.netloc:
        raise ValueError(f"not an http(s) URL: {url!r}")
    return url


def check_state(state: str) -> str:
    """state upper-cased if it is a two-letter postal code; ValueError otherwise.

    The state becomes part of file names (hmda_<st>_<yr>.csv), so anything else — '../x' included — is refused."""
    st = (state or "").strip().upper()
    if not STATE_RX.match(st):
        raise ValueError(f"not a two-letter state code: {state!r}")
    return st
