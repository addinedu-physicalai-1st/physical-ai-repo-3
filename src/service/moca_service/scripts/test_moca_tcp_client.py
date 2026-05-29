#!/usr/bin/env python3
"""Exercise web_service MOCA TCP clients against moca_service."""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SERVICE_ROOT = REPO_ROOT / "src" / "service" / "web_service"
sys.path.insert(0, str(WEB_SERVICE_ROOT))

try:
    from app.clients.catalog_client import MocaTcpCatalogClient
    from app.clients.order_client import MocaTcpOrderClient
    from app.clients.table_client import MocaTcpTableClient
except ModuleNotFoundError:
    from app.clients.moca_tcp_client import (
        MocaTcpCatalogClient,
        MocaTcpOrderClient,
        MocaTcpTableClient,
    )

from app.protocol.order_protocol import MocaOrderItem


DEFAULT_HOST = os.getenv("MOCA_SERVICE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MOCA_SERVICE_PORT", "9001"))
DEFAULT_TIMEOUT = float(os.getenv("MOCA_TCP_TEST_TIMEOUT_SEC", "3.0"))


def parse_order_item(value: str) -> MocaOrderItem:
    try:
        product_id_text, quantity_text = value.split(":", 1)
        product_id = int(product_id_text)
        quantity = int(quantity_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("order item must be PRODUCT_ID:QUANTITY") from exc
    return MocaOrderItem(product_id=product_id, quantity=quantity)


def dump(label: str, value: Any) -> None:
    print(f"[moca-tcp-test] {label}")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def run_catalog(host: str, port: int, timeout: float, command: str) -> None:
    client = MocaTcpCatalogClient(host, port, timeout)
    try:
        if command in {"menu", "all"}:
            dump("menu", client.fetch_menu_options())
        if command in {"allergy", "all"}:
            dump("allergy", client.fetch_allergy())
    finally:
        client.close()


def run_tables(host: str, port: int, timeout: float) -> None:
    client = MocaTcpTableClient(host, port, timeout)
    try:
        dump("tables", client.fetch_tables())
    finally:
        client.close()


def run_order(host: str, port: int, timeout: float, items: list[MocaOrderItem]) -> int:
    client = MocaTcpOrderClient(host, port, timeout)
    try:
        order_id = client.create_order(items)
        dump("order", {"order_id": order_id})
        return order_id
    finally:
        client.close()


def run_assign(
    host: str,
    port: int,
    timeout: float,
    order_id: int,
    receive_type: str,
    table_number: int | None,
) -> None:
    client = MocaTcpTableClient(host, port, timeout)
    try:
        client.assign_table(order_id, receive_type, table_number)
        dump(
            "table_assignment",
            {
                "order_id": order_id,
                "receive_type": receive_type,
                "table_number": table_number,
                "status": "ok",
            },
        )
    finally:
        client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test moca_service TCP communication by importing web_service TCP clients."
    )
    parser.add_argument(
        "command",
        choices=["all", "menu", "allergy", "tables", "order", "assign"],
        help="TCP request to send.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"moca_service host. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"moca_service port. Default: {DEFAULT_PORT}")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"socket timeout seconds. Default: {DEFAULT_TIMEOUT}",
    )
    parser.add_argument(
        "--item",
        action="append",
        type=parse_order_item,
        default=[],
        help="order item as PRODUCT_ID:QUANTITY. Can be repeated. Default for order/all: 1:1",
    )
    parser.add_argument("--order-id", type=int, help="MOCA order id for assign.")
    parser.add_argument(
        "--receive-type",
        choices=["take_out", "dine_in"],
        default="dine_in",
        help="receive type for assign. Default: dine_in",
    )
    parser.add_argument("--table-number", type=int, help="table number for dine_in assign.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.command in {"menu", "allergy", "all"}:
        run_catalog(args.host, args.port, args.timeout, args.command)

    if args.command in {"tables", "all"}:
        run_tables(args.host, args.port, args.timeout)

    if args.command in {"order", "all"}:
        items = args.item or [MocaOrderItem(product_id=1, quantity=1)]
        run_order(args.host, args.port, args.timeout, items)

    if args.command == "assign":
        if args.order_id is None:
            raise SystemExit("--order-id is required for assign")
        if args.receive_type == "dine_in" and args.table_number is None:
            raise SystemExit("--table-number is required when --receive-type dine_in")
        run_assign(
            args.host,
            args.port,
            args.timeout,
            args.order_id,
            args.receive_type,
            args.table_number,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
