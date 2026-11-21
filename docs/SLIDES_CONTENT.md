# IsReal? — od pojedynczej reklamy do całej kampanii oszustów

Finalna treść 8 slajdów (pitch 5:00). Liczby wyników: `reports/reference_run_20261121_181101.md` i `docs/RESULTS_SUMMARY.md`. Liczby skali problemu wyłącznie ze źródeł pierwotnych (CERT Polska / NASK, CSIRT KNF), pełne odnośniki w `docs/skala_problemu.md`. Identyfikatory maskowane (`2012…5163`); bez domen, twarzy i cytatów ze stron.

---

## Slajd 1 · Oszustwa działają kampaniami, a widzimy pojedyncze reklamy (0:00–0:35)
- **97%** incydentów obsłużonych przez CERT Polska w 2025 r. to oszustwa: 253 238 z 260 783.
- Domen związanych z fałszywymi inwestycjami jest niemal **100 tys.**, ponad 2× więcej r/r (NASK, raport roczny CERT Polska 2025). CSIRT KNF zgłosił do blokady **40 225** takich domen, czyli **96,3%** wszystkich swoich zgłoszeń (41 751; raport roczny CSIRT KNF 2025).
- Jutro ta sama strona stoi pod nową domeną, z inną twarzą i przepisanym tekstem. Blokowanie po jednej reklamie nie nadąża.

**Grafika:** trzy duże liczby (97% · ~100 tys. · 96,3%), pod nimi źródła małą czcionką.
**Mówca:** „Za każdą z tych reklam stoi ktoś, kto ma ich setki. Pytanie analityka brzmi nie tylko «czy to oszustwo?», ale «czyje i co jeszcze do tego należy?»”.

## Slajd 2 · IsReal?: od reklamy do kampanii i rodziny (0:35–1:00)
- **Wejście:** zgłoszenie, czyli reklama, zrzut ekranu, zapisana strona, log ruchu sieciowego (HAR).
- **Wyjście:** znana **kampania** albo **„nowa kampania”**, a do tego **rodzina**, czyli wspólny „kit” lub aktor stojący za kilkoma kampaniami.
- Każde powiązanie ma przesłanki po polsku, np. „ten sam piksel reklamowy”.

**Grafika:** schemat w 3 krokach: reklama → kampania → rodzina (ikony, bez zrzutów z danych).
**Mówca:** jedno zdanie wartości: „Z jednego zgłoszenia pokazujemy całą kampanię i mówimy, dlaczego tak uważamy”.

## Slajd 3 · Jak: 5 modułów, reguła twardych dowodów, 2 poziomy (1:00–1:40)
- **5 modułów cech:** struktura HTML, tekst i narracja, obraz i OCR, twarze, infrastruktura (HAR, domeny, OSINT bez kluczy). Razem **28 sygnałów** podobieństwa.
- **Reguła twardych dowodów:** krawędź kampanii tylko przy twardym identyfikatorze (piksel, konto reklamowe, domena, identyczne pliki) albo przy co najmniej 2 niezależnych sygnałach klasy *campaign*. Sam podobny obraz łączy najwyżej w rodzinę.
- **2 poziomy:** kampania (konkretna operacja) i rodzina (szablon, te same twarze, narzędzia reklamowe). Brak danych oznacza „nie porównuj”, a nie „różne”.

**Grafika:** 5 kafelków modułów → lejek „reguła twardych dowodów” → dwa poziomy (kampania / rodzina).
**Mówca:** „Wolimy przeoczyć powiązanie, niż je zmyślić. Błędnie sklejone kampanie kosztują analityka więcej niż przeoczone”.

## Slajd 4 · Przykład z danych: kampania A (1:40–2:20)
- Zgłoszenia 1 i 2 to ta sama strona fałszywego portalu z wizerunkiem znanej osoby, pod dwiema domenami w TLD .live **zarejestrowanymi w odstępie 108 sekund**.
- Twarde dowody: **ten sam piksel Facebooka `2012…5163`** (w kodzie strony i w logu HAR), 17 identycznych plików, ta sama nazwa „platformy”, niemal identyczny tekst. Wynik krawędzi **0,91**.
- Zgłoszenie 3 (inna osoba, inny portal) ma za mało twardych dowodów na tę samą kampanię, ale trafia do **tej samej rodziny**.

