# CONTRACTS.md — Kolekcjoner Fejków / Follow the Fake (HackNation 2026, NASK)

> Jedno źródło prawdy dla interfejsów. Zmiany kontraktu tylko przez koordynatora (CHANGELOG na dole).
> Status: v0.4 (po raporcie 1).

---

## 0. WYMAGANIA ORGANIZATORA

| # | Wymaganie | Źródło | Jak spełniamy |
|---|-----------|--------|---------------|
| R1 | **Dane organizatora wyłącznie na potrzeby wyzwania, zakaz publicznego rozpowszechniania** | opis §8 | `data/` w `.gitignore` od 1. commita. Nie commitujemy surowych plików, zrzutów, wycinków twarzy ani pełnych tekstów stron. W repo tylko kod, config, metryki i zanonimizowane przykłady. Repo publiczne dopiero po przejrzeniu (lub prywatne z dostępem dla jury — decyzja lidera). |
| R2 | Działający demonstrator z prostym GUI, który pokazuje cały proces (wejście → cechy → porównanie → grupowanie → prezentacja) | opis §3–4, §6 | Streamlit, 4 widoki (sekcja 8) |
| R3 | Wejście: URL, zrzut ekranu, plik multimedialny, log, element zbioru albo inna wskazówka | opis §3 | `ingest` przyjmuje folder, plik HTML, obraz, URL (tryb online opcjonalny) |
| R4 | Analiza nowego materiału względem zbioru: przypisanie do kampanii albo **„nowa kampania”** | opis §2, §6 | `engine.assign()` z progiem otwartego zbioru |
| R5 | Wyjaśnialność: przesłanki każdego powiązania | opis §3, §6 | Każda krawędź ma listę `Reason` (sekcja 6) |
| R6 | Odporność na duplikaty, braki danych (martwe strony, brak zdjęć) i różne formaty | opis §3, §6 | Każda cecha może być `null`; podobieństwo liczone tylko na dostępnych modalnościach, z renormalizacją wag |
| R7 | Dokumentacja metodyki: pozyskanie cech, podobieństwo, grupowanie | opis §4 | `docs/METHODOLOGY.md` |
| R8 | Instrukcja instalacji i uruchomienia, zależności; kontener preferowany | opis §4–5 | `Dockerfile`, `docker-compose.yml`, `README.md` |
| R9a | OSINT online (RDAP, DNS, crt.sh) **zatwierdzony**: tylko neutralne usługi publiczne, bez kluczy, z cache w `data/cache/`; demo działa offline z cache | decyzja koord. 14:20 | flaga `--online` |
| R9 | Lista bibliotek, modeli i usług z licencjami i ograniczeniami; zewnętrzne API ma dać się zweryfikować bez naszych kluczy | opis §4 | `docs/LICENSES.md`. Preferujemy źródła bez klucza (RDAP, DNS, crt.sh). Wszystko, co wymaga klucza, jest opcjonalne i wyłączalne. |
| R10 | Dodatkowe dane i źródła dozwolone, ale ze wskazaniem pochodzenia | opis §8 | Pole `provenance` w każdym rekordzie cech |
| R11 | Zwycięzcy przenoszą autorskie prawa majątkowe na NASK (umowa w 7 dni) → kod wolny od wad prawnych | regulamin §4 | Bez kopiowanego kodu o niejasnej licencji. Modele z licencją niekomercyjną (np. wagi InsightFace) opisane w LICENSES.md jako ograniczenie wdrożeniowe. |
| R12 | Kryteria: korelacja/grupowanie 30%, cechy i źródła 30%, end-to-end 15%, interpretowalność 15%, wdrożenie/skalowalność/przenośność 10% | opis §9 | Raport ewaluacji + metodyka + Docker |
| R13 | Ocena na ukrytym zbiorze: nowe warianty znanych kampanii **i** materiały spoza nich | opis §6 | Ewaluacja leave-campaign-out (sekcja 9) |
| R14 | Bezpieczeństwo: materiały to **żywe scamy** | zdrowy rozsądek | Nigdy nie wykonujemy JS z próbek. Render offline z wyłączonym JS i zablokowaną siecią. Pobieranie online tylko w kontenerze, z timeoutem i bez wysyłania formularzy. Nie klikamy linków z danych. |
| R15 | Żadnych kluczy w repo; komentarze w kodzie po angielsku | zasady zespołu | `.env` w `.gitignore`, `.env.example` w repo |

