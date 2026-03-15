import os
import re
import base64
import sqlite3
import pickle
from datetime import datetime

from bs4 import BeautifulSoup
import html

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DB_FILE = "finance.db"

BANK_SENDERS = ["hsbc", "hdfc", "sbi"]


# =========================
# DB
# =========================

def init_db():

    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id TEXT UNIQUE,
        txn_date TEXT,
        amount REAL,
        txn_type TEXT,
        merchant TEXT,
        excluded INTEGER,
        category TEXT,
        notes TEXT        
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS splitwise_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id TEXT UNIQUE,
        person_name TEXT,
        description TEXT,
        total_amount REAL,
        your_share REAL,
        direction TEXT,
        txn_date TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS splitwise_settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id TEXT UNIQUE,
        person_name TEXT,
        amount REAL,
        direction TEXT,
        txn_date TEXT
    )
    """)

    conn.commit()
    conn.close()


# =========================
# AUTH
# =========================

def authenticate():

    creds = None

    if os.path.exists("token.pickle"):

        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds:

        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )

        creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


# =========================
# EMAIL HELPERS
# =========================

def extract_body(payload):

    if "parts" in payload:

        for part in payload["parts"]:

            if part["mimeType"] == "text/html":

                data = part["body"].get("data")

                if data:

                    html = base64.urlsafe_b64decode(data).decode(errors="ignore")

                    soup = BeautifulSoup(html, "html.parser")

                    return soup.get_text(" ")

    body = payload.get("body", {}).get("data")

    if body:
        return base64.urlsafe_b64decode(body).decode(errors="ignore")

    return ""


def clean_email(text):

    if "<html" in text.lower():
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text(" ")

    text = html.unescape(text)

    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_sender(headers):

    for h in headers:
        if h["name"] == "From":

            sender = h["value"].lower()

            match = re.search(r'<(.+?)>', sender)

            if match:
                sender = match.group(1)

            return sender

    return ""

# =========================
# BANK PARSER
# =========================

from datetime import datetime
import re

def normalize_date(date_str):
    
    if not date_str:
        return ""

    date_str = date_str.strip()

    formats = [
        "%d %b %Y",      # 14 Mar 2026
        "%d %b, %Y",     # 14 Mar, 2026
        "%d %B %Y",      # 14 March 2026
        "%d %B, %Y",     # 14 March, 2026
        "%b %d, %Y",     # Mar 14, 2026
        "%B %d, %Y",     # March 14, 2026
        "%d-%m-%y",      # 14-03-26
        "%d-%m-%Y"       # 14-03-2026
    ]
    print(date_str)
    for fmt in formats:

        try:

            dt = datetime.strptime(date_str, fmt)
            print('fixed dt: ', dt, dt.strftime("%Y-%m-%d"))
            return dt.strftime("%Y-%m-%d")

        except:
            pass

    # fallback for weird cases
    match = re.search(r"(\d{1,2})\s([A-Za-z]{3})\s(\d{4})", date_str)

    if match:

        try:
            dt = datetime.strptime(match.group(0), "%d %b %Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass

    return ""

def parse_bank_email(text):

    text = clean_email(text)
    lower = text.lower()

    if not any(k in lower for k in ["debited","credited","used for","spent"]):
        return None

    amount_patterns = [
        r"(?:INR|Rs\.?|₹)\s*([\d,]+\.\d+)",
        r"(?:INR|Rs\.?|₹)\s*([\d,]+)"
    ]

    amount = None

    for p in amount_patterns:

        m = re.search(p, text, re.IGNORECASE)

        if m:
            amount = float(m.group(1).replace(",", ""))
            break

    if not amount:
        return None

    txn_type = "debit"

    if "credited" in lower:
        txn_type = "credit"

    merchant = "Unknown"

    merchant_patterns = [
        r"for payment to\s(.+?)\son",
        r"towards\s(.+?)\son",
        r"paid to\s(.+?)\son",
        r"to\s[A-Za-z0-9@\.\-]+\s(.+?)\son"
    ]

    for p in merchant_patterns:

        m = re.search(p, text, re.IGNORECASE)

        if m:
            merchant = m.group(1).strip()
            break

    date_patterns = [
        r"on\s(\d{1,2}\s[A-Za-z]{3}\s\d{4})",
        r"on\s(\d{1,2}\s[A-Za-z]{3},\s\d{4})",
        r"on\s(\d{2}-\d{2}-\d{2})"
    ]

    txn_date = ""

    for p in date_patterns:

        m = re.search(p, text)

        if m:
            txn_date = m.group(1)
            break

    return {
        "amount": amount,
        "type": txn_type,
        "merchant": merchant,
        "date": normalize_date(txn_date)
    }


# =========================
# SPLITWISE PARSER
# =========================

def parse_splitwise_email(text):

    text = re.sub(r"\s+", " ", text)

    person_match = re.search(r'Hey .*?!\s(.+?) just added', text)

    person = person_match.group(1) if person_match else "Unknown"

    desc_match = re.search(r'added ["“](.+?)["”]', text)

    description = desc_match.group(1) if desc_match else "Unknown"

    total_match = re.search(r"Total:\s?₹([\d,\.]+)", text)

    total = float(total_match.group(1).replace(",", "")) if total_match else None

    date_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s\d{1,2},\s\d{4}",
        text
    )

    date = date_match.group(0) if date_match else ""

    owe = re.search(r"You owe\s?₹([\d,\.]+)", text)

    if owe:

        return {
            "type":"expense",
            "person":person,
            "direction":"owe",
            "description":description,
            "share":float(owe.group(1).replace(",","")),
            "total":total,
            "date":normalize_date(date)
        }

    owed = re.search(r"You get back\s?₹([\d,\.]+)", text)

    if owed:

        return {
            "type":"expense",
            "person":person,
            "direction":"owed",
            "description":description,
            "share":float(owed.group(1).replace(",","")),
            "total":total,
            "date":normalize_date(date)
        }

    return None


# =========================
# DB INSERT
# =========================

def insert_bank(email_id, data):

    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
    INSERT OR IGNORE INTO transactions
    (email_id,txn_date,amount,txn_type,merchant)
    VALUES (?,?,?,?,?)
    """, (
        email_id,
        data["date"],
        data["amount"],
        data["type"],
        data["merchant"]
    ))

    conn.commit()
    conn.close()


