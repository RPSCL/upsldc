"""
Fetches live UPSLDC data and appends one row to upsldc_hourly_data.csv
in the repo root.

Data older than 120 days is automatically moved to historical.csv.
"""

import os
import csv
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import requests


MAIN_URL = "https://www.upsldc.org/assets/dataset/realtime.json"
SUMMARY_URL = "https://www.upsldc.org/assets/dataset/real-time-summary.json"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_CSV = os.path.join(
    BASE_DIR,
    "upsldc_hourly_data.csv"
)

HISTORICAL_CSV = os.path.join(
    BASE_DIR,
    "historical.csv"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


PROXY_URL_TEMPLATES = [
    "https://api.codetabs.com/v1/proxy?quest={target}",
    "https://api.allorigins.win/raw?url={target}",
]


PLANT_SEQUENCE = [
    "MEJA",
    "LANCO",
    "BARA",
    "TANDA",
    "LALITPUR",
    "Harduaganj Ex2",
    "ROSA 1",
    "ROSA 2",
]


PLANT_MAPPING = {
    "MEJA": "MejaUrjaNigamPvtLtd",
    "LANCO": "MEILANPARAENERGYLIMITED",
    "BARA": "PRAYAGRAJSUPERCRITICALTPPBARA",
    "TANDA": "THDCIndiaLimitedKhurja",
    "LALITPUR": "LALITPURPOWERGENERATIONCOMPANYLIMITED",
    "Harduaganj Ex2": "Harduaganj1X660MWUPRVUNL",
    "ROSA 1": "ROSA-I",
    "ROSA 2": "ROSA-II",
}


def header_row():

    header = [
        "Date",
        "Time",
        "TOTAL_DEMAND",
        "SOLAR_GEN"
    ]

    for key in PLANT_SEQUENCE:

        header += [
            f"{key}_DC",
            f"{key}_SG",
            f"{key}_AG",
        ]

    return header


def clean(s):

    return (
        (s or "")
        .lower()
        .replace(" ", "")
    )


def prepare_csv():
    """
    Always runs first.

    1. Creates upsldc_hourly_data.csv with header if it doesn't exist.
    2. Adds/replaces header if existing file has no valid header.
    3. Moves rows older than 120 days to historical.csv.
    4. Keeps only the latest 120 days in upsldc_hourly_data.csv.
    """

    expected_header = header_row()

    # ==========================================================
    # CREATE MAIN CSV IF IT DOES NOT EXIST
    # ==========================================================

    if not os.path.exists(OUTPUT_CSV):

        with open(
            OUTPUT_CSV,
            "w",
            newline="",
            encoding="utf-8"
        ) as f:

            writer = csv.writer(f)
            writer.writerow(expected_header)

        return


    # ==========================================================
    # READ EXISTING MAIN CSV
    # ==========================================================

    with open(
        OUTPUT_CSV,
        "r",
        newline="",
        encoding="utf-8"
    ) as f:

        rows = list(csv.reader(f))


    if not rows:
        rows = []


    # ==========================================================
    # CHECK HEADER
    # ==========================================================

    has_valid_header = (
        len(rows) > 0
        and rows[0] == expected_header
    )


    if has_valid_header:

        data_rows = rows[1:]

    else:

        # Assume all existing rows are data
        data_rows = rows


    # ==========================================================
    # 120-DAY CUTOFF
    # ==========================================================

    cutoff_date = (
        datetime.now().date()
        - timedelta(days=120)
    )


    valid_rows = []
    historical_rows = []


    # ==========================================================
    # SEPARATE CURRENT AND HISTORICAL DATA
    # ==========================================================

    for row in data_rows:

        # Ignore completely empty rows
        if not row or not any(
            cell.strip() for cell in row
        ):
            continue


        try:

            row_date = datetime.strptime(
                row[0].strip(),
                "%d-%b-%y"
            ).date()


            # Older than 120 days
            if row_date < cutoff_date:

                historical_rows.append(row)

            else:

                valid_rows.append(row)


        except (ValueError, IndexError):

            # Keep rows that cannot be interpreted as dates
            # so valid data is not accidentally deleted.

            valid_rows.append(row)


    # ==========================================================
    # APPEND PURGED DATA TO historical.csv
    # ==========================================================

    if historical_rows:

        historical_exists = os.path.exists(
            HISTORICAL_CSV
        )


        with open(
            HISTORICAL_CSV,
            "a",
            newline="",
            encoding="utf-8"
        ) as f:

            writer = csv.writer(f)


            # Create header if historical.csv
            # does not exist or is empty

            if (
                not historical_exists
                or os.path.getsize(HISTORICAL_CSV) == 0
            ):

                writer.writerow(
                    expected_header
                )


            writer.writerows(
                historical_rows
            )


        print(
            f"Moved {len(historical_rows)} "
            f"rows to historical.csv"
        )


    # ==========================================================
    # REWRITE MAIN CSV
    # ==========================================================

    with open(
        OUTPUT_CSV,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            expected_header
        )

        writer.writerows(
            valid_rows
        )


def fetch_json(url):
    """
    Tries each proxy, then falls back to direct request.
    """

    last_error = None


    # ==========================================================
    # TRY PROXIES
    # ==========================================================

    for template in PROXY_URL_TEMPLATES:

        proxied_url = template.format(
            target=quote(
                url,
                safe=""
            )
        )


        try:

            resp = requests.get(
                proxied_url,
                headers=HEADERS,
                timeout=25
            )

            resp.raise_for_status()

            return resp.json()


        except Exception as e:

            last_error = e

            time.sleep(2)


    # ==========================================================
    # LAST RESORT: DIRECT REQUEST
    # ==========================================================

    try:

        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        resp.raise_for_status()

        return resp.json()


    except Exception as e:

        last_error = e


    raise RuntimeError(
        f"All fetch attempts failed for "
        f"{url}: {last_error}"
    )


def extract_summary(summary_json):

    demand = None
    solar = None


    def scan(obj):

        nonlocal demand, solar


        if isinstance(obj, dict):

            for k, v in obj.items():

                if (
                    k.upper() == "DEMAND_MW"
                    and demand is None
                ):

                    demand = v


                if (
                    k.upper()
                    == "RE_SOLAR_GENERATION_MW"
                    and solar is None
                ):

                    solar = v


                scan(v)


        elif isinstance(obj, list):

            for item in obj:

                scan(item)


    scan(summary_json)


    return demand, solar


def extract_plants(main_json):

    plant_data = {
        key: {
            "DC": 0,
            "SG": 0,
            "AG": 0
        }
        for key in PLANT_SEQUENCE
    }


    all_generators = []


    # ==========================================================
    # COLLECT GENERATORS
    # ==========================================================

    if isinstance(main_json, dict):

        for v in main_json.values():

            if isinstance(v, list):

                all_generators.extend(v)


    elif isinstance(main_json, list):

        all_generators = main_json


    # ==========================================================
    # PROCESS GENERATORS
    # ==========================================================

    for gen in all_generators:

        if not isinstance(gen, dict):
            continue


        gen_name = clean(
            gen.get(
                "GEN_NAME",
                ""
            )
        )


        actual = (
            gen.get(
                "ACTUAL",
                0
            )
            or 0
        )


        schedule = (
            gen.get(
                "SCHEDULE",
                0
            )
            or 0
        )


        dc = (
            gen.get(
                "DC",
                0
            )
            or 0
        )


        matched_key = None


        # ======================================================
        # EXACT MATCH
        # ======================================================

        for key, mapped_name in PLANT_MAPPING.items():

            if (
                gen_name
                == clean(mapped_name)
            ):

                matched_key = key
                break


        # ======================================================
        # PARTIAL MATCH
        # ======================================================

        if matched_key is None:

            for key, mapped_name in PLANT_MAPPING.items():

                short = clean(
                    mapped_name
                )[:13]


                if (
                    short
                    and short in gen_name
                ):

                    matched_key = key
                    break


        # ======================================================
        # SAVE PLANT DATA
        # ======================================================

        if matched_key:

            try:

                plant_data[matched_key] = {

                    "DC": round(
                        float(dc)
                    ),

                    "SG": round(
                        float(schedule)
                    ),

                    "AG": round(
                        float(actual)
                    ),

                }


            except (
                TypeError,
                ValueError
            ):

                pass


    return plant_data


def round_to_nearest_10_minutes(dt):

    discard = timedelta(
        minutes=dt.minute % 15,
        seconds=dt.second,
        microseconds=dt.microsecond
    )


    rounded = dt - discard


    # ==========================================================
    # ROUND UP IF 8 MINUTES OR MORE INTO INTERVAL
    # ==========================================================

    if dt.minute % 15 >= 8:

        rounded += timedelta(
            minutes=15
        )


    return rounded


def build_row(
    main_json,
    summary_json
):

    now = round_to_nearest_10_minutes(
        datetime.now()
    )


    date_str = now.strftime(
        "%d-%b-%y"
    )


    time_str = now.strftime(
        "%H:%M"
    )


    demand, solar = extract_summary(
        summary_json
    )


    plants = extract_plants(
        main_json
    )


    row = [
        date_str,
        time_str,
        demand,
        solar
    ]


    for key in PLANT_SEQUENCE:

        p = plants[key]


        row += [
            p["DC"],
            p["SG"],
            p["AG"]
        ]


    return row


def append_row(row):

    with open(
        OUTPUT_CSV,
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        writer.writerow(row)


def main():

    # ==========================================================
    # ALWAYS RUN THIS FIRST
    # ==========================================================
    # Create/fix header and move data older than 120 days
    # to historical.csv.

    prepare_csv()


    # ==========================================================
    # FETCH UPSLDC DATA
    # ==========================================================

    main_json = fetch_json(
        MAIN_URL
    )


    summary_json = fetch_json(
        SUMMARY_URL
    )


    # ==========================================================
    # BUILD ROW
    # ==========================================================

    row = build_row(
        main_json,
        summary_json
    )


    # ==========================================================
    # APPEND NEW DATA
    # ==========================================================

    append_row(
        row
    )


    print(
        "Successful"
    )


if __name__ == "__main__":
    main()