---

## 1. STRUKTURA REPO

```
/
├── data/                    # GITIGNORED w całości
│   ├── raw/nask/            # rozpakowana paczka organizatora (foldery 1,2,3,5,10,...)
│   ├── interim/             # sparsowane rekordy, rendery, wycinki obrazów
│   ├── cache/               # cache odpowiedzi RDAP/DNS/crt.sh (sqlite)
│   ├── features/            # parquet per moduł cech
│   └── graph/               # edges.parquet, clusters.json, eksport Neo4j
├── fakecollector/
│   ├── core/                # W5  models.py, config.py, io.py (właściciel typów)
│   ├── ingest/              # W1  loader zbioru, parser HTML, render offline
│   ├── features/
│   │   ├── html_struct.py   # W1  DOM fingerprint, trackery, skrypty, formularze, hidden text
│   │   ├── text.py          # W2  narracja, słowa kluczowe, encje, embeddingi, MinHash
│   │   ├── visual.py        # W3  pHash, CLIP/SigLIP, OCR obrazów
│   │   ├── faces.py         # W3  detekcja i embedding twarzy, baza referencyjna
│   │   └── infra.py         # W4  domeny, RDAP, DNS, crt.sh, ASN, favicon hash, przekierowania
│   ├── engine/              # W5  podobieństwo, wagi, klastrowanie, przypisanie, wyjaśnienia
│   ├── eval/                # W5  metryki, splity, raporty
│   └── cli.py               # W1  `python -m fakecollector ...`
├── ui/app.py                # W1 (od ~16:00) Streamlit
├── config/
│   ├── settings.yaml        # ścieżki, progi, wagi startowe, przełączniki modułów
│   └── reference/           # lista osób/marek do bazy referencyjnej (same nazwy, bez zdjęć)
├── docs/                    # METHODOLOGY.md, LICENSES.md, DATA_INVENTORY.md, PATTERNS.md, AI_USAGE.md
├── reports/                 # metryki ewaluacji (.md/.csv, bez danych surowych)
├── tests/
├── Dockerfile  docker-compose.yml  requirements.txt  .env.example  .gitignore
├── CONTRACTS.md  README.md
```
Repo: `oskarbrzycki/hackaton1` (prywatne do czasu zgłoszenia).
Branche: W1 `feature/ingest` (od ~16:00 też `feature/ui`), W2 `feature/text`, W3 `feature/visual`, W4 `feature/infra`, W5 `feature/clustering`, lider `feature/docs`. `feature/features` usuwamy. Każdy W modyfikuje tylko swój moduł i swoje testy. Merge do `main` przez Pull Request po akceptacji koordynatora.

---

## 2. JEDNOSTKI DANYCH (potwierdzone inwentaryzacją, docs/DATA_INVENTORY.md)

- **Incident = folder najwyższego poziomu** w zbiorze wejściowym (`data/raw/nask/<id>/`, **bez** pośredniego `do_udostępnienia/`; każdy ma dane dokładnie w tym układzie). Treningowo jest 10 incydentów: `1,2,3,5,10,14,36,47,48,61`. **Jednostka klastrowania.**
- **Material** = plik w incydencie. Rodzaje (`kind`):
  `html` (strona „cała strona” z przeglądarki), `asset` (plik z folderu `X_files/`, np. js/css/obraz; skrypty mają sufiks `.pobrane`), `har` (log ruchu sieciowego), `image` (zrzut reklamy/strony), `video` (mp4; HLS `.m3u8/.ts` traktujemy jak video), `mhtml`, `json` (manifest.json, info.json z yt-dlp), `other`.
