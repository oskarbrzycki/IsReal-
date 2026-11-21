#!/usr/bin/env python3
"""Plan-B screenshots and backup video of the pitch demo, taken on THIS machine (owner: W1).

Follows docs/DEMO_SCRIPT.md in public mode. Captions and expectations are read from this machine's
own engine output (data/graph/clusters.json, edges.parquet), so the material matches what the
reference machine shows live. Nothing scam-related is rendered: the app runs in public mode.

Prerequisites (dev only, not in requirements):  pip install playwright   + Google Chrome installed
    streamlit run ui/app.py                          # in another terminal (http://localhost:8501)
    python scripts/demo_capture.py --shots           # -> docs/img/demo/*.png, docs/img/ui_*.png
    python scripts/demo_capture.py --video           # -> data/demo/IsReal_demo_zapasowe.webm (gitignored)

The demo zips are built on the fly in data/demo/ (gitignored) from data/raw/nask/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"
STATUS_JS = "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')"
CAPTION_JS = """(t) => {
  let d = document.getElementById('demo-caption');
  if (!d) { d = document.createElement('div'); d.id = 'demo-caption'; document.body.appendChild(d);
    Object.assign(d.style, {position:'fixed', top:'14px', left:'50%', transform:'translateX(-50%)',
      background:'rgba(20,20,20,.85)', color:'#fff', padding:'10px 22px', borderRadius:'10px',
      font:'600 20px/1.3 sans-serif', zIndex: 999999, maxWidth:'80%', textAlign:'center'}); }
  d.textContent = t; }"""


def make_zip(folder: str, name: str, skip_har: bool = False) -> Path:
    DEMO.mkdir(parents=True, exist_ok=True)
    out = DEMO / name
    src = ROOT / "data" / "raw" / "nask" / folder
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file() and p.name != ".DS_Store" and not (skip_har and p.name.lower().endswith(".har")):
                zf.write(p, Path(folder) / p.relative_to(src))
    return out


def facts() -> dict:
    """Numbers for the captions, from this machine's engine output."""
    g = ROOT / "data" / "graph"
    cl = json.loads((g / "clusters.json").read_text(encoding="utf-8"))
    edges = pd.read_parquet(g / "edges.parquet")
    rule = [f"{r.a.split(':')[1]}↔{r.b.split(':')[1]}" for r in edges.itertuples()
            if "regula_kampanii" in (r.reasons if isinstance(r.reasons, str) else json.dumps(list(r.reasons)))]
    camp_of = {m: c["campaign_id"] for c in cl["clusters"] for m in c["members"]}
    multi = [c for c in cl["clusters"] if len(c["members"]) > 1]
    fams = [f for f in cl["families"] if len(f["members"]) > 1]
    e12 = edges[(edges.level == "campaign") & (edges.a == "nask:1") & (edges.b == "nask:2")]
    return {
        "n_inc": cl["params"].get("n_incidents"), "n_camp": len(cl["clusters"]), "n_fam": len(cl["families"]),
        "camps": " · ".join(f"{c['campaign_id']} = foldery " + ", ".join(m.split(':')[1] for m in c["members"])
                            for c in multi),
        "fams": " · ".join(f"{f['family_id']} = " + ", ".join(m.split(':')[1] for m in f["members"]) for f in fams),
        "rule": ", ".join(rule) or "brak", "c12": camp_of.get("nask:1", "C001"),
        "s12": f"{float(e12.score.iloc[0]):.2f}".replace(".", ",") if len(e12) else "—",
    }


