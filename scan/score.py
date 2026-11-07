"""Score formula and findings merge helper (docs/contract.md section 2 and 3)."""

PENALTY = {"high": 25, "medium": 10, "low": 3}


def compute_score(findings, error=None):
    """max(0, 100 - 25*high - 10*medium - 3*low); None when the site failed to load."""
    if error:
        return None
    total = sum(PENALTY.get(f.get("severity"), 0) for f in findings)
    return max(0, 100 - total)


def merge_findings(existing, new):
    """Combine two finding lists, deduped by id. A finding in `new` replaces one with the same id."""
    merged = {}
    for f in list(existing) + list(new):
        merged[f["id"]] = f
    return list(merged.values())
