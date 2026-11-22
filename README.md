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

## Słownik pojęć

- **Zgłoszenie (incydent)**: jeden folder z materiałami jednego zgłoszenia, np. `data/raw/nask/47/`; to jednostka, którą grupujemy.
- **Materiał**: pojedynczy plik w zgłoszeniu: zrzut reklamy, wideo, zapisana strona HTML, plik z jej folderu `_files`, log HAR, JSON.
- **Cecha**: wartość wyciągnięta z materiału przez moduł cech (`html_struct`, `text`, `visual`, `faces`, `infra`), np. ID piksela, pHash obrazu, embedding twarzy.
- **Sygnał**: porównanie jednej cechy między dwoma zgłoszeniami (wynik 0–1); ma klasę `campaign` (ślad tej samej akcji) albo `family` (wspólny zestaw narzędzi lub aktor).
- **Twardy dowód**: sygnał, który sam wystarcza do połączenia w kampanię: wspólny piksel lub tag reklamowy, konto reklamowe, domena strony docelowej, identyczny plik strony.
- **Kampania**: zgłoszenia połączone twardym dowodem (albo co najmniej dwoma różnymi sygnałami klasy `campaign`), czyli ta sama akcja oszusta.
- **Kampania wieloincydentowa / pojedyncze zgłoszenie**: kampania z co najmniej dwoma zgłoszeniami / zgłoszenie, którego nie łączy z innymi żaden twardy ślad.
- **Rodzina**: kampanie połączone poszlakami (sygnały klasy `family`: szablon linków, CSS, te same twarze), czyli prawdopodobnie ten sam oszust lub zestaw narzędzi.
- **Przesłanka**: opis sygnału przy połączeniu, z podobieństwem i wagą, np. „wspólny piksel FB …5163, waga 3,5”.
- **Reguła twardych dowodów**: bez twardego dowodu (albo dwóch różnych sygnałów `campaign`) nie łączymy w kampanię; takie połączenie zostaje najwyżej na poziomie rodziny.
- **Nowa kampania**: wynik analizy nowego materiału, gdy żadne znane zgłoszenie nie pasuje powyżej progu (`tau_new` = 0,35).
- **Tryb publiczny**: widok UI z maskowaniem domen, identyfikatorów i nazw platform, do zrzutów, nagrań i prezentacji.
- **Tryb offline / online**: offline (domyślny) działa bez sieci, tylko na plikach i cache; online dodatkowo pyta publiczne usługi RDAP, DNS i crt.sh o nowe domeny.

## Gdzie co jest

| Co | Gdzie |
|---|---|
| Jak to działa: cechy, sygnały, wagi, reguła twardych dowodów, grupowanie | [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) |
| Wyniki na danych NASK (przebieg referencyjny) | [`docs/RESULTS_SUMMARY.md`](docs/RESULTS_SUMMARY.md) |
| Test na obcych danych (300 stron phishingowych) | [`docs/EXTERNAL_TEST.md`](docs/EXTERNAL_TEST.md) |
| Wzorce kampanii znalezione w danych | [`docs/PATTERNS.md`](docs/PATTERNS.md) |
| Biblioteki, modele i licencje | [`docs/LICENSES.md`](docs/LICENSES.md) |
| Użycie narzędzi AI w projekcie | [`docs/AI_USAGE.md`](docs/AI_USAGE.md) |
| Metryki i wagi sygnałów na żywo | zakładka „Metodyka i wyniki” w aplikacji |

---

## Uruchomienie na własnych danych

Chcesz sprawdzić narzędzie na **swoich** zgłoszeniach? Nazwy folderów mogą być dowolne
(`zgloszenie_A`, `case 2`, `47-kopia`, polskie znaki), nie trzeba nic zmieniać w kodzie ani w konfiguracji.
Zgłoszenie może mieć zagnieżdżone podfoldery. Pliki, których nie da się rozpoznać (pusty plik, uszkodzony zip,
samo `.txt`), są **pomijane z ostrzeżeniem**, a pozostałe zgłoszenia przechodzą dalej bez przerwy.

**a) Docker** (zalecane, modele są już w obrazie). Dla Dockera zgłoszenia **muszą leżeć w
`./data/raw/nask/<dowolna_nazwa>/`** w katalogu repozytorium (jeden folder = jedno zgłoszenie): tylko `./data`
jest widoczne w kontenerze. Sprawdzona sekwencja (świeży klon, 3 zgłoszenia):

```bash
docker compose build                                   # pierwszy raz ok. 14 min (torch CPU + modele w obrazie)
docker compose --profile pipeline run --rm pipeline    # ingest -> features -> correlate, kończy się sam
docker compose up app                                  # interfejs: http://localhost:8501
```

