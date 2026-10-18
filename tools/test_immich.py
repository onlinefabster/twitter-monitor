#!/usr/bin/env python3
"""tools/test_immich.py — smoke test the Immich client against a live server.

Verifies album creation + single upload against IMMICH_BASE_URL with
IMMICH_API_KEY. USE A SCRATCH ACCOUNT, not production data.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clients.immich_client import ImmichClient  # noqa: E402

load_dotenv()

USER = "test-user-1"


async def main():
    base = os.environ.get("IMMICH_BASE_URL", "http://immich:2283")
    key = os.environ.get("IMMICH_API_KEY", "")
    if not key or key.startswith("REPLACE_"):
        print("Set IMMICH_BASE_URL and IMMICH_API_KEY first.")
        return 1

    client = ImmichClient(base, key)
    payload = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300"
        "01010101010101010101010101010101010101010101010101"
        "01010101010101010101010101010101010101010101010101"
        "01010101010101010101ffdb00430101010101010101010101"
        "01010101010101010101010101010101010101010101010101"
        "010101ffc00011080001000103012200021101031101ffc400"
        "1f000001050101010101010000000000000000010203040506"
        "0708090a0bffc400b510000201030302040305050404000001"
        "7d01020300041105122131410613516107227114328191a108"
        "2342b1c11552d1f02433627282090a161718191a2526272829"
        "2a3435363738393a434445464748494a535455565758595a63"
        "6465666768696a6b6c737475767778797a838485868788898a"
        "92939495969798999aa2a3a4a5a6a7a8a9aab3b4b5b6b7b8b9"
        "bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6"
        "e7e8e9eaf1f2f3f4f5f6f7f8f9faffc2000101010101010101"
        "01010101000000000000010002030405060708090a0bffda00"
        "0801010003f03f00"
    )
    asset_id = await client.upload_image(USER, payload, "test-sig-0001", "test.jpg")
    print(f"OK uploaded -> asset id {asset_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))