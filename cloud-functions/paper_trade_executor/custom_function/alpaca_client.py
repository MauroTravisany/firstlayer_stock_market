import requests


class AlpacaPaperClient:
    def __init__(self, base_url, api_key, secret_key, timeout_seconds=20):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _request(self, method, path, **kwargs):
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=self.timeout_seconds,
            **kwargs,
        )
        request_id = response.headers.get("X-Request-ID")
        try:
            body = response.json()
        except ValueError:
            body = {"raw_text": response.text}
        return response.status_code, request_id, body

    def get_account(self):
        return self._request("GET", "/v2/account")

    def get_positions(self):
        return self._request("GET", "/v2/positions")

    def create_order(self, payload):
        return self._request("POST", "/v2/orders", json=payload)


def to_alpaca_symbol(ticker):
    mapping = {
        "BTC-USD": "BTC/USD",
        "ETH-USD": "ETH/USD",
    }
    return mapping.get(ticker, ticker)


def is_crypto_ticker(ticker, asset_type):
    return asset_type == "CRYPTO" or ticker in {"BTC-USD", "ETH-USD"}
