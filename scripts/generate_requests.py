"""Deterministic data generation script for order intake requests R5 through R10.
Uses a fixed random seed to guarantee reproducible evaluation fixtures.
"""

import os
import random

RANDOM_SEED = 20261005
random.seed(RANDOM_SEED)

EXTENDED_REQUESTS = [
    {"id": "R5", "order_ref": "O5", "text": "Order 10 units of USB-C cable 1 m."},
    {"id": "R6", "order_ref": "O6", "text": "Need 12 units of CAB-2 and 1 unit of HUB-1."},
    {"id": "R7", "order_ref": "O7", "text": "Please supply a pack of USB hub."},
    {"id": "R8", "order_ref": "O8", "text": "We require 5 USB-C cables urgently."},
    {"id": "R9", "order_ref": "O9", "text": "Ship 3 boxes of CAB-1 to our warehouse."},
    {"id": "R10", "order_ref": "O10", "text": "Please send 15 Solar connectors."},
]

def generate_all_emails():
    os.makedirs("data/emails", exist_ok=True)
    for req in EXTENDED_REQUESTS:
        filepath = f"data/emails/{req['id']}_{req['order_ref']}.txt"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Order-Ref: {req['order_ref']}\n")
            f.write(f"Request-ID: {req['id']}\n")
            f.write(f"Subject: Order Request for {req['order_ref']}\n\n")
            f.write(f"{req['text']}\n")
        print(f"Generated: {filepath}")

if __name__ == "__main__":
    generate_all_emails()