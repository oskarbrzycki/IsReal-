# Pytania jury: krótkie odpowiedzi

Ściąga na sesję pytań po pitchu. Odpowiedzi opierają się na `METHODOLOGY.md`, `RESULTS_SUMMARY.md` i `LICENSES.md`. Liczby pochodzą z przebiegu referencyjnego z kompletem cech, w tym CLIP i OCR (`reports/reference_run_20261121_181101.md`, ewaluacja `reports/eval_20261121_181036.md`). Są zgodne z `RESULTS_SUMMARY.md` i `SLIDES_CONTENT.md`.

---

### 1. Dlaczego tylko 10 incydentów?
Tyle zgłoszeń udostępnił NASK: 10 incydentów, 313 plików. Nie dokładaliśmy danych z zewnątrz, bo nie mielibyśmy dla nich wiarygodnych etykiet. Wyniki traktujemy jako ilustrację działania, nie dowód skuteczności. Dlatego progi wybieramy ze środka stabilnego zakresu, a nie pod pojedyncze pary. Sam silnik od rozmiaru zbioru nie zależy (pytanie 6).

### 2. Skąd macie etykiety?
Są robocze i nasze (`eval/labels.yaml`): kampanie {1, 2, 3} i {48, 61} oraz hipoteza rodziny {1, 2, 3, 48, 61}. Mentorzy NASK ich nie potwierdzili. Część etykiet powstała na podstawie identycznych plików, więc ocena jest częściowo kołowa. Dlatego raportujemy też wariant bez sygnałów „identyczne pliki”: kampanie F1 0,67, rodziny 1,00, czyli wynik się nie zmienia. Chętnie przyjmiemy etykiety od analityków NASK.

### 3. Co z fałszywymi połączeniami?
W testach mamy 0 fałszywych połączeń kampanii i precyzję 100%. Krawędź kampanii powstaje tylko przy co najmniej jednym twardym identyfikatorze (piksel, konto reklamowe, domena, identyczne pliki) albo przy dwóch różnych sygnałach klasy *campaign*. Pojedynczy miękki dowód, np. podobny obraz, łączy najwyżej w rodzinę i dostaje adnotację „za mało twardych dowodów”. Błędne sklejenie dwóch kampanii kosztuje analityka więcej niż przeoczone powiązanie.

### 4. Dlaczego recall kampanii to tylko 50%?
To świadoma decyzja: precyzja ponad kompletność. Brakuje dwóch par i obie dotyczą incydentu 3. Nie ma on logu HAR, a jego tekst jest inny, więc nie ma dowodu na poziomie kampanii. Obniżenie progu do 0,32 dałoby F1 1,0, ale opierałoby się na jednej parze z wynikiem 0,33 i na niepotwierdzonej etykiecie. Incydent 3 i tak trafia do właściwej rodziny, więc analityk go widzi.

### 5. Skąd w raportach wartość 0,57?
W pełnym systemie rodziny mają F1 1,0, także bez sygnałów „identyczne pliki”. Wartość 0,57 pojawia się w dwóch testach obciążeniowych: w ablacji bez modułu infrastruktury (F1 rodzin 0,57) i w teście braków danych (średnie F1 0,57 przy 30% brakujących rodzajów danych). Pokazuje, że rodziny opierają się głównie na infrastrukturze (szablon parametrów URL, zestaw sieci reklamowych). Z testu czułości wag wynika też, że rodziny zależą od wag `face_match`, `same_narrative` i `same_param_template`. Podajemy to jako uczciwą dolną granicę, a nie ukrywamy.

### 6. Jak to się skaluje?
Do 200 incydentów liczymy wszystkie pary, powyżej stosujemy *blocking*. Porównujemy tylko pary, które coś łączy: wspólny element zbioru, ten sam klucz, wiaderko hasha albo pasmo MinHash (LSH). Pary połączone wyłącznie podobnym wektorem wymagałyby indeksu ANN. Nowy materiał trafia do bazy przyrostowo (`analyze`), bez przeliczania całego zbioru, a pełne `correlate` można uruchamiać okresowo.

### 7. Ile trwa analiza nowej reklamy?
`analyze` liczy cechy tylko dla nowego materiału i porównuje go z gotową bazą: pięciu najbliższych sąsiadów plus przesłanki. Całego zbioru nie przelicza. Wszystko działa lokalnie na CPU, a w trybie offline bez sieci. Czas na jedno zgłoszenie: **11–23 s** po rozgrzaniu modeli (maszyna referencyjna, `DEMO_SCRIPT.md`). Pierwsza analiza po starcie, z ładowaniem modeli, trwa ok. 40 s. Pełny przebieg wsadowy 10 zgłoszeń (313 plików): 222 s.

