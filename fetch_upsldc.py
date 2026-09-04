"""
Fetches live UPSLDC data and appends one row to upsldc_hourly_data.csv.
Runs every 5 minutes.

At 00:00 every day:
- Yesterday remains at 5-minute frequency.
- Previous 10 days are reduced to 15-minute frequency.
- Older data is reduced to hourly frequency.
- Data older than 120 days is moved to historical.csv.

New data is sent to Telegram.
"""

import os
import csv
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import requests


MAIN_URL = "https://www.upsldc.org/assets/dataset/realtime.json"
SUMMARY_URL = "https://www.upsldc.org/assets/dataset/real-time-summary.json"

BOT_TOKEN = "5588744140:AAFMzYGBbQDzZ_hYDf9d1WSTHmC3I-Z3kZk#"
TST_ID = "-1003175374557"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(BASE_DIR, "upsldc_hourly_data.csv")
HISTORICAL_CSV = os.path.join(BASE_DIR, "historical.csv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

PROXY_URL_TEMPLATES = [
    "https://api.codetabs.com/v1/proxy?quest={target}",
    "https://api.allorigins.win/raw?url={target}",
]

PLANT_SEQUENCE = [
    "MEJA", "LANCO", "BARA", "TANDA",
    "LALITPUR", "Harduaganj Ex2", "ROSA 1", "ROSA 2"
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
    header = ["Date", "Time", "TOTAL_DEMAND", "SOLAR_GEN"]
    for key in PLANT_SEQUENCE:
        header += [f"{key}_DC", f"{key}_SG", f"{key}_AG"]
    return header


def clean(s):
    return (s or "").lower().replace(" ", "")


def last_row_is_recent():
    if not os.path.exists(OUTPUT_CSV):
        return False

    try:
        with open(OUTPUT_CSV, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        if len(rows) < 2:
            return False

        last_row = None

        for row in reversed(rows[1:]):
            if row and any(cell.strip() for cell in row):
                last_row = row
                break

        if not last_row or len(last_row) < 2:
            return False

        last_datetime = datetime.strptime(
            last_row[0].strip() + " " + last_row[1].strip(),
            "%d-%b-%y %H:%M"
        )

        age = datetime.now() - last_datetime
        age_minutes = age.total_seconds() / 60

        print(f"Last CSV row time: {last_datetime.strftime('%d-%b-%y %H:%M')}")
        print(f"Last CSV row age: {age_minutes:.1f} minutes")

        if age <= timedelta(minutes=5):
            print("Last row is within 5 minutes. Skipping UPSLDC fetch.")
            return True

        return False

    except Exception as e:
        print(f"Could not check last CSV row: {e}")
        return False


def compact_csv():
    if not os.path.exists(OUTPUT_CSV):
        return

    expected_header = header_row()

    with open(OUTPUT_CSV, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    data_rows = rows[1:] if rows and rows[0] == expected_header else rows

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    ten_day_start = yesterday - timedelta(days=20)

    retained_rows = []

    for row in data_rows:
        if not row or not any(cell.strip() for cell in row):
            continue

        try:
            row_date = datetime.strptime(row[0].strip(), "%d-%b-%y").date()
            row_time = datetime.strptime(row[1].strip(), "%H:%M").time()

            # Yesterday and today: keep all data
            if row_date >= yesterday:
                retained_rows.append(row)

            # Previous 10 days: keep 15-minute data
            elif row_date >= ten_day_start:
                if row_time.minute % 15 == 0:
                    retained_rows.append(row)

            # Older data: keep hourly data only
            else:
                if row_time.minute == 0:
                    retained_rows.append(row)

        except (ValueError, IndexError):
            retained_rows.append(row)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(expected_header)
        writer.writerows(retained_rows)

    print(f"CSV compacted: {len(retained_rows)} rows retained")


def prepare_csv():
    expected_header = header_row()

    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(expected_header)
        return

    with open(OUTPUT_CSV, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    data_rows = rows[1:] if rows and rows[0] == expected_header else rows
    cutoff_date = datetime.now().date() - timedelta(days=120)

    valid_rows = []
    historical_rows = []

    for row in data_rows:
        if not row or not any(cell.strip() for cell in row):
            continue

        try:
            row_date = datetime.strptime(row[0].strip(), "%d-%b-%y").date()

            if row_date < cutoff_date:
                historical_rows.append(row)
            else:
                valid_rows.append(row)

        except (ValueError, IndexError):
            valid_rows.append(row)

    if historical_rows:
        historical_exists = os.path.exists(HISTORICAL_CSV)

        with open(HISTORICAL_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            if not historical_exists or os.path.getsize(HISTORICAL_CSV) == 0:
                writer.writerow(expected_header)

            writer.writerows(historical_rows)

        print(f"Moved {len(historical_rows)} rows to historical.csv")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(expected_header)
        writer.writerows(valid_rows)


def fetch_json(url):
    last_error = None

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.json()

        except Exception as e:
            last_error = e
            print(f"Direct fetch attempt {attempt + 1}/3 failed for {url}: {e}")
            time.sleep(2)

    print(f"Direct fetch failed 3x, falling back to proxies for {url}")

    for template in PROXY_URL_TEMPLATES:
        proxied_url = template.format(target=quote(url, safe=""))

        try:
            resp = requests.get(proxied_url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return resp.json()

        except Exception as e:
            last_error = e
            time.sleep(2)

    raise RuntimeError(f"All fetch attempts failed for {url}: {last_error}")


def extract_summary(summary_json):
    demand = None
    solar = None

    def scan(obj):
        nonlocal demand, solar

        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.upper() == "DEMAND_MW" and demand is None:
                    demand = v

                if k.upper() == "RE_SOLAR_GENERATION_MW" and solar is None:
                    solar = v

                scan(v)

        elif isinstance(obj, list):
            for item in obj:
                scan(item)

    scan(summary_json)
    return demand, solar


def extract_plants(main_json):
    plant_data = {
        key: {"DC": 0, "SG": 0, "AG": 0}
        for key in PLANT_SEQUENCE
    }

    all_generators = []

    if isinstance(main_json, dict):
        for v in main_json.values():
            if isinstance(v, list):
                all_generators.extend(v)

    elif isinstance(main_json, list):
        all_generators = main_json

    for gen in all_generators:
        if not isinstance(gen, dict):
            continue

        gen_name = clean(gen.get("GEN_NAME", ""))
        actual = gen.get("ACTUAL", 0) or 0
        schedule = gen.get("SCHEDULE", 0) or 0
        dc = gen.get("DC", 0) or 0

        matched_key = None

        for key, mapped_name in PLANT_MAPPING.items():
            if gen_name == clean(mapped_name):
                matched_key = key
                break

        if matched_key is None:
            for key, mapped_name in PLANT_MAPPING.items():
                short = clean(mapped_name)[:13]

                if short and short in gen_name:
                    matched_key = key
                    break

        if matched_key:
            try:
                plant_data[matched_key] = {
                    "DC": round(float(dc)),
                    "SG": round(float(schedule)),
                    "AG": round(float(actual)),
                }

            except (TypeError, ValueError):
                pass

    return plant_data


def round_to_nearest_5_minutes(dt):
    discard = timedelta(
        minutes=dt.minute % 5,
        seconds=dt.second,
        microseconds=dt.microsecond
    )

    rounded = dt - discard

    if dt.minute % 5 >= 3:
        rounded += timedelta(minutes=5)

    return rounded


def build_row(main_json, summary_json):
    now = round_to_nearest_5_minutes(datetime.now())
    date_str = now.strftime("%d-%b-%y")
    time_str = now.strftime("%H:%M")

    demand, solar = extract_summary(summary_json)
    plants = extract_plants(main_json)

    row = [date_str, time_str, demand, solar]

    for key in PLANT_SEQUENCE:
        p = plants[key]
        row += [p["DC"], p["SG"], p["AG"]]

    return row


def append_row(row):
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def send_to_telegram(row):
    headers = header_row()
    row_dict = dict(zip(headers, row))

    date_str = row_dict["Date"]
    time_str = row_dict["Time"]
    demand = row_dict["TOTAL_DEMAND"]
    solar = row_dict["SOLAR_GEN"]

    name_width = max(len(key) for key in PLANT_SEQUENCE)

    table_lines = []
    for key in PLANT_SEQUENCE:
        ag_value = row_dict[f"{key}_AG"]
        table_lines.append(f"{key.ljust(name_width)}  {str(ag_value).rjust(5)}")

    table_body = "\n".join(table_lines)

    message = (
        f"📊 UPSLDC Data — {date_str} {time_str}\n"
        f"Demand: {demand} MW   Solar: {solar} MW\n\n"
        f"```\n"
        f"{'Plant'.ljust(name_width)}  {'AG'.rjust(5)}\n"
        f"{'-' * (name_width + 7)}\n"
        f"{table_body}\n"
        f"```"
    )

    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

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
        print("Telegram message sent successfully")

    except Exception as e:
        print(f"Telegram send failed: {e}")


def main():
    now = round_to_nearest_5_minutes(datetime.now())

    # Compact CSV once daily at 00:00
    if now.hour == 0 and now.minute == 0:
        compact_csv()

    prepare_csv()

    if last_row_is_recent():
        print("No new fetch required.")
        return

    main_json = fetch_json(MAIN_URL)
    summary_json = fetch_json(SUMMARY_URL)

    row = build_row(main_json, summary_json)

    append_row(row)
    send_to_telegram(row)

    print("Successful")


if __name__ == "__main__":
    main()