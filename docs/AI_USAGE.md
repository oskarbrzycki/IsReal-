# Użycie AI w projekcie IsReal?

## AI w procesie pracy zespołu

- **Koordynator (czat z Claude):** rozbił zadanie NASK na moduły i kontrakt interfejsów (`CONTRACTS.md`), przygotował prompty dla wykonawców W1–W5, weryfikował raporty i zlecał poprawki. Kontrakt zmieniał tylko koordynator, z wpisem w changelogu.
- **Wykonawcy W1–W5 (Claude Code jako asystent programowania):** pisali kod modułów i testy, uruchamiali je na danych i przygotowywali raporty z liczbami. Każdy pracował na własnej gałęzi, w ramach kontraktu.
- **Ludzie** decydowali i weryfikowali: wybór zadania i podejścia, akceptacja raportów, merge do `main` (robi lider), decyzje o danych (np. dane organizatora nigdy w gicie ani poza zespołem, OCR uruchamiany na maszynie referencyjnej zamiast przesyłania plików), potwierdzanie etykiet kampanii z mentorami NASK.
- **Zasady:** AI nie miało dostępu do żywych stron (tylko statyczne parsowanie zapisanych plików, bez JS). Raporty i dokumentacja nie zawierają treści stron ani identyfikatorów. Każda heurystyka była sprawdzana na tabelach par incydentów przed ustawieniem wag.

## Modele w produkcie

Wszystkie modele działają lokalnie na CPU, bez kluczy API. **Produkt nie używa LLM** (`LLM_ENABLED=false`; wszystko działa na regułach, cechach i embeddingach).

| Moduł | Model | Do czego | Licencja |
|---|---|---|---|
| text | `intfloat/multilingual-e5-small` (sentence-transformers) | embedding tekstu stron i OCR → `text_semantic` | MIT |
| visual | OpenCLIP ViT-B-32, wagi „openai” | embedding obrazów → `visual_style` | MIT |
| visual | Tesseract (pol+eng) | OCR obrazów i klatek wideo → `ocr_text` | Apache-2.0 |
| faces | OpenCV YuNet (detekcja) + SFace (embedding twarzy) | `face_match`, `same_identity` | Apache-2.0 |

Pozostałe cechy (MinHash, pHash, simhash, gazetteer encji, reguły narracji, sygnały infrastruktury z HAR i OSINT bez kluczy) to algorytmy deterministyczne, bez uczenia. Wagi sygnałów są startowo ustawione w `config/settings.yaml`; ich strojenie na etykietowanych parach opisuje METHODOLOGY.md (W5).
