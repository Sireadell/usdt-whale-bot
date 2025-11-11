#!/usr/bin/env python3
"""
USDT Whale Watcher – keep an eye on big USDT moves.
Friendly, human-authored style. Inspired by whale-alert bots.
"""

import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from loguru import logger

# Load environment variables from .env (we need API key & token contract)
load_dotenv()

# Configuration settings (everything comes from .env)
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TOKEN_CONTRACT = os.getenv("TOKEN_CONTRACT")
MAX_TX = int(os.getenv("MAX_TX", "100"))  # number of recent transactions to check
THRESHOLD_USDT = int(os.getenv("THRESHOLD_USDT", "100_000"))  # what counts as a “whale”
CHAIN_ID = int(os.getenv("CHAIN_ID", "1"))  # Ethereum mainnet
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # seconds between checks

# Known exchange addresses (comma-separated in .env)
KNOWN_EXCHANGES = [
    addr.strip() for addr in os.getenv("KNOWN_EXCHANGES", "").split(",") if addr.strip()
]

# Quick check: make sure the API key and token contract are set
if not ETHERSCAN_API_KEY or not TOKEN_CONTRACT:
    logger.error("Missing ETHERSCAN_API_KEY or TOKEN_CONTRACT in .env – can't continue!")
    raise SystemExit(1)

# Fetch recent token transfers from Etherscan (with retries in case of network hiccups)
def fetch_recent_txs() -> list[dict]:
    url = "https://api.etherscan.io/v2/api"
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": TOKEN_CONTRACT,
        "page": 1,
        "offset": MAX_TX,
        "sort": "desc",
        "chainid": CHAIN_ID,
        "apikey": ETHERSCAN_API_KEY,
    }

    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                logger.warning(f"HTTP {r.status_code} – partial response: {r.text[:200]}")
                continue

            data = r.json()
            if data.get("status") != "1":
                logger.warning(f"Etherscan error: {data.get('message')}")
                continue

            return data.get("result", [])

        except Exception as e:
            logger.debug(f"Attempt {attempt + 1} failed: {e}")

        # wait a bit longer each retry
        time.sleep(2 ** attempt)

    logger.error("All fetch attempts failed. Giving up for now.")
    return []

# Detect large outgoing USDT transfers (“whale moves”)
def detect_whale_moves(recent_txs: list[dict]) -> pd.DataFrame:
    if not recent_txs:
        return pd.DataFrame()

    df = pd.DataFrame(recent_txs)
    df["amount"] = pd.to_numeric(df["value"]) / 1_000_000  # USDT has 6 decimals
    df["time"] = pd.to_datetime(df["timeStamp"].astype(int), unit="s")

    # Outgoing transfers above threshold, ignore self-transfers
    whales = df[
        (df["amount"] >= THRESHOLD_USDT)
        & (df["from"].str.lower() != df["to"].str.lower())
    ].copy()

    # Tag known exchanges
    exchange_set = {addr.lower() for addr in KNOWN_EXCHANGES}
    whales["is_exchange"] = whales["to"].str.lower().isin(exchange_set)
    whales["label"] = whales["is_exchange"].map({True: "EXCHANGE", False: "UNKNOWN"})

    return whales

# Show results and save them to a CSV for history
def report_whale_moves(whales: pd.DataFrame):
    if whales.empty:
        logger.info(f"No whales spotted ≥ {THRESHOLD_USDT:,} USDT in the last {MAX_TX} transactions.")
        return

    logger.success(f"🚨 Found {len(whales)} big USDT move(s)!")
    for _, row in whales.iterrows():
        logger.info(
            f"{row['amount']:,.0f} USDT | {row['time'].strftime('%H:%M')} | "
            f"{row['from'][:10]}… → {row['to'][:10]}… [{row['label']}]"
        )
        logger.info(f"https://etherscan.io/tx/{row['hash']}\n")

    # Save to CSV – append mode keeps a running history
    csv_path = Path("LARGE_USDT_TRANSFERS.csv")
    header = not csv_path.exists()
    whales.to_csv(csv_path, mode="a", header=header, index=False)
    logger.info(f"Saved {len(whales)} row(s) → {csv_path}")

# Run a single check for large transfers
def run_once():
    logger.info(f"Checking the latest {MAX_TX} USDT transfers…")
    recent_txs = fetch_recent_txs()
    if not recent_txs:
        logger.warning("Nothing came back – will try again later.")
        return

    logger.info(f"Fetched {len(recent_txs)} transfers.")
    whale_moves = detect_whale_moves(recent_txs)
    report_whale_moves(whale_moves)

# Start here if running the script directly
if __name__ == "__main__":
    # Single run
    run_once()

    # Continuous monitoring (optional)
    """
    logger.info(f"Starting continuous monitoring – checking every {POLL_INTERVAL}s")
    while True:
        run_once()
        time.sleep(POLL_INTERVAL)
    """
