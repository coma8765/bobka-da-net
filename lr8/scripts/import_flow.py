"""Import a stopped flow, configure sensitive DB credentials, validate and start it."""

import json
import os
import time
import uuid
from pathlib import Path

from nifi_api import NiFi

ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, description, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(1)
    raise RuntimeError("Timed out: " + description)


def main():
    password = os.environ["PGPASSWORD"]
    api = NiFi()
    root = api.request("GET", "/flow/process-groups/root")["processGroupFlow"]["id"]
    existing = api.request("GET", f"/flow/process-groups/{root}")["processGroupFlow"][
        "flow"
    ]["processGroups"]
    if any(g["component"]["name"] == "lr8-delivery-import" for g in existing):
        raise RuntimeError(
            "lr8-delivery-import already exists; use the existing group or remove it explicitly in UI"
        )
    snapshot = (ROOT / "nifi/lr8-delivery-import.json").read_bytes()
    boundary = "lr8-" + uuid.uuid4().hex
    body = b""
    for key, value in [
        ("groupName", "lr8-delivery-import"),
        ("clientId", str(uuid.uuid4())),
        ("positionX", "0"),
        ("positionY", "0"),
    ]:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="lr8-delivery-import.json"\r\nContent-Type: application/json\r\n\r\n'.encode()
    body += snapshot + f"\r\n--{boundary}--\r\n".encode()
    entity = api.request(
        "POST",
        f"/process-groups/{root}/process-groups/upload",
        body,
        f"multipart/form-data; boundary={boundary}",
    )
    group_id = entity["id"]
    print("Imported group:", group_id, flush=True)
    group = api.request("GET", f"/process-groups/{group_id}")
    context_id = group["component"]["parameterContext"]["id"]
    context = api.request("GET", f"/parameter-contexts/{context_id}")
    parameters = []
    values = {
        "jdbc.password": password,
        "jdbc.user": os.environ.get("PGUSER", "postgres"),
        "jdbc.url": os.environ.get(
            "JDBC_URL",
            "jdbc:postgresql://host.containers.internal:55432/supply_lab?stringtype=unspecified&logServerErrorDetail=false",
        ),
    }
    for name, value in values.items():
        parameters.append(
            {
                "parameter": {
                    "name": name,
                    "sensitive": name == "jdbc.password",
                    "value": value,
                }
            }
        )
    update = api.request(
        "POST",
        f"/parameter-contexts/{context_id}/update-requests",
        {
            "id": context_id,
            "revision": context["revision"],
            "component": {"id": context_id, "parameters": parameters},
        },
    )
    request_id = update["request"]["requestId"]
    endpoint = f"/parameter-contexts/{context_id}/update-requests/{request_id}"
    wait_for(
        lambda: api.request("GET", endpoint)["request"]["complete"], "parameter update"
    )
    result = api.request("GET", endpoint)["request"]
    if result.get("failureReason"):
        raise RuntimeError(result["failureReason"])
    api.request("DELETE", endpoint)
    services = api.request(
        "GET", f"/flow/process-groups/{group_id}/controller-services"
    )["controllerServices"]
    db = next(s for s in services if s["component"]["name"] == "PostgreSQL supply_lab")
    properties = dict(db["component"]["properties"])
    properties["Password"] = "#{jdbc.password}"
    verification_url = f"/controller-services/{db['id']}/config/verification-requests"
    verification = api.request(
        "POST",
        verification_url,
        {"request": {"componentId": db["id"], "properties": properties}},
    )
    verification_url += "/" + verification["request"]["requestId"]
    wait_for(
        lambda: api.request("GET", verification_url)["request"]["complete"],
        "PostgreSQL connection verification",
    )
    result = api.request("GET", verification_url)["request"]
    api.request("DELETE", verification_url)
    if result.get("failureReason") or any(
        r["outcome"] == "FAILED" for r in result.get("results", [])
    ):
        raise RuntimeError(
            "PostgreSQL connection verification failed; inspect DBCP in NiFi UI"
        )
    print("PostgreSQL connection verified", flush=True)
    for service in services:
        api.request(
            "PUT",
            f"/controller-services/{service['id']}/run-status",
            {"revision": service["revision"], "state": "ENABLED"},
        )
    wait_for(
        lambda: all(
            s["component"]["state"] == "ENABLED"
            for s in api.request(
                "GET", f"/flow/process-groups/{group_id}/controller-services"
            )["controllerServices"]
        ),
        "controller services",
    )
    time.sleep(2)
    flow = api.request("GET", f"/flow/process-groups/{group_id}")["processGroupFlow"][
        "flow"
    ]
    errors = [
        (p["component"]["name"], p["component"].get("validationErrors"))
        for p in flow["processors"]
        if p["component"].get("validationStatus") != "VALID"
    ]
    if errors:
        raise RuntimeError("Flow validation: " + json.dumps(errors, ensure_ascii=False))
    api.request(
        "PUT", f"/flow/process-groups/{group_id}", {"id": group_id, "state": "RUNNING"}
    )
    print("Started valid flow:", group_id)


if __name__ == "__main__":
    main()
