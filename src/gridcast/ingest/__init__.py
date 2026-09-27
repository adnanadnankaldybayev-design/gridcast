"""Per-source adapters that normalize operator data into one demand schema."""

from gridcast.ingest import (
    aemo,
    be_elia,
    de_smard,
    dk_energinet,
    eirgrid,
    fr_rte,
    kz_korem,
    neso,
)

ADAPTERS = {
    "GB": neso,
    "IE": eirgrid,
    "AU": aemo,
    "FR": fr_rte,
    "DE": de_smard,
    "BE": be_elia,
    "DK": dk_energinet,
    "KZ": kz_korem,
}

__all__ = [
    "ADAPTERS",
    "aemo",
    "be_elia",
    "de_smard",
    "dk_energinet",
    "eirgrid",
    "fr_rte",
    "kz_korem",
    "neso",
]
