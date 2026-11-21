# DATA_INVENTORY — paczka NASK (`data/raw/nask/`)

> Wygenerowano automatycznie: `python scripts/inventory.py data/raw/nask`. Parsowanie wyłącznie statyczne (bez renderowania, bez JS, bez sieci). Raport zawiera tylko liczby, typy, domeny i skrócone tytuły — bez treści stron i reklam.

> **Wersja publiczna (oczyszczona).** Domeny zastąpione opisem „domena .tld (folder N)”, identyfikatory skrócone do „…NNNN”, tytuły stron zastąpione typem strony, nazwy plików zastąpione wzorcami. Pełna wersja jest tylko lokalnie w `data/interim/` (poza repo). Generator: `python scripts/sanitize_inventory.py`.

## 1. Podsumowanie

- Folderów najwyższego poziomu: **10** (1, 2, 3, 5, 10, 14, 36, 47, 48, 61)
- Plików: **329**, łączny rozmiar: **531.4 MB**
- Kategorie materiałów: page asset (_files/): 278, image: 22, html page: 12, har log: 11, video: 3, json metadata: 2, mhtml: 1

## 2. Foldery × kategorie

| folder | pliki | rozmiar | głęb. | html page | page asset (_files/) | har log | image | video | mhtml | json metadata | other | X.html+X_files |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 21 | 6.2 MB | 2 | 1 | 18 | 1 | 1 | 0 | 0 | 0 | 0 | 1/1 |
| 2 | 21 | 7.5 MB | 2 | 1 | 18 | 2 | 0 | 0 | 0 | 0 | 0 | 1/1 |
| 3 | 15 | 1.8 MB | 2 | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1/1 |
| 5 | 2 | 8.3 MB | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0 | — |
| 10 | 33 | 44.9 MB | 2 | 1 | 25 | 1 | 6 | 0 | 0 | 0 | 0 | 1/1 |
| 14 | 80 | 360.6 MB | 5 | 2 | 63 | 1 | 11 | 1 | 1 | 1 | 0 | 1/3 |
| 36 | 38 | 3.4 MB | 2 | 1 | 35 | 1 | 1 | 0 | 0 | 0 | 0 | 1/1 |
| 47 | 29 | 46.4 MB | 2 | 1 | 26 | 1 | 0 | 1 | 0 | 0 | 0 | 1/1 |
| 48 | 32 | 22.6 MB | 2 | 1 | 29 | 1 | 1 | 0 | 0 | 0 | 0 | 1/1 |
| 61 | 58 | 29.8 MB | 3 | 3 | 51 | 3 | 1 | 0 | 0 | 0 | 0 | 3/3 |

`X.html+X_files` = liczba stron HTML (poza `_files/`), które mają obok folder `X_files/` / wszystkie takie strony.

## 3. Rozszerzenia i typy MIME (sniffing po magic bytes)

| rozszerzenie | razem | 1 | 2 | 3 | 5 | 10 | 14 | 36 | 47 | 48 | 61 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `.webp` | 59 | 8 | 8 | 9 |  | 4 | 2 |  | 1 | 19 | 8 |
| `.js(+pobrane)` | 50 | 2 | 2 |  |  | 5 | 10 | 15 | 2 | 6 | 8 |
| `.png` | 47 | 1 |  | 1 |  | 10 | 25 | 1 | 5 | 1 | 3 |
| `(none)` | 29 | 1 | 1 | 1 |  | 5 | 1 | 16 | 1 | 1 | 2 |
| `.jpg` | 28 | 3 | 3 |  |  |  |  |  | 8 |  | 14 |
| `.html` | 22 | 1 | 1 | 1 |  | 5 | 5 | 4 | 1 | 1 | 3 |
| `.css` | 19 | 1 | 1 |  |  |  | 5 | 1 | 3 | 2 | 6 |
| `.jpeg` | 17 |  |  |  |  |  | 11 |  | 6 |  |  |
| `.svg` | 12 | 3 | 3 |  |  | 1 | 2 |  |  | 1 | 2 |
| `.js` | 12 |  |  |  |  |  | 12 |  |  |  |  |
| `.har` | 11 | 1 | 2 |  |  | 1 | 1 | 1 | 1 | 1 | 3 |
| `.js(+pobierz)` | 9 |  |  |  |  |  |  |  |  |  | 9 |
| `.mp4` | 3 |  |  |  | 1 |  | 1 |  | 1 |  |  |
| `(none)(+pobrane)` | 2 |  |  | 2 |  |  |  |  |  |  |  |
| `.json` | 2 |  |  |  | 1 |  | 1 |  |  |  |  |
| `.gif` | 2 |  |  |  |  | 2 |  |  |  |  |  |
| `.ts` | 2 |  |  |  |  |  | 2 |  |  |  |  |
| `.m(+pobrane)` | 1 |  |  | 1 |  |  |  |  |  |  |  |
| `.mhtml` | 1 |  |  |  |  |  | 1 |  |  |  |  |
| `.m3u8` | 1 |  |  |  |  |  | 1 |  |  |  |  |

