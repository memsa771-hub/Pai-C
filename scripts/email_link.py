"""Local test only (branch pai-merge): open the "verify your email" link of the newest test account.

    python scripts/email_link.py

This stack sends no real emails. The local Firebase Auth emulator keeps every verification link it made; this
script takes the newest one and opens it in your browser (it also prints it).
"""
import json
import sys
import urllib.error
import urllib.request
import webbrowser

from _docker import run_script

CODES = "http://localhost:9099/emulator/v1/projects/demo-pai-merge/oobCodes"
APP_ACTION = "http://localhost:3000/auth/action?mode=verifyEmail&oobCode="


def main():
    try:
        with urllib.request.urlopen(CODES, timeout=10) as response:
            codes = json.loads(response.read()).get("oobCodes", [])
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach the sign-in emulator ({e.reason}). Is the app running? Start it with: python scripts/run.py")
    verify = [c for c in codes if c.get("requestType") == "VERIFY_EMAIL"]
    if not verify:
        sys.exit("No verification link yet. Create the account first (Create account, then wait for 'Check your email').")
    newest = verify[-1]
    link = APP_ACTION + newest["oobCode"]
    print(f"Verification link for {newest.get('email')}:\n{link}")
    webbrowser.open(link)


if __name__ == "__main__":
    run_script(main)
