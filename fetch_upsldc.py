"""
Fetches live UPSLDC data and appends one row to upsldc_hourly_data.csv.
Runs every 5 minutes.

At 00:00 every day:
- Yesterday remains at 5-minute frequency.
- Previous 10 days are reduced to 15-minute frequency.
- Older data is reduced to hourly frequency.
- Data older than 120 days is moved to historical.csv.

Additional data protection:
1. Rows having more than 20 zero values are removed on startup.
2. New rows having more than 20 zero values are rejected.
3. If a numeric value remains exactly the same for more than 2
   consecutive rows, it is considered potentially stuck.
4. Once a different value appears after the stuck section, the
   stuck values are linearly interpolated between the value before
   and the value after the stuck section.
5. If the stuck section is at the end of the CSV, it is not changed
   until a recovery/different value becomes available.
"""

import os
import csv
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import requests


# ============================================================
# CONFIGURATION
# ============================================================

MAIN_URL = "https://www.upsldc.org/assets/dataset/realtime.json"
SUMMARY_URL = "https://www.upsldc.org/assets/dataset/real-time-summary.json"

BOT_TOKEN = "5588744140:AAFMzYGBbQDzZ_hYDf9d1WSTHmC3I-Z3kZk#"
TST_ID = "-1003175374557"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_CSV = os.path.join(
    BASE_DIR,
    "upsldc_hourly_data.csv"
)

HISTORICAL_CSV = os.path.join(
    BASE_DIR,
    "historical.csv"
)


# ============================================================
# HTTP SETTINGS
# ============================================================

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


# ============================================================
# PLANT CONFIGURATION
# ============================================================

PLANT_SEQUENCE = [
    "MEJA",
    "ROSA 1",
    "ROSA 2",
    "LALITPUR"
]


PLANT_MAPPING = {
    "MEJA": "MejaUrjaNigamPvtLtd",
    "ROSA 1": "ROSA-I",
    "ROSA 2": "ROSA-II",
    "LALITPUR": "LALITPURPOWERGENERATIONCOMPANYLIMITED",
}


# ============================================================
# CSV HEADER
# ============================================================

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
            f"{key}_AG"
        ]

    return header


# ============================================================
# BASIC HELPERS
# ============================================================

def clean(s):

    return (
        s or ""
    ).lower().replace(" ", "")


def count_zero_values(row):
    """
    Count numeric zero values.

    Date and Time are ignored.
    Counting starts from TOTAL_DEMAND.
    """

    zero_count = 0

    for cell in row[2:]:

        try:

            if float(cell) == 0:
                zero_count += 1

        except (ValueError, TypeError):

            pass

    return zero_count


# ============================================================
# REMOVE BAD ZERO ROWS
# ============================================================

def remove_zero_rows():
    """
    Runs every time the script starts.

    Deletes any existing row containing more than
    20 numeric zero values.
    """

    if not os.path.exists(OUTPUT_CSV):
        return

    expected_header = header_row()

    try:

        with open(
            OUTPUT_CSV,
            "r",
            newline="",
            encoding="utf-8"
        ) as f:

            rows = list(
                csv.reader(f)
            )

        if not rows:
            return

        if rows[0] == expected_header:

            data_rows = rows[1:]

        else:

            data_rows = rows

        retained_rows = []

        removed_count = 0

        for row in data_rows:

            if (
                not row
                or not any(
                    cell.strip()
                    for cell in row
                )
            ):
                continue

            zero_count = count_zero_values(
                row
            )

            if zero_count > 20:

                removed_count += 1

                date_value = (
                    row[0]
                    if len(row) > 0
                    else "Unknown"
                )

                time_value = (
                    row[1]
                    if len(row) > 1
                    else "Unknown"
                )

                print(
                    f"Removed bad row: "
                    f"{date_value} {time_value} "
                    f"({zero_count} zero values)"
                )

            else:

                retained_rows.append(row)

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
                retained_rows
            )

        print(
            f"Zero-value cleanup complete: "
            f"{removed_count} rows removed"
        )

    except Exception as e:

        print(
            f"Could not remove zero-value rows: {e}"
        )


# ============================================================
# SMOOTH STUCK DATA
# ============================================================