| MIME (sniff) | razem | 1 | 2 | 3 | 5 | 10 | 14 | 36 | 47 | 48 | 61 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| image/webp | 65 | 8 | 8 | 9 |  | 4 | 2 | 6 | 1 | 19 | 8 |
| application/javascript (guess) | 55 | 1 | 1 | 2 |  | 5 | 10 | 16 | 2 | 2 | 16 |
| image/jpeg | 52 | 3 | 3 |  |  |  | 11 | 7 | 14 |  | 14 |
| image/png | 48 | 1 |  | 1 |  | 10 | 25 | 1 | 5 | 2 | 3 |
| text/html | 22 | 1 | 1 | 1 |  | 5 | 5 | 4 | 1 | 1 | 3 |
| text/css | 19 | 1 | 1 |  |  |  | 5 | 1 | 3 | 2 | 6 |
| application/octet-stream | 15 | 2 | 2 | 1 |  | 4 |  |  | 1 | 3 | 2 |
| application/json | 13 | 1 | 2 |  | 1 | 1 | 2 | 1 | 1 | 1 | 3 |
| image/svg+xml | 12 | 3 | 3 |  |  | 1 | 2 |  |  | 1 | 2 |
| application/javascript | 12 |  |  |  |  |  | 12 |  |  |  |  |
| text/css (guess) | 7 |  |  | 1 |  | 1 | 1 | 2 |  | 1 | 1 |
| video/mp4 | 3 |  |  |  | 1 |  | 1 |  | 1 |  |  |
| image/gif | 2 |  |  |  |  | 2 |  |  |  |  |  |
| video/mp2t | 2 |  |  |  |  |  | 2 |  |  |  |  |
| multipart/related (mhtml) | 1 |  |  |  |  |  | 1 |  |  |  |  |
| application/domena .mpegurl | 1 |  |  |  |  |  | 1 |  |  |  |  |

Uwaga: `.js(+pobrane)` itp. to skrypty zapisane przez przeglądarkę w polskiej wersji językowej (sufiks „.pobrane”). `(none)` = brak rozszerzenia (np. `vt(3)`, `css2`, numeryczne ID pikseli FB).

## 4. Pliki na poziomie folderu (poza `_files/`) i wzorce nazw

