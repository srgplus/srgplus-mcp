import srg
from dotenv import load_dotenv

_client: srg.SRGClient | None = None


def get_client() -> srg.SRGClient:
    global _client
    if _client is None:
        load_dotenv()
        _client = srg.SRGClient()
    return _client
