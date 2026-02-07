import gspread
from google.oauth2.service_account import Credentials

# --- Настройки ---
SPREADSHEET_ID = "1uqqmhV2gXAEHTwox8-Zu5syl9YUNI2vTj4gIIWNLL2Y"
SHEET_NAME = "Список задач (2026)"

# --- Авторизация через сервисный аккаунт ---
scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
gc = gspread.authorize(creds)

# --- Попытка открыть лист и вывести 5 первых строк ---
sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
rows = sheet.get_all_records()

print("Успешно подключились! Вот первые 5 задач:")
for r in rows[:5]:
    print(f"{r['Задача']} — {r['Ссылка']}")