| folder | plik (wzorzec nazwy) | kategoria | rozmiar | wymiary |
|---|---|---|---:|---|
| 1 | `Zrzut ekranu N-N-N N.png` | image | 342.2 KB | 537×677 |
| 1 | `«plik».har` | har log | 3.5 MB |  |
| 1 | `«tytuł strony».html` | html page | 205.2 KB |  |
| 2 | `«plik».har` | har log | 3.5 MB |  |
| 2 | `«plik».har` | har log | 1.6 MB |  |
| 2 | `«tytuł strony».html` | html page | 205.4 KB |  |
| 3 | `Zrzut ekranu N-N-N N.png` | image | 450.6 KB | 508×695 |
| 3 | `«tytuł strony».html` | html page | 72.0 KB |  |
| 5 | `Czytać [H_N].info.json` | json metadata | 5.6 KB |  |
| 5 | `Czytać [H_N].mpN` | video | 8.3 MB |  |
| 10 | `«tytuł strony».html` | html page | 200.3 KB |  |
| 10 | `IMG_N.PNG` | image | 4.2 MB | 1170×2532 |
| 10 | `IMG_N.PNG` | image | 4.1 MB | 1170×2532 |
| 10 | `IMG_N.PNG` | image | 5.7 MB | 1170×2532 |
| 10 | `IMG_N.PNG` | image | 663.5 KB | 1170×2532 |
| 10 | `IMG_N.PNG` | image | 1.0 MB | 1170×2532 |
| 10 | `IMG_N.PNG` | image | 1.6 MB | 1170×2532 |
| 10 | `«plik».har` | har log | 15.8 MB |  |
| 14 | `IMG_N.PNG` | image | 812.1 KB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 670.5 KB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 2.9 MB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 2.5 MB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 1.5 MB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 630.6 KB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 728.2 KB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 1.2 MB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 1.6 MB | 1170×2532 |
| 14 | `IMG_N.PNG` | image | 1.0 MB | 1170×2532 |
| 14 | `«tytuł strony».html` | html page | 98.3 KB |  |
| 14 | `ScreenRecording_N-N-N N-N-N_N.MPN` | video | 323.3 MB |  |
| 14 | `«katalog»/«katalog»/«tytuł strony».html` | html page | 88.9 KB |  |
| 14 | `«katalog»/«katalog»/manifest.json` | json metadata | 13.2 KB |  |
| 14 | `«katalog»/«katalog»/page.har` | har log | 1.3 MB |  |
| 14 | `«katalog»/«katalog»/page.mhtml` | mhtml | 8.6 MB |  |
| 14 | `«katalog»/«katalog»/screenshot.png` | image | 555.2 KB | 1249×2281 |
| 36 | `«tytuł strony».html` | html page | 58.9 KB |  |
| 36 | `Zrzut ekranu N-N-N N.png` | image | 297.1 KB | 417×609 |
| 36 | `«plik».har` | har log | 876.9 KB |  |
| 47 | `Nagrywanie ekranu N-N-N domena .mpn` | video | 33.6 MB |  |
| 47 | `«tytuł strony».html` | html page | 37.5 KB |  |
| 47 | `«plik».har` | har log | 10.0 MB |  |
| 48 | `«tytuł strony».html` | html page | 267.8 KB |  |
| 48 | `Zrzut ekranu N-N-N N.png` | image | 400.6 KB | 530×711 |
| 48 | `«plik».har` | har log | 12.6 MB |  |
| 61 | `reklama_N.png` | image | 282.4 KB | 518×420 |
| 61 | `strona_N/.har` | har log | 585.2 KB |  |
| 61 | `strona_1/«tytuł strony».html` | html page | 489.7 KB |  |
| 61 | `strona_2/«tytuł strony».html` | html page | 253.0 KB |  |
| 61 | `strona_N/«plik».har` | har log | 3.1 MB |  |
| 61 | `strona_3/«tytuł strony».html` | html page | 89.1 KB |  |
| 61 | `strona_N/«plik».har` | har log | 3.4 MB |  |

Najczęstsze wzorce nazw (N = cyfry, H = hash hex): `IMG_N.PNG`×16, `Zrzut ekranu N-N-N N.png`×4, `Czytać [H_N].info.json`×1, `Czytać [H_N].mpN`×1, `ScreenRecording_N-N-N N-N-N_N.MPN`×1, `manifest.json`×1, `page.har`×1, `page.mhtml`×1

## 5. Przykładowe drzewa folderów (2 poziomy)

