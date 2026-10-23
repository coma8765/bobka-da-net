"""Optional disruptive local check: restarts lr1-postgres and lr8-nifi.

Run only when other laboratory clients are stopped. Both containers are
restarted in finally, even if a check fails. Requires the NiFi environment
variables used by scripts/import_flow.py.
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from integration import database_count, wait_for_receipt  # noqa: E402
from nifi_api import NiFi  # noqa: E402

from generator import generate_file  # noqa: E402


def podman(*args):
    subprocess.run(["podman", *args], check=True, capture_output=True, text=True)


def main():
    api = NiFi()
    root = api.request("GET", "/flow/process-groups/root")["processGroupFlow"]["flow"]
    group = next(
        g["id"]
        for g in root["processGroups"]
        if g["component"]["name"] == "lr8-delivery-import"
    )

    def retry_count():
        flow = api.request("GET", f"/flow/process-groups/{group}")["processGroupFlow"][
            "flow"
        ]
        return sum(
            c["status"]["aggregateSnapshot"]["flowFilesQueued"]
            for c in flow["connections"]
            if c["component"]["source"]["name"] == "Retry database"
        )

    try:
        podman("stop", "lr1-postgres")
        path, count = generate_file(ROOT / "runtime", 3)
        deadline = time.monotonic() + 90
        while retry_count() == 0:
            if time.monotonic() > deadline:
                raise AssertionError("No database retry queue after PostgreSQL outage")
            time.sleep(2)
        assert not (ROOT / "runtime/receipts" / (path.name + ".loaded.json")).exists()
        print("PASS: database outage retains file in retry queue", flush=True)
        podman("restart", "--time", "30", "lr8-nifi")
        deadline = time.monotonic() + 90
        while True:
            try:
                api = NiFi()
                if retry_count() > 0:
                    break
            except (OSError, RuntimeError):
                pass
            if time.monotonic() > deadline:
                raise AssertionError("Retry queue not restored after NiFi restart")
            time.sleep(2)
        print("PASS: NiFi restart preserves queued file", flush=True)
    finally:
        podman("start", "lr1-postgres")
        podman("start", "lr8-nifi")
    _, receipt = wait_for_receipt(path.name, True)
    assert database_count(path.name.split("__")[0]) == count
    assert int(receipt["record_count"]) == count
    print("PASS: queued file loads after PostgreSQL recovery", flush=True)


if __name__ == "__main__":
    main()
