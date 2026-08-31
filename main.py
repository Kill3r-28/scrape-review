#!/usr/bin/env python3
"""Compatibility entry — prefer tickets agent CLI / ingest CLI."""

from tickets.jobs.ingest_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