```
1/
├── «katalog»/  (18 files)
│   ├── «plik».webp  [63.1 KB]
│   ├── «plik».webp  [51.1 KB]
│   ├── «plik».webp  [32.4 KB]
│   ├── «plik».webp  [45.2 KB]
│   ├── «plik».webp  [87.4 KB]
│   ├── «plik».webp  [69.1 KB]
│   ├── …5163  [367.6 KB]
│   ├── «plik».jpg  [30.0 KB]
│   ├── «plik».js.pobrane  [418.9 KB]
│   ├── «plik».jpg  [9.7 KB]
│   ├── «plik».svg  [2.0 KB]
│   ├── «plik».css  [30.6 KB]
│   └── … (+6 more)
├── «plik».har  [3.5 MB]
├── Zrzut ekranu N-N-N N.png  [342.2 KB]
└── «plik»  [205.2 KB]
```
```
14/
├── «katalog»/  (35 files)
│   └── «katalog»/  (35 files)
├── «strona»_files/  (33 files)
│   ├── «plik».js.pobrane  [17.2 KB]
│   ├── «plik».jpeg  [2.9 KB]
│   ├── «plik».jpeg  [3.0 KB]
│   ├── «plik».jpeg  [2.9 KB]
│   ├── «plik».jpeg  [2.5 KB]
│   ├── «plik».jpeg  [4.0 KB]
│   ├── «plik».jpeg  [4.0 KB]
│   ├── «plik».jpeg  [3.5 KB]
│   ├── «plik».jpeg  [2.6 KB]
│   ├── «plik».jpeg  [3.1 KB]
│   ├── «plik».jpeg  [3.2 KB]
│   ├── «plik».jpeg  [3.3 KB]
│   └── … (+21 more)
├── IMG_3625.PNG  [812.1 KB]
├── IMG_3626.PNG  [670.5 KB]
├── IMG_3627.PNG  [2.9 MB]
├── IMG_3628.PNG  [2.5 MB]
├── IMG_3629.PNG  [1.5 MB]
├── IMG_3630.PNG  [630.6 KB]
├── IMG_3631.PNG  [728.2 KB]
├── IMG_3632.PNG  [1.2 MB]
├── IMG_3633.PNG  [1.6 MB]
├── IMG_3634.PNG  [1.0 MB]
└── … (+2 more)
```
```
61/
├── strona_1/  (26 files)
│   ├── «katalog»/  (24 files)
│   ├── .har  [585.2 KB]
│   └── «plik»  [489.7 KB]
├── strona_2/  (12 files)
│   ├── «strona»_files/  (10 files)
│   ├── «plik».har  [3.1 MB]
│   └── «plik».html  [253.0 KB]
├── strona_3/  (19 files)
│   ├── «katalog»/  (17 files)
│   ├── «plik»  [89.1 KB]
│   └── «plik».har  [3.4 MB]
└── reklama_1.png  [282.4 KB]
```

## 6. Strony HTML (parsowanie statyczne)

