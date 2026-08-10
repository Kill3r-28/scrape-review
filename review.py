from __future__ import annotations

import csv
import json
import re
import time
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests as req
from bs4 import BeautifulSoup, Tag

from scrape import (
    BASE_URL,
    ENV_PATH,
    TIMEOUT_SECONDS,
    create_session,
    fetch_question_summary,
    fetch_question_tags,
    get_all_reports_csv_path,
    get_env,
    get_output_dir_for_date,
    is_login_page,
    load_dotenv,
    login_with_django_admin,
    parse_input_date,
)

PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.md"
QUESTION_SEARCH_URL = f"{BASE_URL}/admin/nkb_question/question/"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat-v3.1"
LLM_MAX_RETRIES = 5
LLM_RETRY_BACKOFF_SECONDS = 5
LLM_JSON_REPAIR_ATTEMPTS = 3

MCQ_HEADERS = [
    "User id",
    "Question id",
    "Question tags",
    "Students claim",
    "AI diagnosis",
    "Question",
    "Option 1",
    "Option 2",
    "Option 3",
    "Option 4",
    "Correct option",
    "LLM assessment",
    "LLM suspected issue type",
    "LLM best answer",
    "Action item for content team",
    "Message to student",
]

COMPUTER_SCIENCE_KEYWORDS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "html",
    "css",
    "sql",
    "query",
    "database",
    "dbms",
    "api",
    "json",
    "xml",
    "frontend",
    "backend",
    "function",
    "variable",
    "array",
    "linked list",
    "stack",
    "queue",
    "tree",
    "graph",
    "algorithm",
    "time complexity",
    "space complexity",
    "compiler",
    "program",
    "code",
    "output",
    "bug",
    "debug",
    "class",
    "object",
    "oop",
    "exception",
    "network",
    "operating system",
    "thread",
    "process",
    "binary search",
    "recursion",
    "node",
    "table",
    "schema",
    "primary key",
    "foreign key",
    "join",
    "select ",
    "insert ",
    "update ",
    "delete ",
    "c++",
    "c language",
    "java.lang",
}


def get_output_paths(input_date: str) -> tuple[Path, Path, Path]:
    target_date = parse_input_date(input_date)
    output_dir = get_output_dir_for_date(target_date)
    return (
        get_all_reports_csv_path(target_date),
        output_dir / "to_review_mcq.csv",
        output_dir / "log.txt",
    )


def append_log(log_path: Path, title: str, details: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {title}\n")
        file.write(details.rstrip() + "\n\n")


def log_exception(log_path: Path, title: str, exc: Exception) -> None:
    append_log(log_path, title, f"{exc}\n\n{traceback.format_exc()}")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


@lru_cache(maxsize=1)
def load_prompt_map() -> dict[str, str]:
    if not PROMPTS_PATH.exists():
        raise ValueError(f"Missing prompts file: {PROMPTS_PATH}")

    prompts: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in PROMPTS_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current_name is not None:
                prompts[current_name] = "\n".join(current_lines).strip()
            current_name = line[3:].strip()
            current_lines = []
            continue
        if current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        prompts[current_name] = "\n".join(current_lines).strip()

    return prompts


def get_prompt_template(name: str) -> str:
    prompts = load_prompt_map()
    if name not in prompts:
        raise ValueError(f"Prompt not found in prompts.md: {name}")
    return prompts[name]


def render_prompt(template: str, replacements: dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    return cleaned.strip()


def extract_first_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1]


def parse_json_text(text: str) -> dict[str, Any]:
    cleaned = strip_code_fences(text)
    if not cleaned:
        raise ValueError("LLM response text was empty.")

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        extracted = extract_first_json_object(cleaned)
        if not extracted:
            raise
        parsed = json.loads(extracted)

    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object.")
    return parsed


def get_openrouter_headers() -> dict[str, str]:
    api_key = get_env("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENROUTER_API_KEY in .env.")

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": get_env("OPENROUTER_REFERER") or "https://localhost",
        "X-Title": get_env("OPENROUTER_TITLE") or "scrape-review",
    }


