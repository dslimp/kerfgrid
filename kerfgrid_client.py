"""Upload DXF files to the shared KerfGrid workspace without a browser."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request_json(url: str, payload: dict | None = None) -> dict:
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        detail = json.load(error)
        raise ValueError(detail.get("error", str(error))) from error


def upload_dxf(path: Path, server: str, *, quantity: int = 1, thickness_mm: float | None = None,
               mode: str = "append", request_id: str | None = None) -> dict:
    root = server.rstrip("/")
    payload = {"filename": path.name, "content": path.read_text(encoding="utf-8"),
               "quantity": quantity, "mode": mode, "request_id": request_id or str(uuid.uuid4())}
    if thickness_mm is not None:
        payload["thickness_mm"] = thickness_mm
    if mode == "replace":
        payload["expected_revision"] = request_json(root + "/api/workspace")["revision"]
    return request_json(root + "/api/workspace/import-dxf", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--server", default="http://192.168.88.61")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--thickness-mm", type=float)
    parser.add_argument("--mode", choices=["append", "replace"], default="append")
    parser.add_argument("--request-id", help="Reuse this ID when retrying the same upload")
    args = parser.parse_args()
    result = upload_dxf(args.file, args.server, quantity=args.quantity, thickness_mm=args.thickness_mm,
                        mode=args.mode, request_id=args.request_id)
    print(json.dumps({"revision": result["revision"], "parts": len(result["project"]["parts"]),
                      "file_id": result.get("file_id"), "replayed": result.get("replayed", False)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
