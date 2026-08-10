from __future__ import annotations

import calendar
import csv
import hashlib
from datetime import date, datetime
from pathlib import Path

import reflex as rx

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
REPORT_FILE = "to_review_mcq.csv"
ALL_REPORTS_FILE = "all_reports.csv"
STATUS_FILE = "sme_status.csv"
STATUS_HEADERS = ["row_id", "SME", "Status", "Notes"]
PENDING = "Not Resolved"
RESOLVED = "Resolved"


def date_from_folder(name: str) -> date | None:
    try:
        return datetime.strptime(name, "%d-%m-%Y").date()
    except ValueError:
        return None


def date_folder(date_text: str) -> Path:
    return OUTPUT_DIR / date_text


def row_id(row: dict[str, str]) -> str:
    raw = "|".join(
        [
            row.get("Students claim", ""),
            row.get("Question", ""),
            row.get("Correct option", ""),
            row.get("Action item for content team", ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=STATUS_HEADERS)
        writer.writeheader()
        writer.writerows([{h: row.get(h, "") for h in STATUS_HEADERS} for row in rows])


def get_report_dates() -> list[date]:
    if not OUTPUT_DIR.exists():
        return []
    dates = []
    for path in OUTPUT_DIR.iterdir():
        parsed = date_from_folder(path.name)
        if parsed and (path / REPORT_FILE).exists():
            dates.append(parsed)
    return sorted(dates)


def load_scraped_lookup(folder: Path) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, dict[str, str]]]:
    exact_lookup: dict[tuple[str, str], dict[str, str]] = {}
    by_claim: dict[str, list[dict[str, str]]] = {}

    for row in read_csv(folder / ALL_REPORTS_FILE):
        claim = row.get("Description", "")
        question = row.get("Question text", "")
        metadata = {
            "User id": row.get("User id", ""),
            "Question id": row.get("Question id", ""),
            "Question tags": row.get("Question tags", "") or row.get("Topic tag", ""),
        }
        exact_lookup[(claim, question)] = metadata
        by_claim.setdefault(claim, []).append(metadata)

    unique_claim_lookup = {
        claim: rows[0] for claim, rows in by_claim.items() if len(rows) == 1
    }
    return exact_lookup, unique_claim_lookup


def get_scraped_metadata(
    report: dict[str, str],
    exact_lookup: dict[tuple[str, str], dict[str, str]],
    unique_claim_lookup: dict[str, dict[str, str]],
) -> dict[str, str]:
    metadata = {
        "User id": report.get("User id", ""),
        "Question id": report.get("Question id", ""),
        "Question tags": report.get("Question tags", ""),
    }
    if all(value.strip() for value in metadata.values()):
        return metadata

    claim = report.get("Students claim", "")
    question = report.get("Question", "")
    fallback = exact_lookup.get((claim, question)) or unique_claim_lookup.get(claim, {})
    return {key: metadata.get(key) or fallback.get(key, "") for key in metadata}


def load_date_rows(date_text: str) -> list[dict[str, str]]:
    folder = date_folder(date_text)
    reports = read_csv(folder / REPORT_FILE)
    statuses = {r.get("row_id", ""): r for r in read_csv(folder / STATUS_FILE)}
    exact_lookup, unique_claim_lookup = load_scraped_lookup(folder)
    rows = []

    for index, report in enumerate(reports, start=1):
        rid = row_id(report)
        status = statuses.get(rid, {})
        scraped_metadata = get_scraped_metadata(report, exact_lookup, unique_claim_lookup)
        rows.append(
            {
                "id": rid,
                "index": str(index),
                "Status": status.get("Status") or PENDING,
                "SME": status.get("SME", ""),
                "Notes": status.get("Notes", ""),
                "User id": scraped_metadata.get("User id", ""),
                "Question id": scraped_metadata.get("Question id", ""),
                "Question tags": scraped_metadata.get("Question tags", ""),
                "Students claim": report.get("Students claim", ""),
                "Question": report.get("Question", ""),
                "LLM assessment": report.get("LLM assessment", ""),
                "Action item": report.get("Action item for content team", ""),
                "Message to student": report.get("Message to student", ""),
            }
        )
    return rows