| folder | plik | typ strony | saved from | og:url / canonical | script src | inline script | img | form | input | iframe | domeny w <a> | piksele FB |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | «tytuł».html | fałszywy artykuł newsowy (wizerunek znanej osoby → inwestycje) | domena .live (folder 1) |  | 3 | 5 | 15 | 0 | 1 | 0 | 1 | 0 |
| 2 | «tytuł».html | fałszywy artykuł newsowy (wizerunek znanej osoby → inwestycje) | domena .live (folder 2) |  | 3 | 5 | 15 | 0 | 1 | 0 | 1 | 0 |
| 3 | «tytuł».html | fałszywy artykuł newsowy (wizerunek znanej osoby → inwestycje) | domena .pro (foldery 2, 3) |  | 3 | 4 | 10 | 0 | 1 | 0 | 1 | 0 |
| 10 | «tytuł».html | fałszywa strona sklepu z aplikacjami (gra / kasyno) | domena .xyz (folder 10) |  | 9 | 2 | 11 | 1 | 6 | 4 | 3 | 3 |
| 10 | (w _files/) saved_resource(1).html |  |  |  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 10 | (w _files/) saved_resource(2).html |  | domena .xyz (folder 10) |  | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| 10 | (w _files/) saved_resource(3).html |  | domena .xyz (folder 10) |  | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| 10 | (w _files/) saved_resource.html |  | domena .xyz (folder 10) |  | 0 | 0 | 5 | 0 | 0 | 0 | 2 | 0 |
| 14 | «tytuł».html | strona sprzedaży suplementu | domena .top (folder 14) |  | 11 | 8 | 40 | 4 | 61 | 2 | 1 | 0 |
| 14 | (w _files/) saved_resource(1).html |  |  |  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 14 | (w _files/) saved_resource.html |  |  |  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 14 | dom.html | strona sprzedaży suplementu |  |  | 12 | 8 | 35 | 4 | 61 | 2 | 0 | 0 |
| 14 | (w _files/) index_H.html | strona sprzedaży suplementu |  |  | 10 | 8 | 35 | 2 | 36 | 0 | 0 | 0 |
| 36 | «tytuł».html | fałszywa konferencja inwestycyjna | domena .life (folder 36) |  | 3 | 1 | 5 | 1 | 4 | 1 | 1 | 0 |
| 36 | (w _files/) embed.html |  | www.google.com |  | 13 | 1 | 40 | 0 | 0 | 2 | 2 | 0 |
| 36 | (w _files/) saved_resource(1).html |  |  |  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 36 | (w _files/) saved_resource.html |  |  |  | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 47 | «tytuł».html | strona sprzedaży suplementu | domena .icu (folder 47) |  | 4 | 9 | 21 | 1 | 10 | 0 | 1 | 0 |
| 48 | «tytuł».html | fałszywy artykuł newsowy | domena .com (folder 48) |  | 6 | 28 | 22 | 2 | 9 | 0 | 1 | 0 |
| 61 | «tytuł».html | fałszywy artykuł newsowy |  |  | 5 | 28 | 19 | 42 | 50 | 0 | 1 | 0 |
| 61 | «tytuł».html | landing produktowy | domena .org (folder 61) |  | 6 | 24 | 3 | 2 | 16 | 0 | 0 | 0 |
| 61 | «tytuł».html | „biała” strona-przykrywka | domena .org (folder 61) |  | 8 | 30 | 9 | 1 | 1 | 0 | 1 | 0 |

## 7. Logi HAR

| folder | plik | narzędzie | requesty | unikalne hosty | IP serwerów | 3xx | pierwszy host |
|---|---|---|---:|---:|---:|---:|---|
| 1 | `«plik».har` | WebInspector | 31 | 3 | 3 | 0 | domena .live (folder 1) |
| 2 | `«plik».har` | WebInspector | 31 | 3 | 3 | 0 | domena .live (folder 2) |
| 2 | `«plik».har` | WebInspector | 17 | 6 | 4 | 0 | domena .pro (foldery 2, 3) |
| 10 | `«plik».har` | WebInspector | 38 | 10 | 9 | 1 | domena .xyz (folder 10) |
| 14 | `«katalog»/«katalog»/page.har` | page-capture | 35 | 6 | 6 | 0 | domena .top (folder 14) |
| 36 | `«plik».har` | WebInspector | 15 | 7 | 5 | 0 | domena .life (folder 36) |
| 47 | `«plik».har` | WebInspector | 43 | 4 | 4 | 2 | domena .net (folder 47) |
| 48 | `«plik».har` | WebInspector | 40 | 4 | 3 | 0 | domena .com (folder 48) |
| 61 | `strona_1/.har` | WebInspector | 13 | 4 | 4 | 0 |  |
| 61 | `strona_2/«plik».har` | WebInspector | 34 | 7 | 8 | 2 | domena .org (folder 61) |
| 61 | `strona_3/«plik».har` | WebInspector | 24 | 3 | 3 | 0 | domena .org (folder 61) |

## 8. Metadane (JSON / MHTML)

- `5/…/«tytuł».info.json` — kind: yt-dlp info.json, extractor: facebook:ads, webpage_host: www.facebook.com
- `14/…/manifest.json` — kind: page-capture manifest, tool: page-capture 0.1.0, captured_at: 2026-10-12T09:48:17+00:00, page_host: domena .top (folder 14), page_url_query_keys: ['_camp_id', '_trk', 'acc', 'ad_id', 'ad_name', 'adset_name', 'clickid', 'country_code', 'fbclid', 'geo', 'key', 'land_id', 'lpkey', 'placement', 'pxl', 'trafficsource', 'user_id', 'utm_campaign', 'utm_content', 'utm_id', 'utm_medium', 'utm_source', 'utm_term']
- `14/…/page.mhtml` — snapshot_host: domena .top (folder 14), subject_present: True

