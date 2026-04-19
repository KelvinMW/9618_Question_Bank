import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAP_FILE = ROOT / "map.csv"
TRANSCRIPTS_DIR = ROOT / "transcripts"
SUPP_FILES_DIR = ROOT / "supp_files"
OUTPUT_FILE = ROOT / "question_source_files.json"
PAGE_SPLIT_RE = re.compile(r"(?=--- Page \d+ ---)")


def load_map_rows():
    with MAP_FILE.open(mode="r", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, skipinitialspace=True))


def load_supp_filenames():
    return sorted(path.name for path in SUPP_FILES_DIR.iterdir() if path.is_file())


def load_transcript_text(paper, start_page, end_page):
    transcript_path = TRANSCRIPTS_DIR / f"{paper}.txt"
    if not transcript_path.exists():
        return ""

    raw_text = transcript_path.read_text(encoding="utf-8", errors="ignore")
    chunks = PAGE_SPLIT_RE.split(raw_text)
    page_map = {}

    for chunk in chunks:
        match = re.match(r"--- Page (\d+) ---", chunk.strip())
        if not match:
            continue
        page_map[int(match.group(1))] = chunk

    selected = [
        page_map[page_number]
        for page_number in range(start_page + 1, end_page + 2)
        if page_number in page_map
    ]
    return "\n".join(selected)


def slice_transcript_to_question(text, q_num):
    start_match = re.search(rf"(?m)^\s*{re.escape(str(q_num))}\b", text)
    if not start_match:
        return text

    start = start_match.start()
    try:
        next_q_num = int(q_num) + 1
    except (TypeError, ValueError):
        return text[start:]

    next_match = re.search(rf"(?m)^\s*{next_q_num}\b", text[start + 1:])
    if next_match:
        end = start + 1 + next_match.start()
        return text[start:end]

    return text[start:]


def build_source_file_map():
    supp_filenames = load_supp_filenames()
    results = {}

    for row in load_map_rows():
        paper = str(row.get("filename", "")).strip()
        q_num = str(row.get("q_num", "")).strip()
        folder = str(row.get("folder", "")).strip()

        if folder != "qp" or not paper.endswith(("41", "42", "43")):
            continue

        try:
            start_page = int(row["start_page"]) - 1
            end_page = int(row["end_page"]) - 1
        except (TypeError, ValueError):
            continue

        transcript_text = load_transcript_text(paper, start_page, end_page)
        if not transcript_text:
            continue

        question_text = slice_transcript_to_question(transcript_text, q_num)
        matches = [name for name in supp_filenames if name.lower() in question_text.lower()]
        if matches:
            results[f"{paper}::{q_num}"] = matches

    return results


def main():
    source_map = build_source_file_map()
    OUTPUT_FILE.write_text(json.dumps(source_map, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(source_map)} question source mappings to {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
