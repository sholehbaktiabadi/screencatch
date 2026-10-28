"""Fail if the version differs between meson, the Python package, Debian and AppStream."""

import os
import re
import sys
import xml.etree.ElementTree as ET

import screencatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(expected: str) -> int:
    found = {"python package": screencatch.__version__}
    with open(os.path.join(ROOT, "debian", "changelog"), encoding="utf-8") as handle:
        match = re.match(r"\S+ \(([^)]+)\)", handle.readline())
    found["debian/changelog"] = match.group(1).split("-")[0] if match else "?"
    metainfo = ET.parse(os.path.join(ROOT, "data", screencatch.APP_ID + ".metainfo.xml"))
    release = metainfo.find("./releases/release")
    found["metainfo"] = release.get("version") if release is not None else "?"
    mismatched = {name: version for name, version in found.items() if version != expected}
    for name, version in mismatched.items():
        print(f"{name} has version {version}, meson has {expected}", file=sys.stderr)
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
