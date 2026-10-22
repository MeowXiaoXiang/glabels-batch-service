"""Exercise a running production image using only the Python standard library."""

import json
import sys
import time
from urllib.request import Request, urlopen
from uuid import UUID


def smoke(base_url: str) -> None:
    def get(path: str):
        return urlopen(base_url + path, timeout=10)  # nosec B310

    request = Request(
        base_url + "/labels/print",
        data=json.dumps(
            {
                "template_name": "demo.glabels",
                "data": [
                    {"ITEM": "CI-A", "CODE": "123"},
                    {"ITEM": "CI-B", "CODE": "456"},
                ],
                "copies": 2,
                "labels_per_page": 1,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # nosec B310
        assert response.status == 202
        identifier = str(UUID(json.load(response)["job_id"]))
    deadline = time.monotonic() + 60
    while True:
        with get(f"/labels/jobs/{identifier}") as response:
            job = json.load(response)
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Production job did not complete: {job}")
        time.sleep(0.2)
    with get(job["download_url"]) as response:
        assert response.headers.get_content_type() == "application/pdf"
        pdf = response.read()
    assert pdf.startswith(b"%PDF-") and b"%%EOF" in pdf[-1024:]
    print(f"Production HTTP job {identifier}: done, downloaded {len(pdf)} PDF bytes")


if __name__ == "__main__":
    smoke(sys.argv[1])