def smooth_stuck_values():
    """
    Detects values that remain exactly the same for
    MORE THAN 2 consecutive rows.

    Example:

        07:30   1325
        07:35   1325
        07:40   1325
        07:45   1325
        07:50   1100

    The 4 repeated values are considered stuck.

    They are replaced by linearly interpolated values
    between 1325 and 1100.

    The Date and Time columns are never modified.

    A stuck section at the END of the CSV is left alone
    until a different/recovery value becomes available.
    """

    if not os.path.exists(OUTPUT_CSV):
        return

    expected_header = header_row()

    try:

        with open(
            OUTPUT_CSV,
            "r",
            newline="",
            encoding="utf-8"
        ) as f:

            rows = list(
                csv.reader(f)
            )

        if len(rows) < 5:
            return

        if rows[0] != expected_header:

            print(
                "Smoothing skipped: "
                "CSV header does not match expected header."
            )

            return

        data_rows = rows[1:]

        if len(data_rows) < 4:
            return

        changed_count = 0

        # ----------------------------------------------------
        # Process each numeric column independently.
        #
        # Columns:
        # 0 = Date
        # 1 = Time
        # 2 onward = numeric data
        # ----------------------------------------------------

        for col in range(2, len(expected_header)):

            i = 1

            while i < len(data_rows) - 1:

                # Try to read current value.
                try:

                    current_value = float(
                        data_rows[i][col]
                    )

                except (
                    ValueError,
                    TypeError,
                    IndexError
                ):

                    i += 1
                    continue

                # ------------------------------------------------
                # Find how many consecutive rows have exactly
                # the same value.
                # ------------------------------------------------

                run_start = i
                run_end = i

                while (
                    run_end + 1 < len(data_rows)
                ):

                    try:

                        next_value = float(
                            data_rows[
                                run_end + 1
                            ][col]
                        )

                    except (
                        ValueError,
                        TypeError,
                        IndexError
                    ):

                        break

                    if next_value == current_value:

                        run_end += 1

                    else:

                        break

                run_length = (
                    run_end - run_start + 1
                )

                # ------------------------------------------------
                # Only act if MORE THAN 2 rows have same value.
                # Therefore minimum run = 3 rows.
                # ------------------------------------------------

                if run_length >= 3:

                    # Need a valid value BEFORE the stuck section.
                    if run_start <= 0:

                        i = run_end + 1
                        continue

                    try:

                        before_value = float(
                            data_rows[
                                run_start - 1
                            ][col]
                        )

                    except (
                        ValueError,
                        TypeError,
                        IndexError
                    ):

                        i = run_end + 1
                        continue

                    # ------------------------------------------------
                    # Need a recovery value AFTER the stuck section.
                    #
                    # If run_end is the final row, the website may
                    # still be stuck. Do NOT alter it yet.
                    # ------------------------------------------------

                    if run_end + 1 >= len(data_rows):

                        i = run_end + 1
                        continue

                    try:

                        after_value = float(
                            data_rows[
                                run_end + 1
                            ][col]
                        )

                    except (
                        ValueError,
                        TypeError,
                        IndexError
                    ):

                        i = run_end + 1
                        continue

                    # ------------------------------------------------
                    # If before and after are also the same,
                    # this is not a useful stuck transition.
                    # ------------------------------------------------

                    if (
                        before_value
                        == current_value
                        == after_value
                    ):

                        i = run_end + 1
                        continue

                    # ------------------------------------------------
                    # Interpolate the stuck values.
                    #
                    # Example:
                    #
                    # Before = 1325
                    # Stuck rows = 4
                    # After = 1100
                    #
                    # The 4 values are distributed evenly between
                    # 1325 and 1100.
                    # ------------------------------------------------

                    total_steps = (
                        run_length + 1
                    )

                    for k in range(
                        1,
                        run_length + 1
                    ):

                        interpolated = (
                            before_value
                            + (
                                after_value
                                - before_value
                            )
                            * k
                            / total_steps
                        )

                        # Keep whole-number MW values.
                        interpolated = round(
                            interpolated
                        )

                        data_rows[
                            run_start + k - 1
                        ][col] = str(
                            interpolated
                        )

                        changed_count += 1

                    print(
                        f"Smoothed "
                        f"{expected_header[col]}: "
                        f"{data_rows[run_start][0]} "
                        f"{data_rows[run_start][1]} "
                        f"to "
                        f"{data_rows[run_end][0]} "
                        f"{data_rows[run_end][1]} | "
                        f"{run_length} repeated values | "
                        f"{before_value} -> "
                        f"{after_value}"
                    )

                i = run_end + 1

        # ----------------------------------------------------
        # Write modified CSV back.
        # ----------------------------------------------------

        if changed_count > 0:

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
                    data_rows
                )

            print(
                f"Data smoothing complete: "
                f"{changed_count} values corrected"
            )

        else:

            print(
                "Data smoothing: "
                "no stuck values requiring correction"
            )

    except Exception as e:

        print(
            f"Could not smooth stuck values: {e}"
        )


