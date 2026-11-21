# Test zewnętrzny: PhreshPhish (300 stron phishingowych, 30 marek)

**Streszczenie.** Na 300 stronach phishingowych z 30 marek, bez żadnego strojenia, poziom kampanii osiągnął **96,1% precyzji par i 90,2% czystości marek**. Przebieg zakończył się bez awarii, w **0,29 s na incydent**. Poziom rodzin jest na phishingu za szeroki, bo zestawy phishingowe dzielą wspólne szablony i skrypty, więc przy wdrożeniu na taki ruch trzeba dostroić `tau_family` albo stoplistę szablonów.

> Cel: sprawdzić, czy metoda łączenia, zaprojektowana na reklamach-scamach NASK, nie skleja „wszystkiego ze wszystkim” na zupełnie innym, publicznym zbiorze. Silnik i moduły cech **bez żadnych zmian**, te same wagi i progi co w przebiegu referencyjnym.
> Przebieg: 21.11.2026, maszyna referencyjna W3 (Windows, Python 3.11.9, `.venv` z `requirements.txt`), tryb offline.

## 1. Zbiór

| | |
|---|---|
| Nazwa | **PhreshPhish**, Hugging Face: `phreshphish/phreshphish` (wersja z 2026-02-07, v1.0.1) |
| Zawartość | pary HTML + URL stron phishingowych i nieszkodliwych; pola `sha256`, `url`, `html`, `label`, `target` (podszywana marka), `date`, `lang` |
| Licencja | **CC BY 4.0**, wyłącznie do badań anti-phishingowych (warunek autorów) |
| Użyty fragment | split **test**, shardy `test-000` i `test-001` (z 21), tylko `label = phish` |
| Cytowanie | T. Dalton, H. Gowda, G. Rao, S. Pargi, A. Hadj Khodabakhshi, J. Rombs, S. Jou, M. Marwah, *PhreshPhish: A Real-World, High-Quality, Large-Scale Phishing Website Dataset and Benchmark*, arXiv preprint 2507.10854, 2025 |

Dane leżą wyłącznie w `data_ext/` (w `.gitignore`), osobno od danych NASK w `data/`. W repo nie ma ani jednej strony, URL-a ani fragmentu HTML z tego zbioru, tylko skrypt importu i ten opis.

## 2. Metodyka

**Dobór próbki** (`scripts/import_phreshphish.py`):
1. pobranie kolejnych shardów splitu test przez `huggingface_hub`, najpierw tylko kolumn metadanych (bez HTML);
2. filtr: `label = phish`, niepusty `target` będący **marką**; etykiety ogólne (`other`, `generic*`) odrzucone, bo nie są markami i zafałszowałyby miarę czystości; duplikaty po `sha256` usunięte;
3. 30 najczęstszych marek, strony brane **po kolei z każdej marki** (round-robin), maks. 10 na markę → **300 stron, 30 marek × 10**;
4. każda strona to jeden incydent z jednym plikiem `page.html`. Metadane (`target`, `date`, `lang`, `url`) zapisane **poza folderem incydentu** (`data_ext/meta/<n>.json`): loader wczytałby `meta.json` jako materiał `json`, a moduł tekstu przeczytałby z niego markę, czyli **etykieta wyciekłaby do cech**. URL-e są tylko w metadanych i nigdy nie były otwierane.

**Przetwarzanie:** ten sam potok co dla NASK, w izolowanym katalogu (`DATA_DIR` ustawiony tylko w bieżącej sesji terminala; `.env` i `settings.yaml` bez zmian):

```powershell
$env:DATA_DIR = "data_ext"
python scripts/import_phreshphish.py
python -m fakecollector ingest --data data_ext/raw/nask --source phreshphish --out data_ext/interim/incidents.jsonl
python -m fakecollector features --module all
python -m fakecollector correlate
```

`ingest` ma domyślne ścieżki `data/...` niezależne od `DATA_DIR`, dlatego `--data` i `--out` trzeba podać jawnie (inaczej nadpisałby `data/interim/incidents.jsonl` z NASK).

**Miary.** Zbiór nie ma etykiet kampanii, więc **marka służy jako etykieta zastępcza**:
- *czystość marek*: odsetek kampanii (i rodzin) wieloelementowych, w których wszystkie incydenty podszywają się pod tę samą markę;
- *precyzja par*: odsetek par incydentów w jednej grupie, które mają tę samą markę;
- *recall par*: odsetek wszystkich par o tej samej marce, które trafiły do jednej grupy (30 marek × 45 par = 1350 par).

Poziom odniesienia: dwa losowe incydenty z próbki mają tę samą markę z prawdopodobieństwem **3,0%**.

## 3. Wyniki

| Miara | Kampanie | Rodziny |
|---|---:|---:|
| Grupy razem | 203 | 102 |
| Grupy wieloelementowe | **41** | 36 |
| Średni / maks. rozmiar grupy wieloelementowej | 3,4 / 10 | 6,5 / 35 |
| Incydenty w grupach wieloelementowych | 138 z 300 | 234 z 300 |
| **Czystość marek** (grupy wieloelementowe w 100% jednej marki) | **90,2%** (37 z 41) | 69,4% (25 z 36) |
| **Precyzja par** (ta sama marka) | **96,1%** | 31,5% |
| Recall par (ta sama marka) | 16,4% | 35,7% |
| Marki z co najmniej jedną kampanią wieloelementową | 25 z 30 | — |

