# IsReal? — wyniki w skrócie (do pitchu)

*Zadanie NASK „Kolekcjoner fejków" (HackNation 2026).*

IsReal? łączy pojedyncze reklamy-scamy w kampanie oszustw i dla każdego powiązania podaje powody. Oficjalne wyniki na 10 przykładowych zgłoszeniach od NASK (313 plików), komplet cech (pięć modułów, w tym CLIP i OCR), 28 sygnałów podobieństwa. Źródło: przebieg referencyjny, `reports/reference_run_20261121_181101.md`.

**Hasło do pitchu: precyzja 100% na obu poziomach, 0 fałszywych połączeń, recall zachowawczy z założenia.** Wolimy przeoczyć powiązanie, niż zmyślić je.

| Metryka | Wartość | Co to znaczy prostymi słowami |
|---|---|---|
| Fałszywe połączenia kampanii | **0** | Nie sklejamy ze sobą reklam, które nie mają ze sobą nic wspólnego. |
| Precyzja kampanii | **100%** | Każda para reklam, którą uznajemy za tę samą kampanię, rzeczywiście nią jest. |
| Kompletność kampanii (recall) | 50% | Znajdujemy połowę prawdziwych par. Zachowawczo z założenia: wolimy przeoczyć powiązanie, niż błędnie połączyć dwie różne kampanie. |
| Rodziny kampanii: precyzja / recall | **100% / 100%** | Kampanie z tym samym „kitem" (szablon, twarze, narzędzia reklamowe) trafiają do jednej rodziny i nic się nie myli (6 rodzin na 10 zgłoszeń: jedna 5-elementowa i 5 pojedynczych). Skład rodziny to hipoteza zespołu, niepotwierdzona przez NASK. |
| Nowa, nieznana kampania | **100%** | Gdy usuniemy kampanię ze zbioru, system poprawnie mówi „to coś nowego", zamiast dokleić ją do innej. |
| …i wskazanie rodziny dla nowej kampanii | 80% | „Nowa kampania, ale pasuje do rodziny X": w 4 z 5 przypadków trafnie. |
| Przypisanie nowego zgłoszenia do znanej kampanii | 80% | Zgłoszenie dołożone do zbioru trafia do właściwej grupy w 4 z 5 przypadków; samotne zgłoszenia zawsze uznajemy za nowe (100%). |
| Odporność na rozbicie zgłoszenia | 70% | Gdy tnie się jedno zgłoszenie na osobne części (strona, reklama), 7 na 10 par wraca do siebie. |
| Odporność na braki danych | F1 0,57 | Gdy losowo brakuje 30% rodzajów danych (martwa strona, brak logu), grupowanie słabnie, ale nie tworzy błędnych połączeń. |
| Wyjaśnialność | 100% powiązań | Każde połączenie ma listę powodów po polsku, np. „to samo konto reklamowe". Identyfikatory z danych są zamaskowane (`1234…3456`). |

**Co działa dzięki twardym dowodom.** Kampanię łączymy tylko przy mocnym śladzie (ten sam piksel, konto reklamowe, domena albo identyczne pliki) lub co najmniej dwóch niezależnych. Podobny obraz sam nie wystarczy: wtedy wskazujemy tylko rodzinę.

**Uczciwa droga wyniku rodzin.** Najpierw 1,0 na uboższych cechach (bez CLIP i OCR), potem 0,57 po dodaniu kompletu cech (szum z OCR obniżał wyniki krawędzi), na końcu 1,0 po poprawce metodycznej: słaby dowód nie może obniżać wyniku. Warunki przyjęcia poprawki ustalono przed przebiegiem, a próg zostawiono bez zmian.

## Ograniczenia
Wyniki pochodzą z 10 zgłoszeń, w tym tylko 4 par z tej samej kampanii, więc są ilustracją działania, a nie dowodem skuteczności na dużym zbiorze, a parametry dobrano na tej samej próbce. Etykiety kampanii, a zwłaszcza rodzin, są hipotezą zespołu i czekają na potwierdzenie ekspertów NASK, a część powstała po identycznych plikach, więc ocena jest częściowo kołowa. Wynik rodzin 1,0 mimo poprawki metodycznej nadal opiera się na tej niepotwierdzonej hipotezie i nie powinien być czytany jako dowód skuteczności.
