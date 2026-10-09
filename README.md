# CMS Hospitals Data Downloader

This script downloads CSV files for datasets in the CMS Provider Data catalog that have the "HOSPITALS theme". It changes the column names to lowercase `snake_case` and downloads files in parallel.

## Run the script

You need Python installed. No extra packages are required.

Open a terminal in this folder and run:

- Windows: `py download_hospitals.py`
- Linux: `python3 download_hospitals.py`

The first run downloads the files. Later runs use `metadata.json` to check for changes and skip files that haven’t been updated.

## Where the files go

The processed CSV files and `metadata.json` are saved in the `hospital_data_clean` folder.

To run the script automatically every day, schedule it with Windows Task Scheduler or cron. Set the project folder as the task’s working directory so it keeps using the same metadata file.