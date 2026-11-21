"""Per-signal similarity functions (CONTRACTS section 4 types) + Polish explanations.

Every function takes two aggregated values (see engine.features) and returns
`(score in [0,1] | None, evidence)`. None means "cannot compare" (missing data on a side).
`evidence` is a small dict used to build a human-readable explanation.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from fakecollector.engine.mask import mask_value

Result = tuple[float | None, dict[str, Any]]


def _rescale(sim: float, floor: float) -> float:
    """Map [floor, 1] -> [0, 1]; values at/below the floor count as 0."""
    if floor <= 0.0:
        return max(0.0, min(1.0, sim))
    if sim <= floor:
        return 0.0
    return min(1.0, (sim - floor) / (1.0 - floor))


def sim_cosine(spec: dict[str, Any], a: list[np.ndarray], b: list[np.ndarray]) -> Result:
    best = None
    for va in a:
        na = float(np.linalg.norm(va))
        for vb in b:
            if va.shape != vb.shape:
                continue
            c = float(np.dot(va, vb)) / (na * float(np.linalg.norm(vb)))
            best = c if best is None else max(best, c)
    if best is None:
        return None, {}
    floor = float(spec.get("floor", 0.0))
    return _rescale(best, floor), {"raw": best, "below_floor": floor > 0 and best <= floor}


def sim_minhash(spec: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> Result:
    best = None
    for sa in a["sigs"]:
        for sb in b["sigs"]:
            if sa.shape == sb.shape:
                v = float(np.mean(sa == sb))
                best = v if best is None else max(best, v)
    if a["set"] and b["set"]:
        union = len(a["set"] | b["set"])
        v = len(a["set"] & b["set"]) / union if union else 0.0
        best = v if best is None else max(best, v)
    if best is None:
        return None, {}
    floor = float(spec.get("floor", 0.0))
    return _rescale(best, floor), {"raw": best, "below_floor": floor > 0 and best <= floor}


def sim_set_overlap(spec: dict[str, Any], a: frozenset, b: frozenset) -> Result:
    shared = sorted(a & b)
    metric = spec.get("metric")
    if metric == "count":                        # saturating count: `saturate` shared items = certain
        score = min(1.0, len(shared) / float(spec.get("saturate", 3)))
        return score, {"shared": shared}
    if metric == "overlap":                      # overlap coefficient: |A∩B| / min(|A|,|B|)
        denom = min(len(a), len(b))
    else:                                        # Jaccard (default, contract)
        denom = len(a | b)
    raw = len(shared) / denom if denom else 0.0
    floor = float(spec.get("floor", 0.0))        # e.g. text.shared_entities: one shared entity = noise
    return _rescale(raw, floor), {"shared": shared, "raw": raw, "below_floor": floor > 0 and raw <= floor}


def sim_exact(spec: dict[str, Any], a: frozenset, b: frozenset) -> Result:
    shared = sorted(a & b)
    return (1.0 if shared else 0.0), {"shared": shared}


def sim_hamming(spec: dict[str, Any], a: list[int], b: list[int]) -> Result:
    bits = int(spec.get("bits", 64))
    best = None
    for x in a:
        for y in b:
            s = 1.0 - bin(x ^ y).count("1") / bits
            best = s if best is None else max(best, s)
    if best is None:
        return None, {}
    floor = float(spec.get("floor", 0.5))        # random hashes agree on ~50% of bits: that is "no information"
    return _rescale(best, floor), {"raw": best, "below_floor": best <= floor}


def sim_numeric(spec: dict[str, Any], a: list[float], b: list[float]) -> Result:
    tol = float(spec.get("tol", 30.0))
    d = min(abs(x - y) for x in a for y in b)
    return max(0.0, 1.0 - d / tol), {"delta": d}


_DISPATCH: dict[str, Callable[..., Result]] = {
    "cosine": sim_cosine,
    "jaccard_minhash": sim_minhash,
    "set_overlap": sim_set_overlap,
    "exact": sim_exact,
    "hamming_hash": sim_hamming,
    "numeric_close": sim_numeric,
}


def compute(spec: dict[str, Any], a: Any, b: Any) -> Result:
    """Similarity of two aggregated values for one signal. None if either side is missing."""
    if a is None or b is None:
        return None, {}
    return _DISPATCH[spec["type"]](spec, a, b)


# --------------------------------------------------------------------------- explanations (PL)
LABELS_PL: dict[str, str] = {
    "shared_trackers": "wspólne identyfikatory trackerów/piksela",
    "shared_assets": "wspólne pliki strony",
    "shared_scripts": "wspólne skrypty",
    "shared_form_endpoint": "wspólny adres wysyłki formularza",
    "dom_template": "podobny szablon strony (struktura DOM)",
    "hidden_text_sim": "podobny ukryty tekst",
    "text_semantic": "podobna treść (semantyka)",
    "text_near_dup": "niemal identyczny tekst",
    "shared_entities": "wspólne osoby/marki w tekście",
    "same_platform_name": "ta sama nazwa platformy",
    "same_narrative": "ten sam typ narracji",
    "image_near_dup": "niemal identyczny obraz",
    "visual_style": "podobny styl wizualny",
    "shared_logo": "wspólne logo",
    "face_match": "podobna twarz",
    "same_identity": "ta sama osoba na materiale",
    "same_registered_domain": "ta sama domena",
    "shared_ip_asn": "wspólne IP/ASN",
    "shared_ns": "wspólne serwery nazw",
    "shared_registrar_and_date": "zbliżona data rejestracji domeny",
    "shared_ad_account": "to samo konto reklamowe",
    "same_param_template": "ten sam szablon parametrów URL reklamy",
    "same_adtech_stack": "ten sam zestaw narzędzi reklamowych",
    "shared_server_stack": "ten sam stos serwerowy",
    "cert_san_overlap": "wspólne nazwy w certyfikacie",
    "same_favicon": "ten sam favicon",
    "shared_redirector": "wspólny serwis przekierowujący",
}


def _short(value: Any, n: int = 42) -> str:
    s = mask_value(value)          # organizer identifiers never appear in full in a Reason
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(signal: str, spec: dict[str, Any], score: float, evidence: dict[str, Any]) -> str:
    """Polish, concrete one-line explanation of one signal's contribution."""
    label = spec.get("label") or LABELS_PL.get(signal, signal)
    stype = spec["type"]
    if stype in ("set_overlap", "exact"):
        shared = evidence.get("shared") or []
        if not shared:
            return f"brak: {label}"
        shown = ", ".join(_short(x) for x in shared[:3])
        more = f" (+{len(shared) - 3})" if len(shared) > 3 else ""
        return f"{label}: {shown}{more}"
    if score <= 0.0:
        return f"brak: {label}"
    if stype == "numeric_close":
        return f"{label} (różnica {evidence.get('delta', 0):.1f})"
    return f"{label} ({score:.2f})"
