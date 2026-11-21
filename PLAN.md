# PLAN.md — Kolekcjoner fejków (aktualizacja: sob 13:00)

## Kamienie milowe
| Czas | Cel |
|---|---|
| 13:45 | Raport 1 od W1–W5. Loader W1 na `main`. |
| 15:15 | Raport 2: wszystkie moduły cech dają parquet; W5 podpina prawdziwe dane. |
| 16:30 | Pierwszy przebieg end-to-end: ingest → cechy → klastry → eval. |
| 17:30 | UI v1 (W1) na prawdziwych wynikach. |
| 18:30 | **Architektura zamknięta.** Lider + koordynator piszą draft. |
| 19:30 | Gotowy tekst draftu i lista załączników. |
| 20:00 | **DRAFT na stronie organizatora.** |
| noc | Strojenie wag i progów, Docker, metodyka, bonus: monitoring domen / biblioteka reklam. |
| ndz 07:00 | Feature freeze. |
| ndz 11:00 | Finalne zgłoszenie. |

## Zadania
| ID | Zadanie | Kto | Branch | Status |
|---|---|---|---|---|
| T0 | Repo, .gitignore, CONTRACTS v0.3, szkielet | lider | main | ✅ |
| T1 | Inwentaryzacja danych | W1 | feature/ingest | ✅ |
| T2 | Loader + runner + CLI | W1 | feature/ingest | ⏳ do 13:45 |
| T3 | html_struct | W1 | feature/ingest | ⏳ do 15:15 |
| T4 | text (+ gazetteer encji, narracje) | W2 | feature/text | ⏳ |
| T5 | visual + faces (+ baza referencyjna twarzy) | W3 | feature/visual | ⏳ |
| T6 | infra (HAR offline, OSINT online), stoplista | W4 | feature/infra | ⏳ |
| T7 | engine + eval (najpierw na danych syntetycznych) | W5 | feature/clustering | ⏳ |
| T8 | UI Streamlit + Docker + README | W1 | feature/ui | od ~16:00 |
| T9 | Nazwanie klastrów twarzy (`config/reference/faces.yaml`) | lider | feature/docs | po raporcie W3 |
| T10 | METHODOLOGY.md, LICENSES.md, AI_USAGE.md, PATTERNS.md | lider + koord. | feature/docs | od 17:00 |
| T11 | Pytania do mentorów: folder/kampania, format testu | lider | — | ⏳ |

## Decyzje
- Zadanie NASK (12:00). Incydent = folder. Etykiety robocze: {1,2,3}, {48,61}.
- Wagi startowe ręcznie + uzasadnienie w metodyce (za mało danych na uczenie wag).
- Twarze: OpenCV YuNet+SFace (Apache 2.0) zamiast InsightFace (licencja niekomercyjna).
- HAR = główne źródło infrastruktury offline; OSINT online tylko opcjonalnie, z cache.

## Otwarte problemy
- Potwierdzenie etykiet kampanii od mentorów.
- Format zbioru testowego (struktura folderów?).