## 9. Domeny

### Domeny stron (saved from / og:url / canonical / manifest / mhtml) (11)

| domena | foldery |
|---|---|
| domena .live (folder 2) | 2 |
| domena .live (folder 1) | 1 |
| domena .org (folder 61) | 61 |
| domena .pro (foldery 2, 3) | 3 |
| domena .top (folder 14) | 14 |
| domena .life (folder 36) | 36 |
| domena .com (folder 48) | 48 |
| domena .xyz (folder 10) | 10 |
| domena .icu (folder 47) | 47 |
| www.facebook.com | 5 |
| www.google.com | 36 |

### Domeny w linkach `<a href>` / `<form action>` (13)

| domena | foldery |
|---|---|
| domena .live (folder 2) | 2 |
| domena .live (folder 1) | 1 |
| domena .org (folder 61) | 61 |
| domena .pro (foldery 2, 3) | 3 |
| domena .top (folder 14) | 14 |
| maps.google.com | 36 |
| domena .life (folder 36) | 36 |
| domena .com (folder 48) | 48 |
| domena .xyz (folder 10) | 10 |
| domena .icu (folder 47) | 47 |
| translate.google.com | 10 |
| translate.googleapis.com | 10 |
| www.google.com | 36 |

### Hosty z logów HAR (37)

| domena | foldery |
|---|---|
| cdn.jsdelivr.net | 14, 36, 47, 48, 61 |
| connect.facebook.net | 1, 2, 10, 48 |
| fonts.googleapis.com | 2, 36, 61 |
| fonts.gstatic.com | 2, 10, 61 |
| www.facebook.com | 1, 2, 10 |
| cdnjs.cloudflare.com | 36, 47 |
| www.google.com | 10, 61 |
| domena .live (folder 2) | 2 |
| ad.doubleclick.net | 61 |
| ajax.googleapis.com | 2 |
| domena .org (folder 14) | 14 |
| domena .org (folder 14) | 14 |
| domena .live (folder 1) | 1 |
| code.jquery.com | 14 |
| domena .pro (folder 2) | 2 |
| domena .org (folder 14) | 14 |
| domena .app (folder 36) | 36 |
| domena .org (folder 61) | 61 |
| googleads.g.doubleclick.net | 61 |
| domena .pro (foldery 2, 3) | 2 |
| images.unsplash.com | 36 |
| domena .top (folder 14) | 14 |
| domena .app (folder 36) | 36 |
| domena .life (folder 36) | 36 |
| domena .com (folder 48) | 48 |
| open.er-api.com | 61 |
| domena .info (folder 48) | 48 |
| domena .xyz (folder 10) | 10 |
| domena .icu (folder 47) | 47 |
| translate-pa.googleapis.com | 10 |
| translate.google.com | 10 |
| translate.googleapis.com | 10 |
| unpkg.com | 10 |
| domena .net (folder 47) | 47 |
| www.google.pl | 61 |
| www.googletagmanager.com | 61 |
| www.gstatic.com | 10 |

### Identyfikatory pikseli Facebook (`fbq('init', …)`, URL-e `signals/config/<id>` / `tr?id=` w HAR, pliki `<id>` w `_files/`)

| pixel ID | foldery |
|---|---|
| …5163 | 1, 2 |
| …2160 | 10 |
| …7817 | 10 |
| …4324 | 10 |

## 10. Duplikaty dokładne (sha1)

- Grup duplikatów: **40**, nadmiarowych kopii: **47** (4.6 MB)
- Grup obejmujących >1 folder: **28**

| foldery dzielące identyczne pliki | liczba wspólnych plików |
|---|---:|
| 1, 2 | 16 |
| 48, 61 | 8 |
| 1, 2, 3 | 1 |
| 1, 2, 61 | 1 |
| 10, 14, 36 | 1 |
| 14, 47 | 1 |

