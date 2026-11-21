# IsReal? — metodyka łączenia reklam-scamów w kampanie

*Zadanie NASK „Kolekcjoner fejków" (HackNation 2026). Silnik korelacji i ewaluacja, opis W5.*

Zespół HackNation 2026. Moduły cech: W1 (`html_struct`, ingest), W2 (`text`, patrz [methodology_text.md](methodology_text.md)), W3 (`visual`, `faces`), W4 (`infra`).

## Streszczenie

**Cel.** Z pojedynczych podejrzanych reklam i ich stron docelowych wydobyć wspólne ślady, połączyć je w **kampanie** i dla każdego powiązania podać **sprawdzalne powody**. Nowy materiał ma trafić do znanej kampanii albo zostać uznany za nowy wzorzec.

**Jak to działa.** Pięć modułów wyciąga z każdego zgłoszenia (incydentu) cechy. Dla pary incydentów liczymy ważoną średnią podobieństw po sygnałach dostępnych po obu stronach, a każde powiązanie niesie listę przesłanek po polsku (identyfikatory z danych NASK są w nich zamaskowane). Grupowanie ma dwa poziomy: **kampanie** (ten sam nadawca) i **rodziny** (ten sam „kit", aktor lub motyw, mogący łączyć różne kampanie).

**Trzy decyzje projektowe.**
1. **Twarde dowody.** Kampanię łączymy tylko przy mocnym śladzie (ten sam piksel, konto reklamowe, domena, identyczne pliki) albo co najmniej dwóch niezależnych sygnałach. Jeden miękki dowód wskazuje najwyżej rodzinę. Wolimy przeoczyć powiązanie, niż je sfabrykować (precyzja ponad recall).
2. **Braki danych nie szkodzą.** Brak wartości oznacza „nie porównuj", a nie „różne". Na poziomie rodzin słaby sygnał poniżej własnego progu (`floor`) nie obniża wyniku.
3. **Otwarty zbiór.** Próg pozwala powiedzieć „to nowa kampania" i wskazać najbliższe znane incydenty z uzasadnieniem.

**Wyniki** (10 incydentów, przebieg referencyjny, komplet cech): precyzja 1,0 na obu poziomach i 0 fałszywych połączeń; recall kampanii 0,5 (zachowawczy z założenia), rodzin 1,0; nowe kampanie rozpoznawane w 100%, a w 80% trafiają do właściwej rodziny. **Zastrzeżenie:** to 10 incydentów, a etykiety (zwłaszcza rodzin) są naszą hipotezą, niepotwierdzoną przez NASK.

## 1. Przepływ

`ingest` → 5 modułów cech → agregacja do incydentu → podobieństwo par → reguła twardych dowodów → grupowanie dwupoziomowe → przypisanie nowego materiału.

- **Incydent** = folder ze zgłoszeniem (reklama, strona docelowa, log HAR), jednostka grupowania. Zbiór: 10 incydentów, 313 plików.
- **Agregacja** do incydentu: zbiory sumujemy, wektory i hashe zostają listą (podobieństwo = maksimum po parach). Elementy ze stoplisty (jQuery, `fbevents.js`, CDN) nie tworzą powiązań; konkretny identyfikator piksela lub konta zostaje.
- **Wynik pary** = `Σ w·sim / Σ w` po sygnałach dostępnych po obu stronach.
- **Maskowanie:** `1234567890123456` → `1234…3456`, `scam-example.live` → `scam-example[.]live`, bo raporty mogą trafić do publicznego repo.

## 2. Sygnały i wagi

Wagi są ręczne, zależne od siły dowodu: unikalny identyfikator 2,5–3,5; treść i wygląd 1,0–2,0; cechy ogólne 0,5–0,8. Moduł deklaruje klasę sygnału (`SIGNAL_CLASS`), `settings.yaml` ma pierwszeństwo; nazwa sygnału jest unikalna.

| Moduł | Klasa | Sygnały (waga) |
|---|---|---|
| html_struct | campaign | `shared_assets` (3,0; liczba wspólnych plików), `shared_trackers` (3,0), `shared_form_endpoint` (2,5) |
| html_struct | family | `dom_template` (1,5), `shared_scripts` (1,5), `hidden_text_sim` (1,0) |
| infra | campaign | `shared_har_trackers` (3,5), `shared_ad_account` (3,0), `same_registered_domain` (3,0), `same_favicon`, `cert_san_overlap`, `shared_registrar_and_date` (2,0) |
| infra | family | `same_adtech_stack` (2,0), `same_param_template` (1,5), `shared_ns`, `shared_ip_asn` (1,0), `shared_server_stack` (0,5) |
| text | campaign / family | `text_near_dup`, `same_platform_name` (2,0) / `same_narrative`, `shared_entities`, `text_semantic` (0,8–1,0) |
| visual | campaign / family | `image_near_dup` (2,0) / `visual_style` (0,8), `shared_logo` |
| faces | family | `face_match`, `same_identity` (2,0) |

**Klasy.** `campaign` = dowód jednej kampanii, `family` = wspólny „kit", aktor lub motyw. Sygnały o losowym tle (cosinus, pHash) mają `floor`, poniżej którego nie są dowodem (np. `visual_style` 0,85).

## 3. Braki danych i poziom rodzin

- **Renormalizacja:** brak wartości (martwa strona, brak HAR, brak twarzy) wypada z licznika i mianownika.
- **`absence_discount` = 0,5:** brak wspólnego identyfikatora jest słabym dowodem *przeciw* (strony jednej kampanii bywają na różnych domenach), więc takie zero liczy się z połową wagi.
- **Rodziny: sygnał poniżej `floor` = brak danych** (`family_positive_only`, domyślnie włączone). Wartość poniżej `floor` jest tym, jak wyglądają niezwiązane materiały. Jako 0 w średniej obniżałaby wynik tylko dlatego, że dodaliśmy słaby sygnał, więc dokładanie cech mogłoby pogarszać grupowanie. Zasada: słaby dowód nie może obniżać wyniku, jedynie go podnosić. Poziom kampanii bez zmian.

## 4. Reguła twardych dowodów i grupowanie

**Krawędź kampanii** powstaje przy ≥ 1 trafieniu twardego identyfikatora (`shared_trackers`, `shared_har_trackers`, `shared_ad_account`, `same_registered_domain`, `shared_assets`) **albo** ≥ 2 różnych sygnałach `campaign` z podobieństwem > 0. Para z jednym miękkim dowodem trafia na poziom rodziny z powodem „za mało twardych dowodów na tę samą kampanię".

1. **Duplikaty:** wynik ≥ 0,95 lub ten sam plik strony/zrzutu → jedna grupa przed klastrowaniem.
2. **Kampanie:** krawędzie ≥ `tau_campaign` (0,5) → Louvain (stały seed, wynik powtarzalny).
3. **Rodziny:** kampanie łączymy, gdy sygnały `family` dają ≥ `tau_family` (0,38) przy ≥ 2 sygnałach.
4. **Nowy materiał** (`analyze`): top-5 sąsiadów. Wynik: `known_campaign` (≥ `tau_new` 0,35), `new_campaign_known_family`, `new_family` albo `insufficient_data`. Zawsze z listą najbliższych incydentów i jednozdaniowym powodem; `exclude_incidents` buduje bazę bez wskazanych incydentów w pamięci (demo „nowej kampanii").

## 5. Progi

Progi leżą w środku stabilnego zakresu, nie w ostrym maksimum: `tau_campaign` 0,5 (F1 niezmienne dla 0,34–0,58), `tau_family` 0,38, `min_signals_family` = 2 (pojedynczy ogólny sygnał łączył niepowiązane incydenty). **Analiza czułości** `tau_family` na pełnych cechach przy wyłączonym wariancie z pkt 3: wynik 1,0 dla 0,2–0,3, ale tego zakresu nie przyjmujemy jako progu. Etykieta rodziny {1,2,3,48,61} jest naszą hipotezą, więc dobieranie progu pod nią byłoby przeuczeniem. Analiza pokazuje tylko, jak recall rodzin zależy od progu.

## 6. Ewaluacja (10 incydentów, etykiety robocze)

Etykiety (`eval/labels.yaml`): kampanie {1,2,3}, {48,61}; rodzina {1,2,3,48,61}, **niepotwierdzone przez NASK**. Liczby z przebiegu referencyjnego W3 (`reports/reference_run_20261121_181101.md`, komplet cech, offline).

| Test | Wynik |
|---|---|
| Kampanie | precyzja 1,0; recall 0,5; F1 0,67; ARI 0,65; 0 fałszywych połączeń |
| Rodziny | precyzja 1,0; recall 1,0; F1 1,0; ARI 1,0 |
| Bez sygnałów „identyczne pliki" | kampanie F1 0,67; rodziny F1 1,0 |
| Nowa, nieznana kampania (usunięta z bazy): rozpoznana jako nowa / przypisana do właściwej rodziny | 100% / 80% |
| Przypisanie nowego zgłoszenia do znanej kampanii (leave-one-out) / samotne zgłoszenia uznane za nowe | 80% / 100% |
| Odporność na rozbicie zgłoszenia (pseudo-warianty: 24 części z 9 incydentów) | 70% par wraca razem, F1 0,74 |
| Odporność na braki danych (30% modalności wyłączone, 20 prób, stały seed) | F1 średnio 0,57, w najgorszej próbie 0 (system woli nic nie łączyć niż łączyć błędnie) |

**Droga wyniku rodzin: 1,0 → 0,57 → 1,0.**
1. **1,0 (cechy bez CLIP i OCR).** Wczesny wynik z uboższego zestawu cech. Nie traktujemy go jako rezultatu.
2. **0,57 (komplet cech, uczciwy wynik).** Z OCR i CLIP przybyły sygnały o szumie (m.in. krótkie, zaszumione teksty z obrazów). Ich wartości poniżej `floor` liczyły się jako 0 w średniej, więc wyniki krawędzi między {1,2,3} i {48,61} spadły do 0,25–0,35. Przy `tau_family` 0,38 krawędzie nie powstawały: precyzja 1,0, recall 0,40, trafienie w rodzinę dla nowej kampanii 0%. To była oficjalna wartość z przebiegu 17:50.
3. **1,0 (poprawka metodyczna).** Zasada z pkt 3 (słaby dowód nie obniża wyniku) usuwa zera spod `floor`. Warunki przyjęcia ustalono **przed** przebiegiem: precyzja rodzin 1,0, open-set „nowa" 100%, singletony 100%, brak nowych fałszywych krawędzi rodzin, krawędzie kampanii bez zmian. Przebieg referencyjny 18:11 (te same progi, bez dostrajania) spełnił wszystkie: rodziny 1,00/0,40 → 1,00/1,00, trafienie w rodzinę 0% → 80%, fałszywe krawędzie 0 → 0. Wariant jest domyślny.

Poprawka ma uzasadnienie metodyczne, ale **wynik 1,0 nadal opiera się na niepotwierdzonej hipotezie rodziny**; nie jest dowodem skuteczności. Analiza czułości wag i regresja logistyczna (informacyjnie) są w raporcie ewaluacji (`reports/eval_<data>.md`): poziom kampanii jest niewrażliwy na wagi, rodziny zależą głównie od `face_match`, `same_narrative` i `same_param_template`.

## 7. Ograniczenia

- **10 incydentów, 4 pary tej samej kampanii:** to ilustracja, nie dowód skuteczności. Parametry dobrano na tej samej próbce i mogą zawieść na zbiorze ukrytym.
- **Etykiety** kampanii i rodzin są hipotezą niepotwierdzoną przez NASK; część powstała po identycznych plikach (stąd wariant bez `shared_assets`).
- **Incydent 3** nie ma dowodu na poziomie kampanii (brak HAR, inny tekst) i łączy się z {1,2} tylko jako rodzina. To **świadoma decyzja: precyzja ponad recall**. Obniżenie `tau_campaign` poniżej 0,33 połączyłoby go, ale opiera się na jednej parze o wyniku 0,33 i niepotwierdzonej etykiecie.
- **Infrastruktura z internetu** (RDAP, DNS, certyfikaty) działa tylko w trybie online; wizerunki osób opierają się na małej bazie referencyjnej.

## 8. Skalowalność i wdrożenie

- Do 200 incydentów liczymy wszystkie pary, powyżej **blocking** (wspólny element zbioru, klucz `exact`, wiaderko hasha, pasma MinHash). Pary wyłącznie z podobnym wektorem wymagałyby indeksu ANN.
- Wyniki: `data/graph/edges.parquet`, `clusters.json`; **eksport do Neo4j** (CSV + Cypher).
- **Przyrostowo:** `analyze` porównuje nowy materiał ze zbiorem bez przeliczania całości; pełne `correlate` uruchamia się okresowo.
- Biblioteki silnika: networkx (BSD), scikit-learn (BSD), datasketch (MIT), pandas/pyarrow/numpy (BSD/Apache).