- Incydent może mieć **łańcuch stron** (np. folder 61: strona „biała” → produkt → fałszywy artykuł) albo kilka zapisów tej samej strony (folder 14). Kolejność w łańcuchu zapisujemy w `Material.meta["chain_index"]`, jeśli da się ją ustalić.
- Incydent może nie mieć landingu (folder 5: sama reklama). Każdy moduł musi to znieść.
- **Campaign** = grupa incydentów. Folder ≠ kampania. Robocze etykiety do ewaluacji są w `eval/labels.yaml`: {1,2,3}, {48,61}, reszta osobno (hipoteza z inwentaryzacji, czekamy na potwierdzenie mentorów).

Identyfikatory:
- `material_id = sha1(bytes)[:16]` — identyczne pliki = ten sam materiał (deduplikacja dokładna).
- `incident_id = "<source>:<folder>"`, np. `nask:36`. Nowe materiały: `upload:<timestamp>`.

Wyjście loadera (W1): `data/interim/incidents.jsonl` — jedna linia = jeden `Incident` (z listą `Material`), serializacja `dataclasses.asdict`.

## 3. TYPY (fakecollector/core/models.py — właściciel W5; plik już jest w repo, plus `Context`)

```python
from dataclasses import dataclass, field
from typing import Any, Literal

MaterialKind = Literal["html", "asset", "har", "image", "video", "mhtml", "json", "other"]

@dataclass
class Material:
    material_id: str
    incident_id: str
    kind: MaterialKind
    path: str                         # path under data/ (never committed)
    original_url: str | None = None   # e.g. from "saved from url" comment, og:url, canonical
    mime: str | None = None
    size_bytes: int = 0
    is_common_lib: bool = False       # True if matched config/stoplist.yaml (jQuery, fbevents.js...)
    parent_html: str | None = None    # for kind="asset": material_id of the page it belongs to
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class Incident:
    incident_id: str
    source: str
    materials: list[Material]
    label_campaign: str | None = None # ground-truth folder id if known (eval only!)
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class FeatureRecord:                  # one row per (material or incident, module)
    entity_id: str                    # material_id or incident_id
    level: Literal["material", "incident"]
    module: str                       # "html_struct" | "text" | "visual" | "faces" | "infra"
    features: dict[str, Any]          # flat scalars, lists or vectors; None = unavailable
    provenance: dict[str, str]        # source -> url/tool + fetched_at ISO
    errors: list[str] = field(default_factory=list)
    incident_id: str | None = None    # always filled, so the engine can aggregate

@dataclass
class Reason:
    signal: str                       # e.g. "same_registered_domain", "face_match", "text_near_dup"
    score: float                      # 0..1 similarity on this signal
    weight: float                     # contribution in final score
    detail: str                       # human-readable, PL, e.g. "wspólna osoba: Rafał Brzoska (cos=0.71)"

@dataclass
class Edge:
    a: str                            # incident_id
    b: str
    score: float                      # combined 0..1
    reasons: list[Reason]

@dataclass
class Cluster:
    campaign_id: str                  # "C001"...
    members: list[str]                # incident_ids
    label: str                        # auto name, e.g. "Brzoska → Świtowin Zyskarnia"
    top_signals: list[str]
    cohesion: float

@dataclass
class Assignment:                     # result for a new incident
    incident_id: str
    campaign_id: str | None           # None = new campaign
    confidence: float
    nearest: list[Edge]               # top-k neighbours with reasons
```

---

## 4. INTERFEJS MODUŁÓW CECH (W1–W4)

