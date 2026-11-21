# IsReal? — od pojedynczej reklamy do całej kampanii oszustów

Plan prezentacji: 5 minut, 8 slajdów. **Finalna treść z prawdziwymi liczbami: `docs/SLIDES_CONTENT.md`** (ten plik to szkic). `XX` = liczby do uzupełnienia (wyniki od W3/W5, statystyki skali z publicznego źródła z podanym pochodzeniem). Na slajdach bez pełnych domen, ID i cytatów ze stron oszustów.

---

### 1. Problem: jedna reklama to za mało (0:00–0:35)
- Fałszywe reklamy z wizerunkami znanych osób i podrobionymi portalami prowadzą do „platform inwestycyjnych” i suplementów.
- Skala (Polska, 2025):
  - **40 225** domen z fałszywymi inwestycjami zgłoszonych do blokady przez CSIRT KNF, czyli 96% wszystkich zgłoszonych domen (Raport roczny CSIRT KNF 2025).
  - **9 751** oszukańczych reklam na Facebooku zablokowanych po zgłoszeniach CSIRT KNF i **4 358** profili z fałszywymi reklamami (tamże).
  - **97%** incydentów CERT Polska to oszustwa internetowe (253 238 z 260 783). Domen związanych z oszustwami inwestycyjnymi: niemal **100 tys.**, ponad 2× r/r (NASK, 23.04.2026, na podstawie Raportu rocznego CERT Polska 2025).
  - Pełne źródła z linkami: `docs/skala_problemu.md`.
- Analityk widzi pojedyncze zgłoszenia, a oszuści działają kampaniami: rotują domeny, podmieniają twarze, przepisują teksty.

> **Mówca:** Zacznij od zrzutu reklamy z zamazaną twarzą. Teza: zablokowanie jednej domeny nic nie daje, bo jutro ta sama strona stoi pod nową. Trzeba widzieć kampanię.

### 2. Co robimy: od reklamy do kampanii i aktora (0:35–1:05)
- Wejście: reklama, zrzut ekranu, zapisana strona, log ruchu (HAR), URL.
- Wyjście: przypisanie do znanej **kampanii** albo „nowa kampania” oraz powiązanie kampanii w **rodzinę** (wspólny aktor lub kit).
- Każde powiązanie ma przesłanki zapisane po polsku, nie tylko wynik liczbowy.

> **Mówca:** Jedno zdanie o wartości: „Z jednego zgłoszenia pokazujemy całą kampanię i mówimy, dlaczego tak uważamy”.

### 3. Jak: 5 modułów cech, twarde dowody, 2 poziomy (1:05–1:50)
- 5 modułów: struktura HTML, tekst i narracja, obraz i OCR, twarze, infrastruktura (HAR, domeny, OSINT bez kluczy).
- **Reguła twardych dowodów:** do „tej samej kampanii” potrzeba co najmniej 2 sygnałów klasy *campaign* (piksel, identyczny asset, domena, near-duplikat tekstu lub obrazu, nazwa produktu). Podobny temat sam nie wystarczy.
- **2 poziomy:** kampania (konkretna operacja) i rodzina (ten sam kit lub aktor: szablon parametrów URL, CSS, te same twarze, narracja).

> **Mówca:** Podkreśl odporność na braki: martwa strona, brak zdjęcia, brak HAR. Liczymy tylko na dostępnych sygnałach. Ten slajd odpowiada na kryteria „korelacja” i „interpretowalność”.

### 4. Przykład z danych: kampania A (1:50–2:35)
- Trzy zgłoszenia: fałszywy artykuł na podrobionym portalu, znana osoba jako „wizerunek”, ten sam „pakiet inwestycyjny”.
- Twarde dowody: **ten sam piksel reklamowy Facebooka**, identyczna strona (17 identycznych plików) pod dwiema domenami w TLD .live, **zarejestrowanymi w odstępie 108 sekund**.
- Trzecie zgłoszenie: inna osoba i inna domena, ale ta sama nazwa produktu i wspólna domena w logu sieciowym. Rodzina łączy też kampanię B (te same twarze i szablon parametrów URL).

> **Mówca:** Pokaż graf: 3 węzły i krawędzie podpisane przesłankami. Domeny i ID w skrócie, np. „piksel …5163”. „108 sekund” to najmocniejszy moment, zrób pauzę.

### 5. Wyniki (2:35–3:10)
- Grupowanie kampanii: precision XX, recall XX, F1 XX (etykiety robocze, zbiór 10 zgłoszeń, 7 kampanii).
- Nowy materiał: trafne przypisanie XX% wariantów; obce kampanie poprawnie odrzucone jako „nowe” w XX% (test leave-one-campaign-out).
- Ablacja: bez modułu XX spada F1 o XX, czyli każda modalność wnosi coś innego.

> **Mówca:** Uczciwie: mały zbiór, etykiety robocze. Nacisk na precision: nie sklejamy obcych kampanii, a tego wymaga ukryty zbiór testowy.

### 6. Demo (3:10–4:10)
- Widok kampanii: tabela klastrów, etykiety, główne sygnały.
- Graf: kliknięcie krawędzi pokazuje przesłanki.
- Nowy materiał: wgrywamy zgłoszenie → cechy → przypisanie do kampanii albo „nowa kampania” z uzasadnieniem.

> **Mówca:** Demo nagrane wcześniej jako zapas, na żywo tylko „nowy materiał”. Wgrać wariant znanej kampanii (ma się przypiąć) i zgłoszenie spoza zbioru (ma być „nowa kampania”).

### 7. Wdrożenie (4:10–4:40)
- Docker, jedno polecenie; tryb **offline** na zapisanych materiałach (bez wykonywania JS, bez łączenia ze stronami oszustów).
- Eksport grafu do **Neo4j** dla analityków; wejście przez CLI, Streamlit lub wsadowo.
- Tylko **licencje permisywne** (MIT / Apache / BSD); modele lokalne na CPU, bez LLM i bez kluczy API.

> **Mówca:** Kryterium „potencjał wdrożeniowy”: działa u NASK bez naszej infrastruktury, kod można przekazać bez wad prawnych.

### 8. Podsumowanie (4:40–5:00)
- **IsReal?**: z jednej reklamy do całej kampanii i aktora, z przesłankami dla każdego powiązania.
- Twarde dowody zamiast podobieństwa „na oko”, więc mniej fałszywych połączeń.
- Następny krok: zasilenie zgłoszeniami NASK i Biblioteką Reklam, monitorowanie nowych wariantów.

> **Mówca:** Zakończ tym samym zrzutem reklamy co na slajdzie 1, tym razem z grafem kampanii obok. „Pytania?”