def insert_splitwise(email_id, data):

    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
    INSERT OR IGNORE INTO splitwise_transactions
    (email_id,person_name,description,total_amount,your_share,direction,txn_date)
    VALUES (?,?,?,?,?,?,?)
    """, (
        email_id,
        data["person"],
        data["description"],
        data["total"],
        data["share"],
        data["direction"],
        data["date"]
    ))

    conn.commit()
    conn.close()

def print_summary():

    conn = sqlite3.connect(DB_FILE)

    # ---------------- BANK ---------------- #

    bank_debits = conn.execute("""
    SELECT SUM(amount)
    FROM transactions
    WHERE txn_type='debit'
    AND excluded = 0
    """).fetchone()[0] or 0

    bank_credits = conn.execute("""
    SELECT SUM(amount)
    FROM transactions
    WHERE txn_type='credit'
    AND excluded = 0WHERE txn_type='credit'
    """).fetchone()[0] or 0


    # ---------------- SPLITWISE ---------------- #

    splitwise_owed_to_you = conn.execute("""
    SELECT SUM(your_share) FROM splitwise_transactions
    WHERE direction='owed'
    """).fetchone()[0] or 0


    splitwise_you_owe = conn.execute("""
    SELECT SUM(your_share) FROM splitwise_transactions
    WHERE direction='owe'
    """).fetchone()[0] or 0


    # ---------------- ACTUAL SPEND ---------------- #

    actual_spend = (
        bank_debits
        - bank_credits
        - splitwise_owed_to_you
        + splitwise_you_owe
    )


    # ---------------- PRINT ---------------- #

    print("\n=========== BANK ==========")
    print("Money Spent   :", round(bank_debits, 2))
    print("Money Earned  :", round(bank_credits, 2))

    print("\n======== SPLITWISE ========")
    print("People owe you:", round(splitwise_owed_to_you, 2))
    print("You owe others:", round(splitwise_you_owe, 2))

    print("\n======= TRUE SPEND ========")
    print("Actual Spend  :", round(actual_spend, 2))

    print("===========================\n")

    conn.close()

# =========================
# MAIN
# =========================

def run():

    init_db()

    service = authenticate()

    results = service.users().messages().list(
        userId="me",
        q="(from:hsbc OR from:hdfc OR from:sbi OR from:splitwise) newer_than:15d"
    ).execute()

    messages = results.get("messages", [])

    print("Emails found:", len(messages))

    for m in messages:

        email_id = m["id"]

        msg = service.users().messages().get(
            userId="me",
            id=email_id,
            format="full"
        ).execute()

        sender = get_sender(msg["payload"]["headers"])

        body = extract_body(msg["payload"])

        if not body:
            continue

        if "splitwise" in sender:

            parsed = parse_splitwise_email(body)

            if parsed:
                insert_splitwise(email_id, parsed)
                print("Splitwise:", parsed)

        elif any(b in sender for b in BANK_SENDERS):

            parsed = parse_bank_email(body)

            if parsed:
                insert_bank(email_id, parsed)
                print("Bank:", parsed)
    print_summary()
    


if __name__ == "__main__":
    run()