Każdy moduł implementuje:
```python
MODULE = "text"                       # unique name
LEVEL = "material"                    # or "incident"
KINDS = ["html"]                      # which Material.kind this module processes
def extract(item: Material | Incident, ctx: Context) -> FeatureRecord | list[FeatureRecord]: ...
# list allowed (e.g. video -> one record per frame, entity_id "<material_id>#f<n>"); [] = skipped
```
- `ctx` daje ścieżki, config, cache HTTP i logger (W5 definiuje w `core/config.py`).
- Runner (W1, `fakecollector/features/runner.py`): wczytuje `incidents.jsonl`, filtruje materiały po `KINDS` (pomija `is_common_lib`), woła `extract`, zapisuje parquet. Moduł sam niczego nie zapisuje.
- Batch: `python -m fakecollector features --module text` → `data/features/text.parquet` (kolumny: `entity_id`, `level`, `module`, plus spłaszczone cechy; wektory jako listy float32).
- Moduł **nigdy nie rzuca wyjątku** na pojedynczym rekordzie: błąd trafia do `errors`, a cechy dostają `None`.
- Moduł deklaruje swoje sygnały podobieństwa w `SIGNALS` (sekcja 5), żeby silnik nie znał szczegółów cech.

```python
SIGNALS = {
  "text_semantic": {"type": "cosine", "field": "text_emb"},
  "text_near_dup": {"type": "jaccard_minhash", "field": "minhash"},
  "shared_entities": {"type": "set_overlap", "field": "entities"},
}
```
Agregacja do poziomu incydentu (W5, w silniku): zbiory = suma, wektory = lista (podobieństwo = **max** po parach materiałów), skalary = pierwszy niepusty. Moduły **nie** agregują same.

Kolejność uruchamiania: `ingest` → `html_struct`, `infra`, `visual`, `faces` (równolegle) → `text` (czyta też `ocr_text` z `visual.parquet`, jeśli istnieje) → `correlate`.

Specyfikacja sygnału może mieć opcjonalne klucze `floor`, `bits`, `tol`, `metric`; pole może wskazywać klucz w liście słowników (`"faces.emb"`). Typ `exact` przy wielu materiałach = zgodność przy dowolnym wspólnym elemencie.
Każdy sygnał ma **klasę** (`SIGNAL_CLASS` w module, domyślnie `"campaign"`): `campaign` = identyfikator konkretnej kampanii (piksel, konto reklamowe, domena landingu, identyczny asset, near-dup obrazu/tekstu); `family` = wspólny „kit”/aktor (szablon parametrów URL, wspólny CSS-kit, ta sama twarz w różnych narracjach, adtech stack, styl wizualny).

Typy podobieństwa obsługiwane przez silnik: `cosine`, `jaccard_minhash`, `set_overlap` (Jaccard), `exact` (równość niepusta), `hamming_hash` (pHash/simhash, znormalizowane), `numeric_close` (np. daty rejestracji domen ±N dni).

---

### Zależności
`requirements.txt` w root zawiera tylko linie `-r requirements/<moduł>.txt`. Każdy W dopisuje biblioteki **wyłącznie** do swojego pliku (`core.txt` W5, `ingest.txt` W1, `text.txt` W2, `visual.txt` W3, `infra.txt` W4). Wersje pinujemy (`==`). Python 3.11 lub 3.12.

## 5. KATALOG CECH (start, właściciele)