# ============================================================
# CHECK LAST ROW
# ============================================================

def last_row_is_recent():

    if not os.path.exists(OUTPUT_CSV):
        return False

    try:

        with open(
            OUTPUT_CSV,
            "r",
            newline="",
            encoding="utf-8"
        ) as f:

            rows = list(
                csv.reader(f)
            )

        if len(rows) < 2:
            return False

        last_row = None

        for row in reversed(rows[1:]):

            if (
                row
                and any(
                    cell.strip()
                    for cell in row
                )
            ):

                last_row = row
                break

        if (
            not last_row
            or len(last_row) < 2
        ):

            return False

        last_datetime = datetime.strptime(
            last_row[0].strip()
            + " "
            + last_row[1].strip(),
            "%d-%b-%y %H:%M"
        )

        age = (
            datetime.now()
            - last_datetime
        )

        age_minutes = (
            age.total_seconds()
            / 60
        )

        print(
            f"Last CSV row time: "
            f"{last_datetime.strftime('%d-%b-%y %H:%M')}"
        )

        print(
            f"Last CSV row age: "
            f"{age_minutes:.1f} minutes"
        )

        if age <= timedelta(
            minutes=5
        ):

            print(
                "Last row is within 5 minutes. "
                "Skipping UPSLDC fetch."
            )

            return True

        return False

    except Exception as e:

        print(
            f"Could not check last CSV row: {e}"
        )

        return False


# ============================================================
# DAILY CSV COMPACTION
# ============================================================

def compact_csv():

    if not os.path.exists(
        OUTPUT_CSV
    ):
        return

    expected_header = header_row()

    with open(
        OUTPUT_CSV,
        "r",
        newline="",
        encoding="utf-8"
    ) as f:

        rows = list(
            csv.reader(f)
        )

    data_rows = (
        rows[1:]
        if rows
        and rows[0] == expected_header
        else rows
    )

    today = datetime.now().date()

    yesterday = (
        today
        - timedelta(days=10)
    )

    ten_day_start = (
        yesterday
        - timedelta(days=30)
    )

    retained_rows = []

    for row in data_rows:

        if (
            not row
            or not any(
                cell.strip()
                for cell in row
            )
        ):
            continue

        try:

            row_date = datetime.strptime(
                row[0].strip(),
                "%d-%b-%y"
            ).date()

            row_time = datetime.strptime(
                row[1].strip(),
                "%H:%M"
            ).time()

            # ------------------------------------------------
            # Recent data
            # ------------------------------------------------

            if row_date >= yesterday:

                retained_rows.append(
                    row
                )

            # ------------------------------------------------
            # Previous period
            # ------------------------------------------------

            elif row_date >= ten_day_start:

                if row_time.minute % 15 == 0:

                    retained_rows.append(
                        row
                    )

            # ------------------------------------------------
            # Older data
            # ------------------------------------------------

            else:

                if row_time.minute == 0:

                    retained_rows.append(
                        row
                    )

        except (
            ValueError,
            IndexError
        ):

            retained_rows.append(
                row
            )

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
            retained_rows
        )

    print(
        f"CSV compacted: "
        f"{len(retained_rows)} rows retained"
    )


# ============================================================
# PREPARE CSV / MOVE OLD DATA
# ============================================================

