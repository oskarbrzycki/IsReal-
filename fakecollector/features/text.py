"""Text & narrative features (module owner: W2).

Extracts, from saved scam landing pages (HTML / MHTML) and metadata JSON
(yt-dlp info.json, page-capture manifest.json):

    visible_text      first 500 chars of normalized visible text (full text -> data/interim/text/<id>.txt)
    text_len          length of the full visible text
    lang              ISO 639-1 language code (langdetect, fallback: stopword heuristic)
    keywords          top-15 keywords (TF-IDF with corpus IDF if available, else TF)
    entities          canonical names of persons / brands from config/reference/entities.yaml
    persons, brands   the same split by type
    platform_name     normalized name of the "investment platform" / product (heuristic)
    platform_candidates  all candidates, best first (for explanations)
    narrative_type    one of NARRATIVE_TYPES (rules from config/reference/narratives.yaml)
    narrative_tags    all narrative types that scored above the tag threshold
    cta_phrases       normalized call-to-action texts (buttons, links, CTA lexicon)
    promised_amounts  normalized money amounts, e.g. "1200 PLN/day"
    earnings_claim    True if the text promises periodic earnings
    text_emb          multilingual-e5-small sentence embedding (float32, L2-normalized) or None
    minhash           datasketch MinHash(num_perm=128) over word 5-grams, list[int]

SAFETY: data are live scam pages. Parsing is purely static (BeautifulSoup / email / json).
No HTML is rendered, no JS is executed and no network request is made, except that
sentence-transformers may download the embedding model from Hugging Face once
(set TEXT_EMB_DISABLED=1 or text.emb_enabled=false in settings to avoid it).

Run (W1 runner):
    python -m fakecollector ingest
    python -m fakecollector features --module text
Image/video OCR: if W3's data/features/visual.parquet has `ocr_text`, image/video/asset materials
get their own text records (entity_id = material_id or "<material_id>#f<n>" for video frames).
Pair check before setting weights: python scripts/text_signal_pairs.py
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit

from fakecollector.core.models import Context, FeatureRecord, Material

MODULE = "text"
LEVEL = "material"
TEXT_KINDS = ["html", "mhtml", "json"]
OCR_KINDS = ["image", "video", "asset"]  # text taken from W3 OCR (visual.parquet), if present
# The W1 runner accepts list returns (CONTRACTS v0.4): materials without OCR text return [] (skipped).
# Set TEXT_OCR=0 to process page text only.
KINDS = TEXT_KINDS + ([] if os.environ.get("TEXT_OCR", "").strip().lower() in ("0", "false", "no") else OCR_KINDS)
VERSION = "0.1"

# "floor" (proposal for the engine): similarity is rescaled as max(0, (s - floor) / (1 - floor)).
# Measured on the 10 NASK incidents: e5 cosine of ANY two Polish scam pages is 0.77-0.84,
# so without a floor text_semantic links 100% of pairs; one shared entity gives Jaccard ~0.15.
SIGNALS = {
    "text_semantic": {"type": "cosine", "field": "text_emb", "floor": 0.85},
    "text_near_dup": {"type": "jaccard_minhash", "field": "minhash"},
    "shared_entities": {"type": "set_overlap", "field": "entities", "floor": 0.2},
    "same_platform_name": {"type": "exact", "field": "platform_name"},
    # narrative_key = narrative_type, but None for "other": an unknown narrative is not a match.
    "same_narrative": {"type": "exact", "field": "narrative_key"},
}

# CONTRACTS v0.4: "campaign" = evidence of the same campaign (near-identical text, same product/
# platform name); "family" = same scam family / theme only (similar topic, same narrative, same
# impersonated people) - must not glue unrelated campaigns on its own.
SIGNAL_CLASS = {
    "text_near_dup": "campaign",
    "same_platform_name": "campaign",
    "text_semantic": "family",
    "same_narrative": "family",
    "shared_entities": "family",
}

NARRATIVE_TYPES = [
    "fake_news_article",
    "celebrity_interview",
    "arrest_scandal",
    "investment_platform",
    "conference_event",
    "health_product",
    "giveaway",
    "other",
]

# Every feature key this module emits; used to build all-None records on failure.
FEATURE_KEYS = [
    "visible_text", "text_len", "lang", "keywords", "entities", "persons", "brands",
    "platform_name", "platform_candidates", "narrative_type", "narrative_key", "narrative_tags",
    "cta_phrases", "promised_amounts", "earnings_claim", "text_emb", "minhash",
]

SNIPPET_CHARS = 500
TOP_KEYWORDS = 15
MINHASH_PERM = 128
MINHASH_SEED = 1
SHINGLE_SIZE = 5
EMB_MODEL_DEFAULT = "intfloat/multilingual-e5-small"
EMB_MAX_CHARS = 2000  # e5-small truncates at 512 tokens anyway

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "config" / "reference"



# ----------------------------------------------------------------- normalization

_FOLD_EXTRA = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "đ": "d", "ß": "ss"})
_ZERO_WIDTH_RE = re.compile(r"[​-‏⁠﻿­]")
_WS_RE = re.compile(r"[^\S\n]+")
_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*")


def normalize_text(text: str) -> str:
    """NFC, drop zero-width chars, collapse whitespace inside lines, drop empty lines."""
    text = unicodedata.normalize("NFC", text or "")
    text = _ZERO_WIDTH_RE.sub("", text).replace(" ", " ")
    lines = (_WS_RE.sub(" ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def fold(text: str) -> str:
    """Lowercase and strip diacritics (Polish-aware): 'Rafała Brzoskę' -> 'rafala brzoske'."""
    text = (text or "").translate(_FOLD_EXTRA)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens (letters/digits, inner hyphens kept)."""
    return [t.casefold() for t in _WORD_RE.findall(text or "")]


# ----------------------------------------------------------------- reference data

