from datetime import datetime

from review import main as review_main
from scrape import main as scrape_main

PROMPT_DATE_FORMAT = "%d-%m-%Y"


def prompt_for_date() -> str:
    while True:
        value = input("Enter date to scrape (dd-mm-yyyy): ").strip()
        try:
            datetime.strptime(value, PROMPT_DATE_FORMAT)
            return value
        except ValueError:
            print("Invalid date format. Please use dd-mm-yyyy.")


def main() -> int:
    print("Starting scrape and local review workflow")
    input_date = prompt_for_date()
    print(f"Selected date: {input_date}")
    print()

    print("[1/2] Collecting reports...")
    scrape_status = scrape_main(input_date)
    if scrape_status != 0:
        print("Could not build all_reports.csv. Stopping workflow.")
        return scrape_status

    print()
    print("[2/2] Building local review files...")
    review_status = review_main(input_date)
    if review_status != 0:
        print(
            "Review pipeline failed. Check log.txt inside the selected date folder under output/."
        )
        return review_status

    print()
    print("Workflow completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