Katalog `./data` na hoście jest montowany w kontenerze jako `/app/data`. Aby użyć innego miejsca, zmień
ścieżkę wolumenu `./data` w `docker-compose.yml`. Krok `pipeline` uruchamiaj przez `run --rm`, a nie `up`:
`up` z profilem `pipeline` startuje też `app` i nie kończy się po przetworzeniu danych.

**b) pip** (Python 3.11 lub 3.12, po instalacji z sekcji niżej): jedna komenda wykonuje ingest, features,
correlate i evaluate:

```bash
python scripts/reference_run.py --data <folder_ze_zgłoszeniami>
# wyniki trafiają do data/ albo do katalogu z DATA_DIR, np.:  DATA_DIR=/ścieżka/data_jury python scripts/reference_run.py --data ...
streamlit run ui/app.py                                # interfejs: http://localhost:8501
```

- **Modele już pobrane?** W świeżym klonie `data/models` jest puste, więc pierwszy przebieg pobierze ok. 1,1 GB.
  Żeby użyć modeli z innej kopii repo, wskaż je zmienną `MODELS_DIR`, np. w PowerShell
  `$env:MODELS_DIR="C:\ścieżka\do\data\models"`, w bash `MODELS_DIR=/ścieżka/do/data/models python scripts/reference_run.py --data ...`.
- **Port 8501 zajęty** (np. przez kontener `app` albo drugą kopię UI)? Uruchom interfejs na innym porcie:
  `streamlit run ui/app.py --server.port 8502` i otwórz http://localhost:8502.

Bez `--data` skrypt bierze `data/raw/nask` (albo `DATA_DIR/raw/nask`). To samo krok po kroku:
`python -m fakecollector ingest --data <folder>`, potem `features --module all`, `correlate`, `evaluate`.
Bez naszych etykiet `evaluate` zapisuje raport z adnotacją „Brak etykiet: metryki pominięte”.

**c) Gdzie jest wynik:**
- interfejs: `streamlit run ui/app.py` (w Dockerze `docker compose up app`), czyli **http://localhost:8501**;
- `data/graph/clusters.json` (kampanie i rodziny) oraz `data/graph/edges.parquet` (krawędzie z przesłankami);
- raport kampanii w **JSON i CSV** (przyciski „Pobierz raport kampanii” w zakładce „Kampanie i rodziny”);
- `reports/eval_<data>.md` oraz `reports/reference_run_<data>.md` (przebieg i czasy).

**d) Tryb online (opcjonalnie).** Domyślnie wszystko działa offline. Flaga `--online` pobiera **świeże** dane
RDAP, DNS i crt.sh dla nowych domen (bez kluczy API): `python -m fakecollector features --module all --online`,
`python scripts/reference_run.py --online` albo w Dockerze `OFFLINE=false docker compose --profile pipeline run --rm pipeline`.

**e) Czas.** Pierwsze uruchomienie bez Dockera pobiera ok. **1,1 GB** modeli (w Dockerze są już w obrazie).
Na CPU ok. **19 s na zgłoszenie z obrazami** (przebieg referencyjny: 10 zgłoszeń, 313 plików, ok. 3 min do `correlate`,
ok. 3,7 min z `evaluate`) i ok. **0,3 s na zgłoszenie bez obrazów**. Najwięcej zajmuje CLIP, ok. 1 s na obraz, więc czas
zależy głównie od liczby obrazów. Analiza jednego nowego materiału w UI trwa 11 do 23 s.

---

## Szybki start (Docker — zalecane)

Wymagania: Docker z Compose v2.

```bash
# 1. dane organizatora -> data/raw/nask/<dowolna_nazwa_zgłoszenia>/   (patrz "Struktura danych")
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
├── raw/nask/<dowolna_nazwa_zgłoszenia>/   # jeden folder = jeden incydent (w danych NASK: 1, 2, 3, 5, 10, 14, 36, 47, 48, 61)
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

Dane muszą leżeć dokładnie w `data/raw/nask/<dowolna_nazwa_zgłoszenia>/`, **bez** pośredniego folderu
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

Interfejs: u góry **pasek zakładek** z pięcioma widokami (Kampanie i rodziny, Graf powiązań, Incydent, Analiza nowego materiału,
Metodyka i wyniki), a po lewej **sidebar „Ustawienia widoku”** z przełącznikami „Tryb prezentacji” (większa treść na rzutnik),
„Ukryj wiersze „brak: …”” i „Tryb publiczny” (maskuje domeny, identyfikatory i nazwy platform). Stan jest w adresie,
np. `http://localhost:8501/?tab=graf&public=1&present=1` (`tab`: `kampanie`, `graf`, `incydent`, `analiza`, `metodyka`).

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
