from __future__ import annotations

from scrape_247_transfers import run_for_year


YEARS = list(range(2018, 2027))


def main() -> None:
    for year in YEARS:
        print(f"Scraping transfers for {year}", flush=True)
        run_for_year(year)


if __name__ == "__main__":
    main()
