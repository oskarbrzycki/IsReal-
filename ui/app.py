"""Streamlit demo: "IsReal? Od pojedynczej reklamy do całej kampanii oszustów". Owner: W1.

The UI only READS engine outputs (data/graph/*, data/features/*.parquet, data/interim/incidents.jsonl,
reports/eval_*.md) and calls fakecollector.engine.api (correlate, analyze). No correlation logic here.

SAFETY: scam HTML is never rendered. Every string that comes from the data is shown as plain text
(st.dataframe / st.text / escaped markdown) with domains defanged (example[.]com) and URLs as hxxp.
The only HTML is the graph that WE generate (pyvis), with sanitized labels and tooltips, and the static
presentation-mode CSS (no data in it).

Run:  streamlit run ui/app.py
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fakecollector.core.config import make_context, resolve_path  # noqa: E402
from fakecollector.ingest.util import etld1  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
TITLE = "IsReal? Od pojedynczej reklamy do całej kampanii oszustów"
RULE_SIGNAL = "regula_kampanii"
RULE_TEXT = "za mało twardych dowodów na tę samą kampanię"
MODULES = ["html_struct", "text", "visual", "faces", "infra"]
VIEWS = ["Kampanie i rodziny", "Graf powiązań", "Incydent", "Analiza nowego materiału", "Metodyka i wyniki"]
VIEW_KEYS = ["kampanie", "graf", "incydent", "analiza", "metodyka"]
STATUS_TEXT = {
    "known_campaign": "Znana kampania {campaign}",
    "new_campaign_known_family": "Nowa kampania, ale pasuje do rodziny {family}",
    "new_family": "Nowa kampania",
    "insufficient_data": "Za mało danych",
}
STATUS_ICON = {"known_campaign": "", "new_campaign_known_family": "", "new_family": "",
               "insufficient_data": ""}       # plain text status (no emoji): calmer, jury-friendly look
UPLOAD_TYPES = ["zip", "html", "htm", "mhtml", "png", "jpg", "jpeg", "webp", "gif"]
PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7",
           "#9c755f", "#bab0ac", "#86bcb6", "#d37295", "#8cd17d", "#b6992d", "#499894", "#79706e"]
# Vector / bulky feature columns: summarised, never dumped
BULKY_HINTS = ("emb", "minhash", "shingles", "phash", "dhash", "vector", "frames")

st.set_page_config(page_title="IsReal?", page_icon=str(ASSETS / "icon.png"), layout="wide")


# =============================================================== safety helpers

HOST_RE = re.compile(r"\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62})\b", re.I)
NOT_DOMAINS = {"md", "py", "yaml", "yml", "json", "jsonl", "parquet", "html", "htm", "css", "js", "har",
               "png", "jpg", "jpeg", "webp", "gif", "svg", "txt", "csv", "mhtml", "pobrane", "pobierz"}
MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-!|<>~])")


# Public / presentation mode (?public=1 or the toggle): for screenshots, video and the live pitch.
PUBLIC = {"on": False}
# Generic infrastructure: naming it reveals nothing about a campaign
PUBLIC_KEEP_DOMAINS = {"google.com", "google.pl", "googleapis.com", "gstatic.com", "facebook.com", "facebook.net",
                       "fbcdn.net", "jsdelivr.net", "cloudflare.com", "unpkg.com", "jquery.com", "doubleclick.net",
                       "googletagmanager.com"}
# Signals whose evidence is page/ad content (platform names, brands, people, hidden text): label only
PUBLIC_HIDE_EVIDENCE = {"same_platform_name", "shared_entities", "hidden_text_sim", "shared_logo", "same_identity",
                        "face_match", "text_keywords", "cta_phrases"}
SHORT_ID_RE = re.compile(r"\b[0-9a-f]{3,}…([0-9a-f]{4})\b", re.I)

# Presentation mode (toggle next to the public one): bigger type for the projector, "brak: ..." rows hidden.
PRESENT = {"on": False, "hide_missing": False}
BASE_CSS = """<style>
:root { --bg:#0c0d10; --panel:#13151a; --panel2:#181b21; --line:#24272e; --ink:#f5f5f4; --muted:#9a9ca4;
  --dim:#5a5c63; --red:#e5484d; }
html, body, .stApp, [data-testid="stAppViewContainer"] { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
  "Inter", "Segoe UI", Roboto, sans-serif; -webkit-font-smoothing: antialiased; }
.block-container { max-width: 1200px; padding-top: 5rem; padding-bottom: 4rem; }
[data-testid="stHeader"] { background: rgba(12,13,16,.85); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
[data-testid="stHeader"] img { height: 1.7rem; }
h1, h2, h3 { color: var(--ink); letter-spacing: -0.025em; font-weight: 600 !important; }
h1 { font-size: 2.05rem !important; line-height: 1.1 !important; padding: 0 0 .4rem !important; }
h2 { font-size: 1.45rem !important; margin-top: 2rem !important; }
h3 { font-size: 1.1rem !important; margin-top: 1.4rem !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
hr { border-color: var(--line) !important; margin: 1.6rem 0 !important; }
a { color: var(--ink); text-decoration-color: var(--red); }
[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.2rem; }
.st-key-hero_metric [data-testid="stMetric"] { border-color: var(--red); background: var(--panel2); }
[data-testid="stMetricLabel"] p { color: var(--muted) !important; font-size: .8rem !important; font-weight: 500; }
[data-testid="stMetricValue"] { font-weight: 600; letter-spacing: -0.03em; }
[data-testid="stExpander"] { background: var(--panel); border: 1px solid var(--line) !important; border-radius: 10px; }
[data-testid="stExpander"] summary:hover { color: var(--ink); }
[data-testid="stDataFrame"], [data-testid="stTable"] { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
[data-testid="stSidebar"] { background: var(--bg); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { font-size: .8rem !important; text-transform: uppercase;
  letter-spacing: .08em; color: var(--muted); font-weight: 500 !important; }
[data-testid="stButtonGroup"] button[role="radio"] { background: transparent !important; border-color: var(--line) !important; }
[data-testid="stButtonGroup"] button[role="radio"] * { color: var(--muted) !important; }
[data-testid="stButtonGroup"] button[role="radio"]:hover * { color: var(--ink) !important; }
[data-testid="stButtonGroup"] button[aria-checked="true"] { background: var(--panel2) !important; box-shadow: inset 0 -2px 0 var(--red); }
[data-testid="stButtonGroup"] button[aria-checked="true"] * { color: var(--ink) !important; font-weight: 600; }
.stButton > button, .stDownloadButton > button { border-radius: 8px; border: 1px solid var(--line); background: var(--panel2);
  color: var(--ink); font-weight: 500; transition: border-color .15s, background .15s; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--dim); background: #1e2128; color: var(--ink); }
.stButton > button[kind="primary"] { background: var(--ink); border-color: var(--ink); color: var(--bg); }
.stButton > button[kind="primary"]:hover { background: #fff; border-color: #fff; color: var(--bg); }
[data-testid="stFileUploader"] section { background: var(--panel); border: 1px dashed var(--dim); border-radius: 10px; }
[data-testid="stAlert"] { background: var(--panel) !important; border: 1px solid var(--line); border-left: 3px solid var(--red);
  border-radius: 10px; }
[data-testid="stAlert"] *, [data-testid="stAlertContainer"] { background: var(--panel) !important; color: var(--ink) !important; }
.legend { display:flex; flex-wrap:wrap; gap:.5rem 1.6rem; font-size:.82rem; color:var(--muted); margin:.2rem 0 .6rem; }
.legend i { display:inline-block; width:1.5rem; border-top:2px solid var(--ink); vertical-align:middle; margin-right:.5rem; }
.legend i.dash { border-top-style:dashed; border-color:var(--dim); } .legend i.rule { border-color:var(--red); }
.legend i.dot { width:.7rem; height:.7rem; border:3px solid var(--dim); border-radius:50%; background:var(--ink); }
.eyebrow { color: var(--red); font-size:.78rem; font-weight:600; letter-spacing:.12em; text-transform:uppercase; margin:0 0 .5rem; }
</style>"""

PRESENT_CSS = """<style>
.block-container { zoom: 1.15; max-width: 1500px; }
[data-testid="stTable"] thead th:first-child, [data-testid="stTable"] tbody th { display: none; }
[data-testid="stTable"] td, [data-testid="stTable"] th { padding: .55rem .8rem !important; font-size: .9rem; }
</style>"""


def plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Polish noun form after a number: 1 kampania / 2-4 kampanie / 5+ kampanii (12-14 -> many)."""
    n = abs(int(n))
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def count_pl(n: int, one: str, few: str, many: str) -> str:
    return f"{int(n)} {plural_pl(n, one, few, many)}"


def campaigns_pl(n: int) -> str:
    return count_pl(n, "kampania", "kampanie", "kampanii")


def incidents_pl(n: int) -> str:
    return count_pl(n, "incydent", "incydenty", "incydentów")


def families_pl(n: int) -> str:
    return count_pl(n, "rodzina", "rodziny", "rodzin")


def records_pl(n: int) -> str:
    return count_pl(n, "rekord", "rekordy", "rekordów")


def show_table(df: pd.DataFrame, **kw: Any) -> None:
    """st.dataframe normally; in presentation mode a static HTML table (canvas grids ignore CSS font size)."""
    if PRESENT["on"]:                       # column_config etc. only apply to st.dataframe
        out = df.reset_index(drop=True)
        out.index = [""] * len(out)
        st.table(out)
    else:
        st.dataframe(df, hide_index=True, use_container_width=True, **kw)


def public_ids(s: str) -> str:
    """IDs and hashes -> '…NNNN' (last 4 characters), also engine-shortened 'abcd…wxyz'."""
    s = re.sub(r"\b\d{8,}\b", lambda m: "…" + m.group(0)[-4:], s)
    s = re.sub(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{10,}\b", lambda m: "…" + m.group(0)[-4:], s, flags=re.I)
    return SHORT_ID_RE.sub(r"…\1", s)


def defang(text: Any) -> str:
    """Make every domain / URL in `text` non-clickable: example.com -> example[.]com, http -> hxxp.

    In public mode scam domains become 'domena .tld' and IDs/hashes '…NNNN'.
    """
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"(?i)\bhttp(s?)://", r"hxxp\1://", s)

    def repl(m: re.Match) -> str:
        host = m.group(1)
        reg = etld1(host.lower())
        if host.rsplit(".", 1)[-1].lower() in NOT_DOMAINS or not reg:
            return host
        if PUBLIC["on"] and reg not in PUBLIC_KEEP_DOMAINS:
            return "domena ." + host.rsplit(".", 1)[-1].lower()
        return host.replace(".", "[.]")

    s = HOST_RE.sub(repl, s)
    return public_ids(s) if PUBLIC["on"] else s


def public_detail(signal: str | None, detail: Any) -> str:
    """Reason text for display; in public mode content-type evidence is reduced to the signal label."""
    text = defang(detail)
    if text.startswith("brak:"):        # "no match on <signal>": nothing to hide
        return text
    if PUBLIC["on"] and signal in PUBLIC_HIDE_EVIDENCE and ":" in text:
        return text.split(":", 1)[0] + ": [ukryte w trybie publicznym]"
    return text


def public_label(label: Any, fallback: str = "-") -> str:
    """Campaign/family labels come from page content (platform names, brands): hidden in public mode."""
    return fallback if PUBLIC["on"] else defang(label)


def md_safe(text: Any) -> str:
    """Defanged text that is safe to embed in st.markdown (no links, no HTML, no formatting)."""
    return MD_SPECIAL.sub(r"\\\1", defang(text))


def plain(text: Any) -> str:
    """Defanged text without HTML-significant characters (for pyvis labels/tooltips)."""
    return re.sub(r"[<>&\"'`]", " ", defang(text))


def short_value(v: Any, limit: int = 160) -> str:
    """Compact, defanged representation of a feature value for tables."""
    if v is None or (isinstance(v, float) and v != v):
        return "-"
    if hasattr(v, "tolist"):
        v = v.tolist()
    if isinstance(v, (list, tuple)):
        if v and all(isinstance(x, (int, float)) for x in v) and len(v) > 8:
            return f"wektor[{len(v)}]"
        if not v:
            return "[]"
        items = [short_value(x, 60) for x in v[:8]]
        more = f" … (+{len(v) - 8})" if len(v) > 8 else ""
        return defang(", ".join(items) + more)[:limit]
    if isinstance(v, dict):
        return defang(json.dumps(v, ensure_ascii=False, default=str))[:limit]
    s = defang(v)
    return s if len(s) <= limit else s[: limit - 1] + "…"


LONG_DIGITS_RE = re.compile(r"\b\d{8,}\b")
LONG_HEX_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{12,}\b", re.I)


def mask_ids(text: Any) -> str:
    """Analyst-safe text: domains defanged, long numeric IDs (pixels, ad accounts) and hashes masked."""
    s = defang(text)
    s = LONG_DIGITS_RE.sub(lambda m: f"{m.group(0)[:4]}…{m.group(0)[-4:]}", s)
    return LONG_HEX_RE.sub(lambda m: f"{m.group(0)[:6]}…{m.group(0)[-2:]}", s)


def human_size(n: Any) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# =============================================================== data loading (read-only)

@st.cache_resource
def get_ctx():
    return make_context()


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def paths() -> dict[str, Path]:
    ctx = get_ctx()
    return {"graph": resolve_path(ctx, "graph"), "features": resolve_path(ctx, "features"),
            "interim": resolve_path(ctx, "interim"), "reports": REPO_ROOT / "reports",
            "uploads": ctx.data_dir / "uploads"}


@st.cache_data(show_spinner=False)
def load_clusters(path: str, _mt: float) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"params": {}, "clusters": [], "families": [], "duplicate_groups": []}
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_edges(path: str, _mt: float) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=["level", "a", "b", "score", "n_signals", "reasons"])
    df = pd.read_parquet(p)
    df["reasons"] = df["reasons"].map(lambda r: json.loads(r) if isinstance(r, str) else (r or []))
    df["rule"] = df["reasons"].map(lambda rs: any(x.get("signal") == RULE_SIGNAL for x in rs))
    return df


@st.cache_data(show_spinner=False)
def load_incidents(path: str, _mt: float) -> dict[str, dict[str, Any]]:
    p = Path(path)
    out: dict[str, dict[str, Any]] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["incident_id"]] = d
    return out


@st.cache_data(show_spinner=False)
def load_feature_table(path: str, _mt: float) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_settings(_mt: float) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}


def _fallback_label(name: str) -> str:
    try:
        from fakecollector.engine.similarity import LABELS_PL
        return LABELS_PL.get(name, "")
    except ImportError:
        return ""


@st.cache_data(show_spinner=False)
def signal_table(_mt: float) -> pd.DataFrame:
    """Signals declared by the feature modules + weights from settings.yaml (read-only)."""
    from fakecollector.engine.features import collect_signals

    settings = load_settings(_mt)
    eng = settings.get("engine", {}) or {}
    weights = eng.get("weights", {}) or {}
    default_w = float(eng.get("default_weight", 1.0))
    hard = set(eng.get("hard_identifiers", []) or [])
    try:
        sigs = collect_signals(eng.get("signal_params"), classes=eng.get("signal_classes"))
    except TypeError:
        sigs = collect_signals(eng.get("signal_params"))
    rows = []
    for name, spec in sorted(sigs.items()):
        rows.append({
            "sygnał": name,
            "opis": spec.get("label") or _fallback_label(name),
            "moduł": spec.get("module", ""),
            "klasa": spec.get("class", "campaign"),
            "waga": float(weights.get(name, default_w)),
            "twardy identyfikator": "tak" if name in hard else "",
            "typ podobieństwa": spec.get("type", ""),
        })
    return pd.DataFrame(rows).sort_values(["klasa", "waga"], ascending=[True, False])


def label_of(signals_df: pd.DataFrame) -> dict[str, str]:
    """Polish label per signal: module's SIGNALS[...]["label"], engine LABELS_PL as fallback."""
    try:
        from fakecollector.engine.similarity import LABELS_PL
    except ImportError:
        LABELS_PL = {}
    out = dict(LABELS_PL)
    if not signals_df.empty:
        out.update({k: v for k, v in zip(signals_df["sygnał"], signals_df["opis"]) if v})
    return out


def state() -> dict[str, Any]:
    p = paths()
    clusters = load_clusters(str(p["graph"] / "clusters.json"), _mtime(p["graph"] / "clusters.json"))
    edges = load_edges(str(p["graph"] / "edges.parquet"), _mtime(p["graph"] / "edges.parquet"))
    incidents = load_incidents(str(p["interim"] / "incidents.jsonl"), _mtime(p["interim"] / "incidents.jsonl"))
    camp_of: dict[str, str] = {}
    for c in clusters.get("clusters", []):
        for m in c["members"]:
            camp_of[m] = c["campaign_id"]
    fam_of_camp = {c["campaign_id"]: c.get("family_id") for c in clusters.get("clusters", [])}
    sig_df = signal_table(_mtime(REPO_ROOT / "config" / "settings.yaml"))
    return {"clusters": clusters, "edges": edges, "incidents": incidents, "camp_of": camp_of,
            "fam_of_camp": fam_of_camp, "signals": sig_df, "labels": label_of(sig_df)}


def clear_caches() -> None:
    st.cache_data.clear()


# =============================================================== shared widgets

def reasons_frame(reasons: list[dict[str, Any]], only_positive: bool = False,
                  hide_missing: bool | None = None) -> pd.DataFrame:
    hide_missing = PRESENT["hide_missing"] if hide_missing is None else hide_missing
    rows = []
    for r in reasons:
        if r.get("signal") == RULE_SIGNAL:
            rows.append({"przesłanka": "Uwaga: " + defang(r.get("detail")), "sygnał": "reguła kampanii",
                         "podobieństwo": None, "waga": None, "wkład": None})
            continue
        score, weight = float(r.get("score") or 0), float(r.get("weight") or 0)
        if only_positive and score <= 0:
            continue
        if hide_missing and str(r.get("detail") or "").startswith("brak:"):
            continue
        rows.append({"przesłanka": public_detail(r.get("signal"), r.get("detail")), "sygnał": r.get("signal"),
                     "podobieństwo": round(score, 3), "waga": weight, "wkład": round(score * weight, 3)})
    return pd.DataFrame(rows)


def key_edge_index(edges: list[dict[str, Any]]) -> int:
    """The edge worth opening first: one carrying the campaign-rule message, else the highest score."""
    for i, e in enumerate(edges):
        if any(r.get("signal") == RULE_SIGNAL for r in e["reasons"]):
            return i
    return max(range(len(edges)), key=lambda i: float(edges[i]["score"]))


def show_edges_list(edges: list[dict[str, Any]], s: dict[str, Any], me: str | None = None,
                    only_key_open: bool = False) -> None:
    """Neighbours with expandable reasons. `edges` rows: level, a, b, score, reasons.
    only_key_open: all collapsed except the most important one (analysis result)."""
    if not edges:
        st.info("Brak powiązań powyżej progu zapisu krawędzi.")
        return
    key = key_edge_index(edges) if only_key_open else -1
    for i, e in enumerate(edges):
        other = e["b"] if me and e["a"] == me else (e["a"] if me else f"{e['a']} ↔ {e['b']}")
        camp = s["camp_of"].get(other, "-") if me else ""
        fam = s["fam_of_camp"].get(camp, "-") if me else ""
        lvl = "kampania" if e["level"] == "campaign" else "rodzina"
        rule = " · odrzucona jako kampania" if any(r.get("signal") == RULE_SIGNAL for r in e["reasons"]) else ""
        head = f"{md_safe(other)} · poziom: {lvl} · wynik {float(e['score']):.2f}"
        if me:
            head += f" · {md_safe(camp)} / {md_safe(fam)}"
        with st.expander(head + rule, expanded=(i == key)):
            show_table(reasons_frame(e["reasons"]))


def edge_to_dict(e) -> dict[str, Any]:
    """engine Edge dataclass -> plain dict with reasons as dicts."""
    if isinstance(e, dict):
        return e
    return {"level": getattr(e, "level", "campaign"), "a": e.a, "b": e.b, "score": e.score,
            "reasons": [r.__dict__ if not isinstance(r, dict) else r for r in e.reasons]}


# =============================================================== analyst report (export)

def _top_reasons(edges: list[dict[str, Any]], labels: dict[str, str], k: int = 5) -> list[dict[str, Any]]:
    """Strongest positive reasons over the given engine edges (one entry per signal, best example)."""
    best: dict[str, dict[str, Any]] = {}
    for e in edges:
        for r in e["reasons"]:
            if r.get("signal") == RULE_SIGNAL:
                continue
            score, weight = float(r.get("score") or 0), float(r.get("weight") or 0)
            if score <= 0:
                continue
            sig = r.get("signal")
            if sig not in best or score * weight > best[sig]["wkład"]:
                best[sig] = {"sygnał": sig, "opis": labels.get(sig) or sig, "podobieństwo": round(score, 3),
                             "waga": weight, "wkład": round(score * weight, 3),
                             "przesłanka": mask_ids(public_detail(sig, r.get("detail"))),
                             "para": f"{e['a']} ↔ {e['b']}",
                             "poziom": "kampania" if e["level"] == "campaign" else "rodzina"}
    return sorted(best.values(), key=lambda x: x["wkład"], reverse=True)[:k]


def build_campaign_report(s: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """(JSON payload, CSV text) for analysts: campaign, family, incidents, top reasons (IDs masked).

    Only re-formats engine outputs (clusters.json + edges.parquet); no scoring happens here.
    """
    cl, labels = s["clusters"], s["labels"]
    edges = s["edges"].to_dict("records") if not s["edges"].empty else []
    fams = {f["family_id"]: f for f in cl.get("families", [])}
    campaigns, rows = [], []
    for c in sorted(cl.get("clusters", []), key=lambda c: (-len(c["members"]), c["campaign_id"])):
        members = set(c["members"])
        fam = fams.get(c.get("family_id") or "", {})
        fam_members = set(fam.get("members", [])) or members
        internal = [e for e in edges if e["level"] == "campaign" and e["a"] in members and e["b"] in members]
        family = [e for e in edges if e["level"] == "family" and e["a"] in fam_members and e["b"] in fam_members
                  and (e["a"] in members or e["b"] in members)]
        rejected = [e for e in family if e.get("rule")]
        top = _top_reasons(internal, labels) if internal else []
        fam_top = _top_reasons(family, labels, k=3)
        entry = {
            "kampania": c["campaign_id"], "etykieta": mask_ids(public_label(c.get("label", ""))),
            "rodzina": c.get("family_id"), "etykieta_rodziny": mask_ids(public_label(fam.get("label", ""))),
            "liczba_incydentów": len(members), "incydenty": sorted(members),
            "spójność": round(float(c.get("cohesion", 0)), 3),
            "główne_sygnały": [labels.get(x) or x for x in c.get("top_signals", [])],
            "przesłanki_kampanii": top, "przesłanki_rodziny": fam_top,
            "odrzucone_jako_kampania": [{"para": f"{e['a']} ↔ {e['b']}", "powód": RULE_TEXT} for e in rejected],
        }
        campaigns.append(entry)
        rows.append({
            "kampania": entry["kampania"], "rodzina": entry["rodzina"] or "",
            "etykieta": entry["etykieta"], "liczba_incydentów": entry["liczba_incydentów"],
            "incydenty": ", ".join(entry["incydenty"]), "spójność": entry["spójność"],
            "główne_sygnały": ", ".join(entry["główne_sygnały"]),
            "top_przesłanki_kampanii": " | ".join(f"{r['przesłanka']} (wkład {r['wkład']})" for r in top),
            "top_przesłanki_rodziny": " | ".join(f"{r['przesłanka']} (wkład {r['wkład']})" for r in fam_top),
            "odrzucone_jako_kampania": " | ".join(x["para"] for x in entry["odrzucone_jako_kampania"]),
        })
    payload = {
        "narzędzie": TITLE,
        "wygenerowano": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "parametry": cl.get("params", {}),
        "uwaga": "Identyfikatory (piksele, konta reklamowe, hashe plików) są zamaskowane, domeny zapisane "
                 "jako example[.]com. Przesłanki pochodzą wprost z krawędzi silnika (wynik = podobieństwo × waga).",
        "kampanie": campaigns,
        "rodziny": [{"rodzina": f["family_id"], "etykieta": mask_ids(public_label(f.get("label", ""))),
                     "kampanie": f.get("campaigns", []), "incydenty": f.get("members", []),
                     "sygnały": [labels.get(x) or x for x in f.get("top_signals", [])]}
                    for f in cl.get("families", [])],
    }
    # ';' + BOM: opens correctly in Polish-locale Excel
    csv_text = pd.DataFrame(rows).to_csv(index=False, sep=";")
    return payload, "﻿" + csv_text


def report_downloads(s: dict[str, Any]) -> None:
    payload, csv_text = build_campaign_report(s)
    stamp = time.strftime("%Y%m%d_%H%M")
    st.download_button("Pobierz raport kampanii (JSON)",
                       json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=f"raport_kampanii_{stamp}.json", mime="application/json",
                       use_container_width=True)
    st.download_button("Pobierz raport kampanii (CSV)", csv_text.encode("utf-8"),
                       file_name=f"raport_kampanii_{stamp}.csv", mime="text/csv", use_container_width=True)
    st.caption("Raport dla analityka: kampania, rodzina, incydenty, najważniejsze przesłanki. "
               "ID zamaskowane, domeny niekilkalne.")


# =============================================================== view 1: campaigns & families

def view_campaigns(s: dict[str, Any]) -> None:
    cl = s["clusters"]
    clusters, families = cl.get("clusters", []), cl.get("families", [])
    c1, c2, c3, c4 = st.columns(4)
    multi = sum(1 for c in clusters if len(c["members"]) > 1)
    c1.metric("Incydenty", len(s["incidents"]) or cl.get("params", {}).get("n_incidents", 0))
    with c2, st.container(key="hero_metric"):
        st.metric("Kampanie wieloincydentowe", multi,
                  help="Kampanie, w których system powiązał co najmniej 2 zgłoszenia. To one pokazują skalę oszustwa.")
    c3.metric("Pojedyncze zgłoszenia", len(clusters) - multi,
              help="Kampanie z jednym incydentem, bez powiązań z innymi zgłoszeniami.")
    c4.metric("Rodziny", len(families))

    left, right = st.columns([3, 1])
    with right:
        if st.button("Przelicz", help="Uruchamia correlate(): krawędzie, kampanie i rodziny z bieżących cech",
                     use_container_width=True):
            from fakecollector.engine import api
            t0 = time.time()
            with st.spinner("Liczę podobieństwa i grupuję…"):
                api.correlate(get_ctx())
            clear_caches()
            st.success(f"Przeliczono w {time.time() - t0:.1f} s")
            st.rerun()
        p = cl.get("params", {})
        st.caption(f"Progi: kampania ≥ {p.get('tau_campaign', '-')}, rodzina ≥ {p.get('tau_family', '-')}, "
                   f"nowa kampania < {p.get('tau_new', '-')} · metoda: {p.get('method', '-')}")
        if clusters:
            report_downloads(s)

    if not clusters:
        left.warning("Brak data/graph/clusters.json: uruchom „Przelicz” (po `ingest` i `features`).")
        return
    labels = s["labels"]
    fam_by_id = {f["family_id"]: f for f in families}
    rows = []
    for c in sorted(clusters, key=lambda c: (c.get("family_id") or "", c["campaign_id"])):
        fam = fam_by_id.get(c.get("family_id") or "", {})
        rows.append({
            "rodzina": c.get("family_id") or "-",
            "etykieta rodziny": public_label(fam.get("label", "")),
            "kampania": c["campaign_id"],
            "etykieta kampanii": public_label(c.get("label", "")),
            "liczba incydentów": len(c["members"]),
            "incydenty": ", ".join(c["members"]),
            "główne sygnały": ", ".join(labels.get(x, x) or x for x in c.get("top_signals", [])) or "-",
            "spójność (cohesion)": round(float(c.get("cohesion", 0)), 3),
        })
    with left:
        st.subheader("Rodziny → kampanie → incydenty")
        show_table(pd.DataFrame(rows), column_config={"spójność (cohesion)": st.column_config.ProgressColumn(
            min_value=0.0, max_value=1.0, format="%.2f")})

    st.subheader("Rodziny")
    for f in families:
        n_c = len(f.get("campaigns", []))
        with st.expander(f"{f['family_id']} · {md_safe(public_label(f.get('label', '')))} · {campaigns_pl(n_c)}, "
                         f"{incidents_pl(len(f.get('members', [])))}"):
            st.write("Kampanie:", ", ".join(f.get("campaigns", [])))
            st.write("Incydenty:", ", ".join(f.get("members", [])))
            st.write("Sygnały łączące rodzinę:",
                     ", ".join(labels.get(x, x) or x for x in f.get("top_signals", [])) or "-")
    if cl.get("duplicate_groups"):
        st.subheader("Grupy duplikatów")
        st.write([", ".join(g) for g in cl["duplicate_groups"]])


# =============================================================== view 2: graph

GRAPH_CSS = ("<style>html,body{margin:0;background:#0c0d10!important;color:#f5f5f4}"
             ".card{border:1px solid #24272e!important;border-radius:10px;background:#0c0d10!important;overflow:hidden}"
             "#mynetwork{border:0!important;background:#0c0d10!important}"
             "div.vis-tooltip{background:#181b21!important;color:#f5f5f4!important;border:1px solid #24272e!important;"
             "border-radius:8px;font-family:-apple-system,system-ui,sans-serif;font-size:12px;padding:8px 10px}</style>")


def build_graph_html(s: dict[str, Any], show_family: bool, show_rule: bool, min_score: float) -> str:
    from pyvis.network import Network

    camp_of, fam_of_camp = s["camp_of"], s["fam_of_camp"]
    camps = sorted({c["campaign_id"] for c in s["clusters"].get("clusters", [])})
    fams = sorted({f["family_id"] for f in s["clusters"].get("families", [])})
    ccol = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(camps)}
    fcol = {f: PALETTE[(i * 5 + 3) % len(PALETTE)] for i, f in enumerate(fams)}

    net = Network(height="680px", width="100%", bgcolor="#0c0d10", font_color="#f5f5f4",
                  cdn_resources="in_line", notebook=False)
    nodes = sorted(set(s["incidents"]) | set(camp_of))
    for n in nodes:
        camp = camp_of.get(n, "-")
        fam = fam_of_camp.get(camp) or "-"
        inc = s["incidents"].get(n, {})
        kinds = inc.get("meta", {}).get("kinds", {})
        tip = (f"{n}\nkampania: {camp}\nrodzina: {fam}\n"
               + ", ".join(f"{k}: {v}" for k, v in sorted(kinds.items())))
        net.add_node(n, label=f"{n}\n{camp}", title=plain(tip), shape="dot", size=26, borderWidth=5,
                     color={"background": ccol.get(camp, "#cccccc"), "border": fcol.get(fam, "#888888"),
                            "highlight": {"background": ccol.get(camp, "#cccccc"), "border": "#000000"}})
    for e in s["edges"].to_dict("records"):
        if e["a"] not in nodes or e["b"] not in nodes or float(e["score"]) < min_score:
            continue
        is_rule, lvl = bool(e.get("rule")), e["level"]
        if lvl == "family" and not (show_rule if is_rule else show_family):
            continue
        lines = [f"{'KAMPANIA' if lvl == 'campaign' else 'RODZINA'}  {e['a']} ↔ {e['b']}  wynik {float(e['score']):.2f}"]
        for r in e["reasons"]:
            if r.get("signal") == RULE_SIGNAL:
                lines.append(f"Uwaga: {r.get('detail')}")
            elif float(r.get("score") or 0) > 0:
                lines.append(f"• {public_detail(r.get('signal'), r.get('detail'))}  (waga {float(r.get('weight') or 0):g}, "
                             f"sim {float(r.get('score') or 0):.2f})")
        color = ("#f5f5f4" if lvl == "campaign" else
                 ("rgba(229,72,77,0.6)" if is_rule else "rgba(154,156,164,0.55)"))
        net.add_edge(e["a"], e["b"], title=plain("\n".join(lines)), width=1 + 3 * float(e["score"]),
                     dashes=lvl != "campaign", color=color,
                     label="", font={"size": 12, "color": "#e5484d", "strokeWidth": 4, "strokeColor": "#0c0d10"})
    net.set_options(json.dumps({
        "physics": {"barnesHut": {"gravitationalConstant": -16000, "springLength": 220, "avoidOverlap": 0.8},
                    "stabilization": {"iterations": 250}},
        "interaction": {"hover": True, "tooltipDelay": 80},
        "edges": {"smooth": False},
        "nodes": {"font": {"size": 17, "face": "system-ui, sans-serif", "multi": False,
                           "strokeWidth": 5, "strokeColor": "#0c0d10"}},
    }))
    html = net.generate_html(notebook=False)
    return html.replace("</head>", GRAPH_CSS + "</head>", 1)


def view_graph(s: dict[str, Any]) -> None:
    if s["edges"].empty and not s["incidents"]:
        st.warning("Brak danych grafu: uruchom „Przelicz” w zakładce Kampanie i rodziny.")
        return
    c1, c2, c3 = st.columns([1, 1, 2])
    show_family = c1.checkbox("Krawędzie rodziny", value=True)
    show_rule = c2.checkbox("Odrzucone regułą", value=True)
    min_score = c3.slider("Minimalny wynik krawędzi", 0.0, 1.0, 0.2, 0.05)
    st.markdown('<div class="legend"><span><i class="dot"></i>węzeł = incydent (wypełnienie: kampania, obwódka: rodzina)</span>'
                '<span><i></i>ta sama kampania</span><span><i class="dash"></i>ta sama rodzina</span>'
                '<span><i class="rule"></i>odrzucona regułą</span></div>', unsafe_allow_html=True)
    st.caption("Najedź na krawędź, aby zobaczyć przesłanki z wagami. Czerwona krawędź: „" + RULE_TEXT + "”.")
    import streamlit.components.v1 as components

    components.html(build_graph_html(s, show_family, show_rule, min_score), height=700, scrolling=False)

    rule_edges = s["edges"][s["edges"]["rule"]]
    st.subheader(f"Krawędzie odrzucone regułą kampanii ({len(rule_edges)})")
    if rule_edges.empty:
        st.caption("Brak: każda para z sygnałami klasy „campaign” spełnia regułę twardych dowodów.")
    for e in rule_edges.to_dict("records"):
        note = next((r.get("detail") for r in e["reasons"] if r.get("signal") == RULE_SIGNAL), RULE_TEXT)
        st.warning(f"{md_safe(e['a'])} ↔ {md_safe(e['b'])}: {md_safe(note)}")

    st.subheader("Wszystkie krawędzie")
    opts = [f"{e['level']} · {e['a']} ↔ {e['b']} · {float(e['score']):.2f}" for e in s["edges"].to_dict("records")]
    if opts:
        pick = st.selectbox("Wybierz krawędź, aby zobaczyć przesłanki", opts)
        e = s["edges"].to_dict("records")[opts.index(pick)]
        show_table(reasons_frame(e["reasons"]))


# =============================================================== view 3: incident

def _thumb(path: Path, width: int = 360) -> bytes | None:
    """Downscaled PNG bytes of a local screenshot (read from data/, never from the network)."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.thumbnail((width, width * 3))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=80)
            return buf.getvalue()
    except Exception:
        return None


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Transpose feature rows (one column per material) into a readable, defanged table."""
    skip = {"incident_id", "level", "module", "provenance"}
    cols = [c for c in df.columns if c not in skip]
    out = {}
    for _, row in df.iterrows():
        name = str(row.get("entity_id"))[:16] + ("…" if len(str(row.get("entity_id"))) > 16 else "")
        vals = {}
        for c in cols:
            if c == "entity_id":
                continue
            v = row[c]
            if any(h in c.lower() for h in BULKY_HINTS) and v is not None and not isinstance(v, str):
                n = len(v) if hasattr(v, "__len__") else 1
                vals[c] = f"(dane binarne/wektor, {n} el.)"
            else:
                vals[c] = short_value(v)
        out[name] = vals
    return pd.DataFrame(out)


def view_incident(s: dict[str, Any]) -> None:
    incs = s["incidents"]
    if not incs:
        st.warning("Brak data/interim/incidents.jsonl: uruchom `python -m fakecollector ingest`.")
        return
    ids = list(incs)
    default = st.query_params.get("incident")
    pick = st.selectbox("Incydent", ids, index=ids.index(default) if default in ids else 0,
                        format_func=lambda i: f"{i} · {s['camp_of'].get(i, '-')} / "
                                              f"{s['fam_of_camp'].get(s['camp_of'].get(i, ''), '-')}")
    inc = incs[pick]
    meta = inc.get("meta", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kampania", s["camp_of"].get(pick, "-"))
    c2.metric("Rodzina", s["fam_of_camp"].get(s["camp_of"].get(pick, ""), "-") or "-")
    c3.metric("Materiały", meta.get("n_materials", len(inc.get("materials", []))))
    c4.metric("Strony (landing)", meta.get("n_pages", 0))
    if meta.get("landing_urls"):
        st.text("Adresy stron (tylko tekst): " + " | ".join(defang(u)[:140] for u in meta["landing_urls"]))

    st.subheader("Materiały")
    show_assets = st.checkbox("Pokaż też pliki zasobów strony (assety)", value=False)
    mats = [m for m in inc.get("materials", []) if show_assets or m["kind"] != "asset"]
    st.dataframe(pd.DataFrame([{
        "typ": m["kind"],
        "nazwa": ("«plik»" + Path(m.get("meta", {}).get("name", "")).suffix) if PUBLIC["on"]
        else defang(m.get("meta", {}).get("name", "")),
        "rozmiar": human_size(m.get("size_bytes")), "mime": m.get("mime") or "",
        "biblioteka/szum": "tak" if m.get("is_common_lib") else "",
        "łańcuch": m.get("meta", {}).get("chain_index", ""), "material_id": m["material_id"],
    } for m in mats]), hide_index=True, use_container_width=True)

    shots = [] if PUBLIC["on"] else [m for m in inc.get("materials", []) if m["kind"] == "image"]
    if shots and st.checkbox(f"Pokaż miniatury zrzutów ({len(shots)}, tylko lokalnie z data/)", value=False):
        cols = st.columns(min(4, len(shots)))
        for i, m in enumerate(shots[:8]):
            p = Path(m["path"])
            p = p if p.is_absolute() else REPO_ROOT / p
            data = _thumb(p)
            if data:
                cols[i % len(cols)].image(data, caption=defang(m.get("meta", {}).get("name", ""))[:40])

    st.subheader("Cechy według modułu")
    if PUBLIC["on"]:
        st.caption("Tryb publiczny: wartości cech (tytuły, teksty, domeny stron) są ukryte. "
                   "Poniżej tylko liczba rekordów na moduł.")
    feat_dir = paths()["features"]
    mat_ids = {m["material_id"] for m in inc.get("materials", [])}
    for mod in MODULES:
        fp = feat_dir / f"{mod}.parquet"
        df = load_feature_table(str(fp), _mtime(fp))
        if df.empty:
            st.caption(f"{mod}: brak pliku cech")
            continue
        sub = df[(df.get("incident_id") == pick) | df["entity_id"].astype(str).str.split("#").str[0].isin(mat_ids)]
        n_err = int(sub["errors"].map(lambda e: len(e) if e is not None else 0).gt(0).sum()) if "errors" in sub else 0
        with st.expander(f"{mod} · {records_pl(len(sub))}" + (f", {n_err} z błędami" if n_err else "")):
            if sub.empty:
                st.caption("Brak rekordów tego modułu dla incydentu (np. brak obsługiwanych materiałów).")
            elif PUBLIC["on"]:
                st.caption(f"{records_pl(len(sub))} (wartości ukryte w trybie publicznym).")
            else:
                st.dataframe(feature_frame(sub.head(12)), use_container_width=True)
                if len(sub) > 12:
                    st.caption(f"Pokazano 12 z {len(sub)} rekordów (np. klatki wideo).")

    st.subheader("Najbardziej podobne incydenty (top 5)")
    e = s["edges"]
    near = e[(e["a"] == pick) | (e["b"] == pick)].sort_values("score", ascending=False).head(5)
    show_edges_list(near.to_dict("records"), s, me=pick)


# =============================================================== view 4: analyze new material

def engine_supports_exclude() -> bool:
    """True when the installed engine.api.analyze accepts `exclude_incidents` (W5, CONTRACTS v0.5)."""
    import inspect

    try:
        from fakecollector.engine import api
        return "exclude_incidents" in inspect.signature(api.analyze).parameters
    except Exception:
        return False


def demo_exclude_picker(s: dict[str, Any]) -> list[str]:
    """'Demo mode': compare the upload against the base without the chosen incidents (in memory)."""
    supported = engine_supports_exclude()
    with st.expander("Tryb demo: wyklucz incydenty z bazy", expanded=False):
        st.caption("Pozwala pokazać na żywo „nową kampanię”: np. wgraj folder 47 i wyklucz nask:47, "
                   "a narzędzie oceni go tak, jakby nigdy go nie widziało. Wykluczenie działa tylko "
                   "w pamięci, na czas tej analizy.")
        if not supported:
            st.caption("Wymaga wersji silnika z `analyze(..., exclude_incidents=...)` (W5), "
                       "opcja aktywna po jej scaleniu.")
        picked = st.multiselect("Incydenty do wykluczenia", sorted(s["incidents"]), disabled=not supported,
                                placeholder="np. nask:47")
    return list(picked) if supported else []


def saved_ids_for(res, s: dict[str, Any]) -> tuple[str | None, str | None]:
    """Display-only: campaign/family IDs as in the SAVED base (clusters.json).

    With exclude_incidents the engine regroups the base in memory and numbers groups anew, so its
    C00x may not match the "Kampanie i rodziny" table. We show the saved IDs of the best neighbour
    the engine itself returned (no scoring here).
    """
    me = res.incident_id

    def best_other(edges) -> str | None:
        edges = sorted(edges or [], key=lambda e: float(e.score), reverse=True)
        return next(((e.b if e.a == me else e.a) for e in edges), None)

    camp = fam = None
    if res.campaign_id:
        other = best_other(res.nearest)
        camp = s["camp_of"].get(other) if other else None
        fam = s["fam_of_camp"].get(camp) if camp else None
    if getattr(res, "family_id", None) and not fam:
        other = best_other(getattr(res, "family_nearest", None)) or best_other(res.nearest)
        fam = s["fam_of_camp"].get(s["camp_of"].get(other, ""), None) if other else None
    return camp, fam


def _reason_label_count(detail: str) -> str:
    """'wspólne piksele: fb:1234…5678, fb:… (+3)' -> 'wspólne piksele (5)'; 'label (0.82)' -> 'label'."""
    head, sep, tail = str(detail).partition(":")
    if not sep:
        return re.sub(r"\s*\([^)]*\)\s*$", "", head).strip()
    n = len([x for x in tail.split(",") if x.strip()])
    m = re.search(r"\(\+(\d+)\)\s*$", tail)
    n += int(m.group(1)) if m else 0
    return f"{head.strip()} ({n})" if n > 1 else head.strip()


def analysis_sentence(res: Any, status: str, camp_id: str | None, fam_id: str | None, tau_new: float) -> str:
    """One plain-language sentence for the top of the analysis result, built only from the engine's reasons."""
    nearest = [edge_to_dict(e) for e in (res.nearest or [])]
    if status == "known_campaign" and camp_id:
        best = max(nearest, key=lambda e: float(e["score"])) if nearest else None
        top = sorted((r for r in (best["reasons"] if best else [])
                      if r.get("signal") != RULE_SIGNAL and float(r.get("score") or 0) > 0
                      and not str(r.get("detail") or "").startswith("brak:")),
                     key=lambda r: -float(r.get("score") or 0) * float(r.get("weight") or 0))[:2]
        labels = [_reason_label_count(public_detail(r.get("signal"), r.get("detail"))) for r in top]
        if labels:
            return f"Ten materiał ma wspólne ślady ze zgłoszeniami z kampanii {camp_id}: " + " i ".join(labels) + "."
        return f"Ten materiał pasuje do zgłoszeń z kampanii {camp_id}."
    if status == "insufficient_data":
        return "Za mało danych w materiale, żeby porównać go z bazą kampanii."
    score = getattr(res, "closest_score", None)
    if score is None and nearest:
        score = max(float(e["score"]) for e in nearest)
    text = "Nie znaleziono twardych dowodów powiązania."
    if score is not None:
        text += f" Najbliższe znane zgłoszenie pasuje w {100 * float(score):.0f}% (próg {100 * float(tau_new):.0f}%)."
    if status == "new_campaign_known_family" and fam_id:
        text += f" Wzorzec pasuje do rodziny {fam_id}."
    return text


def view_analyze(s: dict[str, Any]) -> None:
    st.write("Wgraj pojedynczy materiał: **zip** z zapisem strony (plik HTML + folder *_files*), "
             "plik **HTML/MHTML** albo **obraz** reklamy. Materiał zostanie porównany z bazą kampanii.")
    st.caption("Plik trafia tylko do data/uploads/ (poza gitem). Nic nie jest otwierane w przeglądarce "
               "ani pobierane z sieci, analiza jest statyczna.")
    up = st.file_uploader("Nowy materiał", type=UPLOAD_TYPES)
    if not s["clusters"].get("clusters"):
        st.warning("Baza kampanii jest pusta, najpierw „Przelicz” w zakładce Kampanie i rodziny.")
    exclude = demo_exclude_picker(s)
    if up is None or not st.button("Analizuj", type="primary"):
        return
    updir = paths()["uploads"]
    updir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]+", "_", Path(up.name).name)[:120] or "upload"
    target = updir / f"{time.strftime('%Y%m%dT%H%M%S')}_{safe_name}"
    target.write_bytes(up.getbuffer())

    from fakecollector.engine import api

    t0 = time.time()
    try:
        with st.spinner("Wyciągam cechy i porównuję z bazą kampanii…"):
            res = (api.analyze(target, get_ctx(), exclude_incidents=exclude) if exclude
                   else api.analyze(target, get_ctx()))
    except Exception as exc:
        st.error(f"Analiza nie powiodła się: {md_safe(type(exc).__name__)}: {md_safe(exc)}")
        return
    dt = time.time() - t0
    if exclude:
        st.info("Tryb demo: porównano z bazą BEZ incydentów: " + ", ".join(exclude) +
                " (wykluczenie tylko w pamięci, zapisane wyniki bez zmian).")
    status = getattr(res, "status", None) or ("known_campaign" if res.campaign_id else "new_family")
    camp_id, fam_id = res.campaign_id, getattr(res, "family_id", None)
    if exclude:
        camp_id, fam_id = saved_ids_for(res, s)
    text = STATUS_TEXT.get(status, status).format(campaign=camp_id or "-", family=fam_id or "-")
    camp = next((c for c in s["clusters"].get("clusters", []) if c["campaign_id"] == camp_id), None)
    st.markdown(f"# {md_safe(text)}")
    tau_new = float(s["clusters"].get("params", {}).get("tau_new") or load_settings(0).get("engine", {}).get("tau_new", 0.35))
    st.markdown(f"**{md_safe(analysis_sentence(res, status, camp_id, fam_id, tau_new))}**")
    if camp:
        if not PUBLIC["on"]:
            st.markdown(f"### {md_safe(camp.get('label', ''))}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pewność (kampania)", f"{float(res.confidence or 0):.2f}")
    c2.metric("Pewność (rodzina)", f"{float(getattr(res, 'family_confidence', 0) or 0):.2f}")
    c3.metric("Czas analizy", f"{dt:.1f} s")

    st.subheader("Przesłanki i najbliżsi sąsiedzi, poziom kampanii")
    show_edges_list([edge_to_dict(e) | {"level": "campaign"} for e in (res.nearest or [])], s,
                    me=res.incident_id, only_key_open=True)
    fam_near = getattr(res, "family_nearest", None) or []
    if fam_near:
        st.subheader("Najbliżsi sąsiedzi, poziom rodziny")
        show_edges_list([edge_to_dict(e) | {"level": "family"} for e in fam_near], s, me=res.incident_id,
                        only_key_open=True)


# =============================================================== view 5: methodology

def view_method(s: dict[str, Any]) -> None:
    reports = sorted(paths()["reports"].glob("eval_*.md"))
    st.subheader("Sygnały i wagi (config/settings.yaml)")
    st.caption("Klasa „campaign” = identyfikator konkretnej kampanii (piksel, konto reklamowe, domena, "
               "identyczny plik, near-duplikat). Klasa „family” = wspólny zestaw narzędzi / aktor. "
               "Krawędź kampanii wymaga ≥ 1 twardego identyfikatora albo ≥ 2 różnych sygnałów klasy "
               "campaign, inaczej trafia na poziom rodziny („" + RULE_TEXT + "”).")
    sig = s["signals"]
    if sig.empty:
        st.info("Nie udało się wczytać sygnałów z modułów cech.")
    else:
        st.dataframe(sig, hide_index=True, use_container_width=True,
                     column_config={"waga": st.column_config.NumberColumn(format="%.1f")})
    st.subheader("Raport ewaluacji")
    if not reports:
        st.info("Brak reports/eval_*.md: uruchom `python -m fakecollector evaluate`.")
        return
    latest = reports[-1]
    st.caption(f"Najnowszy raport: {latest.name}")
    st.markdown(defang(latest.read_text(encoding="utf-8")))


# =============================================================== main

def main() -> None:
    st.logo(str(ASSETS / "logo.png"), icon_image=str(ASSETS / "icon.png"), size="large")
    st.markdown('<p class="eyebrow">HackNation 2026 · NASK</p>', unsafe_allow_html=True)
    st.title(TITLE)
    st.caption("Zadanie NASK „Kolekcjoner fejków / Follow the Fake” · HackNation 2026 · analiza statyczna, "
               "offline, bez renderowania stron oszustów")
    s = state()
    qp = st.query_params.get("tab", VIEW_KEYS[0])
    idx = VIEW_KEYS.index(qp) if qp in VIEW_KEYS else 0
    st.markdown(BASE_CSS, unsafe_allow_html=True)       # static CSS only, no data inside
    view = st.segmented_control("Widok", VIEWS, default=VIEWS[idx], label_visibility="collapsed") or VIEWS[idx]
    with st.sidebar:
        st.subheader("Ustawienia widoku")
        PRESENT["on"] = st.toggle("Tryb prezentacji", value=st.query_params.get("present", "0") == "1",
                                  help="Większa czcionka (ok. 130%) i statyczne tabele czytelne na rzutniku; "
                                       "domyślnie ukrywa wiersze „brak: …” w przesłankach.")
        PRESENT["hide_missing"] = st.checkbox("Ukryj wiersze „brak: …”", value=PRESENT["on"],
                                              key=f"hide_missing_{PRESENT['on']}")
        PUBLIC["on"] = st.toggle("Tryb publiczny", value=st.query_params.get("public", "0") == "1",
                                 help="Maskuje domeny (domena .tld), identyfikatory (…NNNN) oraz nazwy "
                                      "platform, marek i osób, do zrzutów, nagrań i prezentacji.")
    st.query_params["tab"] = VIEW_KEYS[VIEWS.index(view)]
    st.query_params["public"] = "1" if PUBLIC["on"] else "0"
    st.query_params["present"] = "1" if PRESENT["on"] else "0"
    if PRESENT["on"]:
        st.markdown(PRESENT_CSS, unsafe_allow_html=True)    # static CSS only, no data inside
    st.divider()
    {"Kampanie i rodziny": view_campaigns, "Graf powiązań": view_graph, "Incydent": view_incident,
     "Analiza nowego materiału": view_analyze, "Metodyka i wyniki": view_method}[view](s)
    st.divider()
    st.caption("**IsReal?** · HackNation 2026 · zadanie NASK „Kolekcjoner fejków” · "
               "dane organizatora tylko lokalnie, aplikacja dostępna wyłącznie na tym komputerze (localhost)")


main()
