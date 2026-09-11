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
QUESTION_CHANGE_URL_TEMPLATE = f"{BASE_URL}/admin/nkb_question/question/{{question_id}}/change/"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
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
    # Django admin sometimes uses "Sept." instead of "Sep."
    cleaned = re.sub(r"\bSept\.", "Sep", cleaned)
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


def fetch_page_html(
    session: requests.Session,
    page_number: int,
    *,
    extra_params: dict[str, str] | None = None,
) -> str:
    params: dict[str, str] = {}
    if extra_params:
        params.update(extra_params)
    if page_number > 1:
        params["p"] = str(page_number)
    response = session.get(
        REPORT_URL, params=params or None, timeout=TIMEOUT_SECONDS
    )
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

    # Prefer estimate from result count when paginator only shows a window of links.
    count = get_result_count(container)
    if count is not None and count > 0:
        try:
            row_count = len(extract_rows_from_container(container))
        except ValueError:
            row_count = 0
        per_page = max(row_count, 50)
        pages.append(max(1, (count + per_page - 1) // per_page))

    return max(pages)


def get_result_count(container: Tag) -> int | None:
    paginator = container.find("p", class_="paginator")
    if not isinstance(paginator, Tag):
        return None
    text = paginator.get_text(" ", strip=True)
    match = re.search(
        r"([\d,]+)\s+(?:reports?|results?|entries|total)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def get_text_from_cell(row: Tag, class_name: str, tag_name: str) -> str:
    cell = row.find(tag_name, class_=class_name)
    return cell.get_text(" ", strip=True) if isinstance(cell, Tag) else ""


def extract_question_id_from_metadata(data: dict) -> str:
    direct = str(data.get("question_id", "") or "").strip()
    if direct:
        return direct

    exam_details = data.get("exam_details") or {}
    if isinstance(exam_details, dict):
        for key in ("questions_id", "question_id", "questionId"):
            raw = exam_details.get(key, "")
            if isinstance(raw, list):
                for item in raw:
                    value = str(item or "").strip()
                    if value:
                        return value
            else:
                value = str(raw or "").strip()
                if value:
                    return value
    return ""


def parse_metadata(metadata_text: str) -> dict[str, str]:
    if not metadata_text.strip():
        return {"question_id": "", "org_assessment_title": ""}

    try:
        data = json.loads(metadata_text)
        return {
            "question_id": extract_question_id_from_metadata(data),
            "org_assessment_title": str(
                data.get("org_assessment_title", "") or ""
            ).strip(),
        }
    except json.JSONDecodeError:
        title_match = re.search(
            r'"org_assessment_title"\s*:\s*"([^"]+)"', metadata_text
        )
        questions_id_match = re.search(
            r'"questions_id"\s*:\s*"([^"]+)"', metadata_text
        )
        question_id_match = re.search(
            r'"question_id"\s*:\s*"([^"]+)"', metadata_text
        )
        question_id = ""
        if questions_id_match:
            question_id = questions_id_match.group(1).strip()
        elif question_id_match:
            question_id = question_id_match.group(1).strip()
        return {
            "question_id": question_id,
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


def _form_field_value(soup: BeautifulSoup, name: str) -> str:
    el = soup.find(["input", "textarea", "select"], attrs={"name": name})
    if not isinstance(el, Tag):
        return ""
    if el.name == "textarea":
        return el.get_text() if el.get_text() is not None else ""
    if el.name == "select":
        selected = el.find("option", selected=True)
        if isinstance(selected, Tag):
            return selected.get_text(" ", strip=True)
        return ""
    value = el.get("value", "")
    return value.strip() if isinstance(value, str) else ""


def fetch_question_summary(
    session: requests.Session, question_id: str
) -> dict[str, str]:
    """Pull question type + content from the Django admin change page."""
    if not question_id.strip():
        return {"Question type": "", "Question text": ""}
    try:
        response = session.get(
            QUESTION_CHANGE_URL_TEMPLATE.format(question_id=question_id.strip()),
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if is_login_page(response):
            return {"Question type": "", "Question text": ""}

        soup = BeautifulSoup(response.text, "html.parser")
        question_type = _form_field_value(soup, "question_type").strip()
        question_text = _form_field_value(soup, "content").strip()
        if not question_text:
            question_text = _form_field_value(soup, "short_text").strip()
        return {
            "Question type": question_type,
            "Question text": question_text,
        }
    except requests.RequestException:
        return {"Question type": "", "Question text": ""}


def fetch_question_tags(session: requests.Session, question_id: str) -> list[str]:
    """Pull tag enums from /admin/nkb_question/questiontag/?q=<question_id>."""
    if not question_id.strip():
        return []
    try:
        response = session.get(
            QUESTION_TAG_URL,
            params={"q": question_id.strip()},
            timeout=TIMEOUT_SECONDS,
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
        seen: set[str] = set()
        qid = question_id.strip().lower()
        for tag_row in tbody.find_all("tr"):
            if not isinstance(tag_row, Tag):
                continue
            tag_value = get_text_from_cell(tag_row, "field-tag_name_enum", "td").strip()
            if not tag_value:
                continue
            # Admin sometimes returns the question id itself as a fake tag row.
            if tag_value.lower() == qid or UUID_RE.match(tag_value):
                continue
            if tag_value in seen:
                continue
            seen.add(tag_value)
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


def scrape_reports_for_date(
    target_date: date,
    *,
    after_datetime: datetime | None = None,
) -> list[dict[str, str]]:
    return scrape_reports_for_date_range(
        target_date, target_date, after_datetime=after_datetime
    )


def _date_filter_param_candidates(start_date: date, end_date: date) -> list[dict[str, str]]:
    """Common Django admin DateTimeField list-filter query shapes to try."""
    next_day = date.fromordinal(end_date.toordinal() + 1)
    if start_date != end_date:
        return [
            {
                "creation_datetime__gte": start_date.isoformat(),
                "creation_datetime__lt": next_day.isoformat(),
            }
        ]
    return [
        {"creation_datetime__date": start_date.isoformat()},
        {"creation_datetime__date__exact": start_date.isoformat()},
        {
            "creation_datetime__gte": start_date.isoformat(),
            "creation_datetime__lt": next_day.isoformat(),
        },
        {
            "creation_datetime__year": str(start_date.year),
            "creation_datetime__month": str(start_date.month),
            "creation_datetime__day": str(start_date.day),
        },
    ]


def _try_admin_date_filter(
    session: requests.Session,
    start_date: date,
    end_date: date,
) -> tuple[dict[str, str], Tag, list[dict[str, str]]] | None:
    """
    Return (params, container, rows) if Django admin appears to honor a date filter.
    Otherwise None (caller falls back to binary page search).
    """
    candidates = _date_filter_param_candidates(start_date, end_date)

    baseline_html = fetch_page_html(session, 1)
    baseline_rows = extract_rows_from_container(
        get_container(BeautifulSoup(baseline_html, "html.parser"))
    )
    baseline_min, baseline_max = get_page_date_range(baseline_rows)

    for params in candidates:
        probe = session.get(REPORT_URL, params=params, timeout=TIMEOUT_SECONDS)
        if is_login_page(probe):
            continue
        if not all(k in probe.url for k in params):
            print(f"Date filter ignored by admin (params dropped): {params}")
            continue
        try:
            container = get_container(BeautifulSoup(probe.text, "html.parser"))
            rows = extract_rows_from_container(container)
        except Exception as exc:  # noqa: BLE001
            print(f"Date filter {params} failed: {exc}")
            continue

        min_date, max_date = get_page_date_range(rows)
        if not rows:
            print(f"Date filter OK (0 rows): {params}")
            return params, container, rows

        overlaps = (
            min_date is not None
            and max_date is not None
            and min_date <= end_date
            and max_date >= start_date
        )
        looks_unfiltered = (
            baseline_max is not None
            and max_date == baseline_max
            and min_date == baseline_min
            and max_date is not None
            and max_date > end_date
            and (baseline_min is None or start_date < baseline_min)
        )
        if overlaps and not looks_unfiltered:
            print(f"Date filter OK: {params} page1 {min_date}→{max_date}")
            return params, container, rows
        print(
            f"Date filter not useful: {params} page1 {min_date}→{max_date} "
            f"(baseline {baseline_min}→{baseline_max})"
        )
    return None


def _fetch_page_bundle(
    session: requests.Session,
    page_number: int,
    cache: dict[int, tuple[list[dict[str, str]], date | None, date | None]],
    *,
    extra_params: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], date | None, date | None]:
    if page_number in cache and not extra_params:
        return cache[page_number]
    html = fetch_page_html(session, page_number, extra_params=extra_params)
    rows = extract_rows_from_container(get_container(BeautifulSoup(html, "html.parser")))
    min_date, max_date = get_page_date_range(rows)
    bundle = (rows, min_date, max_date)
    if not extra_params:
        cache[page_number] = bundle
    return bundle


def _binary_find_first_page_overlapping_end(
    session: requests.Session,
    total_pages: int,
    end_date: date,
    cache: dict[int, tuple[list[dict[str, str]], date | None, date | None]],
) -> int:
    """Smallest page index whose oldest row is <= end_date (pages are newest-first)."""
    lo, hi = 1, total_pages
    answer = total_pages
    while lo <= hi:
        mid = (lo + hi) // 2
        _rows, min_date, max_date = _fetch_page_bundle(session, mid, cache)
        if min_date is None:
            # Empty / unparsable — search later pages cautiously.
            lo = mid + 1
            continue
        if min_date <= end_date:
            answer = mid
            hi = mid - 1
        else:
            # Entire page newer than end_date — need older pages.
            lo = mid + 1
    return answer


def _binary_find_last_page_overlapping_start(
    session: requests.Session,
    total_pages: int,
    start_date: date,
    cache: dict[int, tuple[list[dict[str, str]], date | None, date | None]],
) -> int:
    """Largest page index whose newest row is >= start_date."""
    lo, hi = 1, total_pages
    answer = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        _rows, min_date, max_date = _fetch_page_bundle(session, mid, cache)
        if max_date is None:
            hi = mid - 1
            continue
        if max_date >= start_date:
            answer = mid
            lo = mid + 1
        else:
            # Entire page older than start_date — need newer pages.
            hi = mid - 1
    return answer


def scrape_reports_for_date_range(
    start_date: date,
    end_date: date,
    *,
    after_datetime: datetime | None = None,
) -> list[dict[str, str]]:
    """
    Collect reports with Creation date in [start_date, end_date].

    Strategy (fast for past days deep in the admin list):
    1. Try Django admin date-filter query params when possible.
    2. Else binary-search pagination to jump near the target window, then
       only walk the overlapping pages (not from page 1 through every month).
    3. Optional after_datetime: keep only newer rows and stop early (incremental
       refresh when that day was already partially scraped).
    """
    if end_date < start_date:
        raise ValueError("end_date must be >= start_date")

    load_dotenv(ENV_PATH)
    session = create_session()
    login_with_django_admin(session)

    print(f"Collecting reports from {start_date.isoformat()} to {end_date.isoformat()}")
    if after_datetime is not None:
        print(f"Incremental: only rows after {after_datetime.isoformat()}")

    all_matches: list[dict[str, str]] = []

    def keep_row(row: dict[str, str]) -> bool:
        parsed = parse_creation_datetime(row.get("Creation datetime", ""))
        if not parsed:
            return False
        if not (start_date <= parsed.date() <= end_date):
            return False
        if after_datetime is not None and parsed <= after_datetime:
            return False
        return True

    def collect(rows: list[dict[str, str]]) -> tuple[date | None, date | None, datetime | None]:
        newest: datetime | None = None
        for row in rows:
            parsed = parse_creation_datetime(row.get("Creation datetime", ""))
            if parsed and (newest is None or parsed > newest):
                newest = parsed
            if keep_row(row):
                all_matches.append(row)
        min_date, max_date = get_page_date_range(rows)
        return min_date, max_date, newest

    # --- Path A: server-side date filter ---
    filtered = _try_admin_date_filter(session, start_date, end_date)
    if filtered is not None:
        params, first_container, first_rows = filtered
        total_pages = get_total_pages(first_container)
        print(f"Filtered list pages: {total_pages}")
        min_date, max_date, newest = collect(first_rows)
        print(f"Filtered page 1: matched so far {len(all_matches)}")
        # Incremental stop: whole page older than watermark.
        if (
            after_datetime is not None
            and newest is not None
            and newest <= after_datetime
            and not any(keep_row(r) for r in first_rows)
        ):
            return all_matches
        for page_number in range(2, total_pages + 1):
            html = fetch_page_html(session, page_number, extra_params=params)
            rows = extract_rows_from_container(
                get_container(BeautifulSoup(html, "html.parser"))
            )
            if not rows:
                break
            min_date, max_date, newest = collect(rows)
            print(f"Filtered page {page_number}: matched so far {len(all_matches)}")
            if min_date is not None and min_date < start_date:
                break
            if after_datetime is not None and newest is not None and newest <= after_datetime:
                break
        return all_matches

    # --- Path B: binary search on newest-first pages ---
    first_html = fetch_page_html(session, 1)
    first_container = get_container(BeautifulSoup(first_html, "html.parser"))
    total_pages = get_total_pages(first_container)
    print(f"Detected total pages: {total_pages}")

    cache: dict[int, tuple[list[dict[str, str]], date | None, date | None]] = {}
    first_rows = extract_rows_from_container(first_container)
    cache[1] = (first_rows, *get_page_date_range(first_rows))

    page1_min, page1_max = get_page_date_range(first_rows)
    # If the target window is still on/near page 1, just walk forward (fast path).
    if page1_min is not None and page1_min <= end_date:
        start_page = 1
    else:
        start_page = _binary_find_first_page_overlapping_end(
            session, total_pages, end_date, cache
        )
    end_page = _binary_find_last_page_overlapping_start(
        session, total_pages, start_date, cache
    )
    if end_page < start_page:
        # Expand total_pages once if estimate was low, then retry end bound.
        probe_page = total_pages
        for _ in range(6):
            rows, min_date, max_date = _fetch_page_bundle(session, probe_page, cache)
            if not rows:
                break
            # If last estimated page still overlaps / is newer than start, peek further.
            if max_date is not None and max_date >= start_date:
                probe_page += max(1, total_pages // 4)
                # Refresh total from this page's paginator if possible.
                html = fetch_page_html(session, probe_page)
                container = get_container(BeautifulSoup(html, "html.parser"))
                rows = extract_rows_from_container(container)
                cache[probe_page] = (rows, *get_page_date_range(rows))
                total_pages = max(total_pages, get_total_pages(container), probe_page)
                end_page = _binary_find_last_page_overlapping_start(
                    session, total_pages, start_date, cache
                )
                if end_page >= start_page:
                    break
            else:
                break
        if end_page < start_page:
            print(
                f"No pages overlap {start_date}→{end_date} "
                f"(search window pages {start_page}..{end_page})"
            )
            return []

    print(f"Jumping to pages {start_page}→{end_page} (of ~{total_pages})")
    for page_number in range(start_page, end_page + 1):
        rows, min_date, max_date = _fetch_page_bundle(session, page_number, cache)
        if not rows:
            break
        _mn, _mx, newest = collect(rows)
        print(
            f"Page {page_number} ({min_date}→{max_date}): matched so far {len(all_matches)}"
        )
        if min_date is not None and min_date < start_date:
            break
        if after_datetime is not None and newest is not None and newest <= after_datetime:
            # Remaining rows on later pages are older.
            if max_date is not None and max_date <= start_date:
                break
            # For same-day incremental from page 1, stop once everything is <= watermark.
            if start_page == 1 and start_date == end_date:
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
