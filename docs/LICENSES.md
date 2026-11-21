# Licencje: biblioteki, modele, usługi

> Wymagania organizatora: lista bibliotek, modeli i usług z licencjami i ograniczeniami (R9),
> kod wolny od wad prawnych, bo zwycięzcy przenoszą prawa majątkowe na NASK (R11).
> Opracował W4 (integracja środowiska) na podstawie `requirements/*.txt`, raportów W1–W5
> i plików LICENSE u źródła. Wersje odpowiadają przypięciom w repo.

**Podsumowanie:** wszystkie biblioteki i modele, które linkujemy albo dystrybuujemy w obrazie,
mają **licencje permisywne** (MIT, BSD, Apache-2.0, ISC, HPND). Nie ma żadnej licencji
niekomercyjnej ani copyleft wbudowanej w aplikację. Jedyny komponent GPL to **opcjonalny**
kontener Neo4j, uruchamiany jako osobna usługa (szczegóły niżej). Żadna usługa nie wymaga klucza API.

---

## 1. Biblioteki Pythona (bezpośrednie zależności)

| biblioteka | wersja | licencja | do czego | moduł |
|---|---|---|---|---|
| pyyaml | 6.0.2 | MIT | konfiguracja `settings.yaml`, `stoplist.yaml` | core |
| pandas | 2.2.3 | BSD-3-Clause | tabele cech | core |
| pyarrow | 18.1.0 | Apache-2.0 | zapis/odczyt parquet | core |
| numpy | 2.1.3 | BSD-3-Clause | wektory, macierze podobieństwa | core |
| networkx | 3.4.2 | BSD-3-Clause | graf powiązań, Louvain | core / engine |
| scikit-learn | 1.5.2 | BSD-3-Clause | wagi (regresja logistyczna), HDBSCAN, klastrowanie twarzy | core / engine / faces |
| datasketch | 1.6.5 | MIT | MinHash / LSH (near-duplikaty tekstu) | core / text |
| python-dotenv | 1.0.1 | BSD-3-Clause | wczytanie `.env` | core |
| beautifulsoup4 | 4.12.3 | MIT | parsowanie HTML (statyczne) | ingest / text |
| lxml | 5.3.0 | BSD-3-Clause | parser HTML dla bs4 | ingest |
| tldextract | 5.1.3 | BSD-3-Clause | domena rejestrowana (eTLD+1), offline ze snapshotu PSL | ingest / infra |
| langdetect | 1.0.9 | Apache-2.0 | wykrywanie języka | text |
| sentence-transformers | 3.3.1 | Apache-2.0 | embeddingi tekstu (e5) | text |
| transformers | 4.46.3 | Apache-2.0 | backend modeli tekstowych | text |
| torch | 2.5.1 (CPU) | BSD-3-Clause | inferencja CLIP i e5 | visual / text |
| torchvision | 0.20.1 (CPU) | BSD-3-Clause | transformacje obrazów dla CLIP | visual |
| open_clip_torch | 3.3.0 | MIT | model CLIP (styl wizualny, logo zero-shot) | visual |
| opencv-python-headless | 5.1.0.95 | Apache-2.0 ¹ | YuNet/SFace (`cv2.dnn`), klatki wideo, k-means | visual / faces |
| Pillow | 12.0.0 | MIT-CMU (HPND) | wczytywanie obrazów | visual |
| ImageHash | 4.3.2 | BSD-2-Clause | pHash / dHash (near-duplikaty obrazów) | visual |
| pytesseract | 0.3.13 | Apache-2.0 | wrapper OCR | visual |
| mmh3 | 5.0.1 | MIT | hash favicony (styl Shodana) | infra |
| dnspython | 2.7.0 | ISC | DNS A/NS/MX (tylko tryb online) | infra |
| requests | 2.32.3 | Apache-2.0 | RDAP / crt.sh (tylko tryb online) | infra |
| streamlit | 1.67.0 | Apache-2.0 | demonstrator GUI | ui |
| pyvis | 0.3.2 | BSD-3-Clause | interaktywny widok grafu | ui |
| pytest | 8.3.4 | MIT | testy (tylko `requirements/dev.txt`, nie ma go w obrazie) | dev |

¹ Koła `opencv-python-headless` zawierają dynamicznie linkowaną bibliotekę **FFmpeg (LGPL-2.1)**
do dekodowania wideo. LGPL przy linkowaniu dynamicznym nie narzuca licencji na nasz kod.
Przy dystrybucji obrazu trzeba zachować informację o licencji FFmpeg (jest w pakiecie).

Zależności przechodnie (m.in. huggingface_hub, tokenizers, safetensors, timm, ftfy, regex, tqdm,
protobuf, altair, pydeck) są na licencjach permisywnych: Apache-2.0, MIT albo BSD.
Pełną listę z wersjami da `pip-licenses` uruchomione w zbudowanym obrazie.

---

## 2. Modele

Wszystkie są pobierane przy budowie obrazu do `/models`, a lokalnie przy pierwszym użyciu
do `data/models/` lub cache Hugging Face. **Nigdy nie są commitowane.**