**Sygnały łączące** (liczba krawędzi, na których sygnał dał dodatni wkład):

| Poziom | Krawędzie tej samej marki | Krawędzie między markami |
|---|---|---|
| Kampania (173 krawędzie) | `text_near_dup` 171, `same_platform_name` 87, `shared_trackers` 83, `shared_har_trackers` 82, `shared_form_endpoint` 79, `same_registered_domain` 28 | `same_registered_domain` 2, `text_near_dup` 1 |
| Rodzina (1404 krawędzie) | `dom_template` 486, `text_semantic` 383, `shared_scripts` 372, `text_near_dup` 140, `hidden_text_sim` 131 | `dom_template` 808, `shared_scripts` 559, `text_semantic` 374, `shared_entities` 210, `same_narrative` 125 |

`shared_har_trackers` liczy się tu z HTML (identyfikatory pikseli FB, GA4, GTM, Google Ads w kodzie strony), bo zbiór nie ma plików HAR.

**Kampanie niejednorodne (4 z 41):** {sbi_securities_japan ×4, amazon ×1}, {coinbase, microsoft, netflix}, {coinbase, trezor}, {ndax, ledger}. Łączą je wspólna domena rejestrowa i niemal identyczny tekst, czyli prawdopodobnie jeden operator lub jeden zestaw phishingowy podszywający się pod kilka marek. Marka jest tu tylko etykietą zastępczą, więc nie musi to być błąd.

**Czasy i błędy:**

| Krok | Czas | Rekordy | Błędy |
|---|---:|---:|---:|
| import (2 shardy, ~400 MB, z siecią) | 11–31 s | 300 stron | 0 |
| ingest | 2 s | 300 incydentów, 300 plików | 0 |
| features: html_struct | 9,7 s | 300 | 0 |
| features: infra (offline) | 2,4 s | 300 | 0 |
| features: visual / faces | < 0,1 s | 0 (brak obrazów w zbiorze) | 0 |
| features: text | 68,1 s | 300 | 24 × „no text content” |
| correlate | 3 s | 203 kampanie, 102 rodziny | 0 |
| **razem (ingest → correlate)** | **88 s, ok. 0,29 s na incydent** | | |

24 strony (8%) nie mają widocznego tekstu (np. same skrypty ładujące); moduł tekstu odnotował to w `errors` i zwrócił puste cechy, bez przerwania przebiegu.

## 4. Wnioski

1. **Poziom kampanii nie skleja różnych marek.** Precyzja par 96,1% przy losowym poziomie 3%, a 37 z 41 kampanii jest jednolitych markowo. To ta sama właściwość, którą widać na danych NASK (0 fałszywych połączeń), potwierdzona na 300 obcych stronach bez strojenia.
2. **Łączenie wynika z twardych śladów, nie z tematu.** Kampanie tworzą niemal identyczny tekst, wspólne identyfikatory trackerów, ten sam adres wysyłki formularza i ta sama domena, czyli sygnały klasy `campaign`.
3. **Niski recall jest zamierzony.** Ta sama marka to nie ta sama kampania: wiele niezależnych grup podszywa się pod Google czy Microsoft. Narzędzie łączy tylko strony z konkretnymi wspólnymi śladami.
4. **Poziom rodzin jest na phishingu zbyt szeroki** (precyzja par 31,5%, największa rodzina 35 incydentów z 10 marek, głównie giełd i portfeli kryptowalut). Sygnały `dom_template` i `shared_scripts` częściej łączą tu różne marki niż tę samą (808 i 559 krawędzi między markami), bo popularne zestawy phishingowe dzielą szablony i biblioteki. Progi rodzin dobrano na reklamach NASK. Przy wdrożeniu na phishing trzeba je podnieść albo rozszerzyć stoplistę o typowe szablony zestawów phishingowych.
5. **Skalowalność:** 0,29 s na incydent HTML na laptopie (CPU), z czego ok. 3/4 to embeddingi tekstu; korelacja 300 incydentów w 3 s.

## 5. Ograniczenia

- **Tylko HTML**: brak zrzutów reklam, wideo i HAR, więc moduły `visual` i `faces` nie wzięły udziału w teście, a infra działała wyłącznie na HTML i offline (bez RDAP/DNS).
- **Phishing to nie reklamy**: strony logowania i portfele kryptowalut zamiast fałszywych artykułów z wizerunkami znanych osób; narracje i encje (`same_narrative`, `shared_entities`) są tu mniej informatywne.
- **Marka to tylko etykieta zastępcza**: brak prawdziwych etykiet kampanii; czystość marek ogranicza od góry jakość kampanii, ale jej nie dowodzi.
- **Mała próbka**: 300 stron z 2 z 21 shardów splitu test, 10 stron na markę; wyniki orientacyjne, bez przedziałów ufności.
- **Bez strojenia**: celowo te same wagi i progi co dla NASK, więc wynik pokazuje przenośność metody, a nie maksimum osiągalne na tym zbiorze.
