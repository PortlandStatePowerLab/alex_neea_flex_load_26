import os
import shutil
from datetime import date

script_dir = os.path.dirname(os.path.abspath(__file__))

READY_DIR = os.path.join(script_dir, "Ready_data")

if os.path.isdir(READY_DIR):
    shutil.rmtree(READY_DIR)

files = [f for f in os.listdir(script_dir) if os.path.isfile(os.path.join(script_dir, f))]
print(files)
for i in range(2026, (date.today().year + 1)):
    for j in range(len(files)):
        if files[j][0:4] == str(i):
            os.remove(os.path.join(script_dir, files[j]))

print("Removed old files!")