def run(shots: bool, video: bool, url: str) -> None:
    from playwright.sync_api import sync_playwright

    f = facts()
    z2, z47, z3 = make_zip("2", "folder2_bez_har.zip", skip_har=True), make_zip("47", "folder47.zip"), \
        make_zip("3", "folder3.zip")
    base = url.rstrip("/") + "/?public=1&tab="
    img = ROOT / "docs" / "img"
    (img / "demo").mkdir(parents=True, exist_ok=True)

    def settle(pg, ms=1500):
        pg.wait_for_selector("h1", timeout=60000)
        pg.wait_for_function(STATUS_JS, timeout=300000)
        pg.wait_for_timeout(ms)

    def cap(pg, text):
        if video:
            pg.evaluate(CAPTION_JS, text)

    def wait(pg, ms):
        pg.wait_for_timeout(ms if video else 300)

    def shot(pg, name):
        if shots:
            pg.screenshot(path=str(img / name))
            print("  saved", name, flush=True)

    def analyze(pg, zip_path, exclude):
        pg.goto(base + "analiza"); settle(pg, 500)
        pg.get_by_text("Tryb demo: wyklucz incydenty z bazy").click(); pg.wait_for_timeout(700)
        if exclude:
            pg.locator("[data-testid=stMultiSelect] input").fill(exclude); pg.wait_for_timeout(500)
            pg.keyboard.press("Enter"); pg.keyboard.press("Escape"); pg.wait_for_timeout(800)
        pg.set_input_files("input[type=file]", str(zip_path)); pg.wait_for_timeout(2500)
        t = time.time()
        pg.get_by_role("button", name="Analizuj").click()
        pg.wait_for_selector("text=Czas analizy", timeout=300000); settle(pg, 500)
        heading = [h.strip() for h in pg.locator("h1").all_inner_texts()][1:]
        print(f"  {zip_path.name} excl={exclude}: {heading} ({time.time() - t:.1f} s)", flush=True)
        return heading

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        kw = {"viewport": {"width": 1440, "height": 900 if video else 1100}}
        if video:
            kw.update(record_video_dir=str(DEMO), record_video_size={"width": 1440, "height": 900})
        ctx = browser.new_context(**kw)
        pg = ctx.new_page()

        print("warm-up (first analysis loads the models)...", flush=True)
        analyze(pg, z47, "nask:47")

        pg.goto(base + "kampanie"); settle(pg)
        cap(pg, f"1/4 · {f['n_inc']} zgłoszeń NASK → {f['n_camp']} kampanii, {f['n_fam']} rodzin"); wait(pg, 9000)
        shot(pg, "demo/demo_1_kampanie.png"); shot(pg, "ui_1_kampanie.png")
        cap(pg, f"Kampanie: {f['camps']} · Rodziny: {f['fams']}"); wait(pg, 10000)
        pg.mouse.wheel(0, 450); cap(pg, "Raport dla analityka: JSON / CSV z zamaskowanymi identyfikatorami")
        wait(pg, 7000)

        if not video:
            pg.set_viewport_size({"width": 1440, "height": 1250})
        pg.goto(base + "graf"); settle(pg, 8000)
        cap(pg, "2/4 · Graf: kolor = kampania, obwódka = rodzina, ciągła = kampania, przerywana = rodzina")
        shot(pg, "demo/demo_2_graf.png"); shot(pg, "ui_2_graf.png"); wait(pg, 12000)
        pg.get_by_text("Krawędzie odrzucone regułą kampanii").scroll_into_view_if_needed()
        cap(pg, f"Reguła „za mało twardych dowodów”: {f['rule']} → poziom rodziny, nie kampanii"); wait(pg, 10000)
        sb = pg.locator("[data-testid=stSelectbox]").last
        sb.locator("input").click(); sb.locator("input").fill("campaign · nask:1"); pg.wait_for_timeout(500)
        pg.keyboard.press("Enter"); pg.wait_for_timeout(1200); pg.mouse.wheel(0, 300); pg.wait_for_timeout(800)
        cap(pg, f"Dlaczego 1 i 2 to jedna kampania: wspólny piksel FB, identyczne pliki, wynik {f['s12']}")
        shot(pg, "demo/demo_2b_krawedz_1_2.png"); wait(pg, 12000)

        if not video:
            pg.set_viewport_size({"width": 1440, "height": 1450})
        analyze(pg, z2, "nask:2")
        cap(pg, "3/4 · Folder 2 BEZ logu HAR, wykluczony z bazy → rozpoznana kampania mimo braków")
        pg.locator("[data-testid=stExpander] summary").nth(1).click(); pg.wait_for_timeout(1000)
        shot(pg, "demo/demo_3a_folder2_bez_har.png"); wait(pg, 14000)

        analyze(pg, z47, "nask:47")
        cap(pg, "4/4 · Folder 47 spoza bazy → nowa kampania, bez doklejania na siłę")
        pg.locator("[data-testid=stExpander] summary").nth(1).click(); pg.wait_for_timeout(1000)
        shot(pg, "demo/demo_3b_folder47_nowa.png"); wait(pg, 12000)

        if shots:
            analyze(pg, z3, None)
            pg.locator("[data-testid=stExpander] summary").nth(1).click(); pg.wait_for_timeout(800)
            shot(pg, "ui_4_analiza.png")
        cap(pg, "Każde powiązanie z przesłankami i wagami · 0 fałszywych połączeń kampanii"); wait(pg, 8000)
        vid = pg.video.path() if video else None
        ctx.close(); browser.close()
    if vid:
        out = DEMO / "IsReal_demo_zapasowe.webm"
        shutil.move(vid, out)
        print("video ->", out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shots", action="store_true", help="plan-B screenshots into docs/img/")
    ap.add_argument("--video", action="store_true", help="backup video into data/demo/ (gitignored)")
    ap.add_argument("--url", default="http://localhost:8501")
    args = ap.parse_args(argv)
    if not (args.shots or args.video):
        ap.error("choose --shots and/or --video")
    if args.shots:
        run(shots=True, video=False, url=args.url)
    if args.video:
        run(shots=False, video=True, url=args.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