def _load_yaml(path: Path) -> dict:
    import yaml  # PyYAML

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _stem_token(tok: str) -> str:
    """Very small Polish stemmer for name matching: drop a final vowel, shorten long tokens."""
    if len(tok) >= 4 and tok[-1] in "aeiouy":
        tok = tok[:-1]
    if len(tok) >= 8:
        tok = tok[:-1]
    return tok


def _alias_regex(alias: str, exact: bool) -> re.Pattern:
    if exact:
        return re.compile(r"(?<![\w.])" + re.escape(alias) + r"(?![\w])")
    toks = [t for t in re.split(r"\s+", fold(alias).strip()) if t]
    parts = []
    for t in toks:
        if not re.fullmatch(r"[a-z]+", t) or len(t) < 4:
            parts.append(re.escape(t))  # dots, digits, short tokens: literal
        else:
            parts.append(re.escape(_stem_token(t)) + r"\w{0,5}")
    return re.compile(r"(?<![\w])" + r"\s+".join(parts) + r"(?![\w])")


@lru_cache(maxsize=4)
def load_gazetteer(path: str | None = None) -> list[dict]:
    """Return [{name, type, patterns:[(regex, exact)]}] from entities.yaml (cached)."""
    p = Path(path) if path else REFERENCE_DIR / "entities.yaml"
    data = _load_yaml(p)
    out: list[dict] = []
    for item in data.get("persons", []) or []:
        out.append({"name": item["name"], "type": "person", "exact": False,
                    "aliases": item.get("aliases") or [item["name"]]})
    for item in data.get("brands", []) or []:
        out.append({"name": item["name"], "type": item.get("type", "brand"),
                    "exact": bool(item.get("exact", False)), "generic": bool(item.get("generic", False)),
                    "aliases": item.get("aliases") or [item["name"]]})
    for ent in out:
        ent["patterns"] = []
        for alias in ent["aliases"]:
            alias = str(alias)
            # exact flag applies to short acronym-like aliases only; long aliases stay fuzzy
            is_exact = ent["exact"] and len(alias) <= 5
            ent["patterns"].append((_alias_regex(alias, is_exact), is_exact))
    return out


@lru_cache(maxsize=4)
def load_narratives(path: str | None = None) -> dict:
    p = Path(path) if path else REFERENCE_DIR / "narratives.yaml"
    data = _load_yaml(p)
    types = {k: [re.compile(rx) for rx in (v or [])] for k, v in (data.get("types") or {}).items()}
    return {
        "types": types,
        "min_score": int(data.get("min_score", 2)),
        "tag_min_score": int(data.get("tag_min_score", 2)),
        "priority": list(data.get("priority") or types.keys()),
    }


# ----------------------------------------------------------------- stopwords

_STOP_PL = """
a aby ach acz aczkolwiek aj albo ale alez ani az bardziej bardzo beda bedzie bez bo bowiem by byc byl byla byli bylo byly
bym bys caly cala cie ciebie co cos czy czyli czasem daleko dla dlaczego dlatego do dobrze dokad dosc duzo dwa dwaj dwie
dzis dzisiaj gdy gdyby gdyz gdzie gdziekolwiek go i ich ile im inna inne inny innych iz ja jak jakas jakby jaki jakichs
jakie jakis jakiz jakkolwiek jako jakos je jeden jedna jedno jednak jednakze jego jej jemu jesli jest jestem jeszcze jezeli
juz kazdy kiedy kilka kims kto ktora ktore ktorego ktorej ktory ktorych ktorym ktorzy ku lat lecz lub ma maja mam mi miedzy
mimo mna mnie moga moim moja moje moze mozliwe mozna moj mu musi my na nad nam nami nas nasi nasz nasza nasze naszego
naszych natomiast natychmiast nawet nia nic nich nie niech niego niej niemu nigdy nim nimi niz no o obok od okolo on ona
one oni ono oraz oto owszem pan pana pani po pod podczas pomimo ponad poniewaz powinien powinna powinni powinno poza prawie
przeciez przed przede przedtem przez przy roku rowniez sa sam sama sie skad sobie soba sposob swoje ta tak taka taki takie
takze tam te tego tej temu ten teraz tez to toba tobie totez trzeba tu tutaj twoi twoim twoja twoje twym ty tych tylko tym
u w wam wami was wasz wasza wasze we wedlug wiele wielu wiec wiecej wszyscy wszystkich wszystkie wszystkim wszystko wtedy
wy wlasnie z za zapewne zawsze ze zl zeby zostal zostala zostaly zostanie zawsze nasze nowe moze kazdego ktos tylko
juz jego tego ich swoj swoja swoje swojego swojej przez jako tez tylko moze bylo jesli takze
"""
_STOP_EN = """
a about above after again against all am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers herself him himself his
how i if in into is it its itself just me more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should so some such than that the their theirs them themselves then there these they this
those through to too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves www http https com html
"""
STOPWORDS = frozenset(_STOP_PL.split()) | frozenset(_STOP_EN.split())

_LANG_HINTS = {
    "pl": {"jest", "nie", "sie", "na", "ze", "do", "jak", "ktory", "oraz", "tylko", "przez", "dla", "juz"},
    "en": {"the", "and", "is", "of", "to", "in", "that", "for", "with", "you", "this", "are"},
    "de": {"und", "der", "die", "das", "ist", "nicht", "mit", "sie", "ein", "eine", "auf"},
    "uk": {"що", "не", "на", "як", "та", "це", "він", "вона"},
    "ru": {"что", "не", "на", "как", "это", "он", "она", "и"},
}


# ----------------------------------------------------------------- language

