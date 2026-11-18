import time
from tqdm import tqdm

for i in tqdm(
    range(10),
    desc="Testing simulation",
    bar_format=(
        "{desc}: {percentage:3.0f}%|{bar}| "
        "{n_fmt}/{total_fmt} "
        "[Elapsed: {elapsed} | ETR: {remaining}]"
    ),
    disable=False,
):
    time.sleep(1)