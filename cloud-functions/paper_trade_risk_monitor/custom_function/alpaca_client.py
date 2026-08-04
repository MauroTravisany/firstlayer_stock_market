import requests


class AlpacaPaperClient:
    def __init__(self, base_url, api_key, secret_key, timeout_seconds=20):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key, "Content-Type": "application/json", "Accept": "application/json"})

    def _request(self, method, path, **kwargs):
        response = self.session.request(method, f"{self.base_url}{path}", timeout=self.timeout_seconds, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = {"raw_text": response.text}
        return response.status_code, response.headers.get("X-Request-ID"), body

    def get_account(self):
        return self._request("GET", "/v2/account")

    def get_clock(self):
        return self._request("GET", "/v2/clock")

    def get_positions(self):
        return self._request("GET", "/v2/positions")

    def get_order(self, order_id):
        return self._request("GET", f"/v2/orders/{order_id}")

    def create_order(self, payload):
        return self._request("POST", "/v2/orders", json=payload)


def is_crypto_position(position):
    return str(position.get("asset_class", "")).lower() == "crypto" or "/" in str(position.get("symbol", ""))


def normalize_symbol(symbol):
    """Match Alpaca's compact symbols with the slash notation stored in BigQuery."""
    return "".join(character for character in str(symbol or "").upper() if character.isalnum())
