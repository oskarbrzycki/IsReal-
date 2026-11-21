# IsReal?

**Kolekcjoner fejków / Follow the Fake** · wyzwanie **NASK PIB** · HackNation 2026

Narzędzie bierze pojedyncze podejrzane reklamy
(fałszywe artykuły z wizerunkami znanych osób, „platformy inwestycyjne”, suplementy)
razem z ich stronami docelowymi, wyciąga z nich cechy, wykrywa duplikaty i warianty,
a potem łączy materiały w **kampanie** i **rodziny kampanii**. Nowy materiał przypisuje
do znanej kampanii albo oznacza jako **nową kampanię**. Każde powiązanie ma przesłanki,
np. „wspólny piksel FB”, „domeny zarejestrowane w odstępie 108 s” albo „ta sama osoba na zdjęciu”.

> **Bezpieczeństwo.** Dane to prawdziwe strony oszustów. Narzędzie wykonuje wyłącznie
> **analizę statyczną**: parsuje pliki HTML, HAR i JSON, nigdy nie otwiera stron w przeglądarce,
> nie wykonuje JavaScriptu i nie łączy się z domenami z próbek. Jedyny ruch sieciowy to
> opcjonalne zapytania do neutralnych usług publicznych (RDAP, DNS, crt.sh), domyślnie wyłączone.

---

## Szybki start (Docker — zalecane)

Wymagania: Docker z Compose v2.

```bash
# 1. dane organizatora -> data/raw/nask/<N>/   (patrz "Struktura danych")
# 2. obraz (pierwszy build pobiera torch CPU i modele, kilkanaście minut)
docker compose build

# 3. przebieg wsadowy: ingest -> features -> correlate
docker compose --profile pipeline run --rm pipeline

# 4. demonstrator
docker compose up app            # http://localhost:8501
```

Opcjonalnie graf w Neo4j (CSV z `data/graph/neo4j/`):

```bash
docker compose --profile graph up neo4j     # http://localhost:7474
```

Obraz zawiera wszystkie modele (pobrane przy budowie do `/models`), więc **kontener działa bez sieci**.
Katalog `data/` jest montowany jako wolumen i **nigdy nie trafia do obrazu** (`.dockerignore`).

---

## Instalacja lokalna (bez Dockera)

Python **3.11 lub 3.12**.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate

# Tylko Linux: najpierw torch w wersji CPU (bez wielogigabajtowych kół CUDA).
# Na Windows i macOS koła z PyPI są już CPU-only, więc ten krok można pominąć.
pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
pip install -r requirements/dev.txt      # pytest, tylko do testów
```

OCR wymaga programu **Tesseract** z językiem polskim:

| system | instalacja |
|---|---|
| Debian/Ubuntu | `apt-get install tesseract-ocr tesseract-ocr-pol` |
| macOS | `brew install tesseract tesseract-lang` |
| Windows | instalator UB Mannheim, potem `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` w `.env` |

**Tesseract jest opcjonalny.** Bez niego nie ma OCR, czyli pole `ocr_text` jest puste
(tekst z obrazów reklam nie trafia do modułu `text`). Cała reszta działa normalnie.

### Pierwsze uruchomienie `features` pobiera wagi modeli (~1,1 GB)

Przy pierwszym `python -m fakecollector features` modele pobierają się automatycznie.
W zależności od łącza zajmuje to **od kilku do kilkunastu minut**. Kolejne uruchomienia
korzystają z pobranych plików i działają offline.

| model | rozmiar | dokąd trafia |
|---|---:|---|
| CLIP ViT-B-32 (`visual`) | ~600 MB | `data/models/open_clip/` |
| YuNet + SFace (`faces`) | ~40 MB | `data/models/` |
| multilingual-e5-small (`text`) | ~470 MB | cache Hugging Face: `~/.cache/huggingface/` albo `HF_HOME` |

- Inny katalog modeli ustawisz zmienną `MODELS_DIR`, a cały `data/` przeniesiesz zmienną `DATA_DIR`.
- `TEXT_EMB_DISABLED=1` pomija e5 (oszczędza ~470 MB). Tekst jest wtedy porównywany bez embeddingów.
- **W Dockerze nic się nie pobiera:** wszystkie modele są wbudowane w obraz (`/models`) już przy `docker compose build`.

Konfiguracja: skopiuj `.env.example` do `.env`.

---

## Struktura danych

```
data/                         # w .gitignore i .dockerignore - nigdy nie trafia do repo ani obrazu
├── raw/nask/<N>/             # jeden folder = jeden incydent (1, 2, 3, 5, 10, 14, 36, 47, 48, 61)
│   ├── *.html + *_files/     #   zapis "cała strona" z przeglądarki
│   ├── *.har                 #   log ruchu sieciowego (uwaga: bywa nazwany po prostu ".har")
│   ├── *.png / *.mp4         #   reklama, zrzuty ekranu, nagrania
│   └── manifest.json / *.info.json
├── interim/incidents.jsonl   # wyjście ingest
├── features/<moduł>.parquet  # cechy per moduł
├── cache/osint.sqlite        # odpowiedzi RDAP / DNS / crt.sh (dla trybu offline)
├── graph/                    # edges.parquet, clusters.json, neo4j/*.csv
└── models/                   # wagi modeli (lokalnie; w Dockerze /models)
```

Dane muszą leżeć dokładnie w `data/raw/nask/<N>/`, **bez** pośredniego folderu
(np. `do_udostępnienia/`), czyli tak jak w CONTRACTS.md v0.4.

---

## Komendy CLI

```bash
python -m fakecollector inventory  --data data/raw/nask      # statyczny raport zbioru
python -m fakecollector ingest     --data data/raw/nask      # -> data/interim/incidents.jsonl
python -m fakecollector features   --module all              # -> data/features/*.parquet
python -m fakecollector features   --module infra --online   # z zapytaniami OSINT
python -m fakecollector correlate                            # -> data/graph/ (krawędzie, klastry)
python -m fakecollector analyze    <ścieżka|URL>             # nowy materiał -> przypisanie (JSON)
python -m fakecollector evaluate                             # -> reports/eval_<ts>.md
python -m fakecollector monitor    [--online]                # rotacja domen kampanii -> data/graph/monitor_<ts>.json

