# IsReal? — tekst lektora do wideo (ok. 2:55)

Nagranie ekranu według `docs/DEMO_SCRIPT.md` (te same kroki i kliknięcia Operatora), przesunięte o 15 s planszy otwierającej, a sceny demo skrócone do 2:40. Tempo lektora: ok. 130 słów na minutę. Na ekranie bez twarzy, miniatur reklam i pełnych domen; identyfikatory tylko maskowane (`2012…5163`). Zapas: zrzuty z `docs/img/demo/`.

| Czas | Ekran (krok z DEMO_SCRIPT) | Lektor |
|---|---|---|
| 0:00–0:15 | Plansza: tytuł „IsReal?” i dwie liczby: 97% incydentów CERT Polska to oszustwa; ~100 tys. domen fałszywych inwestycji (2025) | „Prawie wszystkie incydenty obsłużone w zeszłym roku przez CERT Polska to oszustwa, a domen z fałszywymi inwestycjami jest już około stu tysięcy. Oszuści nie działają pojedynczymi reklamami, tylko kampaniami. IsReal? pokazuje te kampanie.” |
| 0:15–0:40 | Zakładka „Kampanie i rodziny”; kursor na „Pobierz raport kampanii (CSV)” | „Dostaliśmy od NASK dziesięć zgłoszeń. Narzędzie samo złożyło je w osiem kampanii i sześć rodzin. Kampania C001 to zgłoszenia 1 i 2: ta sama strona pod dwiema domenami. Rodzina F001 łączy ją z kampanią C002, czyli zgłoszeniami 48 i 61, oraz ze zgłoszeniem 3: wspólny zestaw narzędzi, ale za mało twardych dowodów na jedną kampanię. Wynik można pobrać jako CSV lub JSON, z zamaskowanymi identyfikatorami.” |
| 0:40–1:00 | Zakładka „Graf powiązań”, graf się układa | „Węzeł to zgłoszenie, kolor to kampania, obwódka to rodzina. Linia ciągła to powiązanie kampanii, przerywana to powiązanie rodziny.” |
| 1:00–1:15 | „Wszystkie krawędzie” → `campaign · nask:1` | „Dlaczego 1 i 2 to jedna kampania? Ten sam piksel Facebooka, w kodzie strony i w logu sieciowym, siedemnaście identycznych plików, ta sama nazwa platformy i niemal ten sam tekst. Wynik: 0,91.” |
| 1:15–1:30 | „Krawędzie odrzucone regułą kampanii (1)” (1–3) | „A tu odwrotnie: zgłoszenia 1 i 3 mają tę samą nazwę platformy, ale to jedyny ślad. Reguła twardych dowodów nie pozwala ich skleić w kampanię, więc zostają tylko w rodzinie.” |
| 1:30–2:05 | Zakładka „Analiza nowego materiału”, tryb demo `nask:2`, upload `folder2_bez_har.zip`, „Analizuj”, wynik „Znana kampania C001” (0,89), rozwinięty sąsiad `nask:1` | „Teraz nowy materiał z brakami: zapis strony bez logu sieciowego. Żeby było uczciwie, usuwamy to zgłoszenie z bazy, więc narzędzie nigdy go nie widziało. Po kilkunastu sekundach: znana kampania C001, pewność 0,89. Wspólne pliki i piksel w kodzie strony wystarczą. Brakujący sygnał po prostu nie jest liczony.” |
| 2:05–2:35 | Tryb demo `nask:47`, upload `folder47.zip`, „Analizuj”, wynik „Nowa kampania” | „A teraz reklama suplementu, której w bazie nie ma. Wynik: nowa kampania. Najbliższy sąsiad ma 0,23, poniżej progu nowej kampanii 0,35. Narzędzie nie dokleja niczego na siłę.” |
| 2:35–2:55 | Plansza końcowa z wynikami | „Na zgłoszeniach NASK: precyzja kampanii sto procent i zero fałszywych połączeń. Każda kampania spoza bazy rozpoznana jako nowa, a w czterech na pięć przypadków przypisana do właściwej rodziny. Całość działa offline, na licencjach otwartych i bez modeli językowych. IsReal? — od pojedynczej reklamy do całej kampanii oszustów.” |

**Plansza końcowa (2:35):** precyzja kampanii 100% · 0 fałszywych połączeń · rodziny P/R 100% · nowa kampania rozpoznana 100% (rodzina 80%) · leave-one-out 80% · pełny przebieg 222 s, 0 błędów.

**Uwagi do montażu:** czas analizy na nagraniu skrócić cięciem (na maszynie referencyjnej 11–23 s po rozgrzaniu modeli; rozgrzewka ok. 40 s). Nie pokazywać zakładki „Incydent” z miniaturami. Napisy PL zgodne z tekstem lektora.
