"""Lender identity: HMDA LEI -> GLEIF legal name -> FDIC certificate (name match), plus SBA lenders by FDIC number."""
import re

SUFFIX = re.compile(r"\b(national association|n a|na|the|inc|incorporated|llc|corp|corporation|co|company|fsb|ssb|bank and trust|"
                    r"federal savings bank|state bank)\b")


def norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    s = SUFFIX.sub(" ", s)
    return " ".join(s.split())


def fdic_index(rows):
    idx = {}
    for r in rows:
        idx.setdefault(norm(r["NAME"]), []).append(r)
    return idx


def match(lei, filer_name, gleif, idx):
    """FDIC row for an HMDA lender, or None. Tries the GLEIF legal name, then the HMDA filer name;
    accepts only a unique normalized match, so ambiguity resolves to 'no certificate' rather than a wrong one."""
    for name in (gleif.get(lei, {}).get("legal_name"), filer_name):
        if name:
            hits = idx.get(norm(name), [])
            if len(hits) > 1:   # same name, several charters: keep the one headquartered where GLEIF says
                g = gleif.get(lei, {})
                st = (g.get("hq_region") or "").replace("US-", "")
                hits = [h for h in hits if h.get("STALP") == st] or hits
                if len(hits) > 1:
                    hits = [h for h in hits if (h.get("CITY") or "").lower() == (g.get("hq_city") or "").lower()] or hits
            if len(hits) == 1:
                return hits[0]
    return None


def lender_type(name: str, fdic_row) -> str:
    if fdic_row:
        return "Bank"
    n = name.lower()
    if "credit union" in n:
        return "Credit union"
    return "Bank (no active FDIC charter)" if "bank" in n else "Non-bank lender"