### 8. Dlaczego bez LLM?
Produkt nie używa LLM (`LLM_ENABLED=false`). Wynik musi dać się sprawdzić bez naszych kluczy (R9), a prawa mają przejść na NASK bez obciążeń (R11). Do tego wynik ma być powtarzalny i wyjaśnialny: każda przesłanka wynika z konkretnego sygnału, nie z wygenerowanego tekstu. Dane z prawdziwych zgłoszeń nie wychodzą też do zewnętrznego API. LLM można włączyć jako opcję, ale system go nie potrzebuje.

### 9. Co, jeśli strona oszustów już nie działa?
Pracujemy wyłącznie na zapisanych materiałach (HTML, HAR, zrzuty, wideo) i nigdy nie otwieramy stron. Brak danych po jednej stronie oznacza „nie porównuj”, a nie „różne”: sygnał wypada z wyniku. Przy 30% losowo brakujących rodzajów danych F1 spada średnio do 0,57 (20 prób; minimum 0,00, czyli brak połączeń, a nie połączenia błędne). W najgorszym przypadku system nic nie łączy, ale też nic nie łączy błędnie. Jeśli danych jest za mało, wynik to `insufficient_data`.

### 10. Jak dodać nowe źródło danych?
Nowy moduł cech implementuje jeden interfejs: `MODULE`, `KINDS` (jakie materiały czyta) i `extract()`. Do tego deklaruje `SIGNALS` z typem podobieństwa i klasą (*campaign* albo *family*). Runner sam go uruchomi, a silnik nie musi znać szczegółów cech. Wagi i progi ustawia się w `config/settings.yaml`. Nowy typ materiału dodaje się w `ingest`, a nową usługę OSINT w module `infra`, z zapisem do cache.

### 11. A RODO i wizerunki osób?
Dane NASK nie trafiają do repozytorium ani do obrazu Dockera, tylko są montowane jako wolumen (R1). Baza referencyjna twarzy trzyma w gicie same imiona i nazwiska, bez zdjęć i embeddingów. Osoby publiczne to ofiary wykorzystania wizerunku, nie autorzy treści. Identyfikatory i domeny w raportach są maskowane (np. `2012…5163`). Modele twarzy mają licencje permisywne. Świadomie nie użyliśmy InsightFace, bo jego wagi są tylko do badań niekomercyjnych. Podstawę prawną przetwarzania przy wdrożeniu produkcyjnym ustala NASK.

### 12. Jak to wdrożyć w NASK?
Obraz Dockera zawiera wszystkie modele i działa bez sieci, a dane podłącza się jako wolumen. Mamy przebieg wsadowy (`ingest → features → correlate`), demonstrator w Streamlit i CLI `analyze`, które zwraca JSON, więc można je podpiąć pod istniejący system zgłoszeń. Graf można wyeksportować do Neo4j. Domyślnie wszystko działa offline. W trybie online system odpytuje tylko neutralne usługi publiczne (RDAP, DNS, crt.sh), bez kluczy i nigdy domeny z próbek.

### 13. Skąd wagi i progi?
Wagi są ręczne i zależą od siły dowodu. Unikalny identyfikator waży 2,5–3,5, treść i wygląd 1,0–2,0, cechy ogólne 0,5–0,8. Regresja logistyczna na 45 parach tylko potwierdza kierunek (żaden współczynnik nie jest ujemny), bo do uczenia wag danych jest za mało. Progi leżą w środku stabilnego zakresu, np. F1 kampanii jest takie samo dla `tau_campaign` od 0,34 do 0,58. Przy zmianie wag o ±50% poziom kampanii się nie zmienia.

### 14. Czym różni się kampania od rodziny?
Kampania to konkretna operacja jednego nadawcy: ten sam piksel, konto reklamowe, domena, identyczne pliki, ten sam tekst albo nazwa „platformy”. Rodzina to wspólny „kit” albo aktor: szablon strony i parametrów URL, te same twarze, ta sama narracja, ten sam zestaw sieci reklamowych. Jedna rodzina może prowadzić wiele kampanii. Analityk blokuje kampanię, a rodzina pokazuje, z jakimi innymi kampaniami łączy ją wspólne zaplecze.

### 15. Co z kampanią, której system jeszcze nie widział?
Gdy usuwamy kampanię z bazy, system w 100% przypadków oznacza ją jako nową. W 80% wskazuje też właściwą rodzinę („nowa kampania, ale pasuje do rodziny X”). W teście leave-one-out incydent z kampanii trafia do niej w 80% przypadków, a samotne zgłoszenia są zawsze oznaczane jako nowe. Każdy wynik zawiera najbliższe znane incydenty z przesłankami i jednozdaniowy powód decyzji.
