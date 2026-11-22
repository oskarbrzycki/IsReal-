# Scenariusz demo na pitch (3 minuty)

Demonstrator: `streamlit run ui/app.py`, aplikacja „IsReal? — od pojedynczej reklamy do całej kampanii oszustów”.
Role: **Narrator** mówi, **Operator** (W1) klika. Operator nie mówi, Narrator nie dotyka laptopa.
**Maszyna referencyjna: komputer lidera.** Liczby poniżej pochodzą ze wspólnej próby na tej maszynie (21.11, wieczór, tryb publiczny).
Aplikacja nasłuchuje wyłącznie na `localhost` (`.streamlit/config.toml`), więc nie jest widoczna z sieci wydarzenia.

---

## Przed pitchem (najpóźniej 15 min wcześniej)

| # | Kto | Co | Sprawdzenie |
|---|---|---|---|
| 0 | Operator | **Dzień wcześniej / na stabilnej sieci:** pobrać wagi modeli, łącznie ok. 1,1 GB (sam CLIP ok. 600 MB; YuNet, SFace i CLIP do `data/models/`, e5 do cache Hugging Face; szczegóły w README). Najprościej jednym pełnym przebiegiem `features --module all` | drugi przebieg `features` nic nie pobiera i działa bez sieci |
| 1 | Operator | Przebieg wsadowy: `python -m fakecollector ingest`, `features --module all`, `correlate` | w zakładce 1: 10 incydentów, **2 kampanie wieloincydentowe**, 6 pojedynczych zgłoszeń (razem 8 kampanii), **6 rodzin** |
| 2 | Operator | Przygotować pliki demo w `data/demo/` (poza gitem), komendy niżej | `folder2_bez_har.zip` ok. 1 MB, `folder47.zip` ok. 40 MB |
| 3 | Operator | `streamlit run ui/app.py`, przeglądarka na `http://localhost:8501/?public=1&tab=kampanie` (**Tryb publiczny włączony**: maskuje domeny, ID i nazwy platform), zoom 110–125%, pełny ekran | strona się ładuje, w sidebarze („Ustawienia widoku”) przełącznik „Tryb publiczny” jest włączony, pasek zakładek u góry pokazuje 5 widoków, nie ma czerwonych błędów |
| 4 | Operator | **Rozgrzewka (obowiązkowa):** w zakładce 4 przeanalizować raz `folder47.zip`. Pierwsza analiza ładuje modele (ok. 40 s), kolejne trwają 11–23 s | wynik się pokazał, druga analiza < 25 s |
| 5 | Operator | Wrócić do zakładki 1, zamknąć inne karty i powiadomienia, wyłączyć tryb uśpienia | |
| 6 | Operator | Otworzyć w drugiej karcie folder `docs/img/demo/` (plan B) | 5 zrzutów widocznych |

Pliki demo (z katalogu repo):

```bash
mkdir -p data/demo
(cd data/raw/nask && zip -qr ../../demo/folder2_bez_har.zip 2 -x "*.har" -x "*.DS_Store")
(cd data/raw/nask && zip -qr ../../demo/folder47.zip 47 -x "*.DS_Store")
```

---

## Przebieg (3:00)

### 0:00–0:35 · Zakładka „Kampanie i rodziny”
- **Operator:** nic nie klika, ekran startowy już widać.
- **Narrator:** „Dostaliśmy 10 zgłoszeń od NASK. Narzędzie samo złożyło je w 8 kampanii i 6 rodzin, ale tylko dwie z tych kampanii łączą więcej niż jedno zgłoszenie (wyróżniona karta „Kampanie wieloincydentowe”), pozostałe sześć to pojedyncze zgłoszenia bez powiązań. Kampania C001 to foldery 1 i 2: ta sama strona na dwóch różnych domenach. C002 to foldery 48 i 61. Rodzina F001 łączy obie te kampanie i folder 3: wspólny zestaw narzędzi, ale za mało twardych dowodów, żeby nazwać to jedną kampanią.”
- **Operator (0:25):** pokazać kursorem przycisk „Pobierz raport kampanii (CSV)”, bez klikania.
- **Narrator:** „Analityk dostaje to jako JSON albo CSV, z zamaskowanymi identyfikatorami.”

### 0:35–1:25 · Zakładka „Graf powiązań”
- **Operator:** kliknąć „Graf powiązań” i poczekać ok. 5 s, aż graf się ułoży.
- **Narrator:** „Węzeł to zgłoszenie, kolor to kampania, obwódka to rodzina. Linia ciągła oznacza powiązanie na poziomie kampanii, przerywana na poziomie rodziny.”
- **Operator (0:50):** przewinąć do „Wszystkie krawędzie”, w polu wyboru wpisać `campaign · nask:1` i nacisnąć Enter.
- **Narrator:** „Dlaczego 1 i 2 to jedna kampania? Ten sam piksel Facebooka (na ekranie zamaskowany do …5163), widoczny i w kodzie strony, i w logu HAR. Do tego identyczne pliki strony i niemal identyczny tekst. Każda przesłanka ma wagę.”
- **Operator (1:10):** przewinąć w górę do „Krawędzie odrzucone regułą kampanii (1)”.
- **Narrator:** „A 1 i 3? Mają tę samą nazwę platformy, ale to jedyny sygnał. Reguła mówi: za mało twardych dowodów na tę samą kampanię. Dlatego to powiązanie zostaje na poziomie rodziny i nie skleja dwóch różnych kampanii.”