def save_date_rows(date_text: str, rows: list[dict[str, str]]) -> None:
    status_rows = [
        {
            "row_id": row.get("id", ""),
            "SME": row.get("SME", ""),
            "Status": row.get("Status", PENDING),
            "Notes": row.get("Notes", ""),
        }
        for row in rows
    ]
    write_csv(date_folder(date_text) / STATUS_FILE, status_rows)


def summarize_date(date_text: str) -> dict[str, int]:
    rows = load_date_rows(date_text)
    resolved = sum(1 for row in rows if row.get("Status") == RESOLVED)
    return {"total": len(rows), "resolved": resolved, "pending": len(rows) - resolved}


class DashboardState(rx.State):
    month: int = date.today().month
    year: int = date.today().year
    selected_date: str = ""
    calendar_days: list[dict[str, str | int | bool]] = []
    rows: list[dict[str, str]] = []
    summary: str = "No date selected"

    @rx.var
    def month_title(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"

    def load(self):
        dates = get_report_dates()
        if dates:
            latest = dates[-1]
            self.month = latest.month
            self.year = latest.year
            self.selected_date = latest.strftime("%d-%m-%Y")
            self.rows = load_date_rows(self.selected_date)
            self.summary = self.get_summary_text(self.selected_date)
        self.calendar_days = self.build_calendar_days()

    def get_summary_text(self, date_text: str) -> str:
        summary = summarize_date(date_text)
        return (
            f"{date_text}: {summary['resolved']} resolved, "
            f"{summary['pending']} not resolved, {summary['total']} total"
        )

    def build_calendar_days(self) -> list[dict[str, str | int | bool]]:
        days = []
        report_dates = {d.strftime("%d-%m-%Y") for d in get_report_dates()}
        for day in calendar.Calendar(firstweekday=0).itermonthdates(self.year, self.month):
            date_text = day.strftime("%d-%m-%Y")
            summary = summarize_date(date_text) if date_text in report_dates else {}
            days.append(
                {
                    "date": date_text,
                    "day": day.day,
                    "in_month": day.month == self.month,
                    "has_report": date_text in report_dates,
                    "resolved": summary.get("resolved", 0),
                    "pending": summary.get("pending", 0),
                    "total": summary.get("total", 0),
                }
            )
        return days

    def select_date(self, date_text: str):
        self.selected_date = date_text
        self.rows = load_date_rows(date_text)
        self.summary = self.get_summary_text(date_text)
        self.calendar_days = self.build_calendar_days()

    def previous_month(self):
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        self.calendar_days = self.build_calendar_days()

    def next_month(self):
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        self.calendar_days = self.build_calendar_days()

    def set_status(self, rid: str, status: str):
        for row in self.rows:
            if row.get("id") == rid:
                row["Status"] = status
                break
        self.rows = list(self.rows)
        save_date_rows(self.selected_date, self.rows)
        self.summary = self.get_summary_text(self.selected_date)
        self.calendar_days = self.build_calendar_days()

    def set_sme(self, rid: str, value: str):
        for row in self.rows:
            if row.get("id") == rid:
                row["SME"] = value
                break
        self.rows = list(self.rows)
        save_date_rows(self.selected_date, self.rows)

    def set_notes(self, rid: str, value: str):
        for row in self.rows:
            if row.get("id") == rid:
                row["Notes"] = value
                break
        self.rows = list(self.rows)
        save_date_rows(self.selected_date, self.rows)



def stat_badge(label: str, value: rx.Var | int, color: str) -> rx.Component:
    return rx.badge(
        rx.hstack(rx.text(label), rx.text(value), spacing="1"),
        color_scheme=color,
        variant="soft",
    )


def day_cell(day: rx.Var[dict]) -> rx.Component:
    return rx.button(
        rx.vstack(
            rx.hstack(
                rx.text(day["day"], weight="bold"),
                rx.cond(day["has_report"], rx.badge(day["total"], color_scheme="blue")),
                width="100%",
                justify="between",
            ),
            rx.cond(
                day["has_report"],
                rx.vstack(
                    stat_badge("Done", day["resolved"], "green"),
                    stat_badge("Open", day["pending"], "orange"),
                    spacing="1",
                    align="start",
                ),
                rx.text("No reports", size="1", color="gray"),
            ),
            align="start",
            spacing="2",
            width="100%",
        ),
        on_click=lambda: DashboardState.select_date(day["date"]),
        disabled=rx.cond(day["has_report"], False, True),
        variant=rx.cond(day["has_report"], "surface", "soft"),
        opacity=rx.cond(day["in_month"], "1", "0.35"),
        width="100%",
        min_height="110px",
        padding="3",
    )


def report_row(row: rx.Var[dict]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row["index"]),
        rx.table.cell(
            rx.cond(
                row["Status"] == RESOLVED,
                rx.badge(RESOLVED, color_scheme="green"),
                rx.badge(PENDING, color_scheme="orange"),
            )
        ),
        rx.table.cell(
            rx.input(
                value=row["SME"],
                placeholder="SME name",
                on_change=lambda value: DashboardState.set_sme(row["id"], value),
                width="150px",
            )
        ),
        rx.table.cell(rx.text(row["User id"], max_width="180px")),
        rx.table.cell(rx.text(row["Question id"], max_width="180px")),
        rx.table.cell(
            rx.badge(
                row["Question tags"],
                color_scheme="purple",
                variant="soft",
                max_width="260px",
            )
        ),
        rx.table.cell(rx.text(row["Students claim"], max_width="260px")),
        rx.table.cell(rx.text(row["Question"], max_width="360px")),
        rx.table.cell(rx.text(row["Action item"], max_width="340px")),
        rx.table.cell(
            rx.text_area(
                value=row["Notes"],
                placeholder="Follow-up notes",
                on_change=lambda value: DashboardState.set_notes(row["id"], value),
                width="220px",
            )
        ),
        rx.table.cell(
            rx.hstack(
                rx.button(
                    "Resolved",
                    size="2",
                    color_scheme="green",
                    on_click=lambda: DashboardState.set_status(row["id"], RESOLVED),
                ),
                rx.button(
                    "Not resolved",
                    size="2",
                    color_scheme="orange",
                    on_click=lambda: DashboardState.set_status(row["id"], PENDING),
                ),
            )
        ),
    )


