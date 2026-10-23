"""Small standard-library client for a local NiFi single-user instance."""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request


class NiFi:
    def __init__(self):
        self.base = os.environ.get("NIFI_URL", "https://localhost:8443/nifi-api")
        # Explicit opt-in for the self-signed certificate of the local lab only.
        self.context = (
            ssl._create_unverified_context()
            if os.environ.get("NIFI_INSECURE") == "1"
            else ssl.create_default_context()
        )
        self.token = None
        credentials = urllib.parse.urlencode(
            {
                "username": os.environ.get("NIFI_USERNAME", "student"),
                "password": os.environ["NIFI_PASSWORD"],
            }
        ).encode()
        self.token = self.request(
            "POST",
            "/access/token",
            credentials,
            "application/x-www-form-urlencoded",
            raw=True,
        ).decode()

    def request(
        self, method, path, data=None, content_type="application/json", raw=False
    ):
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode()
        headers = {"Content-Type": content_type}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(
                request, context=self.context, timeout=60
            ) as response:
                result = response.read()
                return result if raw else json.loads(result) if result else None
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"{method} {path}: {exc.code} {exc.read().decode()}"
            ) from None
