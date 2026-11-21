#!/usr/bin/env python3
"""Public (sanitized) version of the data inventory report. Owner: W1.

    python scripts/sanitize_inventory.py [--src data/interim/DATA_INVENTORY_full.md] [--out docs/DATA_INVENTORY.md]

The full report (real domains, IDs, page titles, file names) stays ONLY in data/interim/ (gitignored).
The public report replaces:
  * scam domains            -> "domena .xyz (folder N)"   (generic CDNs / big platforms are kept)
  * long numeric IDs/hashes -> "…NNNN"                    (last 4 characters)
  * page titles             -> description of the page type
  * file / folder names     -> structural placeholders ("«plik».webp", "«strona»_files/")
The hand-written conclusions (section 11) are replaced by a reviewed public text.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

MANUAL_MARKER = "<!-- MANUAL: hand-written section below is preserved by inventory.py -->"

# Infrastructure everybody uses: naming it reveals nothing about a campaign.
KEEP_DOMAINS = {
    "google.com", "google.pl", "googleapis.com", "gstatic.com", "facebook.com", "facebook.net", "fbcdn.net",
    "jsdelivr.net", "cloudflare.com", "unpkg.com", "jquery.com", "doubleclick.net", "googletagmanager.com",
    "unsplash.com", "er-api.com",
}
# Page type per folder (replaces page titles). Folder 61 is a chain: strona_1..3.
PAGE_TYPE = {
    "1": "fałszywy artykuł newsowy (wizerunek znanej osoby → inwestycje)",
    "2": "fałszywy artykuł newsowy (wizerunek znanej osoby → inwestycje)",
    "3": "fałszywy artykuł newsowy (wizerunek znanej osoby → inwestycje)",
    "10": "fałszywa strona sklepu z aplikacjami (gra / kasyno)",
    "14": "strona sprzedaży suplementu",
    "36": "fałszywa konferencja inwestycyjna",
    "47": "strona sprzedaży suplementu",
    "48": "fałszywy artykuł newsowy",
    "61": ["fałszywy artykuł newsowy", "landing produktowy", "„biała” strona-przykrywka"],
}
# Structural names that carry no scam content
SAFE_NAME_RES = [re.compile(p, re.I) for p in (
    r"^IMG_\w+\.(png|jpe?g|heic)$", r"^Zrzut ekranu .*\.png$", r"^reklama_\w+\.png$", r"^strona_\w+/?$",
    r"^manifest\.json$", r"^page\.(har|mhtml)$", r"^screenshot\.png$", r"^dom\.html$", r"^\.har$",
    r"^resources/?$", r"^«(tytuł strony|tytuł|plik|strona|katalog)»", r"^Czytać \[H_N\]", r"^Nagrywanie ekranu", r"^ScreenRecording_",
    r"^saved_resource(\(\d+\))?\.html$", r"^index_[0-9a-f]+\.html$", r"^embed\.html$", r"^\d+$",
    r"^\.\.\.$", r"^… \(\+\d+ more\)$", r"^(stylesheet|document|script|image|media)/?$",
)]
DOMAIN_ROW_RE = re.compile(r"^\|\s*([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})\s*\|\s*([\d, ]+)\s*\|$", re.I)
HOST_RE = re.compile(r"(?<![\w@])((?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?[._])+[a-z]{2,24})(?![\w])", re.I)
LONG_NUM_RE = re.compile(r"(?<![\w…])(\d{10,})(?!\w)")
HEX_RE = re.compile(r"(?<![\w…])([0-9a-f]{12,40})(?![\w])")
TREE_RE = re.compile(r"^([│├└─\s]*[├└]──\s)(.+?)(\s+\[[^\]]+\]|\s+\(\d+ files\))?$")


def etld1(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    two_level = {"co.uk", "com.pl", "net.pl", "org.pl", "com.au"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in two_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def folders_label(folders: str) -> str:
    f = [x.strip() for x in folders.split(",") if x.strip()]
    return f"folder {f[0]}" if len(f) == 1 else "foldery " + ", ".join(f)


def build_domain_map(text: str) -> dict[str, str]:
    """domain -> 'domena .tld (folder N)' from the domain tables of section 9."""
    seen: dict[str, set[str]] = {}
    for line in text.splitlines():
        m = DOMAIN_ROW_RE.match(line.strip())
        if not m:
            continue
        dom = m.group(1).lower()
        if etld1(dom) in KEEP_DOMAINS:
            continue
        # a domain appears in several tables (pages, links, HAR hosts): union of its folders
        seen.setdefault(dom, set()).update(x.strip() for x in m.group(2).split(",") if x.strip())
    key = lambda f: (0, int(f)) if f.isdigit() else (1, 0)
    return {dom: f"domena .{dom.rsplit('.', 1)[-1]} ({folders_label(', '.join(sorted(fs, key=key)))})"
            for dom, fs in seen.items()}


def domain_variants(domain_map: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    """Regexes for every spelling a domain takes in file names: as-is, digits->N, dots->underscores."""
    pats = []
    for dom, label in sorted(domain_map.items(), key=lambda kv: -len(kv[0])):
        for v in {dom, re.sub(r"\d+", "N", dom), dom.replace(".", "_")}:
            pats.append((re.compile(r"(?<![\w.\-])" + re.escape(v) + r"(?![\w\-])", re.I), label))
    return pats


def mask_domains(s: str, pats: list[tuple[re.Pattern, str]]) -> str:
    for rx, label in pats:
        s = rx.sub(label, s)

    def generic(m: re.Match) -> str:     # any other host that is not plain infrastructure
        host = m.group(1)
        if "_" in host or "." not in host:
            return host
        tld = host.rsplit(".", 1)[-1].lower()
        if tld in {"html", "htm", "har", "json", "png", "jpg", "jpeg", "webp", "svg", "css", "js", "mhtml",
                   "mp4", "md", "py", "ts", "m3u8", "pobrane", "pobierz", "gif", "txt", "yaml"}:
            return host
        return host if etld1(host) in KEEP_DOMAINS else f"domena .{tld}"
    return HOST_RE.sub(generic, s)


def mask_ids(s: str) -> str:
    s = LONG_NUM_RE.sub(lambda m: "…" + m.group(1)[-4:], s)
    return HEX_RE.sub(lambda m: "…" + m.group(1)[-4:] if re.search(r"\d", m.group(1)) else m.group(1), s)


def safe_name(name: str) -> str:
    """Structural placeholder for a file/folder name (keeps the extension)."""
    is_dir = name.endswith("/")
    bare = name.rstrip("/")
    # keep structural names, but reduce dates/hashes inside them to N/H patterns (leak_check)
    if re.match(r"^Zrzut ekranu ", bare):
        return re.sub(r"\d+", "N", bare)
    if re.match(r"^index_[0-9a-f]+\.html$", bare, re.I):
        return "index_H.html"
    if any(rx.search(bare) or rx.search(name) for rx in SAFE_NAME_RES):
        return name
    if is_dir:
        return "«strona»_files/" if bare.endswith("_files") or "_files" in bare else "«katalog»/"
    m = re.search(r"(\.[A-Za-z0-9]{1,5})(\.(pobrane|pobierz|download))?$", bare)
    return "«plik»" + (m.group(0) if m else "")


def sanitize_tree_line(line: str) -> str:
    m = TREE_RE.match(line)
    if not m:
        return line
    prefix, name, tail = m.group(1), m.group(2), m.group(3) or ""
    return prefix + safe_name(name.strip()) + tail


def sanitize_file_cell(cell: str) -> str:
    """`a/b/c.ext` path inside backticks -> each component sanitized."""
    def one(m: re.Match) -> str:
        parts = m.group(1).split("/")
        return "`" + "/".join(safe_name(p + ("/" if i < len(parts) - 1 else "")).rstrip("/")
                              if p else p for i, p in enumerate(parts)) + "`"
    return re.sub(r"`([^`]+)`", one, cell)


def sanitize(text: str) -> str:
    generated, _, _ = text.partition(MANUAL_MARKER)
    pats = domain_variants(build_domain_map(generated))
    out: list[str] = []
    section = ""
    seen_61 = 0
    for line in generated.splitlines():
        if line.startswith("## "):
            section = line[3:5].strip(". ")
        if section == "4" and line.startswith("| ") and "`" in line:
            cells = line.split("|")
            cells[2] = sanitize_file_cell(cells[2])
            line = "|".join(cells)
        elif section == "4" and line.startswith("Najczęstsze wzorce nazw"):
            keep = [t for t in re.findall(r"`[^`]+`×\d+", line)
                    if safe_name(t.split("`")[1]) == t.split("`")[1]]
            line = "Najczęstsze wzorce nazw (N = cyfry, H = hash hex): " + ", ".join(keep)
        elif section == "5":
            line = sanitize_tree_line(line)
            if re.match(r"^\d+/$", line.strip()) is None and line.strip().endswith("/") and "──" not in line:
                pass
        elif section == "6" and line.startswith("| ") and not line.startswith("| folder") and "---" not in line:
            cells = line.split("|")
            folder = cells[1].strip()
            if cells[3].strip() or "«" in cells[2]:
                ptype = PAGE_TYPE.get(folder, "strona")
                if isinstance(ptype, list):
                    ptype = ptype[min(seen_61, len(ptype) - 1)] if "(w _files/)" not in cells[2] else ptype[0]
                    seen_61 += "(w _files/)" not in cells[2]
                cells[3] = f" {ptype} " if cells[3].strip() or "«" in cells[2] else cells[3]
            cells[2] = sanitize_file_cell(cells[2]) if "`" in cells[2] else cells[2]
            line = "|".join(cells)
            line = line.replace("| tytuł (skrót) |", "| typ strony |")
        elif section == "7" and line.startswith("| ") and "`" in line:
            cells = line.split("|")
            cells[2] = sanitize_file_cell(cells[2])
            line = "|".join(cells)
        if section == "6":
            line = line.replace("tytuł (skrót)", "typ strony")
        line = re.sub(r"index_[0-9a-f]{6,}\.html", "index_H.html", line, flags=re.I)
        line = mask_domains(line, pats)
        line = mask_ids(line)
        out.append(line)
    header_note = ("> **Wersja publiczna (oczyszczona).** Domeny zastąpione opisem „domena .tld (folder N)”, "
                   "identyfikatory skrócone do „…NNNN”, tytuły stron zastąpione typem strony, nazwy plików "
                   "zastąpione wzorcami. Pełna wersja jest tylko lokalnie w `data/interim/` (poza repo). "
                   "Generator: `python scripts/sanitize_inventory.py`.\n")
    body = "\n".join(out).rstrip() + "\n"
    body = body.replace("\n## 1. Podsumowanie", "\n" + header_note + "\n## 1. Podsumowanie", 1)
    return body + "\n\n" + MANUAL_MARKER + "\n" + PUBLIC_CONCLUSIONS


PUBLIC_CONCLUSIONS = """## 11. Wnioski (ręcznie, W1, wersja publiczna)

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
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=Path("data/interim/DATA_INVENTORY_full.md"))
    ap.add_argument("--out", type=Path, default=Path("docs/DATA_INVENTORY.md"))
    args = ap.parse_args(argv)
    args.out.write_text(sanitize(args.src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"public inventory -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