streamlit run ui/app.py                                      # demonstrator, tylko http://localhost:8501
python -m pytest -q                                          # testy
python scripts/leak_check.py --ref main                      # przed publikacją: czy w drzewie są dane NASK (R1), wymaga lokalnych data/
```

`monitor` ponownie sprawdza RDAP i DNS domen znanych kampanii, porównuje je z poprzednim
przebiegiem (`data/cache/monitor_state.json`) i wypisuje zmiany: nowe NS albo IP, zawieszenie,
wygaśnięcie, zniknięcie z DNS. Bez `--online` korzysta tylko z cache.

`leak_check` buduje w pamięci listę wrażliwych wartości z lokalnych danych (domeny, ID pikseli
i kont, tytuły stron, nazwy plików) i szuka ich w plikach śledzonych przez git. Kod wyjścia 1
oznacza znalezisko. Lista wartości nigdy nie jest zapisywana. `--summary` pokazuje same liczby,
`--redact` maskuje wartości w wyniku. Publiczna wersja powstaje przez `git archive` (bez historii
i wiadomości commitów), więc przed publikacją wystarczy `--ref main`. `--commits` przydaje się
tylko wtedy, gdy udostępniamy całe repozytorium razem z historią.

Moduły cech: `html_struct`, `text`, `visual`, `faces`, `infra` (lista po przecinku też działa).

Demonstrator nasłuchuje wyłącznie na `localhost` (`.streamlit/config.toml`: `server.address = "localhost"`), więc nie jest widoczny z sieci, do której podłączony jest laptop. Nie uruchamiaj go z `--server.address 0.0.0.0` poza kontenerem.

---

## Tryb offline i online

| | offline (domyślny) | online |
|---|---|---|
| przełącznik | `--offline`, `OFFLINE=true` | `--online`, `OFFLINE=false` |
| analiza HTML/HAR/JSON, obrazy, tekst | ✔ | ✔ |
| RDAP, DNS, crt.sh, ASN | tylko z `data/cache/osint.sqlite` | zapytania do usług publicznych + zapis do cache |
| ruch sieciowy | brak | tylko rdap.org, resolwery 1.1.1.1/8.8.8.8, crt.sh, RDAP RIR |

Usługi OSINT **nie wymagają kluczy API**. Odpowiedzi są w cache przez 7 dni (timeout 10 s).
Typowy scenariusz: raz uruchomić `--online`, żeby zapełnić cache, a demo prowadzić offline.

W Dockerze: `OFFLINE=false docker compose --profile pipeline run --rm pipeline`.

---

## Jak to działa (skrót)

1. **ingest**: folder incydentu → lista materiałów (HTML, assety, HAR, obrazy, wideo, JSON) z `sha1`.
2. **cechy** (równolegle): struktura HTML, tekst (e5, MinHash, encje), obraz (pHash, CLIP, OCR),
   twarze (YuNet + SFace), infrastruktura (piksele, konta reklamowe, domeny, RDAP, adtech).
3. **korelacja**: ważone podobieństwo liczone tylko na dostępnych sygnałach, więc braki danych nie
   psują wyniku. Grupowanie jest dwupoziomowe: **kampania** (sygnały identyfikujące, np. piksel)
   i **rodzina** (wspólny „kit”, np. szablon linków albo zestaw sieci reklamowych).
4. **wyjaśnienia**: każda krawędź ma listę przesłanek z wagami.

Szczegóły: `CONTRACTS.md`, `docs/METHODOLOGY.md`. Licencje: `docs/LICENSES.md`.

---

## Zasady repozytorium

- **Dane organizatora nie trafiają do repo ani do obrazu Dockera** (`data/` w `.gitignore` i `.dockerignore`).
- Żadnych kluczy w repo: `.env` jest ignorowany, wzór jest w `.env.example`.
- Zależności: każdy pakiet przypięty (`==`) w **dokładnie jednym** pliku `requirements/<moduł>.txt`.
  Pilnuje tego `tests/test_requirements.py`.
- Praca na własnych branchach, merge do `main` przez lidera po akceptacji koordynatora.

| Branch | Właściciel | Zakres |
|---|---|---|
| `feature/ingest` | W1 | loader, runner, CLI, `html_struct`, UI |
| `feature/text` | W2 | `text` |
| `feature/visual` | W3 | `visual`, `faces` |
| `feature/infra` | W4 | `infra`, stoplista, środowisko, Docker, licencje |
| `feature/clustering` | W5 | `engine`, `eval` |
| `feature/docs` | lider | metodyka, dokumentacja |