| Moduł | Cechy (pola) | Sygnały |
|---|---|---|
| html_struct (W1) | `original_url`, `title`, `meta`, `dom_simhash`, `asset_hashes` (sha1 assetów bez stoplisty), `css_classes`, `script_srcs`, `tracker_ids` (GA/GTM/FB pixel), `form_actions`, `form_fields`, `external_domains`, `hidden_text` (display:none, font-size 0, kolor = tło), `html_comments`, `generator`, `lang` | `dom_template`, `shared_assets`, `shared_trackers`, `shared_scripts`, `shared_form_endpoint`, `hidden_text_sim` |
| text (W2) | `visible_text` (tylko w data/), `keywords`, `entities` (osoby, marki, nazwa „platformy”), `narrative_type` (fałszywy news / wywiad / aresztowanie / „inwestycja” / …), `cta_phrases`, `promised_amounts`, `text_emb`, `minhash` | `text_semantic`, `text_near_dup`, `shared_entities`, `same_platform_name`, `same_narrative` |
| visual (W3) | obrazy + klatki wideo (strumieniowo, maks. N klatek; plik 323 MB!): `phash`, `dhash`, `clip_emb`, `ocr_text`, `logos` (zero-shot na liście marek), `dominant_colors` | `image_near_dup`, `visual_style`, `shared_logo` |
| faces (W3) | `faces: [{bbox, emb, quality, identity, id_score}]` | `face_match`, `same_identity` |
| infra (W4) | **z HAR offline:** `har_domains`, `har_ips`, `redirect_chain`, `har_tracker_ids` (np. `facebook.com/tr?id=`), `ad_params` (ad_id, adset_name, utm_* z URL i manifest.json); **online opcjonalnie (cache):** `domains` (eTLD+1), `rdap` (rejestrator, data rejestracji, NS), `dns` (A, NS, MX), `asn`, `cert_issuer`, `cert_date`, `cert_san`, `favicon_mmh3`, `redirect_chain` (opcjonalnie online) | `same_registered_domain`, `shared_ip_asn`, `shared_ns`, `shared_registrar_and_date`, `cert_san_overlap`, `same_favicon`, `shared_redirector` |

---

## 6. SILNIK KORELACJI (W5)

1. **Kandydaci**: blocking przez LSH (MinHash, pHash) plus pary dzielące dowolny klucz `exact`, żeby nie liczyć O(n²) przy dużym n.
2. **Wektor podobieństwa pary**: wartość każdego sygnału albo `None`, gdy brak danych.
3. **Wynik łączny**: `score = Σ w_s·sim_s / Σ w_s` liczone tylko po dostępnych sygnałach. Wagi startowo z `settings.yaml`, potem **uczone regresją logistyczną na parach (ta sama kampania / nie)** z walidacją grupową po kampanii. Współczynniki są wprost wyjaśnieniem w metodyce.
4. **Grupowanie dwupoziomowe** (odpowiada wymaganiu NASK „kampanie lub grupy podobnych kampanii”):
   - **kampanie**: graf krawędzi liczonych na sygnałach klasy `campaign`, `score ≥ τ_campaign` → Louvain (plus wariant HDBSCAN w raporcie),
   - **rodziny / aktorzy**: kampanie łączone, gdy łączy je sygnał klasy `family` ≥ `τ_family`. Przykład z danych: {1,2,3} i {48,61} dzielą szablon parametrów URL i CSS-kit.
   UI i raport pokazują oba poziomy z przesłankami.
5. **Duplikaty**: `exact material_id` lub `image_near_dup`/`text_near_dup` powyżej progu → łączymy w grupę duplikatów przed klastrowaniem.
6. **Nowy materiał**: `assign(incident) -> Assignment`. Top-k sąsiadów; jeśli max score < `τ_new` → `campaign_id=None` („nowy wzorzec”).
7. **Wyjaśnienie**: każda `Edge` ma posortowane `reasons`. Etykieta klastra powstaje z najczęstszych encji i nazwy platformy.

Wyjścia: `data/graph/edges.parquet`, `data/graph/clusters.json`, `data/graph/neo4j/*.csv` (import do Neo4j opcjonalny).

---

## 7. CLI (W1)

```
python -m fakecollector inventory  --data data/raw/nask
python -m fakecollector ingest     --data data/raw/nask          # -> data/interim/incidents.jsonl
python -m fakecollector features   [--module all|html_struct|text|visual|faces|infra] [--offline]
python -m fakecollector correlate                                 # -> edges, clusters
python -m fakecollector analyze    <path|url>                     # new material -> Assignment JSON
python -m fakecollector evaluate                                  # -> reports/eval_<ts>.md
```
`--offline` wyłącza wszystkie zapytania sieciowe (korzysta tylko z cache).

---

## 8. UI (Streamlit)