| model | licencja | źródło | do czego | moduł |
|---|---|---|---|---|
| `intfloat/multilingual-e5-small` | MIT | Hugging Face | semantyczne podobieństwo tekstu (PL) | text |
| CLIP ViT-B-32 (wagi `openai`, `quickgelu`) | MIT | OpenAI CLIP przez open_clip | styl wizualny, logo zero-shot | visual |
| YuNet `face_detection_yunet_2023mar.onnx` | **MIT** ² | opencv_zoo (GitHub) | detekcja twarzy | faces |
| SFace `face_recognition_sface_2021dec.onnx` | Apache-2.0 | opencv_zoo (GitHub) | embedding twarzy | faces |
| Tesseract, dane `pol.traineddata` | Apache-2.0 | pakiety Debiana `tesseract-ocr`, `tesseract-ocr-pol` | OCR tekstu z obrazów | visual |

² Licencję zweryfikowano w pliku `models/face_detection_yunet/LICENSE` w opencv_zoo.
We wcześniejszym opisie modułu figurowało Apache-2.0. Obie licencje są permisywne.

### Świadomie NIE użyte

| komponent | dlaczego |
|---|---|
| **InsightFace** (np. `buffalo_l`, ArcFace) | Kod jest na MIT, ale **udostępnione wagi modeli są wyłącznie do niekomercyjnych badań**. Użycie kolidowałoby z przeniesieniem praw na NASK (R11) i z wdrożeniem. Zamiast tego używamy YuNet + SFace (MIT / Apache-2.0). |
| modele i API wymagające klucza (np. komercyjne LLM, płatne bazy WHOIS) | Organizator musi móc zweryfikować wynik bez naszych kluczy (R9). LLM jest opcjonalny i domyślnie wyłączony (`LLM_ENABLED=false`). |

---

## 3. Oprogramowanie systemowe i kontenery

| komponent | licencja | uwagi |
|---|---|---|
| Python 3.11 / 3.12 | PSF-2.0 | |
| obraz bazowy `python:3.11-slim-bookworm` | różne (Debian: głównie GPL/LGPL/MIT/BSD) | standardowe narzędzia systemu, nie linkowane z naszym kodem |
| `libgl1`, `libglib2.0-0` | MIT / LGPL-2.1 | biblioteki uruchomieniowe OpenCV, linkowane dynamicznie |
| **Neo4j Community 5.26** (opcjonalnie, profil `graph`) | **GPL-3.0** | **Osobny kontener**, z którym nie linkujemy. Komunikacja wyłącznie przez import CSV i protokół Bolt, więc GPL nie obejmuje naszego kodu. Komponent opcjonalny: aplikacja działa bez niego (graf w UI rysuje pyvis). Przy wdrożeniu komercyjnym trzeba rozważyć Neo4j Enterprise albo zostać przy eksporcie CSV. |

---

## 4. Zewnętrzne usługi

Wszystkie są **opcjonalne**, **bez kluczy API** i **domyślnie wyłączone** (`OFFLINE=true`).
Każdą odpowiedź zapisujemy w `data/cache/osint.sqlite`, więc demo działa offline.
Zapytania idą wyłącznie do neutralnych usług publicznych, **nigdy do domen z próbek**.
User-Agent jest generyczny i nie zawiera danych zespołu.

| usługa | adres | co zwraca | warunki |
|---|---|---|---|
| RDAP (bootstrap) | `rdap.org` → serwery RDAP rejestrów | rejestrator, data rejestracji, NS, status domeny | publiczne, bez klucza (następca WHOIS, RFC 9082/9083) |
| RDAP RIR | `rdap.org/ip/…`, `rdap.db.ripe.net` | sieć / właściciel bloku IP | publiczne, bez klucza; IP z zakresów Cloudflare są pomijane |
| DNS | resolwery `1.1.1.1` (Cloudflare), `8.8.8.8` (Google) | rekordy A, NS, MX | publiczne |
| crt.sh | `crt.sh` (Sectigo) | certyfikaty z Certificate Transparency: wystawca, daty, SAN | publiczne, bez klucza, ograniczona przepustowość (timeout 10 s) |

Źródła używane **tylko przy budowie obrazu** (pobieranie paczek i modeli): PyPI,
`download.pytorch.org` (torch CPU), Hugging Face Hub (e5, CLIP), GitHub (opencv_zoo),
repozytoria Debiana. Uruchomiony kontener z nich nie korzysta.

---

## 5. Dane

- **Dane organizatora (NASK)**: wyłącznie do wyzwania, zakaz rozpowszechniania (R1). Nie są w repo
  ani w obrazie Dockera. Montujemy je jako wolumen (`data/`), co pilnują `.gitignore` i `.dockerignore`.
- **Lista publicznych sufiksów (PSL)** w tldextract: MPL-2.0 (dane, nie kod). Snapshot jest
  dołączony do pakietu, więc niczego nie pobieramy.
- Listy referencyjne w `config/reference/` zawierają same nazwy osób i marek, bez zdjęć.
