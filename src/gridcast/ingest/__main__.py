"""Allow `python -m gridcast.ingest --all` as an alias of `gridcast ingest --all`."""

import sys

from gridcast.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["ingest", *sys.argv[1:]]))
