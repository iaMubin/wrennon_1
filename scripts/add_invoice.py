import re

filepath = 'd:/ai_engineering/wrennon-showcase - Copy/backend/app/services/mock_apis.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

def replace_func(match):
    order_id = match.group(1)
    # Add invoice_url right after order_id
    return match.group(0) + f'\n        "invoice_url": "https://wrennon.com/invoice/{order_id}",'

new_content = re.sub(r'"order_id": "(\d+)",', replace_func, content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Updated mock_apis.py with invoice_url")
