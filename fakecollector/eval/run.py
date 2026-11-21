"""`evaluate()` - run all experiments and write reports/eval_<timestamp>.md (no raw data inside)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fakecollector.core.config import make_context, resolve_path
from fakecollector.core.models import Context
from fakecollector.engine import correlate as co
from fakecollector.engine.mask import mask_text
from fakecollector.engine.features import aggregate_incidents, collect_signals, load_feature_tables, normalize_signals
from fakecollector.engine.pipeline import load_incident_index
from fakecollector.eval import experiments as ex
from fakecollector.eval import sensitivity as sens
from fakecollector.eval.metrics import load_family_labels, load_labels

log = logging.getLogger("fakecollector.eval")

METRIC_COLS = ["precision", "recall", "f1", "ari", "n_clusters"]
FAMILY_COLS = ["fam_precision", "fam_recall", "fam_f1", "fam_ari", "n_families"]


def md_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    if not rows:
        return "_brak danych_\n"
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out) + "\n"


def _kv(d: dict[str, Any]) -> str:
    return "\n".join(f"- **{k}**: {v}" for k, v in d.items()) + "\n"


def evaluate(
    ctx: Context | None = None,
    labels_path: Path | None = None,
    tables: dict | None = None,
    signals: dict | None = None,
    out_dir: Path | None = None,
    dropout_trials: int = 20,
) -> Path:
    """Run the full evaluation and return the path of the written markdown report.

    tables/signals can be injected (tests, synthetic data); by default they are read from
    data/features and the feature modules' SIGNALS.
    """
    ctx = ctx or make_context()
    cfg = co.engine_cfg(ctx.settings)
    signals = normalize_signals(signals, cfg["signal_params"], cfg["signal_class"]) if signals is not None \
        else collect_signals(cfg["signal_params"], classes=cfg["signal_class"])
    tables = tables if tables is not None else load_feature_tables(resolve_path(ctx, "features"))
    labels_path = labels_path or (ctx.repo_root / "eval" / "labels.yaml")
    truth = load_labels(labels_path)
    ftruth = load_family_labels(labels_path, truth)
    mat_to_inc, dup_mats, inc_ids = load_incident_index(resolve_path(ctx, "interim"))
    stoplist = ctx.settings.get("stoplist")
    feats = aggregate_incidents(tables, signals, stoplist, mat_to_inc, extra_ids=inc_ids)
    feats = {i: f for i, f in feats.items() if i in truth or not truth}

    out_dir = out_dir or (ctx.repo_root / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"eval_{stamp}.md"

    lines = [f"# Raport ewaluacji ({datetime.now():%Y-%m-%d %H:%M})\n"]
    lines.append("Etykiety: `" + labels_path.name + "` (robocze, niepotwierdzone przez mentorów NASK). "
                 "Raport nie zawiera treści danych, tylko identyfikatory incydentów i nazwy sygnałów.\n")
    n_labeled = len([i for i in feats if i in truth])
    lines.append(f"- Incydentów z etykietą: **{n_labeled}**, kampanii: **{len(set(truth.values()))}**\n"
                 f"- Aktywne sygnały: {', '.join(sorted(signals)) or '(brak)'}\n"
                 f"- Progi: tau_campaign={cfg['tau_campaign']}, tau_family={cfg['tau_family']}, tau_new={cfg['tau_new']}, "
                 f"min_signals={cfg['min_signals']} (kampania) / {cfg['min_signals_family']} (rodzina)\n"
                 f"- Sygnały klasy campaign: {', '.join(sorted(n for n, x in signals.items() if x['class'] == 'campaign')) or '-'}\n"
                 f"- Sygnały klasy family: {', '.join(sorted(n for n, x in signals.items() if x['class'] == 'family')) or '-'}\n")
    if n_labeled < 2 or not signals:
        lines.append("\n**Za mało danych do ewaluacji** (brak sygnałów albo incydentów z etykietą).\n")
        path.write_text(mask_text("\n".join(lines)), encoding="utf-8")
        return path

    metrics, res = ex.cluster_eval(feats, signals, cfg, truth, family_truth=ftruth)
    summary: dict[str, Any] = {
        "n_incidents": n_labeled, "n_campaigns_truth": len(set(truth.values())),
        "campaign": {k: v for k, v in metrics.items() if not k.startswith("fam_")},
        "family": {k[4:]: v for k, v in metrics.items() if k.startswith("fam_")},
        "thresholds": {k: cfg[k] for k in ("tau_campaign", "tau_family", "tau_new", "absence_discount")},
    }
    lines.append("\n## 1. Wynik bazowy\n\n**Poziom kampanii** (etykiety: " + ", ".join(
        f"{k}={'/'.join(i.split(':')[-1] for i in v)}" for k, v in _groups(truth).items() if len(v) > 1) + ")\n\n"
        + md_table([metrics], METRIC_COLS + ["tp", "fp", "fn"]))
    lines.append("\n**Poziom rodzin** (etykieta rodziny to hipoteza, niepotwierdzona: " + ", ".join(
        f"{k}={'/'.join(i.split(':')[-1] for i in v)}" for k, v in _groups(ftruth).items() if len(v) > 1) + ")\n\n"
        + md_table([{k[4:]: v for k, v in metrics.items() if k.startswith("fam_")}],
                   ["precision", "recall", "f1", "ari", "n"]))
    lines.append("\nNajsilniejsze krawędzie kampanii:\n\n" + md_table(
        ex.edge_table(res).to_dict("records"), ["a", "b", "score", "signals"]))
    lines.append("\nNajsilniejsze krawędzie rodzin:\n\n" + md_table(
        ex.edge_table(res, level="family").to_dict("records"), ["a", "b", "score", "signals"]))
    lines.append("\nKlastry:\n\n" + md_table(
        [{"kampania": c.campaign_id, "rodzina": res.family_of.get(c.campaign_id, ""), "członkowie": ", ".join(
            m.split(":")[-1] for m in c.members), "spójność": c.cohesion, "sygnały": ", ".join(c.top_signals)}
         for c in res.clusters], ["kampania", "rodzina", "członkowie", "spójność", "sygnały"]))
    err = ex.errors(res, truth)
    lines.append("\n### Błędy (poziom kampanii)\n")
    for kind, rows in err.items():
        lines.append(f"**{kind}** ({len(rows)})\n\n" + md_table(rows, ["a", "b", "score", "top_signals"]))

    abl = ex.ablation(feats, signals, cfg, truth, ftruth)
    summary["ablation"] = [{k: r[k] for k in ("variant", "f1", "ari", "fam_f1", "fam_ari")} for r in abl]
    lines.append("\n## 2. Ablacja (oba poziomy; wiersz bez shared_assets = wynik bez błędnego koła)\n" + md_table(
        abl,
        ["variant", "f1", "ari", "n_clusters", "fam_f1", "fam_ari", "n_families"]))
    lines.append("\n## 3. Progi\n\n`tau_campaign` (rośnie = mniej połączeń):\n\n" + md_table(
        ex.threshold_sweep(feats, signals, cfg, truth, ftruth, "tau_campaign"),
        ["tau_campaign"] + METRIC_COLS + ["fam_f1"]))
    lines.append("\n`tau_family`:\n\n" + md_table(
        ex.threshold_sweep(feats, signals, cfg, truth, ftruth, "tau_family", (0.2, 0.3, 0.4, 0.5, 0.6, 0.7)),
        ["tau_family", "fam_precision", "fam_recall", "fam_f1", "fam_ari", "n_families"]))
    lines.append("\n## 4. Metoda grupowania kampanii\n" + md_table(
        ex.method_comparison(feats, signals, cfg, truth), ["method"] + METRIC_COLS + ["error"]))

    parts = _material_parts(resolve_path(ctx, "interim"))
    summary["pseudo_variants"] = ex.pseudo_variants(tables, signals, stoplist, cfg, truth, parts)
    summary["dropout"] = ex.dropout(feats, signals, cfg, truth, 0.3, dropout_trials)
    summary["open_set"] = ex.open_set(feats, signals, cfg, truth, ftruth)
    lines.append("\n## 5. Pseudo-warianty (incydenty rozbite na części)\n" + _kv(summary["pseudo_variants"]))
    lines.append("\n## 6. Odporność na braki danych (losowe wyłączanie modalności)\n" + _kv(summary["dropout"]))
    lines.append("\n## 7. Open-set (nowa kampania)\n" + _kv(summary["open_set"]))
    fv = ex.family_variant_check(feats, signals, cfg, truth, ftruth)
    summary["family_variant"] = fv
    keys = ["family_precision", "family_recall", "family_f1", "family_ari", "n_families", "n_family_edges",
            "loco_new_rate", "loco_family_hit_rate", "singleton_new_rate", "loo_assign_accuracy"]
    lines.append("\n## 7a. Wariant „sygnały family tylko na plus”\n\n"
                 "Sygnał family poniżej własnego floor traktowany jako brak danych, a nie jako 0 w średniej "
                 "(słaby dowód nie obniża wyniku). Poziom kampanii bez zmian.\n\n"
                 + md_table([{"wariant": n, **{k: fv[n][k] for k in keys}} for n in ("current", "positive_only")], ["wariant"] + keys)
                 + "\nWarunki przyjęcia wariantu: " + ", ".join(f"{k}={'OK' if v else 'NIE'}" for k, v in fv["conditions"].items())
                 + f"\n\n**Wszystkie warunki spełnione: {'TAK' if fv['conditions_met'] else 'NIE'}**. "
                 f"Fałszywe krawędzie rodzin: obecny {fv['current']['false_family_edges'] or 'brak'}, "
                 f"wariant {fv['positive_only']['false_family_edges'] or 'brak'}. "
                 f"Domyślnie w tym przebiegu: `family_positive_only={cfg.get('family_positive_only')}`.\n")
    lines.append("\n## 8. Czułość wag (każda waga ±50%, pojedynczo)\n\n"
                 "Zmiana F1 względem wyniku bazowego. Wiersz z zerami = ta waga nie rozstrzyga o grupowaniu na tych próbkach.\n\n"
                 + md_table(sens.weight_sensitivity(feats, signals, cfg, truth, ftruth),
                            ["signal", "class", "w", "dF1_camp x0.5", "dF1_camp x1.5", "dF1_fam x0.5", "dF1_fam x1.5", "max_abs_dF1"]))
    check = sens.logistic_check(feats, signals, cfg, truth, ftruth)
    lines.append("\n## 9. Regresja logistyczna (tylko informacyjnie)\n\n"
                 f"Pary incydentów: {check['n_pairs']}; pary tej samej kampanii: {check['levels']['campaign'].get('n_pos')}, "
                 f"tej samej rodziny: {check['levels']['family'].get('n_pos')}. To za mało, żeby uczyć wagi, więc wagi ręczne "
                 "zostają. Współczynnik dodatni = sygnał pomaga odróżnić „to samo\" od „różne\" (potwierdza kierunek wagi); "
                 "wartości nie są porównywalne z wagami ani między poziomami.\n\n"
                 + md_table(sens.direction_table(check, signals, cfg), ["signal", "class", "w", "coef_campaign", "coef_family"]))
    lines.append("\n## Konfiguracja wag\n```json\n" +
                 json.dumps(cfg["weights"], indent=1, ensure_ascii=False) + "\n```\n")
    path.write_text(mask_text("\n".join(lines)), encoding="utf-8")
    # the same numbers as data (read by scripts/reference_run.py); numbers and ids only
    path.with_suffix(".json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("evaluation report written to %s", path)
    return path


def _groups(labels: dict[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for inc, lab in sorted(labels.items()):
        out.setdefault(lab, []).append(inc)
    return out


def _material_parts(interim_dir: Path) -> dict[str, str]:
    """material_id -> part it belongs to: an HTML page (assets map to their parent page), or the
    single part "creative" for all stand-alone ad screenshots/videos of an incident."""
    jsonl = interim_dir / "incidents.jsonl"
    if not jsonl.exists():
        return {}
    parts: dict[str, str] = {}
    try:
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for m in json.loads(line).get("materials") or []:
                if m.get("parent_html"):
                    parts[m["material_id"]] = m["parent_html"]
                elif m.get("kind") in ("html", "mhtml"):
                    parts[m["material_id"]] = m["material_id"]
                else:
                    parts[m["material_id"]] = f"creative:{json.loads(line).get('incident_id')}"
    except Exception as exc:
        log.warning("cannot read material parts: %s", exc)
    return parts