| sha1[:12] | kopie | rozmiar | kategoria | foldery |
|---|---:|---:|---|---|
| …0bb2 | 3 | 418.9 KB | page asset (_files/) | 1, 2, 3 |
| …6822 | 3 | 30.6 KB | page asset (_files/) | 1, 2, 61 |
| …61c9 | 5 | 149 B | page asset (_files/) | 10, 14, 36 |
| …d07a | 2 | 849.2 KB | page asset (_files/) | 1, 2 |
| …3722 | 2 | 367.6 KB | page asset (_files/) | 1, 2 |
| …0ce6 | 3 | 273.0 KB | page asset (_files/) | 48, 61 |
| …474e | 2 | 148.2 KB | page asset (_files/) | 48, 61 |
| …4e31 | 3 | 87.4 KB | page asset (_files/) | 14, 47 |
| …00f5 | 2 | 87.4 KB | page asset (_files/) | 1, 2 |
| …c9ce | 2 | 69.1 KB | page asset (_files/) | 1, 2 |
| …1033 | 2 | 68.6 KB | page asset (_files/) | 48, 61 |
| …9987 | 2 | 63.1 KB | page asset (_files/) | 1, 2 |
| …193e | 2 | 59.8 KB | page asset (_files/) | 48, 61 |
| …bfd8 | 2 | 51.1 KB | page asset (_files/) | 1, 2 |
| …4764 | 2 | 49.2 KB | page asset (_files/) | 1, 2 |
| …8478 | 2 | 45.2 KB | page asset (_files/) | 1, 2 |
| …e326 | 2 | 42.8 KB | page asset (_files/) | 1, 2 |
| …7e09 | 2 | 32.4 KB | page asset (_files/) | 1, 2 |
| …7a24 | 2 | 31.4 KB | page asset (_files/) | 48, 61 |
| …1b92 | 2 | 30.0 KB | page asset (_files/) | 1, 2 |
| …f52c | 2 | 29.1 KB | page asset (_files/) | 48, 61 |
| …c7f2 | 2 | 26.9 KB | page asset (_files/) | 1, 2 |
| …8e39 | 2 | 16.5 KB | page asset (_files/) | 48, 61 |
| …1282 | 2 | 9.7 KB | page asset (_files/) | 1, 2 |
| …cb58 | 2 | 5.8 KB | page asset (_files/) | 48, 61 |
| …cc48 | 2 | 2.0 KB | page asset (_files/) | 1, 2 |
| …1a2a | 2 | 314 B | page asset (_files/) | 1, 2 |
| …87c4 | 2 | 312 B | page asset (_files/) | 1, 2 |
| …0be2 | 2 | 768.6 KB | page asset (_files/) | 14 |
| …72a4 | 2 | 77.3 KB | page asset (_files/) | 14 |
| …b860 | 2 | 58.8 KB | page asset (_files/) | 14 |
| …79f2 | 2 | 56.0 KB | page asset (_files/) | 14 |
| …6e31 | 2 | 22.4 KB | page asset (_files/) | 14 |
| …7d96 | 2 | 17.2 KB | page asset (_files/) | 14 |
| …e1a7 | 2 | 6.2 KB | page asset (_files/) | 36 |
| …39e4 | 2 | 3.2 KB | page asset (_files/) | 14 |
| …487f | 2 | 3.2 KB | page asset (_files/) | 14 |
| …5180 | 2 | 1.7 KB | page asset (_files/) | 14 |
| …ff08 | 2 | 892 B | page asset (_files/) | 14 |
| …3d51 | 2 | 806 B | page asset (_files/) | 14 |


<!-- MANUAL: hand-written section below is preserved by inventory.py -->
## 11. Wnioski (ręcznie, W1, wersja publiczna)

### Tematyka folderów (na podstawie typów stron i struktury, bez treści)

