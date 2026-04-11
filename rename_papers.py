import os
import re

# Mapping for month abbreviations
months_map = {
    "january": "jan", "february": "feb", "march": "mar", "april": "apr",
    "may": "may", "june": "june", "july": "july", "august": "aug",
    "september": "sep", "october": "oct", "november": "nov", "december": "dec"
}

folders = ["ins", "ms", "other", "qp", "src"]

for folder in folders:
    if not os.path.isdir(folder):
        continue

    for filename in os.listdir(folder):
        # Matches: [Month] [4-digit Year] (the rest of the name)
        # e.g., "June 2021 Paper 1.pdf"
        match = re.match(r'^(\w+)\s+(\d{2})(\d{2})\s*(.*)', filename)

        if match:
            month_full = match.group(1).lower()
            year_short = match.group(3)
            rest_of_name = match.group(4)

            # Get the short version of the month
            month_short = months_map.get(month_full, month_full)

            # Construct new name: yy_month_rest.pdf
            new_name = f"{year_short}_{month_short}_{rest_of_name}".strip("_")

            old_path = os.path.join(folder, filename)
            new_path = os.path.join(folder, new_name)

            print(f"Renaming: {filename} -> {new_name}")
            os.rename(old_path, new_path)
