import concurrent.futures
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items"
OUTPUT_DIR = Path("hospital_data_clean")
STATE_FILE = OUTPUT_DIR / "metadata.json"
WORKERS = 6


def open_url(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "CMS-Hospitals-Downloader"}
    )
    return urllib.request.urlopen(request, timeout=120)


def snake_case(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text.strip())
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_").lower()


def unique_headers(headers):
    result = []
    counts = {}

    for number, header in enumerate(headers, start=1):
        name = snake_case(header) or f"column_{number}"
        counts[name] = counts.get(name, 0) + 1

        if counts[name] > 1:
            name = f"{name}_{counts[name]}"

        result.append(name)

    return result


def safe_name(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_").lower() or "dataset"


def get_resources():
    with open_url(API_URL) as response:
        catalog = json.load(response)

    resources = []
    hospital_count = 0

    for dataset in catalog:
        themes = dataset.get("theme", [])
        if isinstance(themes, str):
            themes = [themes]

        if not any(str(theme).strip().lower() == "hospitals" for theme in themes):
            continue

        hospital_count += 1
        dataset_id = safe_name(str(dataset.get("identifier", "dataset")))
        version = str(dataset.get("modified") or dataset.get("released") or "")

        for number, distribution in enumerate(dataset.get("distribution", []), start=1):
            url = distribution.get("downloadURL", "")
            media_type = str(distribution.get("mediaType", "")).lower()
            url_path = urllib.parse.urlsplit(url).path

            if not url or ("csv" not in media_type and not url_path.lower().endswith(".csv")):
                continue

            source_name = Path(urllib.parse.unquote(url_path)).name
            source_stem = safe_name(source_name.rsplit(".", 1)[0])
            short_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
            filename = f"{dataset_id}_{number}_{source_stem}_{short_hash}.csv"

            resources.append({
                "key": f"{dataset_id}:{url}",
                "url": url,
                "version": version,
                "filename": filename,
            })

    if hospital_count == 0:
        raise RuntimeError("The CMS catalog returned no datasets with the Hospitals theme.")

    return resources, hospital_count


def download_and_process(item):
    destination = OUTPUT_DIR / item["filename"]
    temporary_path = None

    try:
        with open_url(item["url"]) as response:
            source = io.TextIOWrapper(response, encoding="utf-8-sig", newline="")
            reader = csv.reader(source)
            headers = next(reader, None)

            if headers is None:
                raise ValueError("The CSV is empty.")

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=OUTPUT_DIR,
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                writer = csv.writer(output)
                writer.writerow(unique_headers(headers))
                writer.writerows(reader)

        os.replace(temporary_path, destination)
        return item["key"], item["version"], destination.name

    except Exception:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        raise


def save_state(state):
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=OUTPUT_DIR,
        suffix=".tmp",
        delete=False,
    ) as file:
        temporary_path = Path(file.name)
        json.dump(state, file, indent=2)

    os.replace(temporary_path, STATE_FILE)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    else:
        state = {}

    resources, hospital_count = get_resources()
    to_download = []
    skipped = 0

    for item in resources:
        output_file = OUTPUT_DIR / item["filename"]
        previous = state.get(item["key"], {})

        if previous.get("version") == item["version"] and output_file.exists():
            skipped += 1
        else:
            to_download.append(item)

    downloaded = []
    failures = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = {
            pool.submit(download_and_process, item): item
            for item in to_download
        }

        for job in concurrent.futures.as_completed(jobs):
            item = jobs[job]

            try:
                key, version, filename = job.result()
                state[key] = {"version": version, "filename": filename}
                downloaded.append(filename)
                print(f"Downloaded: {filename}")
            except Exception as error:
                failures.append((item["filename"], str(error)))
                print(f"Failed: {item['filename']} — {error}")

    save_state(state)

    print()
    print(f"Hospital datasets found: {hospital_count}")
    print(f"CSV files found: {len(resources)}")
    print(f"Downloaded this run: {len(downloaded)}")
    print(f"Skipped as unchanged: {skipped}")
    print(f"Failed: {len(failures)}")

    if failures:
        raise SystemExit(1)

    files = sorted(OUTPUT_DIR.glob("*.csv"))
    print("\nCSV files in the output folder:")
    for file_path in files:
        print(f" - {file_path.name}")


if __name__ == "__main__":
    main()