def prepare_csv():

    expected_header = header_row()

    # --------------------------------------------------------
    # Create CSV if it does not exist.
    # --------------------------------------------------------

    if not os.path.exists(
        OUTPUT_CSV
    ):

        with open(
            OUTPUT_CSV,
            "w",
            newline="",
            encoding="utf-8"
        ) as f:

            csv.writer(f).writerow(
                expected_header
            )

        return

    # --------------------------------------------------------
    # Read existing CSV.
    # --------------------------------------------------------

    with open(
        OUTPUT_CSV,
        "r",
        newline="",
        encoding="utf-8"
    ) as f:

        rows = list(
            csv.reader(f)
        )

    data_rows = (
        rows[1:]
        if rows
        and rows[0] == expected_header
        else rows
    )

    cutoff_date = (
        datetime.now().date()
        - timedelta(days=120)
    )

    valid_rows = []

    historical_rows = []

    for row in data_rows:

        if (
            not row
            or not any(
                cell.strip()
                for cell in row
            )
        ):
            continue

        try:

            row_date = datetime.strptime(
                row[0].strip(),
                "%d-%b-%y"
            ).date()

            if row_date < cutoff_date:

                historical_rows.append(
                    row
                )

            else:

                valid_rows.append(
                    row
                )

        except (
            ValueError,
            IndexError
        ):

            valid_rows.append(
                row
            )

    # --------------------------------------------------------
    # Move old data to historical.csv.
    # --------------------------------------------------------

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

            if (
                not historical_exists
                or os.path.getsize(
                    HISTORICAL_CSV
                ) == 0
            ):

                writer.writerow(
                    expected_header
                )

            writer.writerows(
                historical_rows
            )

        print(
            f"Moved "
            f"{len(historical_rows)} "
            f"rows to historical.csv"
        )

    # --------------------------------------------------------
    # Rewrite main CSV.
    # --------------------------------------------------------

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


# ============================================================
# FETCH JSON
# ============================================================

def fetch_json(url):

    last_error = None

    # --------------------------------------------------------
    # Direct attempts
    # --------------------------------------------------------

    for attempt in range(3):

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

            print(
                f"Direct fetch attempt "
                f"{attempt + 1}/3 failed "
                f"for {url}: {e}"
            )

            time.sleep(2)

    print(
        f"Direct fetch failed 3x, "
        f"falling back to proxies for {url}"
    )

    # --------------------------------------------------------
    # Proxy attempts
    # --------------------------------------------------------

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

    raise RuntimeError(
        f"All fetch attempts failed "
        f"for {url}: {last_error}"
    )


# ============================================================
# EXTRACT SUMMARY
# ============================================================

