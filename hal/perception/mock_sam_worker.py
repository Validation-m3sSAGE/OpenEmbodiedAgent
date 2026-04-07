from __future__ import annotations

import json
import sys


def main() -> None:
    sys.stdout.write(json.dumps({"ok": True, "ready": True}) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        sys.stdout.write(json.dumps({"ok": True, "detections": []}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
