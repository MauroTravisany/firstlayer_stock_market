"""Compatibility import for the canonical WP-04 official FX source."""

from tools.wp04_fx_source import *  # noqa: F401,F403
from tools.wp04_fx_source import fetch_bcch_observed_dollar as _fetch

BcchFxSourceError = OfficialFxSourceError


def fetch_bcch_observed_dollar(*, ticker="CLP=X", series_id=SERIES_ID, **kwargs):
    """Accept the retired adapter arguments while enforcing canonical identities."""

    if ticker != "CLP=X" or series_id != SERIES_ID:
        raise OfficialFxSourceError(
            "SERIES_MISMATCH", "official FX compatibility arguments are invalid"
        )
    return _fetch(**kwargs)
