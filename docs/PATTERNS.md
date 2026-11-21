# IsReal? — katalog wzorców kampanii (zbiór NASK, 10 incydentów)

> Opis wzorców wyciągniętych z cech (tekst, wizualia, infrastruktura). Bez cytatów z treści stron, bez domen i identyfikatorów: zamiast nich typ (np. „domena w TLD .live”). Podział na kampanie i rodziny to **hipoteza robocza** (`eval/labels.yaml`), czeka na potwierdzenie mentorów NASK. Nazwy osób publicznych to osoby, których **wizerunek** wykorzystano bez ich zgody; nie są autorami treści.

## Rodzina F1: „fałszywy portal informacyjny + znana osoba → inwestycja” (incydenty 1, 2, 3, 48, 61)

Wspólny „kit” obu kampanii tej rodziny:
- strona podszywa się pod duży polski portal lub stację TV (logotypy, układ artykułu, sekcja komentarzy);
- osoba publiczna rzekomo zdradza sposób na zarobek albo jest ofiarą ataku lub aresztowania;
- w treści pojawia się nazwa „pakietu” lub „systemu” inwestycyjnego;
- wpłatę ułatwiają logotypy banków i BLIK, a stopka ma loga mediów, które rzekomo pisały o produkcie.

Infrastruktura rodziny (W4): ten sam szablon parametrów URL z reklamy, wspólny nietypowy arkusz CSS i te same twarze na zdjęciach (W3) w obu kampaniach.

| | **Kampania A** (1, 2, 3) | **Kampania B** (48, 61) |
|---|---|---|
| Narracja | atak lub zamach na znaną osobę → wywiad → rzekomy sposób na zarobek | aresztowanie po programie TV, skandal, rzekome blokowanie przez banki |
| Podszycie: media | duży portal informacyjny; w 3 stacja TV | duży portal informacyjny, stacja TV |
| Podszycie: osoby | prezes firmy kurierskiej, przedsiębiorczyni, ekspremier (1, 2); dziennikarka TV i prezes banku centralnego (3) | ekspremier, dziennikarz TV, przedsiębiorca (48); premier, prezenter TV (61) |
| Platforma / produkt | ta sama nazwa „pakietu” w 1, 2, 3; w 1 i 2 dodatkowo nazwa „platformy” | nazwa „programu oszczędzania emerytalnego”; drugi krok łańcucha to landing z własną nazwą produktu |
| CTA | przycisk przejścia do „oficjalnej” strony platformy, formularz rejestracji; wpłata startowa ok. 1 000–1 150 zł | otwarcie konta z aktywacją kwoty, „dostęp” do programu, rezerwacja rozmowy z „doradcą”; wpłata startowa ok. 950 zł |
| Kwoty | obietnice zarobku 1 600–7 500 zł, także w skali miesiąca | podobne progi kwot jak w A (to wskazówka wspólnego kitu) |
| Infrastruktura | **rotacja domen**: identyczna strona (17 identycznych plików) pod dwiema domenami w TLD .live, zarejestrowanymi w odstępie 108 s (RDAP, W4); trzecia strona na domenie w TLD .pro, której log ruchu sieciowego trafił do zgłoszenia 2; wspólny piksel reklamowy Facebooka (1, 2) | 8 identycznych assetów (logo, avatar, zdjęcia „newsów”, paczka JS); w 61 łańcuch 3 stron: „biała” strona-przykrywka (portal analityczny) → landing produktu → artykuł; domeny w TLD .com i .org |
| Wykrywają: campaign | `shared_trackers`, `shared_assets`, `shared_har_trackers`, `text_near_dup` (1–2: 0,98), `same_platform_name` (1–2–3), `same_registered_domain` (2–3) | `shared_assets`, `image_near_dup`; tekst artykułu **przepisany** (`text_near_dup` 0,01), ale semantycznie bliski (`text_semantic` 0,94 przed floor) |
| Wykrywają: family | `dom_template`, `same_param_template`, `shared_entities`, `same_narrative`, `face_match` | jak w A, a do tego `same_adtech_stack`, `hidden_text_sim`, `shared_scripts` |

Słabość: incydent 3 łączy się z 1 i 2 tylko przez nazwę „pakietu” i wspólną domenę (wynik krawędzi 0,32, poniżej progu kampanii). Rotacja domen i nowe osoby w tej samej kampanii to dokładnie ten przypadek, w którym tekst i nazwa produktu muszą zastąpić identyczne pliki.

## Pojedyncze incydenty (osobne rodziny)

| Incydent | Narracja | Podszycie | Produkt / CTA | Infrastruktura | Wykrywające sygnały |
|---|---|---|---|---|---|
| **10** | fałszywa karta aplikacji w sklepie z aplikacjami: gra lub kasyno z bonusami | sklep z aplikacjami producenta telefonów; logotypy banków przy płatnościach | nazwa gry jako produkt; przycisk instalacji; kwoty bonusów i wygranych | domena w TLD .xyz, 3 piksele reklamowe, osadzony tłumacz stron | `same_platform_name`, `same_narrative` (giveaway), `shared_trackers` |
| **14** | suplement odchudzający, fałszywe komentarze rzekomych klientów (ukryte do czasu uruchomienia JS) | brak znanych osób, styl strony z opiniami | nazwa suplementu; przycisk lub formularz zamówienia; cena promocyjna ok. 69 zł zamiast 138 zł | domena w TLD .top; URL wejścia z pełnym szablonem parametrów reklamy (identyfikator reklamy, zestawu reklam, piksela, utm) | `same_platform_name`, `same_narrative` (health), `same_param_template` |
| **47** | suplement na prostatę, rzekomy wywiad z lekarzem i komentarze | autorytet medyczny (bez nazwiska z gazetteera) | nazwa suplementu; formularz zamówienia; „promocja” o połowę: ok. 137 zł zamiast 274 zł | domena w TLD .icu; wideo z CDN; 2 przekierowania | `same_narrative` (health); z 14 łączy go tylko rodzina tematyczna (`text_semantic` 0,89 przed floor), wspólne jQuery to szum ze stoplisty |
| **36** | fałszywa konferencja inwestycyjna | wydarzenie biznesowe (bez znanych osób) | pakiety biletów ok. 1 900–15 000 zł; zakup biletu, formularz zapytania | domena w TLD .life; biblioteki z darmowego hostingu statycznego | `same_narrative` (conference_event) |
| **5** | sama reklama wideo z Biblioteki Reklam (bez landingu) | — | tylko etykieta przycisku reklamy | metadane narzędzia do pobierania wideo | tylko wizualia i twarze; sygnały tekstowe puste (test odporności na braki) |

## Wnioski dla metody

1. **Identyczne pliki i piksel** wykrywają rotację domen w obrębie kampanii (A: 1–2). **Nazwa produktu** (`same_platform_name`) łączy warianty, które nie dzielą plików (3).
2. **Tekst bywa przepisywany** między wariantami (B). Wtedy `text_near_dup` milczy, a niesie go `text_semantic`. Sam `text_semantic` bez floor łączy jednak 100% par: każde dwie polskie strony scamowe mają podobieństwo e5 0,77–0,84. Dlatego ma floor 0,85 i klasę family.
3. **Wizerunki osób** i **logotypy mediów** to wzorzec rodziny, nie kampanii. Te same osoby wracają w różnych kampaniach. Banki, BLIK i widżety Facebooka występują prawie wszędzie, więc nie liczą się do `shared_entities`.
4. Kandydat na nowy sygnał rodziny: **progi kwot** (wpłata startowa, obiecany zarobek) powtarzają się między kampaniami A i B.
