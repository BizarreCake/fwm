"""The economies the system holds accounts for.

An economy is a currency area with its own sector accounts: who holds and who
owes each instrument, sector by sector. The United States and the euro area are loaded.
Other countries appear only as counterparties of the US (see `countries.py`),
which is not the same thing: that shows their claims on the US and the US's
claims on them, not their own balance sheets.

Pages and API paths carry the economy id (`#/us/sector/S121`, `#/ea/sector/S1M`,
`/api/economy/ea/sectors`). Amounts are in each economy's own currency; nothing is converted.
"""

from __future__ import annotations

DEFAULT = "us"

ECONOMIES = {
    "us": {
        "name": "United States",
        "currency": "USD",
        "accounts": "Federal Reserve Z.1 Financial Accounts, quarterly from 1952",
        "extras": ["Federal Reserve balance sheet, weekly (H.4.1)", "Interest rates, daily (H.15)",
                   "Foreign holders of US securities by country, monthly (Treasury TIC)"],
    },
    "ea": {
        "name": "Euro area",
        "currency": "EUR",
        "accounts": "ECB Quarterly Sector Accounts, quarterly from 1999",
        "extras": [],
    },
}

# Checked on 2026-11-24, not loaded.
CANDIDATES = {
    "japan": {
        "name": "Japan", "currency": "JPY",
        "accounts": "Bank of Japan Flow of Funds, quarterly",
        "access": "The Bank of Japan's download page responded; the file format has not been examined.",
    },
}


def accounts(economy: str):
    """The modules that list and build one economy's sector and instrument views, with the same interface."""
    from fwm import euroarea, instruments, sectors

    if economy == "ea":
        return euroarea, euroarea
    return sectors, instruments


def listing() -> list[dict]:
    return [{"id": key, **value, "loaded": True} for key, value in ECONOMIES.items()] + \
           [{"id": key, **value, "loaded": False} for key, value in CANDIDATES.items()]
