"""Estado por período (spec 030, RF-3031..3035): casos montados à mão."""

from datetime import date, datetime
from typing import Any

import polars as pl
import pytest

from prodata.nodes.temporal import NO_HISTORY, PeriodStateConfig, period_state

D = datetime


def cfg(**kw: Any) -> PeriodStateConfig:
    base = {
        "item_key": "id",
        "created": "criado",
        "event_key": "id",
        "when": "quando",
        "new_state": "para",
        "old_state": "de",
        "period": "month",
    }
    return PeriodStateConfig(**{**base, **kw})


ITEMS = pl.DataFrame(
    {
        "id": ["A", "B"],
        "criado": [D(2026, 1, 10), D(2026, 2, 5)],
        "atual": ["Feito", "Novo"],
        "time": ["X", "Y"],
    }
)
EVENTS = pl.DataFrame({
    "id": ["A", "A"], "quando": [D(2026, 1, 20), D(2026, 3, 3)], "de": ["Novo", "Fazendo"], "para": ["Fazendo", "Feito"], "campo": ["status", "status"],
})  # fmt: skip


def states(frame: pl.DataFrame, key: str) -> list[tuple[date, str]]:
    part = frame.filter(pl.col("id") == key)
    return list(zip(part["periodo"].to_list(), part["estado"].to_list(), strict=True))


def test_state_at_the_end_of_each_period() -> None:
    frame, _ = period_state(ITEMS, EVENTS, cfg())
    assert states(frame, "A") == [
        (date(2026, 1, 1), "Fazendo"),
        (date(2026, 2, 1), "Fazendo"),
        (date(2026, 3, 1), "Feito"),
    ]


def test_item_appears_only_after_it_exists() -> None:
    frame, _ = period_state(ITEMS, EVENTS, cfg(current_state="atual"))
    assert states(frame, "B") == [(date(2026, 2, 1), "Novo"), (date(2026, 3, 1), "Novo")]


def test_item_with_no_events_is_never_filled_with_today() -> None:
    frame, unknown = period_state(ITEMS, EVENTS, cfg())
    assert {s for _, s in states(frame, "B")} == {NO_HISTORY} and unknown == 1


def test_before_the_first_event_uses_the_old_state() -> None:
    late = EVENTS.with_columns(pl.Series("quando", [D(2026, 2, 20), D(2026, 3, 3)]))
    frame, _ = period_state(ITEMS, late, cfg())
    assert states(frame, "A")[0] == (date(2026, 1, 1), "Novo")


def test_without_old_state_the_past_is_unknown() -> None:
    late = EVENTS.with_columns(pl.Series("quando", [D(2026, 2, 20), D(2026, 3, 3)]))
    frame, unknown = period_state(ITEMS, late, cfg(old_state=""))
    assert states(frame, "A")[0] == (date(2026, 1, 1), NO_HISTORY) and unknown == 2


def test_only_events_of_a_given_kind_count() -> None:
    mixed = pl.concat(
        [
            EVENTS,
            pl.DataFrame(
                {
                    "id": ["A"],
                    "quando": [D(2026, 2, 2)],
                    "de": ["x"],
                    "para": ["Outro campo"],
                    "campo": ["prioridade"],
                }
            ),
        ]
    )
    frame, _ = period_state(ITEMS, mixed, cfg(only_column="campo", only_value="status"))
    assert "Outro campo" not in frame["estado"].to_list()


def test_days_in_state_and_since_created() -> None:
    frame, _ = period_state(ITEMS, EVENTS, cfg())
    feb = frame.filter((pl.col("id") == "A") & (pl.col("periodo") == date(2026, 2, 1))).row(0, named=True)
    assert feb["dias_no_estado"] == 39 and feb["dias_desde_criacao"] == 49


def test_weeks_start_on_monday_and_keep_columns() -> None:
    frame, _ = period_state(ITEMS, EVENTS, cfg(period="week", keep=["time"]))
    assert all(p.weekday() == 0 for p in frame["periodo"].to_list()) and frame.columns[-1] == "time"


def test_days_cover_every_day() -> None:
    frame, _ = period_state(ITEMS, EVENTS, cfg(period="day"))
    assert frame.filter(pl.col("id") == "A").height == (D(2026, 3, 3) - D(2026, 1, 10)).days + 1


def test_until_today_extends_the_periods() -> None:
    frame, _ = period_state(ITEMS, EVENTS, cfg(until="today"), today=date(2026, 5, 15))
    assert frame["periodo"].max() == date(2026, 5, 1)


def test_text_dates_are_accepted() -> None:
    text = EVENTS.with_columns(pl.col("quando").dt.strftime("%Y-%m-%d %H:%M:%S"))
    assert states(period_state(ITEMS, text, cfg())[0], "A")[-1][1] == "Feito"


def test_bad_date_is_explained() -> None:
    with pytest.raises(ValueError, match=r"\[quando\].*datas"):
        period_state(ITEMS, EVENTS.with_columns(pl.lit("ontem").alias("quando")), cfg())


def test_missing_choice_is_explained() -> None:
    with pytest.raises(ValueError, match="Escolha o identificador do item"):
        period_state(ITEMS, EVENTS, cfg(item_key=""))


def test_explosion_is_refused_before_running() -> None:
    many = pl.DataFrame({"id": [str(i) for i in range(20000)], "criado": [D(2000, 1, 1)] * 20000})
    ev = pl.DataFrame({"id": ["0"], "quando": [D(2026, 1, 1)], "para": ["x"], "de": ["y"]})
    with pytest.raises(ValueError, match="passam do limite"):
        period_state(many, ev, cfg(period="day"))
