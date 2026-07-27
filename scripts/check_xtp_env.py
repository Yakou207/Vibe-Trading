"""XTP simulation-environment connectivity smoke check (Phase 0.3).

Runs inside the linux/amd64 container built from docker/xtp/Dockerfile (the
official XTP bindings have no macOS build). Two levels:

1. No credentials: verify the trader/quote bindings import.
2. With XTP_* environment variables (from the test-account email): log in to
   the simulation trading server, query asset and positions, log out.

Credentials come only from environment variables; nothing is written to disk.
"""

from __future__ import annotations

import os
import platform
import sys
import tempfile
from time import sleep


def main() -> int:
    if platform.system() != "Linux":
        raise SystemExit("run this inside the docker/xtp container (Linux x86_64)")

    import vnxtpquote  # noqa: F401
    import vnxtptrader

    print("bindings: import ok")

    ip = os.environ.get("XTP_TRADER_IP")
    if not ip:
        print("XTP_TRADER_IP not set; skipping login check")
        return 0
    port = int(os.environ["XTP_TRADER_PORT"])
    user = os.environ["XTP_USER"]
    password = os.environ["XTP_PASSWORD"]
    software_key = os.environ["XTP_SOFTWARE_KEY"]
    client_id = int(os.environ.get("XTP_CLIENT_ID", "1"))

    class SmokeApi(vnxtptrader.TraderApi):
        def onDisconnected(self, session_id, reason):
            print(f"onDisconnected: session={session_id} reason={reason}")

        def onError(self, data):
            print(f"onError: {data}")

        def onQueryAsset(self, data, error, reqid, last, session_id):
            print(f"asset: {data} error={error}")

        def onQueryPosition(self, data, error, reqid, last, session_id):
            print(f"position: {data} error={error}")

    api = SmokeApi()
    api.createTraderApi(client_id, tempfile.mkdtemp(prefix="xtp-smoke-"), 4)
    api.subscribePublicTopic(2)
    api.setSoftwareKey(software_key)
    api.setSoftwareVersion("vibe-smoke-0.1")
    api.setHeartBeatInterval(15)

    session_id = api.login(ip, port, user, password, 1, "0.0.0.0")
    if session_id == 0:
        print(f"login FAILED: {api.getApiLastError()}")
        return 1
    print(f"login ok: session={session_id} trading_day={api.getTradingDay()} api={api.getApiVersion()}")

    api.queryAsset(session_id, 1)
    api.queryPosition("", session_id, 2)
    sleep(3)
    # Do NOT call api.logout(): its disconnect callback deadlocks the interpreter
    # (GIL) under this wrapper. Process exit closes the TCP session server-side.
    print("smoke ok")
    return 0


if __name__ == "__main__":
    # The XTP api spawns non-daemon threads; a plain sys.exit would hang forever.
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