**Grafika:** `docs/img/demo/demo_2b_krawedz_1_2.png` (krawędź 1–2 z przesłankami).
**Mówca:** pauza po „108 sekundach”. „Dwie domeny założone w niecałe dwie minuty. To nie przypadek, to jedna operacja”.

## Slajd 5 · Wyniki: precyzja ponad wszystko (2:20–2:55)
- **Kampanie: precyzja 100%, 0 fałszywych połączeń.** Rodziny: precyzja i recall **100%**.
- Kampania spoza bazy rozpoznana jako **nowa: 100%**, a w **80%** wskazana właściwa rodzina. Nowe zgłoszenie znanej kampanii (leave-one-out): **80%** trafień.
- Pełny przebieg na 10 zgłoszeniach (313 plików, 5 modułów): **222 s, 0 błędów**.

**Grafika:** tabela 5 metryk; pod spodem jedna linia ograniczeń.
**Mówca:** uczciwie: „10 zgłoszeń, etykiety robocze, czekamy na potwierdzenie NASK. Recall kampanii to celowo 50%: brakuje par z incydentem 3, który nie ma logu HAR. Mimo to trafia do właściwej rodziny”.

## Slajd 6 · Demo (2:55–3:55)
- Kampanie i rodziny: 10 zgłoszeń daje 8 kampanii i 6 rodzin.
- Graf: krawędź 1–2 z przesłankami; 1–3 (tylko wspólna nazwa platformy) odrzucone regułą twardych dowodów.
- Nowy materiał: folder 2 bez HAR → **znana kampania C001** (pewność 0,89); reklama suplementu → **nowa kampania** (najbliższy sąsiad 0,23, próg 0,35).

**Grafika:** demo na żywo. Plan B: `docs/img/demo/demo_1_kampanie.png`, `demo_2_graf.png`, `demo_3a_folder2_bez_har.png`, `demo_3b_folder47_nowa.png`.
**Mówca:** krótka wersja `docs/DEMO_SCRIPT.md` (pełny scenariusz trwa 3:00). Na żywo tylko zakładka „Analiza nowego materiału”; modele rozgrzane przed pitchem, jedna analiza trwa 11–23 s.

## Slajd 7 · Gotowe do wdrożenia w NASK (3:55–4:35)
- **Docker** z modelami w obrazie, tryb **offline**, dane jako wolumen (nigdy w obrazie ani w repo); analiza zapisanych materiałów statyczna, bez wykonywania JS. Eksport grafu do **Neo4j**, CLI `analyze` zwraca JSON.
- **Monitoring domen** (`python -m fakecollector monitor`): okresowo sprawdza przez publiczne RDAP/DNS, czy domeny znanych kampanii działają; nigdy nie łączy się ze stronami oszustów. W testach wykrył, że domena jednej z kampanii przestała działać.
- Tylko **licencje permisywne** (MIT / Apache-2.0 / BSD), modele lokalne na CPU, **bez LLM** i bez kluczy API.

**Grafika:** prosty diagram: wolumen z danymi → kontener IsReal? → Streamlit / JSON / Neo4j, a z boku pętla „monitor” z sygnalizatorem stanu domeny (działa / nie działa).
**Mówca:** „Działa u Was bez naszej infrastruktury, a kod można przekazać bez wad prawnych. Monitor pokazuje, kiedy kampania zmienia domenę, czyli kiedy szukać jej nowej odsłony”.

## Slajd 8 · IsReal? (4:35–5:00)
- Od pojedynczej reklamy do całej kampanii i rodziny, z przesłankami przy każdym powiązaniu.
- Twarde dowody zamiast podobieństwa „na oko”: **0 fałszywych połączeń**.
- Następny krok: etykiety od analityków NASK, zasilenie zgłoszeniami i Biblioteką Reklam.

**Grafika:** `docs/img/demo/demo_2_graf.png` (graf kampanii i rodzin) z hasłem.
**Mówca:** „IsReal? Teraz już wiemy, czyje to jest. Dziękujemy, pytania?”
