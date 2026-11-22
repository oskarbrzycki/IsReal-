#!/usr/bin/env python3
"""Tutorial video for the submission, from ONE clean screen recording of the UI (owner: W3).

    python scripts/make_tutorial.py                     # record + post-produce both videos
    python scripts/make_tutorial.py --post-only         # re-render from data/demo/scenes.json + its raw video

1. Recording (Playwright + Chrome, public mode, no overlays in the page): every step of the tutorial is a
   segment in data/demo/scenes.json with start/end (seconds in the raw video), the highlighted element's
   bounding box in video pixels, and the caption. Numbers in captions are read from the screen; if they
   differ from the expected wording, the caption uses the on-screen value and the difference is listed
   under "discrepancies". Waiting for an analysis result is a "wait" segment (sped up 4x later).
   Segment types: skip (cut), transition (kept, long ones sped up), scene (spotlight + caption), wait.
2. Post-production (ffmpeg from imageio-ffmpeg, libass):
     data/demo/IsReal_tutorial_final.mp4  spotlight (outside the box darkened, 5 px #E5484D frame),
                                          ASS captions at the bottom, waits 4x with a caption, title/results cards
     data/demo/IsReal_tutorial_basic.mp4  same cut and cards, no spotlight and no captions
   Both H.264 1440x900, 25 fps, outside the repo (data/ is gitignored). Review frames every 5 s are written
   to data/demo/tutorial_frames/.

Dev-only dependencies, not in requirements: playwright (+ Google Chrome), imageio-ffmpeg.
Prerequisite: `streamlit run ui/app.py` on localhost:8501 with the NASK data, models warmed up by one
analysis, demo zips in data/demo/ (scripts/demo_cases.py). The UI itself is not modified.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"
LOGO = ROOT / "ui" / "assets" / "logo.png"
W, H, FPS = 1440, 900, 25
ROW_H, HEAD_H = 35, 35                     # st.dataframe (glide grid) row / header height in px
STATUS_JS = "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')"

TITLE = "IsReal? — od pojedynczej reklamy do całej kampanii oszustów"
TITLE_SUB = "Zadanie NASK · HackNation 2026"
RESULTS = ["Kampanie: 100% precyzji, 0 fałszywych połączeń",
           "Nowe kampanie rozpoznane w 100%",
           "300 obcych stron phishingowych: 96% precyzji par",
           "Offline, Docker, otwarte licencje"]
WAIT_CAPTION = "Analiza… (przyspieszone 4×)"
ACCENT, CAPTION_BG = "E5484D", "0F172A"


# =============================================================================== recording
class Recorder:
    def __init__(self, page, base: float, per12: float):
        self.pg, self.base, self.per12 = page, base, per12
        self.t0 = time.monotonic()
        self.segments: list[dict] = []
        self.cursor = 0.0
        self.values: dict = {}
        self.discrepancies: list[dict] = []

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def close(self, kind: str, **extra) -> None:
        """Close the segment that started at the cursor and ends now."""
        end = self.now()
        if end - self.cursor > 0.05:
            self.segments.append({"type": kind, "start": self.cursor, "end": end, **extra})
        self.cursor = end

    def settle(self, ms: int = 1200) -> None:
        self.pg.wait_for_function(STATUS_JS, timeout=300000)
        self.pg.wait_for_timeout(ms)
        self.pg.wait_for_function(STATUS_JS, timeout=300000)

    def center(self, locator) -> None:
        locator.evaluate("e => e.scrollIntoView({block: 'center', inline: 'nearest'})")
        self.pg.wait_for_timeout(700)

    def scene(self, name: str, caption: str, box: dict) -> None:
        self.close("transition")
        words = len(caption.split())
        dur = self.base + self.per12 * words / 12.0
        self.pg.wait_for_timeout(int(dur * 1000))
        self.close("scene", name=name, caption=caption, box=box)

    def check(self, key: str, expected, on_screen, caption: str) -> str:
        """Record an on-screen value; if it differs, put the on-screen value into the caption."""
        self.values[key] = on_screen
        if str(expected) != str(on_screen):
            self.discrepancies.append({"value": key, "expected": expected, "on_screen": on_screen})
            caption = caption.replace(str(expected), str(on_screen))
        return caption


def union(*boxes: dict, pad: int = 8) -> dict:
    x0 = min(b["x"] for b in boxes) - pad
    y0 = min(b["y"] for b in boxes) - pad
    x1 = max(b["x"] + b["width"] for b in boxes) + pad
    y1 = max(b["y"] + b["height"] for b in boxes) + pad
    x0, y0 = max(6, int(x0)), max(6, int(y0))
    x1, y1 = min(W - 6, int(x1)), min(H - 6, int(y1))
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def grid_rows(df) -> list[str]:
    """Texts of data rows of a st.dataframe (ARIA rows of the glide grid; row 0 = header)."""
    rows = df.locator("[role=row]")
    return [rows.nth(i).inner_text().replace("\n", " ") for i in range(1, rows.count())]


def rows_box(df, idx: list[int]) -> dict:
    b = df.bounding_box()
    top = b["y"] + 1 + HEAD_H + ROW_H * min(idx)
    return {"x": b["x"], "y": top, "width": b["width"], "height": ROW_H * (max(idx) - min(idx) + 1)}


def metric(pg, label: str):
    return pg.locator("[data-testid=stMetric]").filter(has_text=label).first


def analyze(r: Recorder, url: str, zip_path: Path, exclude: str, fresh: bool) -> None:
    """Open the analysis view (tab click, or a fresh load = clean widget state), exclude, upload, run."""
    pg = r.pg
    demo_toggle = "text=Tryb demo: wyklucz incydenty z bazy"
    if not fresh:
        r.settle(800)                       # a click during a running rerun is ignored by Streamlit
        tab = pg.locator("[data-testid=stButtonGroup] button").filter(has_text="Analiza nowego materiału").first
        for attempt in range(2):
            tab.scroll_into_view_if_needed(); tab.click()
            try:
                pg.wait_for_selector(demo_toggle, timeout=8000)
                break
            except Exception:
                r.settle(500)
        else:
            pg.screenshot(path=str(DEMO / "tutorial_debug_tab.png"))
            print("  tab click did not open the analysis view (debug: data/demo/tutorial_debug_tab.png); "
                  "loading it directly", flush=True)
            fresh = True
    if fresh:
        pg.goto(url.rstrip("/") + "/?public=1&present=0&tab=analiza")
    pg.wait_for_selector(demo_toggle, timeout=120000); r.settle(800)
    pg.get_by_text("Tryb demo: wyklucz incydenty z bazy").click(); pg.wait_for_timeout(800)
    ms = pg.locator("[data-testid=stMultiSelect]")
    ms.locator("input").fill(exclude); pg.wait_for_timeout(600)
    pg.keyboard.press("Enter"); pg.keyboard.press("Escape"); pg.wait_for_timeout(900)
    pg.set_input_files("input[type=file]", str(zip_path)); pg.wait_for_timeout(2500)
    pg.get_by_role("button", name="Analizuj").click()
    r.close("transition")
    pg.wait_for_selector("text=Czas analizy", timeout=300000)
    r.settle(600)
    r.close("wait", name=f"analysis {zip_path.name}")


def record(url: str, base: float, per12: float) -> Path:
    from playwright.sync_api import sync_playwright

    z2, z47 = DEMO / "folder2_bez_har.zip", DEMO / "folder47.zip"
    for z in (z2, z47):
        if not z.exists():
            raise SystemExit(f"missing {z} - run scripts/demo_cases.py first")
    tmp = DEMO / "rec_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    q = url.rstrip("/") + "/?public=1&present=0&tab="
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                  record_video_size={"width": W, "height": H})
        pg = ctx.new_page()
        r = Recorder(pg, base, per12)

        # ---- campaigns view (initial load is cut)
        pg.goto(q + "kampanie")
        pg.wait_for_selector("text=Pojedyncze zgłoszenia", timeout=120000)
        pg.wait_for_selector("[data-testid=stDataFrame] [role=row]", state="attached", timeout=120000)
        r.settle(2500)
        r.close("skip")

        multi = metric(pg, "Kampanie wieloincydentowe")
        single = metric(pg, "Pojedyncze zgłoszenia")
        n_inc = metric(pg, "Incydenty").locator("[data-testid=stMetricValue]").inner_text().strip()
        n_multi = multi.locator("[data-testid=stMetricValue]").inner_text().strip()
        n_single = single.locator("[data-testid=stMetricValue]").inner_text().strip()
        cap = "Z 10 zgłoszeń system połączył 2 kampanie (po 2 zgłoszenia). Pozostałe 6 nie ma twardych powiązań, więc zostają osobno."
        cap = r.check("incydenty", "Z 10", f"Z {n_inc}", cap)
        cap = r.check("kampanie_wieloincydentowe", "połączył 2", f"połączył {n_multi}", cap)
        cap = r.check("pojedyncze", "Pozostałe 6", f"Pozostałe {n_single}", cap)
        r.scene("1 karty", cap, union(multi.bounding_box(), single.bounding_box()))

        df = pg.locator("[data-testid=stDataFrame]").first
        rows = grid_rows(df)
        idx_c = [i for i, t in enumerate(rows) if re.search(r"\bC00[12]\b", t)]
        sizes = [int(m.group(1)) for t in rows for m in [re.search(r"C00[12]-?(\d+)nask", t)] if m]
        cap = "Kampania = ta sama akcja oszusta, połączona twardym dowodem: wspólny piksel albo identyczne pliki."
        r.values["c001_c002_rows"] = idx_c
        r.scene("2 kampanie C001 C002", cap, union(rows_box(df, idx_c), pad=2))

        idx_f = [i for i, t in enumerate(rows) if t.startswith("F001")]
        n_f001 = sum(int(m.group(1)) for t in rows if t.startswith("F001")
                     for m in [re.search(r"C\d{3}-?(\d+)nask", t)] if m)
        cap = ("Rodzina = różne akcje prawdopodobnie tego samego oszusta: wspólny szablon linków, CSS "
               "i te same podrabiane twarze (5 zgłoszeń).")
        cap = r.check("rodzina_F001_zgloszen", "(5 zgłoszeń)", f"({n_f001} zgłoszeń)", cap)
        r.values["campaign_sizes"] = sizes
        r.scene("3 rodzina F001", cap, union(rows_box(df, idx_f), pad=2))

        # ---- graph
        pg.locator("[data-testid=stButtonGroup] button").filter(has_text="Graf powiązań").first.click()
        frame = pg.locator("iframe").first
        frame.wait_for(timeout=120000); r.settle(1000)
        r.center(frame); pg.wait_for_timeout(6000)              # let the physics layout settle
        n_nodes = pg.evaluate("() => { try { return document.querySelector('iframe').contentWindow"
                              ".network.body.data.nodes.length } catch (e) { return null } }")
        r.values["graph_nodes"] = n_nodes
        cap = "Graf powiązań: kropki to zgłoszenia, linie to połączenia z uzasadnieniem."
        r.scene("4 graf", cap, union(frame.bounding_box(), pad=4))

        alert = pg.locator("[data-testid=stAlert]").filter(has_text="za mało twardych dowodów").first
        r.center(alert)
        head = pg.get_by_text(re.compile(r"Krawędzie odrzucone regułą kampanii")).first
        rule_txt = alert.inner_text()
        pair = re.search(r"nask:(\d+)\s*\S\s*nask:(\d+)", rule_txt)
        pair_s = f"{pair.group(1)}–{pair.group(2)}" if pair else "?"
        cap = ("Połączenie 1–3 odrzucone: sama wspólna nazwa platformy to za mało. "
               "Kampanie łączymy tylko na twardych dowodach.")
        cap = r.check("krawedz_odrzucona", "1–3", pair_s, cap)
        if "same_platform_name" not in rule_txt:
            r.discrepancies.append({"value": "powod_odrzucenia", "expected": "same_platform_name",
                                    "on_screen": rule_txt[:160]})
        r.scene("5 krawedz odrzucona", cap, union(head.bounding_box(), alert.bounding_box()))

        sb = pg.locator("[data-testid=stSelectbox]").last
        chosen = sb.locator("input").input_value() or sb.inner_text()      # selected option, not the label
        if not ("campaign" in chosen and "nask:1" in chosen and "nask:2" in chosen):
            sb.locator("input").click(); sb.locator("input").fill("campaign · nask:1")
            pg.wait_for_timeout(500); pg.keyboard.press("Enter"); r.settle(800)
        r.values["edge_selected"] = chosen
        rdf = pg.locator("[data-testid=stDataFrame]").last
        r.center(rdf)
        rrows = grid_rows(rdf)
        idx_r = [i for i, t in enumerate(rrows) if ("piksel" in t or "identyczne pliki" in t)]
        files = next((t for t in rrows if "identyczne pliki" in t), "")
        m = re.search(r"\(sha1\):\s*(.*?)\s*\(\+(\d+)\)", files)
        n_files = (len(m.group(1).split(",")) + int(m.group(2))) if m else None
        cap = "Dlaczego 1 i 2 to jedna kampania? Ten sam piksel Facebooka i 17 identycznych plików na stronach z różnych domen."
        cap = r.check("identyczne_pliki_1_2", "17", n_files, cap)
        r.scene("6 krawedz 1-2", cap, union(rows_box(rdf, idx_r), pad=2))

        # ---- analysis (a): folder 2 without HAR, nask:2 excluded
        analyze(r, url, z2, "nask:2", fresh=False)
        res = pg.get_by_role("heading", name=re.compile(r"Znana kampania|Nowa kampania")).first
        r.center(res)
        expl = pg.locator("[data-testid=stMarkdownContainer]").filter(has_text="wspólne ślady").last
        hdr = res.inner_text().strip()
        camp = re.search(r"C\d{3}", hdr)
        cap = ("Nowe zgłoszenie, nawet bez logu sieciowego: system rozpoznaje znaną kampanię C001 "
               "i pokazuje dowody.")
        cap = r.check("wynik_a", "C001", camp.group(0) if camp else hdr, cap)
        r.scene("7 analiza folder2 bez HAR", cap, union(res.bounding_box(), expl.bounding_box()))

        # ---- analysis (b): folder 47, nask:47 excluded
        analyze(r, url, z47, "nask:47", fresh=True)
        res = pg.get_by_role("heading", name=re.compile(r"Nowa kampania|Znana kampania")).first
        r.center(res)
        expl = pg.locator("[data-testid=stMarkdownContainer]").filter(has_text="próg").last
        pct = re.findall(r"(\d+)%", expl.inner_text())
        cap = ("Zgłoszenie spoza bazy: najbliższe znane pasuje tylko w 23% (próg 35%). "
               "System nie dokleja na siłę, oznacza je jako nową kampanię.")
        if len(pct) >= 2:
            cap = r.check("sasiad_b", "23%", f"{pct[0]}%", cap)
            cap = r.check("prog_nowej", "35%", f"{pct[1]}%", cap)
        cap = r.check("wynik_b", "Nowa kampania", res.inner_text().strip(), cap) if "Nowa kampania" not in res.inner_text() else cap
        r.scene("8 analiza folder47", cap, union(res.bounding_box(), expl.bounding_box()))
        pg.wait_for_timeout(500)
        r.close("skip")

        vid = pg.video.path()
        ctx.close(); browser.close()

    ts = time.strftime("%Y%m%d_%H%M%S")
    raw = DEMO / f"raw_{ts}.webm"
    shutil.move(vid, raw)
    shutil.rmtree(tmp, ignore_errors=True)
    meta = {"raw": raw.name, "size": [W, H], "recorded": ts, "scene_timing": {"base_s": base, "per_12_words_s": per12},
            "segments": r.segments, "values": r.values, "discrepancies": r.discrepancies}
    (DEMO / "scenes.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"raw -> {raw}\nscenes -> {DEMO / 'scenes.json'}")
    for d in r.discrepancies:
        print("  discrepancy:", d)
    return DEMO / "scenes.json"


# =============================================================================== cards
def font(bold: bool, size: int):
    from PIL import ImageFont
    names = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
    for d in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts")):
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default()


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if draw.textlength(cand, font=fnt) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def cards() -> tuple[Path, Path]:
    from PIL import Image, ImageDraw
    logo = Image.open(LOGO).convert("RGB")
    bg = logo.getpixel((2, 2))
    # title card: logo, title, subtitle
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    lw = 560
    lg = logo.resize((lw, int(logo.height * lw / logo.width)))
    img.paste(lg, ((W - lw) // 2, 190))
    f_t, f_s = font(True, 50), font(False, 32)
    y = 190 + lg.height + 70
    for ln in wrap(d, TITLE, f_t, W - 240):
        d.text(((W - d.textlength(ln, font=f_t)) / 2, y), ln, font=f_t, fill=(245, 245, 243))
        y += 66
    d.rectangle([(W - 140) // 2, y + 18, (W + 140) // 2, y + 24], fill=tuple(int(ACCENT[i:i + 2], 16) for i in (0, 2, 4)))
    d.text(((W - d.textlength(TITLE_SUB, font=f_s)) / 2, y + 50), TITLE_SUB, font=f_s, fill=(160, 163, 172))
    title = DEMO / "tutorial_title.png"
    img.save(title)
    # results card
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    small = logo.resize((300, int(logo.height * 300 / logo.width)))
    img.paste(small, (120, 90))
    f_h, f_l = font(True, 56), font(True, 40)
    d.text((120, 230), "Wyniki", font=f_h, fill=(245, 245, 243))
    d.rectangle([120, 310, 260, 316], fill=tuple(int(ACCENT[i:i + 2], 16) for i in (0, 2, 4)))
    y = 370
    for item in RESULTS:
        d.ellipse([124, y + 18, 140, y + 34], fill=tuple(int(ACCENT[i:i + 2], 16) for i in (0, 2, 4)))
        d.text((170, y), item, font=f_l, fill=(245, 245, 243))
        y += 92
    end = DEMO / "tutorial_end.png"
    img.save(end)
    return title, end


# =============================================================================== post-production
def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, cwd=cwd)


def duration(path: Path) -> float:
    out = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def clip(raw: Path, seg: dict, speed: float, spotlight: bool, out: Path) -> float:
    vf = [f"setpts=(PTS-STARTPTS)/{speed}", f"fps={FPS}", f"scale={W}:{H}"]
    chain = ",".join(vf)
    if spotlight and seg.get("box"):
        b = seg["box"]
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        flt = (f"[0:v]{chain},split[a][b];[a]colorchannelmixer=rr=0.45:gg=0.45:bb=0.45[dk];"
               f"[b]crop={w}:{h}:{x}:{y}[hi];[dk][hi]overlay={x}:{y},"
               f"drawbox=x={x - 5}:y={y - 5}:w={w + 10}:h={h + 10}:color=0x{ACCENT}@1:t=5[v]")
    else:
        flt = f"[0:v]{chain}[v]"
    run(["-ss", f"{seg['start']:.3f}", "-to", f"{seg['end']:.3f}", "-i", str(raw),
         "-filter_complex", flt, "-map", "[v]", "-an", *ENC, str(out)])
    return duration(out)


def card_clip(png: Path, secs: float, out: Path) -> float:
    run(["-loop", "1", "-t", f"{secs}", "-i", str(png), "-vf",
         f"fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.5,fade=t=out:st={secs - 0.6}:d=0.6", "-an", *ENC, str(out)])
    return secs


def ass_time(t: float) -> str:
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ass_file(events: list[tuple[float, float, str]], path: Path) -> None:
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    bg = "&H00" + CAPTION_BG[4:6] + CAPTION_BG[2:4] + CAPTION_BG[0:2]
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,Segoe UI,32,&H00FFFFFF,&H00FFFFFF,{bg},{bg},-1,0,0,0,100,100,0,0,3,14,0,2,90,90,34,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    for start, end, text in events:
        size, rows = 32, []
        while size >= 26:                                   # max 2 lines
            rows = wrap(d, text, font(True, size), W - 2 * 90 - 2 * 14 - 20)
            if len(rows) <= 2:
                break
            size -= 2
        txt = ("{\\fs%d}" % size if size != 32 else "") + "\\N".join(rows)
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{txt}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def post(scenes_json: Path, title_s: float, end_s: float, wait_speed: float, max_transition: float) -> dict:
    meta = json.loads(scenes_json.read_text(encoding="utf-8"))
    raw = DEMO / meta["raw"]
    work = DEMO / "tutorial_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    title_png, end_png = cards()
    fonts = work / "fonts"
    fonts.mkdir()
    for n in ("segoeui.ttf", "segoeuib.ttf"):
        if (Path("C:/Windows/Fonts") / n).exists():
            shutil.copy(Path("C:/Windows/Fonts") / n, fonts / n)

    results = {}
    for variant in ("final", "basic"):
        parts, events, t = [], [], 0.0
        p = work / f"{variant}_000_title.mp4"
        t += card_clip(title_png, title_s, p); parts.append(p)
        timeline = []
        for i, seg in enumerate(meta["segments"]):
            if seg["type"] == "skip":
                continue
            dur = seg["end"] - seg["start"]
            speed = (wait_speed if seg["type"] == "wait"
                     else max(1.0, dur / max_transition) if seg["type"] == "transition" else 1.0)
            out = work / f"{variant}_{i + 1:03d}_{seg['type']}.mp4"
            d = clip(raw, seg, speed, spotlight=(variant == "final" and seg["type"] == "scene"), out=out)
            parts.append(out)
            if variant == "final" and seg["type"] == "scene":
                events.append((t + 0.15, t + d - 0.1, seg["caption"]))
            if variant == "final" and seg["type"] == "wait":
                events.append((t, t + d, WAIT_CAPTION))
            timeline.append({"type": seg["type"], "name": seg.get("name", ""), "start": round(t, 2),
                             "end": round(t + d, 2), "speed": round(speed, 2)})
            t += d
        p = work / f"{variant}_999_end.mp4"
        t += card_clip(end_png, end_s, p); parts.append(p)
        lst = work / f"{variant}_list.txt"
        lst.write_text("".join(f"file '{x.name}'\n" for x in parts), encoding="utf-8")
        joined = work / f"{variant}_joined.mp4"
        run(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", joined.name], cwd=work)
        out = DEMO / f"IsReal_tutorial_{variant}.mp4"
        if variant == "final":
            ass_file(events, work / "captions.ass")
            run(["-i", joined.name, "-vf", "subtitles=captions.ass:fontsdir=fonts", "-an", *ENC,
                 "-movflags", "+faststart", str(out)], cwd=work)
        else:
            run(["-i", joined.name, "-c", "copy", "-movflags", "+faststart", str(out)], cwd=work)
        results[variant] = {"path": str(out), "seconds": round(duration(out), 1),
                            "timeline": [{"type": "card", "name": "title", "start": 0, "end": title_s}] + timeline +
                                        [{"type": "card", "name": "results", "start": round(t - end_s, 2), "end": round(t, 2)}]}
    (DEMO / "tutorial_timeline.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return results


def frames(video: Path, every: float) -> Path:
    fdir = DEMO / "tutorial_frames" / video.stem
    shutil.rmtree(fdir, ignore_errors=True)
    fdir.mkdir(parents=True)
    run(["-i", str(video), "-vf", f"fps=1/{every}", str(fdir / "f_%03d.png")])
    return fdir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--post-only", action="store_true", help="skip recording, re-render from data/demo/scenes.json")
    ap.add_argument("--scene-base", type=float, default=4.0, help="seconds per scene before reading time")
    ap.add_argument("--per-12-words", type=float, default=1.0, help="extra seconds per 12 caption words")
    ap.add_argument("--title-s", type=float, default=5.0)
    ap.add_argument("--end-s", type=float, default=8.0)
    ap.add_argument("--wait-speed", type=float, default=4.0)
    ap.add_argument("--max-transition", type=float, default=4.0, help="longer transitions are sped up to this")
    ap.add_argument("--frame-every", type=float, default=5.0)
    args = ap.parse_args(argv)
    DEMO.mkdir(parents=True, exist_ok=True)
    scenes = DEMO / "scenes.json" if args.post_only else record(args.url, args.scene_base, args.per_12_words)
    res = post(scenes, args.title_s, args.end_s, args.wait_speed, args.max_transition)
    for v, r in res.items():
        fdir = frames(Path(r["path"]), args.frame_every)
        print(f"{v}: {r['path']}  {int(r['seconds'] // 60)}:{r['seconds'] % 60:04.1f}  frames -> {fdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
