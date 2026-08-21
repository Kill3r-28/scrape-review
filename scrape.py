from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, Tag

DEFAULT_INPUT_DATE = "21-06-2026"

BASE_URL = "https://nxtwave-assessments-backend-topin-prod-apis.ccbp.in"
REPORT_PATH = "/admin/nw_assessments_core/orgassessmentreport/"
REPORT_URL = f"{BASE_URL}{REPORT_PATH}"
LOGIN_URL = f"{BASE_URL}/admin/login/?next={quote(REPORT_PATH)}"
QUESTION_SEARCH_URL = f"{BASE_URL}/admin/nkb_question/question/"
QUESTION_TAG_URL = f"{BASE_URL}/admin/nkb_question/questiontag/"

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
OUTPUT_DIR = BASE_DIR / "output"
TIMEOUT_SECONDS = 30

CSV_HEADERS = [
    "Org assessment id",
    "Org assessment title",
    "User id",
    "Category",
    "Sub category",
    "Description",
    "Creation datetime",
    "Question id",
    "Question type",
    "Question text",
    "Topic tag",
    "Question tags",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def parse_input_date(value: str) -> date:
    for fmt in (
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%B %d %Y",
        "%B %d, %Y",
        "%d %B %Y",
        "%b %d %Y",
        "%b %d, %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass

    raise ValueError(
        f"Could not parse INPUT_DATE={value!r}. Use formats like '2026-06-21' or 'June 21 2026'."
    )


def parse_creation_datetime(value: str) -> datetime | None:
    cleaned = " ".join(value.split()).strip()
    cleaned = cleaned.replace("a.m.", "AM").replace("p.m.", "PM")
    cleaned = cleaned.replace("a.m", "AM").replace("p.m", "PM")
    cleaned = cleaned.replace("A.M.", "AM").replace("P.M.", "PM")
    # Django admin often renders abbreviated months with a trailing dot: "Aug. 20, 2026"
    cleaned = re.sub(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.",
        r"\1",
        cleaned,
    )

    for fmt in (
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y, %I %p",
        "%b %d, %Y, %I:%M %p",
        "%b %d, %Y, %I %p",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass

    return None


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "scrape-review/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def is_login_page(response: requests.Response) -> bool:
    return "/admin/login/" in response.url


def login_with_django_admin(session: requests.Session) -> None:
    username = get_env("SCRAPER_USERNAME", "USERNAME", "ADMIN_USERNAME")
    password = get_env("SCRAPER_PASSWORD", "PASSWORD", "ADMIN_PASSWORD")
    if not username or not password:
        raise ValueError(
            "Missing username/password in .env. Use SCRAPER_USERNAME/SCRAPER_PASSWORD or USERNAME/PASSWORD."
        )

    login_page = session.get(LOGIN_URL, timeout=TIMEOUT_SECONDS)
    login_page.raise_for_status()

    soup = BeautifulSoup(login_page.text, "html.parser")
    csrf_input = soup.find("input", attrs={"name": "csrfmiddlewaretoken"})
    if not isinstance(csrf_input, Tag):
        raise ValueError("Could not find csrfmiddlewaretoken on login page.")

    csrf_value = csrf_input.get("value", "")
    csrf_token = csrf_value.strip() if isinstance(csrf_value, str) else ""
    if not csrf_token:
        raise ValueError("csrfmiddlewaretoken value is empty.")

    response = session.post(
        LOGIN_URL,
        data={
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": csrf_token,
            "next": REPORT_PATH,
            "this_is_the_login_form": "1",
        },
        headers={"Referer": LOGIN_URL, "Origin": BASE_URL},
        timeout=TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    response.raise_for_status()

    if is_login_page(response):
        raise ValueError("Login failed. Still on the admin login page.")


def fetch_page_html(session: requests.Session, page_number: int) -> str:
    params = {"p": page_number} if page_number > 1 else None
    response = session.get(REPORT_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    if is_login_page(response):
        raise ValueError(
            "Authentication failed; request was redirected to the admin login page."
        )

    print(f"Fetched page {page_number}: {response.url}")
    return response.text


def get_container(soup: BeautifulSoup) -> Tag:
    container = soup.find("div", class_="changelist-form-container")
    if not isinstance(container, Tag):
        raise ValueError("Could not find div.changelist-form-container.")
    return container


def get_total_pages(container: Tag) -> int:
    paginator = container.find("p", class_="paginator")
    if not isinstance(paginator, Tag):
        return 1

    pages = [1]
    current_page = paginator.find("span", class_="this-page")
    if isinstance(current_page, Tag):
        text = current_page.get_text(strip=True)
        if text.isdigit():
            pages.append(int(text))

    for link in paginator.find_all("a", href=True):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        match = re.search(r"[?&]p=(\d+)", href)
        if match:
            pages.append(int(match.group(1)))

    return max(pages)


def get_text_from_cell(row: Tag, class_name: str, tag_name: str) -> str:
    cell = row.find(tag_name, class_=class_name)
    return cell.get_text(" ", strip=True) if isinstance(cell, Tag) else ""


def parse_metadata(metadata_text: str) -> dict[str, str]:
    if not metadata_text.strip():
        return {"question_id": "", "org_assessment_title": ""}

    try:
        data = json.loads(metadata_text)
        return {
            "question_id": str(data.get("question_id", "") or "").strip(),
            "org_assessment_title": str(
                data.get("org_assessment_title", "") or ""
            ).strip(),
        }
    except json.JSONDecodeError:
        question_match = re.search(r'"question_id"\s*:\s*"([^"]+)"', metadata_text)
        title_match = re.search(
            r'"org_assessment_title"\s*:\s*"([^"]+)"', metadata_text
        )
        return {
            "question_id": question_match.group(1).strip() if question_match else "",
            "org_assessment_title": title_match.group(1).strip() if title_match else "",
        }


def extract_rows_from_container(container: Tag) -> list[dict[str, str]]:
    table = container.find("table", id="result_list")
    if not isinstance(table, Tag):
        raise ValueError("Could not find table#result_list inside target container.")

    tbody = table.find("tbody")
    if not isinstance(tbody, Tag):
        return []

    rows: list[dict[str, str]] = []
    for tr in tbody.find_all("tr", recursive=False):
        if not isinstance(tr, Tag):
            continue

        metadata = parse_metadata(get_text_from_cell(tr, "field-metadata", "td"))
        org_assessment_id = get_text_from_cell(tr, "field-org_assessment_id", "th")
        if not org_assessment_id:
            org_assessment_id = get_text_from_cell(tr, "field-org_assessment_id", "td")

        row = {
            "Org assessment id": org_assessment_id,
            "Org assessment title": metadata["org_assessment_title"],
            "User id": get_text_from_cell(tr, "field-user_id", "td"),
            "Category": get_text_from_cell(tr, "field-category", "td"),
            "Sub category": get_text_from_cell(tr, "field-sub_category", "td"),
            "Description": get_text_from_cell(tr, "field-description", "td"),
            "Creation datetime": get_text_from_cell(
                tr, "field-creation_datetime", "td"
            ),
            "Question id": metadata["question_id"],
        }
        if any(row.values()):
            rows.append(row)

    return rows


def filter_rows_by_date(
    rows: list[dict[str, str]], target_date: date
) -> list[dict[str, str]]:
    matched_rows: list[dict[str, str]] = []
    for row in rows:
        parsed = parse_creation_datetime(row.get("Creation datetime", ""))
        if parsed and parsed.date() == target_date:
            matched_rows.append(row)
    return matched_rows


def get_page_date_range(rows: list[dict[str, str]]) -> tuple[date | None, date | None]:
    dates = [
        parsed.date()
        for row in rows
        if (parsed := parse_creation_datetime(row.get("Creation datetime", "")))
    ]
    return (min(dates), max(dates)) if dates else (None, None)


def get_output_dir_for_date(target_date: date) -> Path:
    return OUTPUT_DIR / target_date.strftime("%d-%m-%Y")


def get_all_reports_csv_path(target_date: date) -> Path:
    return get_output_dir_for_date(target_date) / "all_reports.csv"


def fetch_question_summary(
    session: requests.Session, question_id: str
) -> dict[str, str]:
    if not question_id.strip():
        return {"Question type": "", "Question text": ""}
    try:
        response = session.get(
            QUESTION_SEARCH_URL, params={"q": question_id}, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        if is_login_page(response):
            return {"Question type": "", "Question text": ""}
        soup = BeautifulSoup(response.text, "html.parser")
        container = soup.find("div", class_="changelist-form-container")
        if not isinstance(container, Tag):
            return {"Question type": "", "Question text": ""}
        table = container.find("table", id="result_list")
        if not isinstance(table, Tag):
            return {"Question type": "", "Question text": ""}
        tbody = table.find("tbody")
        if not isinstance(tbody, Tag):
            return {"Question type": "", "Question text": ""}
        first_row = tbody.find("tr")
        if not isinstance(first_row, Tag):
            return {"Question type": "", "Question text": ""}
        return {
            "Question type": get_text_from_cell(first_row, "field-question_type", "td"),
            "Question text": get_text_from_cell(first_row, "field-content", "td"),
        }
    except requests.RequestException:
        return {"Question type": "", "Question text": ""}


def fetch_question_tags(session: requests.Session, question_id: str) -> list[str]:
    if not question_id.strip():
        return []
    try:
        response = session.get(
            QUESTION_TAG_URL, params={"q": question_id}, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        if is_login_page(response):
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        container = soup.find("div", class_="changelist-form-container")
        if not isinstance(container, Tag):
            return []
        table = container.find("table", id="result_list")
        if not isinstance(table, Tag):
            return []
        tbody = table.find("tbody")
        if not isinstance(tbody, Tag):
            return []

        tags: list[str] = []
        for tag_row in tbody.find_all("tr"):
            if not isinstance(tag_row, Tag):
                continue
            tag_value = get_text_from_cell(tag_row, "field-tag_name_enum", "td")
            if tag_value:
                tags.append(tag_value)
        return tags
    except requests.RequestException:
        return []


def get_topic_tag(tags: list[str]) -> str:
    return next((tag for tag in tags if tag.startswith("TOPIC_")), "")


def enrich_rows(
    session: requests.Session, rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    total = len(rows)
    question_cache: dict[str, dict[str, str]] = {}
    tag_cache: dict[str, list[str]] = {}

    for index, row in enumerate(rows, start=1):
        print(f"\rEnriching report row {index}/{total}", end="", flush=True)
        question_id = row.get("Question id", "").strip()

        if question_id not in question_cache:
            question_cache[question_id] = fetch_question_summary(session, question_id)
        if question_id not in tag_cache:
            tag_cache[question_id] = fetch_question_tags(session, question_id)

        tags = tag_cache[question_id]
        row.update(question_cache[question_id])
        row["Topic tag"] = get_topic_tag(tags)
        row["Question tags"] = ", ".join(tags)
        enriched.append(row)
    if total:
        print()
    return enriched


def save_rows_to_csv(rows: list[dict[str, str]], target_date: date) -> Path:
    output_dir = get_output_dir_for_date(target_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_rows = [
        {
            "Org assessment id": row.get("Org assessment id", ""),
            "Org assessment title": row.get("Org assessment title", ""),
            "User id": row.get("User id", ""),
            "Category": row.get("Category", ""),
            "Sub category": row.get("Sub category", ""),
            "Description": row.get("Description", ""),
            "Creation datetime": row.get("Creation datetime", ""),
            "Question id": row.get("Question id", ""),
            "Question type": row.get("Question type", ""),
            "Question text": row.get("Question text", ""),
            "Topic tag": row.get("Topic tag", ""),
            "Question tags": row.get("Question tags", ""),
        }
        for row in rows
    ]

    output_path = get_all_reports_csv_path(target_date)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(output_rows)

    return output_path


def scrape_reports_for_date(target_date: date) -> list[dict[str, str]]:
    return scrape_reports_for_date_range(target_date, target_date)


def scrape_reports_for_date_range(
    start_date: date, end_date: date
) -> list[dict[str, str]]:
    if end_date < start_date:
        raise ValueError("end_date must be >= start_date")

    session = create_session()
    login_with_django_admin(session)

    first_html = fetch_page_html(session, 1)
    first_container = get_container(BeautifulSoup(first_html, "html.parser"))
    total_pages = get_total_pages(first_container)
    print(f"Detected total pages: {total_pages}")
    print(f"Collecting reports from {start_date.isoformat()} to {end_date.isoformat()}")

    all_matches: list[dict[str, str]] = []

    def collect(rows: list[dict[str, str]]) -> date | None:
        for row in rows:
            parsed = parse_creation_datetime(row.get("Creation datetime", ""))
            if parsed and start_date <= parsed.date() <= end_date:
                all_matches.append(row)
        _, max_date = get_page_date_range(rows)
        return max_date

    max_date = collect(extract_rows_from_container(first_container))
    print(f"Page 1: matched so far {len(all_matches)}")

    for page_number in range(2, total_pages + 1):
        html = fetch_page_html(session, page_number)
        container = get_container(BeautifulSoup(html, "html.parser"))
        rows = extract_rows_from_container(container)
        if not rows:
            break

        max_date = collect(rows)
        print(f"Page {page_number}: matched so far {len(all_matches)}")
        if max_date is not None and max_date < start_date:
            break

    return all_matches


def main(input_date: str | None = None) -> int:
    load_dotenv(ENV_PATH)

    try:
        target_date = parse_input_date(input_date or DEFAULT_INPUT_DATE)
        output_dir = get_output_dir_for_date(target_date)
        output_path = get_all_reports_csv_path(target_date)
        print(f"Preparing output folder: {output_dir}")

        if output_path.exists():
            print(f"Reusing existing reports file: {output_path}")
            return 0

        matched_rows = scrape_reports_for_date(target_date)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return 1
    except ValueError as exc:
        print(exc)
        return 1

    print(
        f"Found {len(matched_rows)} matching reports for {target_date.strftime('%d-%m-%Y')}"
    )

    session = create_session()
    login_with_django_admin(session)
    print("Enriching rows with question type and topic tag...")
    enriched_rows = enrich_rows(session, matched_rows)

    output_path = save_rows_to_csv(enriched_rows, target_date)
    print(f"Saved all reports to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
