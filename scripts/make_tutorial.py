#!/usr/bin/env python3
"""Tutorial video for the submission: title card + demo recording + results card (owner: W3).

    python scripts/make_tutorial.py                       # record + assemble
    python scripts/make_tutorial.py --reuse-recording     # only re-assemble from the last recording

Steps:
  1. runs `scripts/demo_capture.py --video` (W1; public mode, Polish step captions computed from this
     machine's data/graph) and timestamps its output, so the recorded warm-up analysis (it only loads
     the models) can be cut from the start of the recording;
  2. draws the title and the results card with Pillow (1440x900, same size as the recording);
  3. joins card + recording + card with ffmpeg (imageio-ffmpeg binary) into an H.264 MP4.

Output: data/demo/IsReal_tutorial.mp4 (gitignored, never committed). Frames for review are written to
data/demo/tutorial_frames/ (one every --frame-every seconds).
Dev-only dependencies, not in requirements: playwright (+ Chrome), imageio-ffmpeg.
Streamlit must already run on localhost:8501 with the NASK data (see docs/DEMO_SCRIPT.md).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"
W, H, FPS = 1440, 900, 25

TITLE = "IsReal? — od pojedynczej reklamy do całej kampanii oszustów"
TITLE_SUB = ["Zadanie NASK „Kolekcjoner fejków / Follow the Fake” · HackNation 2026",
             "Tutorial: kampanie i rodziny → graf powiązań → analiza nowego materiału"]
RESULTS_HEAD = "Wyniki"
RESULTS = [
    "Kampanie: 100% precyzji · 0 fałszywych połączeń",
    "Nowe kampanie rozpoznane w 100%",
    "Test na 300 obcych stronach phishingowych: 96% precyzji par",
]
RESULTS_FOOT = "Analiza statyczna, offline · każde powiązanie z przesłankami i wagami"
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts")]


def font(bold: bool, size: int):
    from PIL import ImageFont
    names = (["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    for d in FONT_DIRS:
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default()


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if draw.textlength(cand, font=fnt) <= max_w:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def card(path: Path, head: str, lines: list[str], foot: str | None, big_head: bool) -> Path:
    """White card in the app's style: dark heading, red accent bar, grey sub-lines."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_head = font(True, 64 if big_head else 58)
    f_line = font(not big_head, 34 if big_head else 40)
    f_foot = font(False, 26)
    y = 230 if big_head else 190
    for ln in wrap(d, head, f_head, W - 240):
        d.text((120, y), ln, font=f_head, fill=(38, 39, 48))
        y += 84
    d.rectangle([120, y + 18, 300, y + 26], fill=(196, 52, 42))
    y += 70
    for text in lines:
        for ln in wrap(d, text, f_line, W - 240):
            d.text((120, y), ln, font=f_line, fill=(90, 90, 100) if big_head else (38, 39, 48))
            y += 54 if big_head else 62
        y += 6 if big_head else 14
    if foot:
        d.text((120, H - 120), foot, font=f_foot, fill=(130, 130, 140))
    img.save(path)
    return path


def record(url: str) -> tuple[Path, float]:
    """Run demo_capture --video; return (recording, seconds of warm-up to cut)."""
    cmd = [sys.executable, "-u", str(ROOT / "scripts" / "demo_capture.py"), "--video", "--url", url]
    t_page = t_warm = None
    with subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace") as proc:
        for line in proc.stdout:
            now = time.time()
            print("  [capture]", line.rstrip(), flush=True)
            if line.startswith("warm-up") and t_page is None:
                t_page = now                          # printed right after the recorded page opens
            elif "excl=nask:47" in line and t_page is not None and t_warm is None:
                t_warm = now                          # warm-up analysis finished
    if proc.returncode != 0:
        raise SystemExit(f"demo_capture.py --video failed (exit {proc.returncode})")
    rec = DEMO / "IsReal_demo_zapasowe.webm"
    cut = max(0.0, (t_warm - t_page) + 1.0) if t_page and t_warm else 0.0
    (DEMO / "tutorial_cut.txt").write_text(f"{cut:.2f}", encoding="utf-8")
    return rec, cut


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(path: Path) -> float:
    out = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def assemble(rec: Path, cut: float, title_png: Path, end_png: Path, out: Path,
             title_s: float, end_s: float) -> None:
    norm = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:white," \
           f"fps={FPS},format=yuv420p,setsar=1"
    rec_len = max(1.0, duration(rec) - cut)
    filt = (f"[0:v]{norm},fade=t=in:st=0:d=0.6,fade=t=out:st={title_s - 0.6}:d=0.6[t];"
            f"[1:v]{norm},fade=t=in:st=0:d=0.5[r];"
            f"[2:v]{norm},fade=t=in:st=0:d=0.6,fade=t=out:st={end_s - 0.8}:d=0.8[e];"
            f"[t][r][e]concat=n=3:v=1:a=0[v]")
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
           "-loop", "1", "-t", f"{title_s}", "-i", str(title_png),
           "-ss", f"{cut:.2f}", "-t", f"{rec_len:.2f}", "-i", str(rec),
           "-loop", "1", "-t", f"{end_s}", "-i", str(end_png),
           "-filter_complex", filt, "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def frames(video: Path, every: float) -> Path:
    fdir = DEMO / "tutorial_frames"
    fdir.mkdir(parents=True, exist_ok=True)
    for old in fdir.glob("*.png"):
        old.unlink()
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                    "-vf", f"fps=1/{every}", str(fdir / "f_%03d.png")], check=True)
    return fdir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://localhost:8501", help="Streamlit address (public mode is set by demo_capture)")
    ap.add_argument("--reuse-recording", action="store_true", help="skip recording, use the last one")
    ap.add_argument("--title-s", type=float, default=6.0)
    ap.add_argument("--end-s", type=float, default=10.0)
    ap.add_argument("--frame-every", type=float, default=10.0)
    ap.add_argument("--out", default=str(DEMO / "IsReal_tutorial.mp4"))
    args = ap.parse_args(argv)
    DEMO.mkdir(parents=True, exist_ok=True)

    if args.reuse_recording:
        rec = DEMO / "IsReal_demo_zapasowe.webm"
        cut_file = DEMO / "tutorial_cut.txt"
        cut = float(cut_file.read_text()) if cut_file.exists() else 0.0
    else:
        rec, cut = record(args.url)
    if not rec.exists():
        print(f"recording not found: {rec}", file=sys.stderr)
        return 1
    title_png = card(DEMO / "tutorial_title.png", TITLE, TITLE_SUB, None, big_head=True)
    end_png = card(DEMO / "tutorial_end.png", RESULTS_HEAD, RESULTS, RESULTS_FOOT, big_head=False)
    out = Path(args.out)
    assemble(rec, cut, title_png, end_png, out, args.title_s, args.end_s)
    total = duration(out)
    fdir = frames(out, args.frame_every)
    print(f"tutorial -> {out}  ({int(total // 60)}:{total % 60:04.1f}, warm-up cut {cut:.1f} s)")
    print(f"review frames -> {fdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