| folder | typ oszustwa (wstępnie) | domena landingu | materiały |
|---|---|---|---|
| 1 | fałszywy artykuł podszywający się pod portal newsowy, wizerunek znanej osoby → inwestycje | domena .live | HTML+_files, HAR, zrzut ekranu |
| 2 | **ta sama strona co 1** (identyczne pliki, ten sam piksel FB), inna domena + HAR innej domeny | domena .live, domena .pro (HAR) | HTML+_files, 2× HAR |
| 3 | fałszywy artykuł podszywający się pod serwis telewizyjny, wizerunek znanej osoby → inwestycje | domena .pro | HTML+_files, zrzut ekranu (HAR tej domeny leży w folderze 2) |
| 5 | sama reklama wideo z Biblioteki Reklam FB | (platforma FB, extractor `facebook:ads`) | MP4 + yt-dlp info.json |
| 10 | fałszywa strona sklepu z aplikacjami z grą / kasynem | domena .xyz | HTML+_files, HAR, 6 zrzutów telefonu |
| 14 | suplement | domena .top | 2 zapisy strony (przeglądarka + narzędzie `page-capture` z manifestem, MHTML, HAR, zrzutem), 10 zrzutów telefonu, nagranie ekranu 323 MB |
| 36 | fałszywa konferencja inwestycyjna | domena .life | HTML+_files, HAR, zrzut ekranu |
| 47 | suplement | domena .icu | HTML+_files, HAR, nagranie ekranu |
| 48 | fałszywy artykuł newsowy | domena .com | HTML+_files, HAR, zrzut ekranu |
| 61 | reklama + łańcuch 3 stron: „biała” strona → landing produktowy → ten sam fałszywy artykuł co w 48 | domena .org | `reklama_N.png` + `strona_1..3/` (każda: HTML+_files+HAR) |

### Sygnały łączące foldery (już na poziomie sha1 / identyfikatorów)

- **1 ↔ 2**: 16 identycznych plików (cała strona), wspólny piksel FB `…5163`, różne domeny (rotacja domen).
- **1 ↔ 2 ↔ 61**: identyczny, nietypowy arkusz stylów (wspólny „kit” szablonu).
- **1/2 ↔ 3**: HAR domeny z folderu 3 leży w folderze 2; ten sam schemat „fałszywy portal + znana osoba”.
- **48 ↔ 61**: 8 identycznych plików (logo, avatar, 5 obrazów newsów, bundle JS) i ten sam tytuł strony.
- **14 ↔ 47**: ten sam typ (suplementy), wspólny jest tylko jQuery — to szum, nie dowód.
- Szum do wycięcia (stoplista): `fbevents.js`, jQuery, puste `saved_resource*.html` (149 B), fonty Google, CDN-y (jsdelivr, cdnjs).

### Odpowiedzi

- **(a) Folder = kampania?** Raczej **nie**. Folder wygląda na jedno zgłoszenie (incydent), a kilka folderów należy do tej samej kampanii (1+2+3, 48+61). Numeracja z lukami (1…61) sugeruje próbkę większej bazy zgłoszeń.
- **(b) Incydent** = folder: reklama (zrzut / wideo / `reklama_N.png`) + landing (HTML+`_files/`) + HAR. Folder 61 zawiera łańcuch przekierowań w `strona_N/`, folder 14 dwa zapisy tej samej strony, folder 5 samą reklamę bez landingu.
- **(c) Typy**: HTML „cała strona” (`X.html` + `X_files/`, skrypty z sufiksem `.pobrane`/`.pobierz`), HAR (WebInspector / Safari i `page-capture`), PNG (zrzuty telefonu 1170×2532 i Windows), MP4 (nagrania ekranu, reklama FB), MHTML, HLS (`.m3u8`+`.ts`), JSON (manifest, yt-dlp). Brak TXT i logów innych niż HAR.
- **(d) Metadane/etykiety**: **brak** CSV i etykiet kampanii. Są tylko metadane techniczne: `manifest.json` (czas zrzutu, URL z parametrami reklamy: `ad_id`, `adset_name`, `pxl`, `utm_*`, `placement`), `info.json` z yt-dlp (FB Ad Library), daty w nazwach zrzutów i `startedDateTime` w HAR.
