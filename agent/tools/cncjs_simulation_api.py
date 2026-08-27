from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


class CncjsSimulationApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class CncjsSimulationApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or os.getenv("CNCJS_SIMULATION_API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.token = token if token is not None else os.getenv("CNCJS_SIMULATION_API_TOKEN")
        self.timeout = timeout

    def create_and_fetch_job(
        self,
        *,
        gcode: str,
        name: str = "student.nc",
        options: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created = self.create_job(gcode=gcode, name=name, options=options, metadata=metadata)
        job_id = created.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise CncjsSimulationApiError("CNCjs simulation API did not return a job_id.", payload=created)
        fetched = self.get_job(job_id)
        return {"created": created, "fetched": fetched}

    def create_job(
        self,
        *,
        gcode: str,
        name: str = "student.nc",
        options: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "api_version": "v1",
            "name": name,
            "machine_type": "lathe",
            "dialect": "standard-gcode",
            "source": "api",
            "gcode": gcode,
            "options": _default_options(options),
            "metadata": metadata or {},
        }
        return self._request_json("POST", "/api/simulation/jobs", payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/simulation/jobs/{job_id}")

    def _request_json(self, method: str, path: str, payload: Any = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return _decode_response(response.read())
        except error.HTTPError as exc:
            payload = _decode_response(exc.read())
            api_error = payload.get("error") if isinstance(payload, dict) else None
            message = api_error.get("message") if isinstance(api_error, dict) else str(exc)
            raise CncjsSimulationApiError(message, status=exc.code, payload=payload) from exc
        except error.URLError as exc:
            raise CncjsSimulationApiError(str(exc.reason)) from exc


def _default_options(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    options = {
        "rapid_rate_x_mm_min": 3000,
        "rapid_rate_z_mm_min": 5000,
        "initial_position": {"x": 0, "z": 0},
        "initial_speed_multiplier": 1,
        "optional_stop_enabled": False,
    }
    for key, value in (overrides or {}).items():
        if key == "initial_position" and isinstance(value, dict):
            options["initial_position"] = {**options["initial_position"], **value}
        else:
            options[key] = value
    return options


def _decode_response(data: bytes) -> dict[str, Any]:
    if not data:
        return {}
    decoded = json.loads(data.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {"value": decoded}