def calendar_view() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.button("← Previous", on_click=DashboardState.previous_month),
            rx.heading(DashboardState.month_title, size="5"),
            rx.button("Next →", on_click=DashboardState.next_month),
            justify="between",
            width="100%",
        ),
        rx.grid(
            *[rx.center(rx.text(day, weight="bold")) for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]],
            columns="7",
            width="100%",
        ),
        rx.grid(
            rx.foreach(DashboardState.calendar_days, day_cell),
            columns="7",
            spacing="2",
            width="100%",
        ),
        width="100%",
        spacing="3",
    )


def reports_table() -> rx.Component:
    return rx.vstack(
        rx.heading("Selected date reports", size="4"),
        rx.text(DashboardState.summary),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("#"),
                    rx.table.column_header_cell("Status"),
                    rx.table.column_header_cell("SME"),
                    rx.table.column_header_cell("User id"),
                    rx.table.column_header_cell("Question id"),
                    rx.table.column_header_cell("Tags"),
                    rx.table.column_header_cell("Student claim"),
                    rx.table.column_header_cell("Question"),
                    rx.table.column_header_cell("Action item"),
                    rx.table.column_header_cell("Notes"),
                    rx.table.column_header_cell("Actions"),
                )
            ),
            rx.table.body(rx.foreach(DashboardState.rows, report_row)),
            width="100%",
            variant="surface",
        ),
        width="100%",
        overflow_x="auto",
    )


@rx.page(route="/", title="Topin SME Follow-up", on_load=DashboardState.load)
def index() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading("Topin SME Follow-up Dashboard", size="7"),
            rx.text("Open dashboard for tracking MCQ report resolution by date."),
            calendar_view(),
            rx.divider(),
            reports_table(),
            spacing="6",
            width="100%",
            max_width="1600px",
            margin="0 auto",
        ),
        width="100%",
        min_height="100vh",
        padding="5",
    )


app = rx.App()
