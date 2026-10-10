"""Copy the dmc4xml package (SDL / PLA codecs) from a dmc4_xml checkout into albam_vendor/dmc4xml.

    python scripts/sync_dmc4xml.py [path to the dmc4_xml checkout]

dmc4xml is maintained upstream (https://github.com/vieris123/dmc4_xml); don't edit the vendored copy, change it
there and re-run this. The source commit is recorded in albam_vendor/dmc4xml/UPSTREAM.txt.
"""
import datetime
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ALBAM = os.path.dirname(HERE)
DEFAULT_SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ALBAM))), "dmc4_xml")
TARGET = os.path.join(ALBAM, "albam_vendor", "dmc4xml")


def git(source, *args):
    try:
        return subprocess.run(["git", "-C", source, *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def main():
    source = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE)
    package = os.path.join(source, "dmc4xml")
    if not os.path.isfile(os.path.join(package, "__init__.py")):
        sys.exit(f"no dmc4xml package in {source}")
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    os.makedirs(TARGET)
    copied = []
    for name in sorted(os.listdir(package)):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(package, name), os.path.join(TARGET, name))
            copied.append(name)
    commit = git(source, "rev-parse", "HEAD") or "unknown"
    dirty = git(source, "status", "--porcelain", "--", "dmc4xml")
    remote = git(source, "remote", "get-url", "origin") or "unknown"
    with open(os.path.join(TARGET, "UPSTREAM.txt"), "w", encoding="utf-8") as f:
        f.write("Vendored copy of the dmc4xml package. Don't edit it here: change it upstream and run\n"
                "scripts/sync_dmc4xml.py.\n\n")
        f.write(f"repository: {remote}\n")
        f.write(f"commit: {commit}{' + uncommitted changes' if dirty else ''}\n")
        f.write(f"synced: {datetime.date.today().isoformat()}\n")
        f.write(f"files: {', '.join(copied)}\n")
    print(f"copied {len(copied)} files from {package} (commit {commit[:10]}{', dirty' if dirty else ''})")


if __name__ == "__main__":
    main()
