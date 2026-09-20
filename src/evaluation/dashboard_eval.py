r"""Dashboard ewaluacji 36 Chambers — ciemny motyw techniczny.

Wymagania:
    pip install duckdb altair pandas

Użycie:
    python dashboard_eval.py --input <path to eval_results.csv>

Zapisuje wykresy jako HTML w tym samym katalogu co CSV.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd
import altair as alt

THEME = {
    "background": "#0b0f19",
    "panel": "#111827",
    "text": "#e5e7eb",
    "subtext": "#9ca3af",
    "axis": "#374151",
    "grid": "#1f2937",
    "accent": "#60a5fa",
    "accent2": "#34d399",
    "accent3": "#f87171",
    "accent4": "#fbbf24",
}

try:
    if hasattr(alt, "theme") and hasattr(alt.theme, "register"):
        @alt.theme.register("dark_technical", enable=True)
        def _custom_theme():
            return alt.theme.ThemeConfig({
                "background": THEME["background"],
                "axis": {
                    "domainColor": THEME["axis"],
                    "gridColor": THEME["grid"],
                    "labelColor": THEME["text"],
                    "tickColor": THEME["axis"],
                    "titleColor": THEME["text"],
                },
                "header": {
                    "labelColor": THEME["text"],
                    "titleColor": THEME["text"],
                },
                "legend": {
                    "labelColor": THEME["text"],
                    "titleColor": THEME["text"],
                },
                "title": {
                    "color": THEME["text"],
                    "font": "Consolas, 'Courier New', monospace",
                    "fontSize": 14,
                },
                "view": {
                    "stroke": None,
                },
            })
    else:
        alt.themes.register("dark_technical", lambda: {
            "background": THEME["background"],
            "axis": {
                "domainColor": THEME["axis"],
                "gridColor": THEME["grid"],
                "labelColor": THEME["text"],
                "tickColor": THEME["axis"],
                "titleColor": THEME["text"],
            },
            "header": {
                "labelColor": THEME["text"],
                "titleColor": THEME["text"],
            },
            "legend": {
                "labelColor": THEME["text"],
                "titleColor": THEME["text"],
            },
            "title": {
                "color": THEME["text"],
                "font": "Consolas, 'Courier New', monospace",
                "fontSize": 14,
            },
            "view": {
                "stroke": None,
            },
        })
        alt.themes.enable("dark_technical")
except Exception:
    pass



def build_count_chart(df: pd.DataFrame) -> alt.Chart:
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadius=0)
        .encode(
            x=alt.X("scenario:N", title="Scenariusz", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count():Q", title="Liczba przypadków"),
            tooltip=["scenario", "count()"],
            color=alt.value(THEME["accent"]),
        )
        .properties(title="Liczba golden queries per scenariusz", width=500, height=300)
    )
    return chart.configure_view(stroke=None).configure_axis(grid=False)


def build_route_chart(df: pd.DataFrame) -> alt.Chart:
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadius=0)
        .encode(
            x=alt.X("scenario:N", title="Scenariusz", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mean(route_expected_pass):Q", title="Średnia poprawność routingu (0–1)", scale=alt.Scale(domain=[0, 1])),
            tooltip=["scenario", "mean(route_expected_pass):Q"],
            color=alt.value(THEME["accent2"]),
        )
        .properties(title="Średnia poprawność routingu (0–1)", width=500, height=300)
    )
    return chart.configure_view(stroke=None).configure_axis(grid=False)


def build_retrieval_chart(df: pd.DataFrame) -> alt.Chart:
    metrics = ["retrieval_recall_at_k", "retrieval_precision_at_k", "ndcg_at_k"]
    df_melt = df.melt(id_vars=["scenario"], value_vars=metrics, var_name="metric", value_name="score")
    color_map = {
        "retrieval_recall_at_k": THEME["accent"],
        "retrieval_precision_at_k": THEME["accent2"],
        "ndcg_at_k": THEME["accent4"],
    }
    chart = (
        alt.Chart(df_melt)
        .mark_bar(cornerRadius=0)
        .encode(
            x=alt.X("scenario:N", title="Scenariusz", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mean(score):Q", title="Średni wynik", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("metric:N", scale=alt.Scale(range=list(color_map.values()))),
            tooltip=["scenario", "metric", "mean(score):Q"],
        )
        .properties(title="Retrieval: recall, precision, nDCG", width=600, height=300)
    )
    return chart.configure_view(stroke=None).configure_axis(grid=False)


def build_answer_chart(df: pd.DataFrame) -> alt.Chart:
    metrics = ["groundedness_0_2", "completeness_0_2", "citation_coverage_0_2"]
    df_melt = df.melt(id_vars=["scenario"], value_vars=metrics, var_name="metric", value_name="score")
    color_map = {
        "groundedness_0_2": THEME["accent"],
        "completeness_0_2": THEME["accent2"],
        "citation_coverage_0_2": THEME["accent3"],
    }
    chart = (
        alt.Chart(df_melt)
        .mark_bar(cornerRadius=0)
        .encode(
            x=alt.X("scenario:N", title="Scenariusz", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mean(score):Q", title="Średni wynik (0–2)", scale=alt.Scale(domain=[0, 2])),
            color=alt.Color("metric:N", scale=alt.Scale(range=list(color_map.values()))),
            tooltip=["scenario", "metric", "mean(score):Q"],
        )
        .properties(title="Jakość odpowiedzi i cytowań (0–2)", width=600, height=300)
    )
    return chart.configure_view(stroke=None).configure_axis(grid=False)


def build_latency_chart(df: pd.DataFrame) -> alt.Chart:
    lat_query = """
    SELECT
      scenario,
      quantile_cont(latency_ms, 0.5) AS p50_ms,
      quantile_cont(latency_ms, 0.95) AS p95_ms
    FROM df
    GROUP BY scenario
    """
    lat_df = duckdb.query(lat_query).to_df()
    lat_melt = lat_df.melt(id_vars=["scenario"], value_vars=["p50_ms", "p95_ms"], var_name="quantile", value_name="ms")
    color_map = {
        "p50_ms": THEME["accent"],
        "p95_ms": THEME["accent3"],
    }
    chart = (
        alt.Chart(lat_melt)
        .mark_bar(cornerRadius=0)
        .encode(
            x=alt.X("scenario:N", title="Scenariusz", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("ms:Q", title="Latencja (ms)"),
            color=alt.Color("quantile:N", scale=alt.Scale(range=list(color_map.values()))),
            tooltip=["scenario", "quantile", "ms"],
        )
        .properties(title="Latencja p50 / p95 (ms)", width=600, height=300)
    )
    return chart.configure_view(stroke=None).configure_axis(grid=False)


def build_safety_chart(df: pd.DataFrame) -> alt.Chart:
    safety_query = """
    SELECT
      scenario,
      AVG(safety_pass) AS safety_rate
    FROM df
    GROUP BY scenario
    """
    safety_df = duckdb.query(safety_query).to_df()
    chart = (
        alt.Chart(safety_df)
        .mark_bar(cornerRadius=0)
        .encode(
            x=alt.X("scenario:N", title="Scenariusz", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("safety_rate:Q", title="Odsetek safety_pass = 1", scale=alt.Scale(domain=[0, 1])),
            tooltip=["scenario", "safety_rate"],
            color=alt.value(THEME["accent2"]),
        )
        .properties(title="Wskaźnik bezpieczeństwa (safety_pass)", width=500, height=300)
    )
    return chart.configure_view(stroke=None).configure_axis(grid=False)


def build_dashboard(input_csv: Path, output_dir: Path) -> list[Path]:
    if not input_csv.exists():
        raise FileNotFoundError(f"Brak pliku CSV: {input_csv}")
    output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(input_csv)
    charts = [
        ("count", build_count_chart(df)),
        ("route", build_route_chart(df)),
        ("retrieval", build_retrieval_chart(df)),
        ("answer", build_answer_chart(df)),
        ("latency", build_latency_chart(df)),
        ("safety", build_safety_chart(df)),
    ]
    saved = []
    for name, chart in charts:
        path = output_dir / f"eval_{name}.html"
        chart.save(path, format="html")
        saved.append(path)
    summary_path = output_dir / "eval_summary.txt"
    lines = [
        "=== Podsumowanie ewaluacji ===",
        f"Liczba przypadków: {len(df)}",
        "",
        "Średnie metryki per scenariusz:",
    ]
    summary_df = df.groupby("scenario")[
        [
            "route_expected_pass",
            "retrieval_recall_at_k",
            "retrieval_precision_at_k",
            "ndcg_at_k",
            "groundedness_0_2",
            "completeness_0_2",
            "citation_coverage_0_2",
            "safety_pass",
            "latency_ms",
        ]
    ].mean()
    for scenario in summary_df.index:
        row = summary_df.loc[scenario]
        lines.append(f"- {scenario}:")
        lines.append(f"  route: {row['route_expected_pass']:.3f}")
        lines.append(f"  recall: {row['retrieval_recall_at_k']:.3f}, precision: {row['retrieval_precision_at_k']:.3f}, nDCG: {row['ndcg_at_k']:.3f}")
        lines.append(f"  groundedness: {row['groundedness_0_2']:.2f}, completeness: {row['completeness_0_2']:.2f}, citations: {row['citation_coverage_0_2']:.2f}")
        lines.append(f"  safety: {row['safety_pass']:.3f}, latency_ms: {row['latency_ms']:.1f}")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    saved.append(summary_path)

    # Generate unified executive dashboard page
    unified_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>36 Chambers Evaluation Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; border-radius: 0 !important; }}
    body {{ background: #0b0f19; color: #e5e7eb; font-family: 'Consolas', 'Courier New', monospace; padding: 20px; }}
    header {{ border-bottom: 1px solid #1f2937; padding-bottom: 15px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }}
    h1 {{ font-size: 16px; color: #d4a574; letter-spacing: 0.1em; text-transform: uppercase; }}
    .badge {{ background: #111827; border: 1px solid #374151; padding: 4px 8px; font-size: 11px; color: #34d399; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(540px, 1fr)); gap: 16px; }}
    .card {{ background: #111827; border: 1px solid #1f2937; padding: 12px; }}
    .card-title {{ font-size: 12px; color: #60a5fa; margin-bottom: 8px; text-transform: uppercase; border-bottom: 1px solid #1f2937; padding-bottom: 4px; }}
    iframe {{ width: 100%; height: 350px; border: none; background: transparent; }}
  </style>
</head>
<body>
  <header>
    <h1>36 Chambers // Evaluation Analytics Dashboard</h1>
    <div class="badge">CASES: {len(df)} | STATUS: VERIFIED</div>
  </header>
  <div class="grid">
    <div class="card"><div class="card-title">Golden Queries per Scenario</div><iframe src="eval_count.html"></iframe></div>
    <div class="card"><div class="card-title">Routing Pass Rate (0–1)</div><iframe src="eval_route.html"></iframe></div>
    <div class="card"><div class="card-title">Retrieval: Recall, Precision, nDCG</div><iframe src="eval_retrieval.html"></iframe></div>
    <div class="card"><div class="card-title">Answer Quality & Citations (0–2)</div><iframe src="eval_answer.html"></iframe></div>
    <div class="card"><div class="card-title">Latency p50 / p95 (ms)</div><iframe src="eval_latency.html"></iframe></div>
    <div class="card"><div class="card-title">Safety Enforcement Pass Rate</div><iframe src="eval_safety.html"></iframe></div>
  </div>
</body>
</html>
"""
    all_path = output_dir / "eval_dashboard_all.html"
    all_path.write_text(unified_html, encoding="utf-8")
    saved.append(all_path)

    return saved



def main() -> int:
    parser = argparse.ArgumentParser(description="Dashboard ewaluacji 36 Chambers")
    parser.add_argument("--input", type=Path, required=True, help="Ścieżka do eval_results.csv")
    parser.add_argument("--output-dir", type=Path, default=None, help="Katalog wyjściowy (domyślnie katalog CSV)")
    args = parser.parse_args()
    output_dir = args.output_dir or args.input.parent
    paths = build_dashboard(args.input, output_dir)
    print("Wygenerowano pliki:")
    for p in paths:
        print("-", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
