"""Per-source adapters that normalize operator data into one demand schema."""

from gridcast.ingest import aemo, be_elia, de_smard, dk_energinet, eirgrid, fr_rte, neso

ADAPTERS = {
    "GB": neso,
    "IE": eirgrid,
    "AU": aemo,
    "FR": fr_rte,
    "DE": de_smard,
    "BE": be_elia,
    "DK": dk_energinet,
}

__all__ = [
    "ADAPTERS",
    "aemo",
    "be_elia",
    "de_smard",
    "dk_energinet",
    "eirgrid",
    "fr_rte",
    "neso",
]
