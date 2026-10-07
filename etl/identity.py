"""Lender identity: HMDA LEI -> GLEIF legal name -> FDIC certificate (name match), plus SBA lenders by FDIC number.

The usual LEI -> RSSD route (HMDA reporter panel, FFIEC NIC) is not reachable, so a certificate is assigned
only when a normalised legal name matches exactly one active FDIC institution. A wrong certificate would be
worse than none: ambiguity resolves to None.
"""

import re

SUFFIX = re.compile(
    r"\b(national association|n a|na|the|inc|incorporated|llc|corp|corporation|co|company|fsb|ssb|bank and trust|"
    r"federal savings bank|state bank)\b"
)
US_REGION_PREFIX = "US-"  # GLEIF writes a U.S. state as ISO 3166-2, e.g. "US-VA"
BANK, CREDIT_UNION, NON_BANK, BANK_NO_CHARTER = "Bank", "Credit union", "Non-bank lender", "Bank (no active FDIC charter)"


def norm(name: str) -> str:
    """Lower-case, '&' -> 'and', punctuation and legal-form suffixes removed, whitespace collapsed."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    s = SUFFIX.sub(" ", s)
    return " ".join(s.split())


def fdic_index(rows):
    """{normalised name: [FDIC institution rows with that name]}."""
    idx = {}
    for r in rows:
        idx.setdefault(norm(r.get("NAME", "")), []).append(r)
    return idx


def match(lei, filer_name, gleif, idx):
    """FDIC row for an HMDA lender, or None. Tries the GLEIF legal name, then the HMDA filer name;
    accepts only a unique normalized match, so ambiguity resolves to 'no certificate' rather than a wrong one."""
    g = gleif.get(lei, {})
    for name in (g.get("legal_name"), filer_name):
        if not name:
            continue
        hits = idx.get(norm(name), [])
        if len(hits) > 1:  # same name, several charters: keep the one headquartered where GLEIF says
            st = (g.get("hq_region") or "").replace(US_REGION_PREFIX, "")
            hits = [h for h in hits if h.get("STALP") == st] or hits
            if len(hits) > 1:
                hits = [h for h in hits if (h.get("CITY") or "").lower() == (g.get("hq_city") or "").lower()] or hits
        if len(hits) == 1:
            return hits[0]
    return None


def lender_type(name: str, fdic_row) -> str:
    """Bank when an FDIC row matched; otherwise read from the name (credit union, bank without a charter, non-bank)."""
    if fdic_row:
        return BANK
    n = (name or "").lower()
    if "credit union" in n:
        return CREDIT_UNION
    return BANK_NO_CHARTER if "bank" in n else NON_BANK