def detect_lang(text: str) -> str | None:
    """ISO 639-1 code or None for too short text. Deterministic (seeded langdetect)."""
    sample = (text or "")[:3000]
    if len(re.sub(r"\W", "", sample)) < 20:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(sample)
    except ImportError:
        pass
    except Exception:  # langdetect raises on texts without features
        return None
    toks = set(tokenize(fold(sample)))
    scores = {lang: len(toks & hints) for lang, hints in _LANG_HINTS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else None


# ----------------------------------------------------------------- keywords

def content_tokens(text: str) -> list[str]:
    """Tokens used for keywords and IDF: lowercase, >=3 letters, no stopwords, no pure digits."""
    out = []
    for t in tokenize(text):
        if sum(ch.isalpha() for ch in t) < 3 or fold(t) in STOPWORDS:
            continue
        out.append(t)
    return out


def build_idf(docs: Iterable[str]) -> dict:
    """Smoothed IDF over a corpus of texts: idf = ln((1+N)/(1+df)) + 1."""
    df: Counter = Counter()
    n = 0
    for doc in docs:
        n += 1
        df.update(set(content_tokens(doc)))
    return {"n_docs": n, "idf": {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}}


def keywords(text: str, idf: dict | None = None, k: int = TOP_KEYWORDS) -> list[str]:
    toks = content_tokens(text)
    if not toks:
        return []
    tf = Counter(toks)
    table = (idf or {}).get("idf") or {}
    default_idf = math.log((1 + (idf or {}).get("n_docs", 1)) / 1) + 1.0 if table else 1.0
    # sublinear TF (1 + ln tf) so repeated boilerplate words do not dominate
    scored = {t: (1.0 + math.log(c)) * table.get(t, default_idf) for t, c in tf.items()}
    return [t for t, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


# ----------------------------------------------------------------- entities

def find_entities(text: str, gazetteer: list[dict] | None = None) -> dict[str, list[str]]:
    """Gazetteer lookup. Returns {'entities', 'persons', 'brands'} as sorted lists.

    Brands marked `generic: true` (e.g. Facebook comment widgets, Google) are kept in
    `brands` but left out of `entities`, which feeds the shared_entities signal.
    """
    gaz = gazetteer if gazetteer is not None else load_gazetteer()
    folded = fold(text)
    persons, brands, generic = set(), set(), set()
    for ent in gaz:
        for rx, is_exact in ent["patterns"]:
            if rx.search(text if is_exact else folded):
                (persons if ent["type"] == "person" else brands).add(ent["name"])
                if ent.get("generic"):
                    generic.add(ent["name"])
                break
    return {
        "entities": sorted((persons | brands) - generic),
        "persons": sorted(persons),
        "brands": sorted(brands),
    }


# ----------------------------------------------------------------- platform name

_PLATFORM_KW = (
    r"(?i:platform\w*|aplikacj\w*|system\w*|bot\w*|algorytm\w*|narzędzi\w*|narzedzi\w*|"
    r"giełd\w*|gield\w*|app|application)"
)
_PLATFORM_MID = (
    r"(?i:(?:inwestycyjn\w*|tradingow\w*|handlow\w*|finansow\w*|kryptowalutow\w*|"
    r"o nazwie|nazywan\w*|zwan\w*|pod nazwą|pod nazwa|marki)\s+)*"
)
_NAME_TOKEN = r"[„\"«'“]?[A-ZĄĆĘŁŃÓŚŹŻ0-9][\w\-\.]*[”\"»']?"
_PLATFORM_RE = re.compile(
    _PLATFORM_KW + r"\s+" + _PLATFORM_MID + r"(" + _NAME_TOKEN + r"(?:[^\S\n]+" + _NAME_TOKEN + r"){0,2})"
)
_QUOTED_RE = re.compile(r"[„\"«“]([A-ZĄĆĘŁŃÓŚŹŻ0-9][^„\"«»“”\n]{1,40}?)[”\"»]")
_TITLE_SPLIT_RE = re.compile(r"\s+[–—|\-:]\s+|\s*\|\s*")
_GENERIC_NAME_WORDS = frozenset(
    fold(w) for w in """
    ai sztuczna sztucznej inteligencja polska polski polsce polskiej polaków polakow ue unia europejska usa pl
    the a to i w na z nie jest dla oficjalna oficjalnej strona strony stronie zarejestruj kliknij teraz tutaj
    więcej wiecej sprawdź sprawdz zobacz czytaj czytać czytac nowa nowy nowe online internet dziś dzis już juz tylko
    app store sklep home główna glowna start menu kontakt regulamin polityka prywatności prywatnosci
    akceptuję akceptuj zgoda zamknij ok dostęp zamówienie zamów konto wybierz wyślij dalej tak rezerwuj
    kup pobierz zainstaluj purchases komentarz komentarze odpowiedz lubię udostępnij formularz cena
    """.split()
)


def _clean_name(raw: str) -> str | None:
    s = raw.strip(" „\"«»“”'.,:;!?()[]")
    toks = s.split()
    # keep leading capitalized / numeric tokens only
    kept = []
    for t in toks:
        t2 = t.strip(" „\"«»“”'.,:;!?()[]")
        if not t2:
            break
        if not (t2[0].isupper() or t2[0].isdigit()):
            break
        kept.append(t2)
        if re.search(r"[.!?,;:]$", t):  # sentence/clause ends after this token
            break
    while kept and fold(kept[-1]) in _GENERIC_NAME_WORDS:
        kept.pop()
    while kept and fold(kept[0]) in _GENERIC_NAME_WORDS:
        kept.pop(0)
    if not kept:
        return None
    name = " ".join(kept)
    if len(name) < 3 or len(name) > 40 or not re.search(r"[^\W\d_]{2,}", name):
        return None  # too short/long or no real word (e.g. "1 150")
    alpha = [t for t in kept if any(ch.isalpha() for ch in t)]
    if alpha and all(t.isupper() for t in alpha) and (len(kept) > 1 or len(kept[0]) > 4):
        return None  # ALL-CAPS button / banner text, not a product name
    return name


def _variant_key(name: str) -> str:
    """Key merging inflected variants: 'Pakietem Wzrostu' ~ 'Pakiet Wzrostu'."""
    return " ".join(fold(t)[:5] for t in name.split())


def _is_common_word(name: str, text: str) -> bool:
    """Single word that also occurs lowercase in the text at least as often -> ordinary word."""
    if " " in name:
        return False
    low = len(re.findall(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text))
    cap = len(re.findall(r"(?<!\w)" + re.escape(name[:1].upper() + name[1:].lower()) + r"(?!\w)", text))
    return low >= 1 and low >= cap


def _is_known_entity(name: str, gazetteer: list[dict]) -> bool:
    folded = fold(name)
    for ent in gazetteer:
        if ent["type"] == "platform":
            continue
        for rx, is_exact in ent["patterns"]:
            m = rx.search(name if is_exact else folded)
            if m and (m.end() - m.start()) >= len(folded) * 0.6:
                return True
    return False


def normalize_platform(name: str | None) -> str | None:
    if not name:
        return None
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", name)).strip().casefold()
    s = re.sub(r"[™®©]", "", s).strip()
    return s or None


def guess_platform_name(
    text: str,
    title: str | None = None,
    cta_texts: Iterable[str] | None = None,
    gazetteer: list[dict] | None = None,
) -> tuple[str | None, list[str]]:
    """Heuristic name of the advertised platform/product.

    Votes: name after a platform keyword (x2 each), short product-like title part (x3),
    capitalized names in CTA buttons/links (x2), quoted capitalized names (x1), plus a
    bonus for how often the name is mentioned in the text (max +5). Inflected variants
    are merged. Known persons/media/banks, ALL-CAPS button texts and ordinary words
    are excluded. Returns (normalized best name or None, display candidates best-first).
    """
    gaz = gazetteer if gazetteer is not None else load_gazetteer()
    votes: Counter = Counter()
    variants: dict[str, Counter] = {}
    body = text or ""

    def vote(raw: str | None, w: int, strict: bool = False) -> None:
        if strict:  # every word capitalized, at most 3 words (quoted names)
            words = (raw or "").split()
            if not 1 <= len(words) <= 3 or not all(x[:1].isupper() or x[:1].isdigit() for x in words):
                return
        name = _clean_name(raw or "")
        if not name or _is_known_entity(name, gaz) or _is_common_word(name, body):
            return
        key = _variant_key(name)
        votes[key] += w
        variants.setdefault(key, Counter())[name] += 1

    for m in _PLATFORM_RE.finditer(text or ""):
        vote(m.group(1), 2)
    for m in _QUOTED_RE.finditer(text or ""):
        vote(m.group(1), 1, strict=True)
    for cta in cta_texts or []:
        toks = cta.split()
        if len(toks) >= 2 and _CTA_RE.match(_norm_phrase(cta)):  # "Przejdź do Quantum AI" -> "Quantum AI"
            caps = [t for t in toks[1:] if t[:1].isupper() or t[:1].isdigit()]
            if caps:
                vote(" ".join(caps), 2)
    if title:
        for part in _TITLE_SPLIT_RE.split(title.strip()):
            words = part.split()
            # product-like: 1-3 words, no sentence punctuation, every word capitalized
            if 1 <= len(words) <= 3 and not re.search(r"[.!?,«»„”\"]", part):
                if all(w[:1].isupper() or w[:1].isdigit() for w in words):
                    vote(part, 3)

    if not votes:
        return None, []
    folded = fold(body)
    best_display: dict[str, str] = {}
    for key, ctr in variants.items():
        mentions: Counter = Counter()
        for name in ctr:
            mentions[name] = len(re.findall(r"(?<!\w)" + re.escape(fold(name)) + r"(?!\w)", folded))
        votes[key] += min(5, sum(mentions.values()))
        # display form = most mentioned variant (usually the nominative), then shortest
        best_display[key] = sorted(ctr, key=lambda n: (-mentions[n], -ctr[n], len(n)))[0]
    ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
    return normalize_platform(best_display[ranked[0][0]]), [best_display[k] for k, _ in ranked[:5]]


# ----------------------------------------------------------------- narrative

def classify_narrative(text: str, title: str | None = None, rules: dict | None = None) -> tuple[str, list[str]]:
    r = rules if rules is not None else load_narratives()
    body = fold(text)
    head = fold(title or "")
    scores: dict[str, int] = {}
    for ntype, patterns in r["types"].items():
        s = 0
        for rx in patterns:
            if rx.search(body):
                s += 1
            if head and rx.search(head):
                s += 2
        scores[ntype] = s
    tags = [t for t in r["priority"] if scores.get(t, 0) >= r["tag_min_score"]]
    tags += sorted(t for t, s in scores.items() if s >= r["tag_min_score"] and t not in tags)
    best = max(scores.values(), default=0)
    if best < r["min_score"]:
        return "other", tags
    winners = [t for t, s in scores.items() if s == best]
    order = {t: i for i, t in enumerate(r["priority"])}
    winners.sort(key=lambda t: order.get(t, len(order)))
    return winners[0], tags


# ----------------------------------------------------------------- CTA

_CTA_LEXICON = [
    r"zarejestruj", r"przejdz", r"oficjaln\w* stron", r"zamow", r"kup\b", r"kup teraz", r"dowiedz sie",
    r"sprawdz", r"zacznij", r"odbierz", r"zapisz sie", r"skorzystaj", r"dolacz", r"pobierz", r"zagraj",
    r"graj\b", r"zainstaluj", r"otworz konto", r"zaloz konto", r"wyslij", r"zostaw (numer|dane|kontakt)",
    r"zadzwon", r"zarezerwuj", r"rezerwuj", r"kliknij", r"aktywuj", r"wez udzial", r"zarabiaj",
    r"rozpocznij", r"zyskaj", r"otrzymaj", r"wyplac", r"inwestuj", r"chce\b", r"tak\b", r"dalej\b",
    r"register", r"sign up", r"join", r"get started", r"order now", r"buy now", r"claim", r"download", r"install",
]
_CTA_RE = re.compile(r"\b(?:" + "|".join(_CTA_LEXICON) + r")")


def _norm_phrase(s: str) -> str:
    """Lowercase, diacritic-folded, single-spaced phrase (robust for exact/set matching)."""
    s = re.sub(r"\s+", " ", fold(s)).strip()
    return s.strip(" .,:;!?»«„”\"'→>-–—")


def cta_phrases(cta_texts: Iterable[str] | None, text: str = "") -> list[str]:
    """Short CTA texts from buttons/links that match the CTA lexicon (normalized, deduped)."""
    out: set[str] = set()
    for raw in cta_texts or []:
        p = _norm_phrase(raw)
        if not p or len(p) > 60 or len(p.split()) > 8:
            continue
        if _CTA_RE.match(p):
            out.add(p)
    # imperative CTA phrases inside running text (e.g. "Przejdź na oficjalną stronę")
    for m in re.finditer(r"\b(?:przejdz|zarejestruj sie|zamow|kup teraz|zacznij zarabiac|dolacz)\b[^.!?\n]{0,40}", fold(text)):
        p = _norm_phrase(m.group(0))
        if 2 <= len(p.split()) <= 7:
            out.add(p)
    return sorted(out)[:30]


# ----------------------------------------------------------------- money

_NUM = r"\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MULT = r"(?:\s*(tys\.|tys\b|tysi[eę]cy\b|tysiące\b|tysiace\b|mln\b|milion\w*|k\b))?"
_CUR = r"(zł|zl|złotych|zlotych|pln|eur|euro|€|usd|\$|dolar\w*)"
_AMOUNT_AFTER_RE = re.compile(r"(?<![\w.,])(" + _NUM + r")" + _MULT + r"\s*" + _CUR + r"(?![a-ząćęłńóśźż])", re.I)
_AMOUNT_BEFORE_RE = re.compile(r"(€|\$|pln|zł)\s?(" + _NUM + r")" + _MULT, re.I)
_PERIOD_RE = [
    (re.compile(r"^\W{0,3}(dziennie|na dzie[nń]|każdego dnia|kazdego dnia|w ciągu dnia|w ciagu dnia|/\s?dzie[nń]|per day|a day|daily)", re.I), "day"),
    (re.compile(r"^\W{0,3}(tygodniowo|na tydzie[nń]|w tydzie[nń]|/\s?tydz|per week|weekly)", re.I), "week"),
    (re.compile(r"^\W{0,3}(miesięcznie|miesiecznie|na miesiąc|na miesiac|w miesiąc|w miesiac|/\s?mies|per month|monthly)", re.I), "month"),
]
_EARNINGS_RE = re.compile(r"\b(zarab\w*|zarobek|zarobki|zarobi\w*|dochod\w*|zysk\w*|earn\w*|profit\w*)\b")


def _parse_number(raw: str) -> float | None:
    s = raw.replace(" ", " ").strip()
    m = re.fullmatch(r"(.*?)([.,])(\d{1,2})", s)
    if m and not re.search(r"[.,]\d{3}$", s):
        int_part, dec = m.group(1), m.group(3)
    else:
        int_part, dec = s, ""
    int_part = re.sub(r"[ .,]", "", int_part)
    if not int_part.isdigit():
        return None
    try:
        return float(int_part + ("." + dec if dec else ""))
    except ValueError:
        return None


def _currency(raw: str) -> str:
    r = raw.casefold()
    if r in ("zł", "zl", "złotych", "zlotych", "pln"):
        return "PLN"
    if r in ("eur", "euro", "€"):
        return "EUR"
    return "USD"


def _multiplier(raw: str | None) -> float:
    if not raw:
        return 1.0
    r = fold(raw)
    if r.startswith("mln") or r.startswith("milion"):
        return 1e6
    return 1e3


def promised_amounts(text: str) -> tuple[list[str], bool]:
    """Normalized amounts like '1200 PLN' or '800 EUR/day'; second value = periodic earnings claim."""
    found: dict[str, None] = {}
    periodic = False
    t = text or ""

    def add(num_raw: str, mult_raw: str | None, cur_raw: str, end: int) -> None:
        nonlocal periodic
        val = _parse_number(num_raw)
        if val is None or val <= 0:
            return
        val *= _multiplier(mult_raw)
        if val >= 1e10:
            return
        period = ""
        tail = t[end:end + 30]
        for rx, name in _PERIOD_RE:
            if rx.search(tail):
                period = "/" + name
                periodic = True
                break
        amount = f"{val:.2f}".rstrip("0").rstrip(".")
        found.setdefault(f"{amount} {_currency(cur_raw)}{period}", None)

    for m in _AMOUNT_AFTER_RE.finditer(t):
        add(m.group(1), m.group(2), m.group(3), m.end())
    for m in _AMOUNT_BEFORE_RE.finditer(t):
        add(m.group(2), m.group(3), m.group(1), m.end())
    if not periodic and found and _EARNINGS_RE.search(fold(t)):
        periodic = bool(re.search(r"\b(dziennie|tygodniowo|miesiecznie|kazdego dnia|na dzien)\b", fold(t)))
    return list(found)[:20], periodic


# ----------------------------------------------------------------- MinHash

def minhash_signature(text: str, num_perm: int = MINHASH_PERM, k: int = SHINGLE_SIZE) -> list[int] | None:
    """MinHash over word k-shingles of folded text; None if there are no tokens."""
    from datasketch import MinHash

    toks = tokenize(fold(text))
    if not toks:
        return None
    if len(toks) < k:
        shingles = {" ".join(toks)}
    else:
        shingles = {" ".join(toks[i:i + k]) for i in range(len(toks) - k + 1)}
    mh = MinHash(num_perm=num_perm, seed=MINHASH_SEED)
    for sh in shingles:
        mh.update(sh.encode("utf-8"))
    return [int(v) for v in mh.hashvalues]


def minhash_jaccard(a: list[int] | None, b: list[int] | None) -> float | None:
    """Estimated Jaccard similarity of two signatures (helper for tests / engine)."""
    if not a or not b or len(a) != len(b):
        return None
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


# ----------------------------------------------------------------- embeddings

class _Embedder:
    """Lazy sentence-transformers wrapper; disabled on any load error."""

    def __init__(self) -> None:
        self.model = None
        self.name: str | None = None
        self.error: str | None = None

    def get(self, name: str):
        if self.model is not None and self.name == name:
            return self.model
        if self.error and self.name == name:
            return None
        self.name = name
        try:
            from sentence_transformers import SentenceTransformer

            # cache dir: SENTENCE_TRANSFORMERS_HOME / HF_HOME (outside the repo by default)
            self.model = SentenceTransformer(name, device="cpu")
            self.error = None
        except Exception as exc:  # missing package, no network, bad model name
            self.model = None
            self.error = f"{type(exc).__name__}: {exc}"[:300]
        return self.model


_EMBEDDER = _Embedder()


def embeddings_enabled(config: dict | None = None) -> bool:
    if os.environ.get("TEXT_EMB_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return False
    return bool((config or {}).get("emb_enabled", True))


def embed_text(text: str, model_name: str = EMB_MODEL_DEFAULT) -> list[float]:
    """L2-normalized float32 embedding of a passage (e5 'passage: ' prefix). Raises on failure."""
    import numpy as np

    model = _EMBEDDER.get(model_name)
    if model is None:
        raise RuntimeError(f"embedding model unavailable ({_EMBEDDER.error})")
    prefix = "passage: " if "e5" in model_name.lower() else ""
    vec = model.encode([prefix + text[:EMB_MAX_CHARS]], normalize_embeddings=True, show_progress_bar=False)[0]
    return np.asarray(vec, dtype=np.float32).tolist()


# ----------------------------------------------------------------- feature bundle

def empty_features() -> dict[str, Any]:
    return {k: None for k in FEATURE_KEYS}


def text_features(
    text: str,
    *,
    title: str | None = None,
    cta_texts: Iterable[str] | None = None,
    idf: dict | None = None,
    embed: bool = True,
    emb_model: str = EMB_MODEL_DEFAULT,
    gazetteer: list[dict] | None = None,
    narratives: dict | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """All text features for one piece of text (page text or OCR of an image).

    `title` and `cta_texts` are optional extra signals (HTML <title>, button/link texts).
    Each sub-feature fails independently: its value becomes None and a message is
    appended to `errors` (if given). Never raises.
    """
    errs = errors if errors is not None else []
    feats = empty_features()
    full = normalize_text(text or "")
    cta_list = [normalize_text(c) for c in (cta_texts or []) if c and c.strip()]
    feats["text_len"] = len(full)
    analysis = "\n".join(x for x in (title or "", full) if x)
    if not analysis.strip():
        errs.append("text: no text content")
        return feats
    feats["visible_text"] = full[:SNIPPET_CHARS].replace("\n", " ") if full else None

    def run(key: str, fn):
        try:
            return fn()
        except Exception as exc:
            errs.append(f"text.{key}: {type(exc).__name__}: {exc}"[:300])
            return None

    feats["lang"] = run("lang", lambda: detect_lang(analysis))
    feats["keywords"] = run("keywords", lambda: keywords(analysis, idf))
    ents = run("entities", lambda: find_entities(analysis + "\n" + "\n".join(cta_list), gazetteer))
    if ents is not None:
        feats.update(ents)
    plat = run("platform_name", lambda: guess_platform_name(full, title, cta_list, gazetteer))
    if plat is not None:
        feats["platform_name"], feats["platform_candidates"] = plat
    narr = run("narrative_type", lambda: classify_narrative(full, title, narratives))
    if narr is not None:
        feats["narrative_type"], feats["narrative_tags"] = narr
        feats["narrative_key"] = narr[0] if narr[0] != "other" else None
    feats["cta_phrases"] = run("cta_phrases", lambda: cta_phrases(cta_list, full))
    money = run("promised_amounts", lambda: promised_amounts(analysis))
    if money is not None:
        feats["promised_amounts"], feats["earnings_claim"] = money
    feats["minhash"] = run("minhash", lambda: minhash_signature(full or analysis))
    if embed:
        feats["text_emb"] = run("text_emb", lambda: embed_text(analysis, emb_model))
    return feats


# ----------------------------------------------------------------- readers (static only)

_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_\-]+)""", re.I)
_HIDDEN_STYLE_RE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem)?\s*(?:;|$)|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)",
    re.I,
)
# <embed>/<object> are unwrapped, not dropped: lxml may nest the rest of the page inside an
# unclosed <embed>, and dropping it would delete all visible text.
_UNWRAP_TAGS = ["object", "embed"]
_DROP_TAGS = ["script", "style", "noscript", "template", "svg", "canvas", "iframe",
              "head", "meta", "link"]
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th",
               "section", "article", "header", "footer", "nav", "aside", "blockquote", "form", "label",
               "button", "a", "figcaption", "dd", "dt", "table", "main", "option"}


def decode_html_bytes(raw: bytes) -> str:
    m = _META_CHARSET_RE.search(raw[:4096])
    enc = m.group(1).decode("ascii", "ignore").lower() if m else "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def parse_html(html: str) -> dict[str, Any]:
    """Static parse: {'title', 'description', 'text', 'cta_texts'}. Hidden elements are dropped."""
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title = None
    if soup.title and soup.title.string:
        title = normalize_text(soup.title.get_text(" "))
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = normalize_text(og["content"])
    desc = None
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            desc = normalize_text(tag["content"])
            break

    for tag in soup.find_all(_UNWRAP_TAGS):
        tag.unwrap()
    for tag in soup.find_all(_DROP_TAGS):
        if not getattr(tag, "decomposed", False):
            tag.decompose()
    for tag in soup.find_all(True):
        if getattr(tag, "decomposed", False):
            continue
        attrs = tag.attrs or {}
        if ("hidden" in attrs or str(attrs.get("aria-hidden", "")).lower() == "true"
                or (tag.name == "input" and str(attrs.get("type", "")).lower() == "hidden")
                or _HIDDEN_STYLE_RE.search(str(attrs.get("style", "")))):
            tag.decompose()

    cta: list[str] = []
    for tag in soup.find_all(["a", "button"]):
        t = normalize_text(tag.get_text(" "))
        if t:
            cta.append(t)
    for tag in soup.find_all(attrs={"role": "button"}):
        t = normalize_text(tag.get_text(" "))
        if t:
            cta.append(t)
    for tag in soup.find_all("input"):
        if str(tag.get("type", "")).lower() in ("submit", "button") and tag.get("value"):
            cta.append(normalize_text(str(tag["value"])))

    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    body = soup.body or soup
    text = normalize_text(body.get_text())
    return {"title": title, "description": desc, "text": text, "cta_texts": cta}


def mhtml_to_html(raw: bytes) -> str | None:
    """First text/html part of an MHTML archive (quoted-printable / base64 decoded)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                content = decode_html_bytes(payload)
            return content if isinstance(content, str) else decode_html_bytes(content)
    return None


_JSON_TEXT_KEYS = {
    "title", "fulltitle", "alt_title", "description", "uploader", "channel", "creator", "page_title",
    "ad_name", "adset_name", "campaign_name", "ad_creative_body", "ad_creative_link_title",
    "ad_creative_link_caption", "ad_creative_link_description", "body", "caption", "headline",
    "utm_campaign", "utm_content", "utm_term", "text", "playlist_title", "playlist_uploader",
}
_JSON_QS_KEYS = {"ad_name", "adset_name", "campaign_name", "utm_campaign", "utm_content", "utm_term"}


def json_text(obj: Any, max_items: int = 200) -> dict[str, Any]:
    """Collect human-readable strings from a metadata JSON (yt-dlp info.json, page-capture manifest)."""
    parts: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        s = normalize_text(s)
        if s and s not in seen and len(parts) < max_items:
            seen.add(s)
            parts.append(s)

    def walk(o: Any, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                key = str(k).lower()
                if isinstance(v, str):
                    if key in _JSON_TEXT_KEYS and not v.startswith(("http://", "https://")):
                        add(v)
                    elif v.startswith(("http://", "https://")) and "?" in v:
                        try:
                            qs = parse_qs(urlsplit(v).query)
                        except ValueError:
                            qs = {}
                        for qk, qv in qs.items():
                            if qk.lower() in _JSON_QS_KEYS:
                                for x in qv:
                                    add(x.replace("_", " ").replace("+", " "))
                else:
                    walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o[:500]:
                walk(v, depth + 1)

    walk(obj, 0)
    # JSON titles are often generic CTA labels (e.g. FB ad "Czytać"), so they stay in the text
    # but are not passed as a page <title> (which votes for platform_name).
    return {"title": None, "description": None, "text": "\n".join(parts), "cta_texts": []}


def read_material(path: Path, kind: str) -> dict[str, Any]:
    """Load a material file statically and return {'title', 'description', 'text', 'cta_texts'}."""
    raw = path.read_bytes()
    if kind == "html":
        return parse_html(decode_html_bytes(raw))
    if kind == "mhtml":
        html = mhtml_to_html(raw)
        if html is None:
            raise ValueError("no text/html part in MHTML")
        return parse_html(html)
    if kind == "json":
        return json_text(json.loads(raw.decode("utf-8", errors="replace")))
    raise ValueError(f"unsupported kind: {kind}")


# ----------------------------------------------------------------- context helpers

def _ctx_get(ctx: Any, *names: str) -> Any:
    for n in names:
        if isinstance(ctx, dict) and ctx.get(n) is not None:
            return ctx[n]
        v = getattr(ctx, n, None)
        if v is not None:
            return v
    return None


def _ctx_data_dir(ctx: Any) -> Path:
    v = _ctx_get(ctx, "data_dir")
    return Path(v or os.environ.get("DATA_DIR", "data"))


def _ctx_text_config(ctx: Any) -> dict:
    """`text:` section of settings.yaml (Context.settings), empty dict if absent."""
    cfg = _ctx_get(ctx, "settings")
    if isinstance(cfg, dict):
        sub = cfg.get("text") or {}
        return sub if isinstance(sub, dict) else {}
    return {}


def _resolve_path(path: str | Path, repo_root: Path | None) -> Path:
    """Material.path is relative to the repo root (CONTRACTS §3)."""
    p = Path(path)
    if p.is_absolute() or repo_root is None:
        return p
    return Path(repo_root) / p


_IDF_CACHE: dict[str, tuple[float, dict | None]] = {}


def corpus_idf(data_dir: Path, repo_root: Path | None) -> dict | None:
    """IDF over all text materials listed in data/interim/incidents.jsonl (W1 ingest).

    Computed in memory once per incidents.jsonl version (nothing is written to disk).
    Returns None if the file is missing; keywords then fall back to plain TF.
    """
    p = data_dir / "interim" / "incidents.jsonl"
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    cached = _IDF_CACHE.get(str(p))
    if cached and cached[0] == mtime:
        return cached[1]
    docs: dict[str, str] = {}
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for m in json.loads(line).get("materials", []):
                if m.get("kind") not in TEXT_KINDS or m.get("is_common_lib") or m.get("material_id") in docs:
                    continue
                try:
                    d = read_material(_resolve_path(m["path"], repo_root), m["kind"])
                    docs[m["material_id"]] = "\n".join(x for x in (d.get("title"), d.get("text")) if x)
                except Exception:
                    continue
        idf = build_idf(t for t in docs.values() if t) if docs else None
    except Exception:
        idf = None
    _IDF_CACHE[str(p)] = (mtime, idf)
    return idf


def _provenance(emb_model: str | None) -> dict[str, str]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prov = {
        "text": f"fakecollector.features.text v{VERSION} (static BeautifulSoup/lxml parse)",
        "extracted_at": now,
        "entities": "config/reference/entities.yaml (gazetteer)",
        "narrative_type": "config/reference/narratives.yaml (rules)",
        "minhash": f"datasketch MinHash num_perm={MINHASH_PERM}, word {SHINGLE_SIZE}-grams",
    }
    if emb_model:
        prov["text_emb"] = f"sentence-transformers {emb_model}"
    return prov


# ----------------------------------------------------------------- core extraction (dict form)

def extract_dict(
    path: str | Path,
    *,
    entity_id: str | None = None,
    kind: str | None = None,
    data_dir: Path | None = None,
    config: dict | None = None,
    idf: dict | None = None,
    write_full_text: bool = True,
) -> dict[str, Any]:
    """Extract one material into a plain dict {entity_id, level, module, features, provenance, errors}.

    Never raises. Used by `extract()` (FeatureRecord) and the standalone batch runner.
    """
    cfg = config or {}
    data_dir = data_dir or Path(os.environ.get("DATA_DIR", "data"))
    errors: list[str] = []
    p = Path(path)
    eid = entity_id
    emb_model = cfg.get("emb_model", EMB_MODEL_DEFAULT)
    embed = embeddings_enabled(cfg)
    feats = empty_features()
    try:
        if eid is None:
            eid = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
        if kind not in TEXT_KINDS:
            raise ValueError(f"unsupported Material.kind for text module: {kind!r}")
        doc = read_material(p, kind)
        text = doc.get("text") or ""
        if doc.get("description") and doc["description"] not in text:
            text = (text + "\n" + doc["description"]).strip()
        feats = text_features(
            text,
            title=doc.get("title"),
            cta_texts=doc.get("cta_texts"),
            idf=idf,
            embed=embed,
            emb_model=emb_model,
            errors=errors,
        )
        if write_full_text and text:
            try:
                out = data_dir / "interim" / "text" / f"{eid}.txt"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(normalize_text(text), encoding="utf-8")
            except Exception as exc:
                errors.append(f"text.full_text_write: {type(exc).__name__}: {exc}"[:300])
    except Exception as exc:
        errors.append(f"text: {type(exc).__name__}: {exc}"[:300])
        feats = empty_features()
    return {
        "entity_id": eid or str(path),
        "level": LEVEL,
        "module": MODULE,
        "features": feats,
        "provenance": _provenance(emb_model if embed else None),
        "errors": errors,
    }


def extract(item: Material, ctx: Context) -> FeatureRecord | list[FeatureRecord]:
    """Module interface (CONTRACTS §4, v0.4). Never raises.

    html/mhtml/json -> one FeatureRecord. image/video/asset -> one record per OCR text found
    for this material in W3's data/features/visual.parquet (video frames "<id>#f<n>"),
    or [] (skipped) when there is no OCR text.
    """
    data_dir = _ctx_data_dir(ctx)
    cfg = _ctx_text_config(ctx)
    repo_root = _ctx_get(ctx, "repo_root")
    mid = getattr(item, "material_id", None) or getattr(item, "incident_id", None)
    inc = getattr(item, "incident_id", None)
    path = getattr(item, "path", None)
    if path is None:
        return FeatureRecord(
            entity_id=str(mid), level=LEVEL, module=MODULE, features=empty_features(),
            provenance=_provenance(None), errors=["text: item has no path"], incident_id=inc,
        )
    kind = getattr(item, "kind", None)
    if kind in OCR_KINDS:
        return _ocr_extract(item, data_dir, repo_root, cfg)
    d = extract_dict(
        _resolve_path(path, repo_root), entity_id=mid, kind=kind,
        data_dir=data_dir, config=cfg, idf=corpus_idf(data_dir, repo_root),
    )
    return FeatureRecord(
        entity_id=d["entity_id"], level=d["level"], module=d["module"],
        features=d["features"], provenance=d["provenance"], errors=d["errors"], incident_id=inc,
    )


# ----------------------------------------------------------------- OCR records (from visual.parquet)

_OCR_CACHE: dict[str, tuple[float, dict[str, list[tuple[str, str]]]]] = {}

# Signal fields left empty for OCR records: text_semantic, same_narrative, same_platform_name.
OCR_DISABLED_FIELDS = ("text_emb", "narrative_key", "platform_name")


def _ocr_index(data_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """material_id -> [(entity_id, ocr_text)] from W3 visual.parquet (cached per file version)."""
    p = data_dir / "features" / "visual.parquet"
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    cached = _OCR_CACHE.get(str(p))
    if cached and cached[0] == mtime:
        return cached[1]
    index: dict[str, list[tuple[str, str]]] = {}
    try:
        import pandas as pd

        df = pd.read_parquet(p, columns=["entity_id", "ocr_text"])
        for eid, txt in zip(df["entity_id"], df["ocr_text"]):
            if isinstance(txt, str) and txt.strip():
                mid = str(eid).split("#", 1)[0]
                index.setdefault(mid, []).append((str(eid), txt))
    except Exception:
        index = {}
    _OCR_CACHE[str(p)] = (mtime, index)
    return index


def _ocr_extract(item: Any, data_dir: Path, repo_root: Path | None, cfg: dict) -> list[FeatureRecord]:
    mid = getattr(item, "material_id", None)
    inc = getattr(item, "incident_id", None)
    hits = _ocr_index(data_dir).get(str(mid), [])
    if not hits:
        return []
    idf = corpus_idf(data_dir, repo_root)
    out = []
    for eid, txt in hits:
        errors: list[str] = []
        try:
            feats = text_features(txt, idf=idf, embed=False, errors=errors)
        except Exception as exc:  # text_features should not raise; belt and braces
            feats, errors = empty_features(), [f"text.ocr: {type(exc).__name__}: {exc}"[:300]]
        # OCR text is short and noisy (W3 reference run: text_semantic linked 82% of pairs even
        # with floor 0.85, every narrative "other", platform names from OCR garbage). For OCR
        # records only text_near_dup and shared_entities are used; the other signals get None.
        for key in OCR_DISABLED_FIELDS:
            feats[key] = None
        prov = _provenance(None)
        prov["ocr_text"] = "W3 visual.parquet (Tesseract OCR)"
        out.append(FeatureRecord(entity_id=eid, level=LEVEL, module=MODULE, features=feats,
                                 provenance=prov, errors=errors, incident_id=inc))
    return out
