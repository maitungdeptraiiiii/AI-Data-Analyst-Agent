from pathlib import Path
from typing import Literal

import matplotlib
import pandas as pd

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from analyst_agent.schemas import ChartSpec
from analyst_agent.state import AnalysisStep, ChartArtifact

_MIN_LINE_POINTS = 4
_BAR_GROUP_WIDTH = 0.8


class ChartValidationError(ValueError):
    """Raised when a chart specification cannot be grounded in successful analysis data."""


def _resolve_chart_type(
    spec: ChartSpec, rows: list[dict[str, object]]
) -> Literal["bar", "line", "scatter"]:
    """Downgrade "line" to "bar" when there are too few points per series to show a
    meaningful trend. A straight line through 2-3 sparse points visually implies a
    smooth continuous change the data does not actually contain.
    """
    if spec.chart_type != "line":
        return spec.chart_type
    if spec.series_column:
        counts: dict[object, int] = {}
        for row in rows:
            key = row.get(spec.series_column)
            counts[key] = counts.get(key, 0) + 1
        points = min(counts.values()) if counts else 0
    else:
        points = len(rows)
    return "line" if points >= _MIN_LINE_POINTS else "bar"


def validate_chart_spec(spec: ChartSpec, analysis_log: list[AnalysisStep]) -> AnalysisStep:
    step = next(
        (
            candidate
            for candidate in analysis_log
            if candidate["step_id"] == spec.source_step_id and candidate["success"]
        ),
        None,
    )
    if step is None:
        raise ChartValidationError("Chart source must reference a successful analysis step")
    if not step["rows"]:
        raise ChartValidationError("Chart source has no rows")

    required = {spec.x_column, spec.y_column}
    if spec.series_column:
        required.add(spec.series_column)
    if any(not required.issubset(row.keys()) for row in step["rows"]):
        raise ChartValidationError(f"Chart columns do not exist in every row: {sorted(required)}")
    return step


def _prepare_frame(spec: ChartSpec, source: AnalysisStep, chart_type: str) -> pd.DataFrame:
    frame = pd.DataFrame(source["rows"])
    frame[spec.y_column] = pd.to_numeric(frame[spec.y_column], errors="raise")
    if len(frame) > 200:
        raise ChartValidationError("Chart source exceeds 200 rows")
    if spec.series_column and frame[spec.series_column].nunique(dropna=False) > 8:
        raise ChartValidationError("Chart source exceeds 8 series")
    if frame[spec.x_column].nunique(dropna=False) > 50:
        raise ChartValidationError("Chart source exceeds 50 x-axis categories")
    if chart_type == "line":
        parsed = pd.to_datetime(frame[spec.x_column], errors="coerce", utc=True, format="mixed")
        if parsed.notna().all():
            frame = frame.assign(_chart_x=parsed).sort_values("_chart_x")
        else:
            frame = frame.assign(_chart_x=frame[spec.x_column])
    else:
        frame = frame.assign(_chart_x=frame[spec.x_column])
    return frame


def create_chart(
    spec: ChartSpec,
    analysis_log: list[AnalysisStep],
    output_directory: Path,
    chart_number: int,
) -> ChartArtifact:
    source = validate_chart_spec(spec, analysis_log)
    chart_type = _resolve_chart_type(spec, source["rows"])
    frame = _prepare_frame(spec, source, chart_type)
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    chart_id = f"chart_{chart_number}"
    output_path = (output_directory / f"{chart_id}_{spec.source_step_id}.png").resolve()
    if output_directory not in output_path.parents:
        raise ChartValidationError("Chart output escaped the artifact directory")
    temporary_path = output_path.with_suffix(".tmp.png")

    figure, axis = plt.subplots(figsize=(10, 6))
    try:
        if spec.series_column and chart_type == "bar":
            # Grouped bars: give each series its own x-offset so bars sit side by side
            # instead of stacking on top of each other at the same x position.
            categories = list(dict.fromkeys(frame["_chart_x"].astype(str)))
            positions = {category: index for index, category in enumerate(categories)}
            groups = list(frame.groupby(spec.series_column, dropna=False, sort=False))
            width = _BAR_GROUP_WIDTH / len(groups)
            for series_index, (name, group) in enumerate(groups):
                offset = (series_index - (len(groups) - 1) / 2) * width
                x = [positions[value] + offset for value in group["_chart_x"].astype(str)]
                axis.bar(x, group[spec.y_column], width=width, label=str(name))
            axis.set_xticks(range(len(categories)))
            axis.set_xticklabels(categories)
            axis.legend()
        elif spec.series_column:
            for name, group in frame.groupby(spec.series_column, dropna=False, sort=False):
                if chart_type == "line":
                    axis.plot(group["_chart_x"], group[spec.y_column], marker="o", label=str(name))
                else:
                    axis.scatter(group["_chart_x"], group[spec.y_column], label=str(name))
            axis.legend()
        elif chart_type == "line":
            axis.plot(frame["_chart_x"], frame[spec.y_column], marker="o")
        elif chart_type == "bar":
            axis.bar(frame["_chart_x"].astype(str), frame[spec.y_column])
        else:
            axis.scatter(frame["_chart_x"], frame[spec.y_column])

        axis.set_title(spec.title)
        axis.set_xlabel(spec.x_label or spec.x_column)
        axis.set_ylabel(spec.y_label or spec.y_column)
        axis.grid(axis="y", alpha=0.25)
        figure.autofmt_xdate()
        figure.tight_layout()
        figure.savefig(temporary_path, dpi=150, format="png")
        temporary_path.replace(output_path)
    finally:
        plt.close(figure)
        if temporary_path.exists():
            temporary_path.unlink()

    return {
        "chart_id": chart_id,
        "path": str(output_path),
        "title": spec.title,
        "description": spec.description,
        "chart_type": chart_type,
        "source_step_id": spec.source_step_id,
    }
