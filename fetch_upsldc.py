"""
Fetches live UPSLDC data and appends one row to upsldc_hourly_data.csv
in the repo root. Runs inside GitHub Actions on an hourly schedule
(see .github/workflows/update-data.yml) -- no AHK, Excel, or local
machine required.
"""

import os
import csv
from datetime import datetime

import requests

MAIN_URL = "https://www.upsldc.org/assets/dataset/realtime.json"
SUMMARY_URL = "https://www.upsldc.org/assets/dataset/real-time-summary.json"

OUTPUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upsldc_hourly_data.csv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

PLANT_SEQUENCE = ["MEJA", "LANCO", "BARA", "TANDA", "LALITPUR", "Harduaganj Ex2", "ROSA 1", "ROSA 2"]

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


def clean(s):
    return (s or "").lower().replace(" ", "")


def fetch_json(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def extract_summary(summary_json):
    demand, solar = None, None

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
    plant_data = {key: {"DC": 0, "SG": 0, "AG": 0} for key in PLANT_SEQUENCE}

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


def build_row(main_json, summary_json):
    now = datetime.now()
    date_str = now.strftime("%d-%b-%Y")
    time_str = now.strftime("%H:%M")

    demand, solar = extract_summary(summary_json)
    plants = extract_plants(main_json)

    row = [date_str, time_str, demand, solar]
    for key in PLANT_SEQUENCE:
        p = plants[key]
        row += [p["DC"], p["SG"], p["AG"]]
    return row


def header_row():
    header = ["Date", "Time", "TOTAL_DEMAND", "SOLAR_GEN"]
    for key in PLANT_SEQUENCE:
        header += [f"{key}_DC", f"{key}_SG", f"{key}_AG"]
    return header


def append_row(row):
    file_exists = os.path.isfile(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header_row())
        writer.writerow(row)


def main():
    main_json = fetch_json(MAIN_URL)
    summary_json = fetch_json(SUMMARY_URL)
    row = build_row(main_json, summary_json)
    append_row(row)
    print("Appended:", row)


if __name__ == "__main__":
    main()