1. **Zbiór i kampanie**: tabela klastrów, liczności, etykiety, główne sygnały.
2. **Graf**: interaktywny (pyvis); krawędź po kliknięciu pokazuje `reasons`.
3. **Incydent**: materiały (miniatury tylko lokalnie), wyciągnięte cechy w podziale na moduły, top-5 podobnych z przesłankami.
4. **Nowy materiał**: upload HTML, obrazu, zipa albo URL → pipeline na żywo → przypisanie lub „nowa kampania” z uzasadnieniem.
5. **Metodyka i metryki**: wyniki ewaluacji, wagi sygnałów.

---

## 9. EWALUACJA (W5)

Danych jest mało (10 incydentów), więc ewaluacja ma 3 części:
1. **Etykiety ręczne** `eval/labels.yaml` (hipoteza: {1,2,3}, {48,61}, reszta singletony). Metryki: pairwise precision/recall/F1, ARI. Uwaga: te etykiety wykryto po wspólnych plikach, więc w raporcie pokazujemy wynik też **bez** sygnałów `shared_assets`/`same_material`, żeby nie było błędnego koła.
2. **Pseudo-warianty**: rozbijamy incydenty wielostronowe (61: 3 strony, 14: 2 zapisy) i wielomateriałowe na osobne pseudo-incydenty. Powinny wrócić do jednej kampanii. Do tego testy odporności: usuwamy losowo modalności (brak HAR, brak landingu, sam obraz).
3. **Open-set**: leave-one-campaign-out. Usuwamy kampanię z bazy; jej incydenty mają dostać „nowa kampania”.

Ablacja: wynik bez każdego modułu po kolei. Raport: `reports/eval_<ts>.md`, bez treści danych.

## 9a. STOPLISTA (właściciel W4, dopisują wszyscy)
`config/stoplist.yaml`: nazwy i sha1 popularnych bibliotek (jquery, fbevents.js, gtm.js, bootstrap, google fonts), puste `saved_resource.html`, domeny CDN i trackerów ogólnych (facebook.net, google-analytics.com, gstatic.com, cdnjs…). Materiały i domeny ze stoplisty **nie** dają sygnału „wspólny element”, ale identyfikator konkretnego piksela/konta (np. FB pixel id) **jest** sygnałem.

## 10. KONFIG I ŚRODOWISKO

`.env.example`:
```
DATA_DIR=./data
OFFLINE=true
HTTP_TIMEOUT_S=10
LLM_ENABLED=false
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
```
LLM jest opcjonalny (np. do klasyfikacji typu narracji). Bez niego wszystko działa na regułach i embeddingach.

---

## 11. OTWARTE PYTANIA (lider → mentorzy NASK)
1. Czy numer folderu = ID kampanii (ground truth)? Co jest jednostką „incydentu” w folderze?
2. W jakim formacie przyjdzie zbiór testowy (ta sama struktura folderów?) i jak będzie podany podczas oceny (live na demo czy oddany wcześniej)?
3. Czy można zapisać repo jako publiczne, jeśli nie zawiera danych organizatora (tylko kod i metryki)?
4. Czy oczekują ruchu sieciowego do żywych domen podczas oceny, czy wystarczy tryb offline z cache?

---

## CHANGELOG
- v0.1 — szkic dla zadania UZP (porzucony po zmianie zadania).
- v0.2 (sob ~12:10) — przejście na NASK „Kolekcjoner fejków”.
- v0.4 (sob ~14:20) — extract może zwracać listę; klucze opcjonalne SIGNALS; klasy sygnałów i grupowanie dwupoziomowe (kampania/rodzina); incidents.jsonl; Python 3.11–3.12; ścieżka danych bez `do_udostępnienia`; OSINT online dozwolony (bez kluczy, z cache).
- v0.3 (sob ~13:00) — po inwentaryzacji: incydent = folder, nowe rodzaje materiałów (asset/har/mhtml/json), HAR jako główne źródło infra offline, agregacja w silniku, stoplista, nowa ewaluacja (etykiety ręczne + pseudo-warianty + open-set).
