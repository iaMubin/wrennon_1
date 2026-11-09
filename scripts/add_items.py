import re
import random

filepath = 'd:/ai_engineering/wrennon-showcase - Copy/backend/app/services/mock_apis.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

def replace_func(match):
    items_count = random.randint(1, 4)
    return match.group(0) + f'\n        "items_count": {items_count},'

new_content = re.sub(r'"order_id": "\d+",', replace_func, content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Updated mock_apis.py")
