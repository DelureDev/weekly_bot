import os

import gspread
from google.oauth2.service_account import Credentials


def main() -> None:
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME", "Список задач (2026)")
    creds_file = os.getenv("CREDS_FILE", "credentials.json")

    if not spreadsheet_id:
        raise SystemExit("Set SPREADSHEET_ID before running this smoke script.")

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
    gc = gspread.authorize(creds)

    sheet = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
    rows = sheet.get_all_records()

    print("Connected to Google Sheets. First 5 rows:")
    for row in rows[:5]:
        task = row.get("Задача", "")
        link = row.get("Ссылка", "")
        print(f"{task} - {link}")


if __name__ == "__main__":
    main()
