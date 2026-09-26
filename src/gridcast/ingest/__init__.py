"""Per-source adapters that normalize operator data into one demand schema."""

from gridcast.ingest import aemo, eirgrid, neso

ADAPTERS = {"GB": neso, "IE": eirgrid, "AU": aemo}

__all__ = ["ADAPTERS", "aemo", "eirgrid", "neso"]