### 1:25–2:15 · Zakładka „Analiza nowego materiału” (a): folder 2 bez HAR
- **Operator:** kliknąć „Analiza nowego materiału” w pasku zakładek u góry, rozwinąć „Tryb demo”, w polu wpisać `nask:2` i nacisnąć Enter, a potem Escape.
- **Operator:** przeciągnąć `data/demo/folder2_bez_har.zip` na pole „Nowy materiał” i kliknąć „Analizuj”.
- **Narrator (w trakcie, 11–23 s):** „Teraz sprawdzimy nowy materiał z brakami danych: zapis strony bez logu sieciowego. Żeby było uczciwie, wyrzucamy ten folder z bazy, więc narzędzie nigdy go nie widziało. Analiza wyciąga cechy z HTML, obrazów i tekstu, a potem porównuje je z całą bazą.”
- **Wynik na ekranie:** **„Znana kampania C001”**.
- **Operator:** rozwinąć pierwszego sąsiada (`nask:1`).
- **Narrator:** „Rozpoznało kampanię mimo braku HAR: wspólne pliki i piksel w kodzie strony wystarczą. Brakujący sygnał po prostu nie jest liczony.”

### 2:15–2:50 · Analiza (b): folder 47 jako nowa kampania
- **Operator:** usunąć `nask:2` (krzyżyk), dodać `nask:47`, wgrać `data/demo/folder47.zip`, kliknąć „Analizuj”.
- **Narrator (w trakcie):** „A teraz coś, czego w bazie nie ma: reklama suplementu z innej kampanii.”
- **Wynik na ekranie:** **„Nowa kampania”** (11–23 s).
- **Narrator:** „Narzędzie nie dokleja jej na siłę do żadnej znanej kampanii. Najbliższy sąsiad ma wynik 0,23, poniżej progu nowej kampanii 0,35.”

### 2:50–3:00 · Puenta
- **Narrator:** „Precyzja 100% na obu poziomach, 0 fałszywych połączeń, recall zachowawczy z założenia. Każde powiązanie da się wyjaśnić.”

---

## Czasy na maszynie referencyjnej (komputer lidera)

| Krok | Komputer lidera | Laptop W1 (dla porównania) | Uwagi |
|---|---|---|---|
| Rozgrzewka: pierwsza analiza po starcie (zimne modele) | ok. 40 s (zmierzone 42–43 s) | 116–126 s | dlatego krok 4 jest obowiązkowy |
| Analiza (a) folder 2 bez HAR, po rozgrzewce | 11–23 s | ok. 11 s | Narrator mówi w trakcie; ok. 6 s to skanowanie świeżo rozpakowanych plików przez antywirusa |
| Analiza (b) folder 47, po rozgrzewce | 11–23 s | ok. 11 s | |
| Graf: ułożenie węzłów | ok. 5 s | 5–9 s | |
| Cały scenariusz | ok. 3:00 | ok. 3:00 | |

Jeśli analiza przekracza 25 s po rozgrzewce, Narrator mówi dłużej w trakcie, a w razie potrzeby Operator przechodzi do planu B.

## Zrzuty planu B i wideo zapasowe

Robione **na maszynie referencyjnej**, przy uruchomionej aplikacji, w trybie publicznym. Podpisy i liczby skrypt bierze z danych tej maszyny:

```bash
pip install playwright                     # tylko lokalnie, nie ma go w requirements
streamlit run ui/app.py                    # w drugim terminalu
python scripts/demo_capture.py --shots     # -> docs/img/demo/*.png, docs/img/ui_*.png
python scripts/demo_capture.py --video     # -> data/demo/IsReal_demo_zapasowe.webm (poza repo, ok. 2,5 min)
```

Wideo jest bez dźwięku, z podpisami kroków (Narrator może dograć lektora). Lider wrzuca je na YouTube jako „Niepubliczny”.

## Plan B (gdy coś padnie)

Zrzuty w `docs/img/demo/` (tryb publiczny, bez twarzy i treści stron):

| Krok | Zrzut |
|---|---|
| Kampanie i rodziny | `demo_1_kampanie.png` |
| Graf | `demo_2_graf.png` |
| Krawędź odrzucona regułą (1–3) + krawędź 1–2 z przesłankami | `demo_2b_krawedz_1_2.png` |
| (a) folder 2 bez HAR → Znana kampania C001 | `demo_3a_folder2_bez_har.png` |
| (b) folder 47 → Nowa kampania | `demo_3b_folder47_nowa.png` |

| Problem | Reakcja Operatora | Co mówi Narrator |
|---|---|---|
| Analiza trwa > 25 s (modele nie były rozgrzane) | nie czekać: przełączyć na kartę ze zrzutem 3a/3b | „Pokażę wynik z próby, na żywo trwa to kilkanaście sekund.” |
| Graf się nie rysuje lub jest pusty | przewinąć do „Wszystkie krawędzie”: tabela przesłanek działa bez grafu; ewentualnie zrzut 2 | bez zmian |
| Czerwony błąd lub aplikacja nie odpowiada | karta ze zrzutami; w tle w terminalu `Ctrl+C`, potem `streamlit run ui/app.py` | „Pokażę na zrzutach z dzisiejszej próby.” |
| Upload nie przyjmuje pliku | sprawdzić, czy to `.zip` z `data/demo/`; jeśli dalej nie działa, zrzut 3a/3b | bez zmian |
| Wszystko pada | wideo zapasowe z YouTube (link u lidera) | „Pokażę nagranie z próby.” |

Zasady: **nie otwieramy żadnych stron z danych**, nie pokazujemy miniatur zrzutów reklam (twarze), w zakładce „Incydent” nie zaznaczamy „Pokaż miniatury”, aplikacja tylko na `localhost`.
