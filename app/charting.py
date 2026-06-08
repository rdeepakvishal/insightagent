"""
charting.py
-----------
Turns the agent's chart spec (or, if absent, a heuristic) into a Plotly figure.
Kept separate from the agent so the visualization rules are easy to tweak.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_CHURN_RATE_KEYWORDS = ("churn_rate", "churn rate", "retention_rate", "retention rate")
_CANCELLATION_KEYWORDS = ("cancel", "cancellation", "churned", "lost")
_TEMPORAL_KEYWORDS = ("month", "date", "year", "day", "week", "quarter", "period")


def _is_temporal(x: str | None) -> bool:
    return bool(x) and any(k in x.lower() for k in _TEMPORAL_KEYWORDS)


def _is_rate(col: str | None) -> bool:
    """A rate/percentage column we should render as a percentage."""
    if not col:
        return False
    c = col.lower()
    return any(k in c for k in ("rate", "pct", "percent", "ratio", "share"))


def _enforce_chart_rules(spec: dict, df: pd.DataFrame) -> dict:
    """Override chart type based on business rules.

    - Rates over time (churn/retention with a temporal x-axis) -> line.
    - Rates compared across categories -> bar (a line implies a trend that
      isn't there).
    - Absolute cancellations -> bar.
    - Never pie.
    """
    # Combo charts (bar + line on a shared time axis) are explicit; don't
    # rewrite them with the single-series rules below.
    if spec.get("chart_type") == "combo":
        return spec

    y = (spec.get("y") or "").lower()
    title = (spec.get("title") or "").lower()
    combined = y + " " + title

    if any(k in combined for k in _CHURN_RATE_KEYWORDS):
        spec = {**spec, "chart_type": "line" if _is_temporal(spec.get("x")) else "bar"}
    elif any(k in combined for k in _CANCELLATION_KEYWORDS):
        spec = {**spec, "chart_type": "bar"}
    elif spec.get("chart_type") == "pie":
        spec = {**spec, "chart_type": "bar"}

    return spec


def _heuristic_spec(df: pd.DataFrame) -> dict | None:
    """Pick a reasonable chart when the agent did not supply one."""
    if df is None or df.empty or df.shape[1] < 2:
        return None
    cols = list(df.columns)
    num_cols = df.select_dtypes("number").columns.tolist()
    cat_cols = [c for c in cols if c not in num_cols]
    if not num_cols:
        return None
    x = cat_cols[0] if cat_cols else cols[0]
    y = num_cols[0]
    looks_temporal = any(k in x.lower() for k in ("month", "date", "year", "day"))
    return {"chart_type": "line" if looks_temporal else "bar", "x": x, "y": y,
            "color": None, "title": f"{y} by {x}"}


def _build_combo(df: pd.DataFrame, spec: dict):
    """Bar (absolute values) + line (rate) on a shared x-axis, dual y-axes.

    Spec shape:
        {"chart_type": "combo", "x": "<time col>",
         "bar_y": "<absolute col>", "line_y": "<rate col>", "title": "..."}
    """
    x = spec.get("x")
    bar_y = spec.get("bar_y")
    line_y = spec.get("line_y")
    valid = set(df.columns)
    if not (x in valid and bar_y in valid and line_y in valid):
        return None

    try:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(x=df[x], y=df[bar_y], name=bar_y.replace("_", " "),
                   marker_color="#38bdf8", opacity=0.55),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(x=df[x], y=df[line_y], name=line_y.replace("_", " "),
                       mode="lines+markers", line=dict(color="#2dd4bf", width=3)),
            secondary_y=True,
        )
    except Exception:  # noqa: BLE001
        return None

    fig.update_yaxes(title_text=bar_y.replace("_", " "), secondary_y=False)
    fig.update_yaxes(title_text=line_y.replace("_", " "), secondary_y=True)
    if _is_rate(line_y):
        fig.update_yaxes(tickformat=".2%", secondary_y=True)
    if _is_rate(bar_y):
        fig.update_yaxes(tickformat=".2%", secondary_y=False)

    fig.update_layout(
        title=spec.get("title") or "",
        margin=dict(l=10, r=10, t=60, b=10),
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def build_figure(df: pd.DataFrame | None, spec: dict | None):
    """Return a Plotly figure, or None if a chart is not appropriate."""
    if df is None or df.empty:
        return None
    if not spec or spec.get("chart_type") in (None, "none"):
        spec = _heuristic_spec(df)
    if not spec:
        return None

    spec = _enforce_chart_rules(spec, df)

    # Combo chart: try it, and fall back to a single-series heuristic if the
    # named columns don't line up with the data.
    if spec.get("chart_type") == "combo":
        fig = _build_combo(df, spec)
        if fig is not None:
            return fig
        spec = _heuristic_spec(df)
        if not spec:
            return None
        spec = _enforce_chart_rules(spec, df)

    kind = spec.get("chart_type", "bar")
    x, y = spec.get("x"), spec.get("y")
    color = spec.get("color")
    title = spec.get("title") or ""

    # Validate columns against the actual frame; fall back if mismatched.
    valid = set(df.columns)
    if x not in valid or y not in valid:
        spec = _heuristic_spec(df)
        if not spec:
            return None
        spec = _enforce_chart_rules(spec, df)
        kind, x, y, color = spec["chart_type"], spec["x"], spec["y"], spec.get("color")
        title = spec.get("title", title)
    if color and color not in valid:
        color = None
    # A continuous numeric column as the color legend produces an unreadable
    # list of raw floats. Drop it; the x/y already carry the information.
    if color and pd.api.types.is_numeric_dtype(df[color]):
        color = None

    try:
        if kind == "line":
            fig = px.line(df, x=x, y=y, color=color, markers=True, title=title)
        elif kind == "scatter":
            fig = px.scatter(df, x=x, y=y, color=color, title=title)
        else:
            fig = px.bar(df, x=x, y=y, color=color, title=title)
    except Exception:  # noqa: BLE001  any plotting issue -> no chart, not a crash
        return None

    # Render rate columns as percentages, rounded to 2 decimals.
    if _is_rate(y):
        fig.update_yaxes(tickformat=".2%")
        fig.update_traces(hovertemplate=f"%{{x}}<br>{y}=%{{y:.2%}}<extra></extra>")
    if _is_rate(x):
        fig.update_xaxes(tickformat=".2%")

    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=420)
    return fig


def empty_note() -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text="No chart for this answer", showarrow=False)
    fig.update_layout(height=200)
    return fig
