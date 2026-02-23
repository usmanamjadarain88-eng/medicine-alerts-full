import json
import os
import requests
from datetime import datetime

def send_email(subject, text):
    api_key = os.environ['MAILGUN_API_KEY']
    domain = os.environ['MAILGUN_DOMAIN']
    to_email = os.environ['ALERT_EMAIL']
    return requests.post(
        f"https://api.mailgun.net/v3/{domain}/messages",
        auth=("api", api_key),
        data={"from": f"Medicine Alert <mailgun@{domain}>",
              "to": [to_email],
              "subject": subject,
              "text": text})

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_path = os.path.join(_repo_root, 'frontend', 'medicine_times.json')
with open(_path) as f:
    times = json.load(f)

now = datetime.utcnow().strftime('%H:%M')
for entry in times:
    if entry['time'] == now:
        send_email("Medicine Reminder", entry['message'])
