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


def build_figure(df: pd.DataFrame | None, spec: dict | None):
    """Return a Plotly figure, or None if a chart is not appropriate."""
    if df is None or df.empty:
        return None
    if not spec or spec.get("chart_type") in (None, "none"):
        spec = _heuristic_spec(df)
    if not spec:
        return None

    kind = spec.get("chart_type", "bar")
    x, y = spec.get("x"), spec.get("y")
    color = spec.get("color")
    title = spec.get("title") or ""

    # Validate columns against the actual frame; fall back if mismatched.
    valid = set(df.columns)
    if x not in valid or (y not in valid and kind != "pie"):
        spec = _heuristic_spec(df)
        if not spec:
            return None
        kind, x, y, color = spec["chart_type"], spec["x"], spec["y"], spec.get("color")
        title = spec.get("title", title)
    if color and color not in valid:
        color = None

    try:
        if kind == "bar":
            fig = px.bar(df, x=x, y=y, color=color, title=title)
        elif kind == "line":
            fig = px.line(df, x=x, y=y, color=color, markers=True, title=title)
        elif kind == "scatter":
            fig = px.scatter(df, x=x, y=y, color=color, title=title)
        elif kind == "pie":
            fig = px.pie(df, names=x, values=y, title=title)
        else:
            fig = px.bar(df, x=x, y=y, color=color, title=title)
    except Exception:  # noqa: BLE001  any plotting issue -> no chart, not a crash
        return None

    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=420)
    return fig


def empty_note() -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text="No chart for this answer", showarrow=False)
    fig.update_layout(height=200)
    return fig