def extract_summary(summary_json):

    demand = None

    solar = None

    def scan(obj):

        nonlocal demand, solar

        if isinstance(obj, dict):

            for k, v in obj.items():

                if (
                    k.upper()
                    == "DEMAND_MW"
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


# ============================================================
# EXTRACT PLANTS
# ============================================================

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

    if isinstance(
        main_json,
        dict
    ):

        for v in main_json.values():

            if isinstance(
                v,
                list
            ):

                all_generators.extend(v)

    elif isinstance(
        main_json,
        list
    ):

        all_generators = main_json

    for gen in all_generators:

        if not isinstance(
            gen,
            dict
        ):
            continue

        gen_name = clean(
            gen.get(
                "GEN_NAME",
                ""
            )
        )

        actual = gen.get(
            "ACTUAL",
            0
        ) or 0

        schedule = gen.get(
            "SCHEDULE",
            0
        ) or 0

        dc = gen.get(
            "DC",
            0
        ) or 0

        matched_key = None

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        for key, mapped_name in (
            PLANT_MAPPING.items()
        ):

            if (
                gen_name
                == clean(mapped_name)
            ):

                matched_key = key

                break

        # ----------------------------------------------------
        # Partial match
        # ----------------------------------------------------

        if matched_key is None:

            for key, mapped_name in (
                PLANT_MAPPING.items()
            ):

                short = clean(
                    mapped_name
                )[:13]

                if (
                    short
                    and short in gen_name
                ):

                    matched_key = key

                    break

        # ----------------------------------------------------
        # Store values
        # ----------------------------------------------------

        if matched_key:

            try:

                plant_data[
                    matched_key
                ] = {

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


# ============================================================
# ROUND TIME
# ============================================================

def round_to_nearest_5_minutes(dt):

    discard = timedelta(
        minutes=dt.minute % 5,
        seconds=dt.second,
        microseconds=dt.microsecond
    )

    rounded = dt - discard

    if dt.minute % 5 >= 3:

        rounded += timedelta(
            minutes=5
        )

    return rounded


# ============================================================
# BUILD NEW ROW
# ============================================================

def build_row(
    main_json,
    summary_json
):

    now = round_to_nearest_5_minutes(
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


# ============================================================
# APPEND NEW ROW
# ============================================================

def append_row(row):
    """
    Write new row only if it has 20 or fewer zero values.
    """

    zero_count = count_zero_values(
        row
    )

    if zero_count > 20:

        date_value = (
            row[0]
            if len(row) > 0
            else "Unknown"
        )

        time_value = (
            row[1]
            if len(row) > 1
            else "Unknown"
        )

        print(
            f"New row REJECTED: "
            f"{date_value} {time_value} "
            f"contains {zero_count} zero values"
        )

        return False

    with open(
        OUTPUT_CSV,
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        csv.writer(f).writerow(
            row
        )

    return True


# ============================================================
# TELEGRAM
# ============================================================

def send_to_telegram(row):

    headers = header_row()

    row_dict = dict(
        zip(
            headers,
            row
        )
    )

    date_str = row_dict[
        "Date"
    ]

    time_str = row_dict[
        "Time"
    ]

    demand = row_dict[
        "TOTAL_DEMAND"
    ]

    solar = row_dict[
        "SOLAR_GEN"
    ]

    name_width = max(
        len(key)
        for key in PLANT_SEQUENCE
    )

    table_lines = []

    for key in PLANT_SEQUENCE:

        ag_value = row_dict[
            f"{key}_AG"
        ]

        table_lines.append(
            f"{key.ljust(name_width)}  "
            f"{str(ag_value).rjust(5)}"
        )

    table_body = "\n".join(
        table_lines
    )

    message = (
        f"📊 UPSLDC Data — "
        f"{date_str} {time_str}\n"
        f"Demand: {demand} MW   "
        f"Solar: {solar} MW\n\n"
        f"```\n"
        f"{'Plant'.ljust(name_width)}  "
        f"{'AG'.rjust(5)}\n"
        f"{'-' * (name_width + 7)}\n"
        f"{table_body}\n"
        f"```"
    )

    telegram_url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TST_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:

        response = requests.post(
            telegram_url,
            data=payload,
            timeout=20
        )

        response.raise_for_status()

        print(
            "Telegram message sent successfully"
        )

    except Exception as e:

        print(
            f"Telegram send failed: {e}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # STEP 1
    # Remove existing bad rows.
    #
    # This happens EVERY TIME the script starts.
    # ========================================================

    print(
        "Checking CSV for bad zero-value rows..."
    )

    remove_zero_rows()


    # ========================================================
    # STEP 2
    # Prepare / maintain CSV.
    # ========================================================

    now = round_to_nearest_5_minutes(
        datetime.now()
    )

    # Compact CSV once daily at 00:00.
    if (
        now.hour == 0
        and now.minute == 0
    ):

        compact_csv()

    # Move data older than 120 days
    # to historical.csv.
    prepare_csv()


    # ========================================================
    # STEP 3
    # Check whether latest row is recent.
    # ========================================================

    if last_row_is_recent():

        print(
            "No new fetch required."
        )

        return


    # ========================================================
    # STEP 4
    # Fetch UPSLDC data.
    # ========================================================

    main_json = fetch_json(
        MAIN_URL
    )

    summary_json = fetch_json(
        SUMMARY_URL
    )


    # ========================================================
    # STEP 5
    # Build new row.
    # ========================================================

    row = build_row(
        main_json,
        summary_json
    )


    # ========================================================
    # STEP 6
    # Check new row.
    #
    # If >20 zeros:
    #   - Do NOT write
    #   - Do NOT send Telegram
    # ========================================================

    if append_row(row):

        print(
            "New row written successfully."
        )

        # ====================================================
        # STEP 7
        # Now look for stuck values and smooth them.
        # ====================================================

        smooth_stuck_values()

        # ====================================================
        # STEP 8
        # Send the actual newly fetched row to Telegram.
        # ====================================================

        send_to_telegram(row)

        print(
            "Successful"
        )

    else:

        print(
            "Bad row detected. "
            "Data was NOT written "
            "and Telegram was NOT sent."
        )


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":

    main()