def get_openrouter_model() -> str:
    return get_env("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL


def extract_openrouter_text(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenRouter response did not contain choices.")

    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("OpenRouter choice was malformed.")

    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("OpenRouter response did not contain a message.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenRouter response did not contain text content.")

    return content.strip()


def call_openrouter_with_retries(
    prompt: str, model: str | None = None
) -> dict[str, Any]:
    headers = get_openrouter_headers()
    selected_model = model or get_openrouter_model()
    last_error: Exception | None = None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = req.post(
                OPENROUTER_URL,
                headers=headers,
                json={
                    "model": selected_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except req.RequestException as exc:
            last_error = exc
            if attempt == LLM_MAX_RETRIES:
                break
            wait_seconds = LLM_RETRY_BACKOFF_SECONDS * attempt
            print(
                f"\nOpenRouter request failed (attempt {attempt}/{LLM_MAX_RETRIES}): {exc}"
            )
            print(f"Retrying in {wait_seconds} seconds...")
            time.sleep(wait_seconds)

    if last_error is not None:
        raise last_error
    raise ValueError("OpenRouter request failed for an unknown reason.")


def build_json_retry_prompt(prompt: str) -> str:
    return (
        prompt
        + "\n\nIMPORTANT: Return only one valid JSON object."
        + " Do not include markdown, code fences, notes, or explanation outside JSON."
    )


def call_openrouter_json(
    prompt: str,
    model: str | None = None,
    log_path: Path | None = None,
    context_label: str = "LLM call",
) -> dict[str, Any]:
    current_prompt = prompt
    last_error: Exception | None = None

    for attempt in range(1, LLM_JSON_REPAIR_ATTEMPTS + 1):
        raw_text = ""
        try:
            response_json = call_openrouter_with_retries(current_prompt, model=model)
            raw_text = extract_openrouter_text(response_json)
            return parse_json_text(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if log_path is not None:
                append_log(
                    log_path,
                    f"{context_label} returned invalid JSON",
                    f"Attempt: {attempt}/{LLM_JSON_REPAIR_ATTEMPTS}\n"
                    f"Model: {model or get_openrouter_model()}\n"
                    f"Error: {exc}\n"
                    f"Raw response:\n{raw_text or '[empty]'}",
                )
            if attempt == LLM_JSON_REPAIR_ATTEMPTS:
                break
            print(
                f"\nInvalid JSON from LLM. Retrying {attempt}/{LLM_JSON_REPAIR_ATTEMPTS}..."
            )
            current_prompt = build_json_retry_prompt(prompt)

    if last_error is not None:
        raise ValueError(
            f"{context_label} failed after {LLM_JSON_REPAIR_ATTEMPTS} attempts."
        ) from last_error
    raise ValueError(f"{context_label} failed for an unknown reason.")




def normalize_question_type(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def is_multiple_choice_question(value: str) -> bool:
    return normalize_question_type(value) in {"multiplechoice", "mcq"}


def get_input_or_textarea_value(soup: BeautifulSoup, field_name: str) -> str:
    candidates = [
        soup.find(id=field_name),
        soup.find(id=f"id_{field_name}"),
        soup.find(True, attrs={"name": field_name}),
    ]
    for c in candidates:
        if not isinstance(c, Tag):
            continue
        if c.name == "textarea":
            return c.get_text(strip=True)
        val = c.get("value", "")
        if isinstance(val, str):
            return val.strip()
    return ""


def fetch_question_admin_page_html(session: req.Session, question_id: str) -> str:
    response = session.get(
        f"{QUESTION_SEARCH_URL}{question_id}",
        timeout=TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    response.raise_for_status()
    if is_login_page(response):
        raise ValueError(
            "Question detail request was redirected to the admin login page."
        )
    return response.text


def extract_mcq_details_from_html(html_content: str) -> dict[str, str]:
    soup = BeautifulSoup(html_content, "html.parser")
    options: list[str] = []
    correct_option = ""

    for idx in range(4):
        opt_text = get_input_or_textarea_value(soup, f"option_set-{idx}-content")
        options.append(opt_text)
        checkbox = soup.find(id=f"id_option_set-{idx}-is_correct")
        if isinstance(checkbox, Tag) and checkbox.has_attr("checked"):
            correct_option = opt_text

    while len(options) < 4:
        options.append("")

    return {
        "Option 1": options[0],
        "Option 2": options[1],
        "Option 3": options[2],
        "Option 4": options[3],
        "Correct option": correct_option,
    }


def build_multiple_choice_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    mcq_rows = [
        r for r in rows if is_multiple_choice_question(r.get("Question type", ""))
    ]
    if not mcq_rows:
        return []

    session = create_session()
    login_with_django_admin(session)
    detail_cache: dict[str, dict[str, str]] = {}
    summary_cache: dict[str, dict[str, str]] = {}
    tag_cache: dict[str, list[str]] = {}
    output_rows: list[dict[str, str]] = []
    total = len(mcq_rows)

    for idx, row in enumerate(mcq_rows, start=1):
        print(f"\rPreparing MCQs {idx}/{total}", end="", flush=True)
        qid = row.get("Question id", "").strip()

        details = {
            "Option 1": "",
            "Option 2": "",
            "Option 3": "",
            "Option 4": "",
            "Correct option": "",
        }
        if qid:
            if qid not in detail_cache:
                detail_cache[qid] = extract_mcq_details_from_html(
                    fetch_question_admin_page_html(session, qid)
                )
            details = detail_cache[qid]

        question_text = row.get("Question text", "").strip()
        if not question_text and qid:
            if qid not in summary_cache:
                summary_cache[qid] = fetch_question_summary(session, qid)
            question_text = summary_cache[qid].get("Question text", "").strip()

        question_tags = row.get("Question tags", "").strip()
        if not question_tags and qid:
            if qid not in tag_cache:
                tag_cache[qid] = fetch_question_tags(session, qid)
            question_tags = ", ".join(tag_cache[qid])

        output_rows.append(
            {
                "User id": row.get("User id", ""),
                "Question id": row.get("Question id", ""),
                "Question tags": question_tags,
                "Students claim": row.get("Description", ""),
                "AI diagnosis": build_report_context(row),
                "Question": question_text,
                "Option 1": details.get("Option 1", ""),
                "Option 2": details.get("Option 2", ""),
                "Option 3": details.get("Option 3", ""),
                "Option 4": details.get("Option 4", ""),
                "Correct option": details.get("Correct option", ""),
            }
        )

    print()
    return output_rows


def build_report_context(row: dict[str, str]) -> str:
    parts = []
    for label, key in (
        ("Category", "Category"),
        ("Sub category", "Sub category"),
        ("Topic tag", "Topic tag"),
        ("Question tags", "Question tags"),
    ):
        value = row.get(key, "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


# Keep future question-type expansion here, e.g. build_coding_rows(source_rows).
def mcq_row_key(row: dict[str, str]) -> str:
    fields = [
        "User id",
        "Question id",
        "Question tags",
        "Students claim",
        "AI diagnosis",
        "Question",
        "Option 1",
        "Option 2",
        "Option 3",
        "Option 4",
        "Correct option",
    ]
    return json.dumps(
        {f: row.get(f, "") for f in fields}, ensure_ascii=False, sort_keys=True
    )


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        w = csv.DictWriter(file, fieldnames=headers)
        w.writeheader()
        w.writerows([{h: r.get(h, "") for h in headers} for r in rows])


def detect_question_domain_heuristically(row: dict[str, str]) -> str:
    text = " ".join(
        [
            row.get("Question", ""),
            row.get("Option 1", ""),
            row.get("Option 2", ""),
            row.get("Option 3", ""),
            row.get("Option 4", ""),
        ]
    ).lower()
    return (
        "computer_science"
        if any(kw in text for kw in COMPUTER_SCIENCE_KEYWORDS)
        else "non_computer_science"
    )


def get_row_review_config(row: dict[str, str]) -> dict[str, str]:
    domain = detect_question_domain_heuristically(row)
    return {
        "question_domain": domain,
        "model": get_openrouter_model(),
        "prompt_name": "MCQ_CORRECTNESS_REVIEW_CS_PROMPT"
        if domain == "computer_science"
        else "MCQ_CORRECTNESS_REVIEW_NON_CS_PROMPT",
    }


def review_mcq_row_with_llm(
    row: dict[str, str], config: dict[str, str], log_path: Path, row_number: int
) -> dict[str, str]:
    prompt_template = get_prompt_template(config["prompt_name"])
    prompt = render_prompt(
        prompt_template,
        {
            "STUDENT_CLAIM": row.get("Students claim", ""),
            "AI_DIAGNOSIS": row.get("AI diagnosis", ""),
            "QUESTION": row.get("Question", ""),
            "OPTION_1": row.get("Option 1", ""),
            "OPTION_2": row.get("Option 2", ""),
            "OPTION_3": row.get("Option 3", ""),
            "OPTION_4": row.get("Option 4", ""),
            "CORRECT_OPTION": row.get("Correct option", ""),
        },
    )
    return call_openrouter_json(
        prompt,
        model=config["model"],
        log_path=log_path,
        context_label=f"MCQ row {row_number}",
    )


def _sanitize_reviewed_row(row: dict[str, str]) -> dict[str, str]:
    if row.get("LLM assessment") == "likely_valid_concern":
        best = row.get("LLM best answer", "").strip()
        correct = row.get("Correct option", "").strip()
        if best and best == correct:
            row["LLM assessment"] = "likely_not_a_content_issue"
            if row.get("LLM suspected issue type") in (
                "wrong_answer_key",
                "incorrect_option_text",
            ):
                row["LLM suspected issue type"] = "not_a_content_issue"
    return row


def should_rebuild_mcq_output(
    existing_rows: list[dict[str, str]], fresh_rows: list[dict[str, str]]
) -> bool:
    if not existing_rows:
        return False

    existing_has_empty_question = any(
        not r.get("Question", "").strip() for r in existing_rows
    )
    fresh_has_question = any(r.get("Question", "").strip() for r in fresh_rows)
    if existing_has_empty_question and fresh_has_question:
        return True

    existing_missing_ids = any(
        "User id" not in r or "Question id" not in r for r in existing_rows
    )
    fresh_has_ids = any(
        r.get("User id", "").strip() or r.get("Question id", "").strip()
        for r in fresh_rows
    )
    if existing_missing_ids and fresh_has_ids:
        return True

    existing_missing_tags = any("Question tags" not in r for r in existing_rows)
    fresh_has_tags = any(r.get("Question tags", "").strip() for r in fresh_rows)
    return existing_missing_tags and fresh_has_tags


def review_multiple_choice_rows_with_llm(
    rows: list[dict[str, str]], output_path: Path, log_path: Path
) -> list[dict[str, str]]:
    if not rows:
        write_csv(output_path, MCQ_HEADERS, [])
        return []

    completed = read_csv_rows(output_path) if output_path.exists() else []
    if should_rebuild_mcq_output(completed, rows):
        print("Found stale MCQ output. Rebuilding it with latest fields...")
        completed = []

    completed_keys = {mcq_row_key(r) for r in completed}
    reviewed = list(completed)
    pending = [r for r in rows if mcq_row_key(r) not in completed_keys]

    if completed:
        print(f"Resuming MCQ review from {len(completed)}/{len(rows)}")

    for row in pending:
        done = len(reviewed) + 1
        config = get_row_review_config(row)
        label = "CS" if config["question_domain"] == "computer_science" else "Non-CS"
        print(
            f"\rRunning MCQ review {done}/{len(rows)} [{label} prompt -> DeepSeek]",
            end="",
            flush=True,
        )

        try:
            parsed = review_mcq_row_with_llm(row, config, log_path, done)
        except Exception as exc:
            append_log(
                log_path,
                "MCQ review crashed",
                f"Row: {done}/{len(rows)}\nQuestion domain: {config['question_domain']}\nClaim: {row.get('Students claim', '')}\nQuestion: {row.get('Question', '')}\nCorrect: {row.get('Correct option', '')}\nError: {exc}",
            )
            raise ValueError(
                f"MCQ review stopped at row {done}. Re-run to resume. See {log_path}."
            ) from exc

        reviewed_row = dict(row)
        reviewed_row["LLM assessment"] = str(parsed.get("assessment", "")).strip()
        reviewed_row["LLM suspected issue type"] = str(
            parsed.get("suspected_issue_type", "")
        ).strip()
        reviewed_row["LLM best answer"] = str(parsed.get("best_answer", "")).strip()
        reviewed_row["Action item for content team"] = str(
            parsed.get("action_item_for_content_team", "")
        ).strip()
        reviewed_row["Message to student"] = str(
            parsed.get("message_to_student", "")
        ).strip()
        reviewed_row = _sanitize_reviewed_row(reviewed_row)
        reviewed.append(reviewed_row)
        write_csv(output_path, MCQ_HEADERS, reviewed)

    if rows:
        print()

    return reviewed


def main(input_date: str | None = None) -> int:
    load_dotenv(ENV_PATH)
    date_text = input_date or "21-06-2026"
    log_path = Path(__file__).resolve().parent / "output" / "log.txt"

    try:
        source_csv, output_path, log_path = get_output_paths(date_text)
        append_log(log_path, "Review run started", f"Input date: {date_text}")

        print(f"Using reports file: {source_csv}")
        source_rows = read_csv_rows(source_csv)
        print(f"Loaded {len(source_rows)} reports")

        print("Building multiple-choice rows...")
        mcq_rows = build_multiple_choice_rows(source_rows)
        print(f"Prepared {len(mcq_rows)} MCQ rows")

        print("Reviewing with domain-routed prompts...")
        review_multiple_choice_rows_with_llm(mcq_rows, output_path, log_path)
    except FileNotFoundError as exc:
        append_log(log_path, "Review run failed", str(exc))
        print("all_reports.csv not found. Run scraping first.")
        print(f"See log: {log_path}")
        return 1
    except req.RequestException as exc:
        log_exception(log_path, "Review request error", exc)
        print(f"Request failed: {exc}\nSee log: {log_path}")
        return 1
    except json.JSONDecodeError as exc:
        log_exception(log_path, "Review JSON parse error", exc)
        print(f"LLM JSON parse failed: {exc}\nSee log: {log_path}")
        return 1
    except ValueError as exc:
        log_exception(log_path, "Review value error", exc)
        print(f"{exc}\nSee log: {log_path}")
        return 1
    except Exception as exc:
        log_exception(log_path, "Review unexpected error", exc)
        print(f"Unexpected error: {exc}\nSee log: {log_path}")
        return 1

    print(f"Saved to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
