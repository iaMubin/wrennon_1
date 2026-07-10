import os
import re

def fix_utcnow():
    directory = r"d:\ai_engineering\wrennon-showcase\backend"
    for root, dirs, files in os.walk(directory):
        if 'temp_env' in root or '.venv' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                new_content = content
                
                # Replace the exact function calls
                new_content = re.sub(
                    r"datetime\.datetime\.utcnow\(\)", 
                    r"datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)", 
                    new_content
                )
                
                # In models.py we used datetime.UTC earlier, replace it to be safe
                new_content = re.sub(
                    r"datetime\.datetime\.now\(datetime\.UTC\)",
                    r"datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)",
                    new_content
                )
                
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"Fixed {path}")

if __name__ == "__main__":
    fix_utcnow()
