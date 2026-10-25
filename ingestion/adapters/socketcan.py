"""SocketCAN adapter - interface only.

NOT IMPLEMENTED / NOT TESTED in this environment: no Linux CAN interface, no
authorised vehicle or bench ECU is available, and touching a real vehicle bus
requires explicit authorisation and an isolated test setup (docs/security.md).

The class shows the intended shape of the integration and raises clearly if
used, so nobody can mistake an interface for a working implementation.
"""
from __future__ import annotations

from typing import Iterator

from ingestion.adapters.base import AdapterInfo, SourceAdapter


class SocketCanAdapter(SourceAdapter):
    info = AdapterInfo(
        name="socketcan",
        input_format="CAN/CAN-FD frames from a Linux SocketCAN interface (can0), "
                     "decoded with a DBC file",
        dependencies="python-can, a DBC matrix, Linux SocketCAN (vcan for testing)",
        permissions="CAP_NET_RAW / access to can0; write access NOT required and NOT used",
        implemented=False,
        test_status="NOT RUN - environment lacks SocketCAN and an authorised bus",
        limitations="Read-only design. No frame transmission path exists in this codebase.",
        maturity="real (when connected)",
    )

    def __init__(self, channel: str = "can0", dbc_path: str | None = None):
        self.channel = channel
        self.dbc_path = dbc_path

    def read(self) -> Iterator[dict]:
        raise NotImplementedError(
            "SocketCAN adapter is an interface in this environment. "
            "See docs/adapters.md for what is required to implement and test it."
        )
