import csv
import json
import os
import re

import fitz

import clipper


MAP_FILE = "map.csv"
OUTPUT_FILE = "question_marks.json"
QUESTION_FOLDER = "qp"
MARK_RE = re.compile(r"\[(\d{1,2})\]")
OCR_MARK_RE = re.compile(r"(?<![\dA-Za-z])1([1-9])\]|(?<![\dA-Za-z])([1-9])\]")
PAGE_SPLIT_RE = re.compile(r"(?=--- Page \d+ ---)")


def load_map_rows():
    with open(MAP_FILE, mode="r", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, skipinitialspace=True))


def extract_question_text(doc, start_page, end_page, q_num):
    segments = []

    for page_index in range(start_page, end_page + 1):
        if page_index < 0 or page_index >= len(doc):
            continue

        page = doc[page_index]
        words = clipper.get_page_words(page)
        clip_rect, _ = clipper.build_clip_rect(
            page,
            words,
            q_num,
            is_first_page=(page_index == start_page),
            is_last_page=(page_index == end_page),
        )
        text = page.get_text("text", clip=clip_rect, sort=True)
        if text.strip():
            segments.append(text)

    return "\n".join(segments)


def infer_total_marks(mark_values):
    if not mark_values:
        return None

    if len(mark_values) == 1:
        return mark_values[0]

    subtotal = sum(mark_values[:-1])
    last_value = mark_values[-1]

    # Only treat the trailing mark as a printed total when there are already
    # multiple earlier part-marks to sum. For two-part questions like [2][2],
    # collapsing the second value would undercount the total as 2 instead of 4.
    if len(mark_values) >= 3 and subtotal and last_value == subtotal:
        return subtotal

    return sum(mark_values)


def load_transcript_text(paper, start_page, end_page):
    transcript_path = os.path.join("transcripts", f"{paper}.txt")
    if not os.path.exists(transcript_path):
        return ""

    raw_text = open(transcript_path, encoding="utf-8", errors="ignore").read()
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
    next_match = re.search(rf"(?m)^\s*{int(q_num) + 1}\b", text[start + 1:])
    if next_match:
        end = start + 1 + next_match.start()
        return text[start:end]

    return text[start:]


def extract_mark_values(question_text):
    direct_marks = [int(value) for value in MARK_RE.findall(question_text)]
    if direct_marks:
        return direct_marks

    fallback_marks = []
    for match in OCR_MARK_RE.finditer(question_text):
        value = next(group for group in match.groups() if group)
        fallback_marks.append(int(value))
    return fallback_marks


def build_question_marks():
    results = {}
    rows = [row for row in load_map_rows() if row.get("folder", "").strip() == QUESTION_FOLDER]

    for row in rows:
        paper = row["filename"].strip()
        q_num = str(row["q_num"]).strip()
        pdf_path = os.path.join(QUESTION_FOLDER, f"{paper}.pdf")
        if not os.path.exists(pdf_path):
            continue

        try:
            start_page = int(row["start_page"]) - 1
            end_page = int(row["end_page"]) - 1
        except (TypeError, ValueError):
            continue

        with fitz.open(pdf_path) as doc:
            question_text = extract_question_text(doc, start_page, end_page, q_num)

        mark_values = extract_mark_values(question_text)
        if not mark_values:
            transcript_text = load_transcript_text(paper, start_page, end_page)
            if transcript_text:
                mark_values = extract_mark_values(slice_transcript_to_question(transcript_text, q_num))
        total_marks = infer_total_marks(mark_values)

        if total_marks is not None:
            results[f"{paper}_q{q_num}"] = total_marks

    return results


def main():
    question_marks = build_question_marks()
    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(question_marks, handle, indent=2, sort_keys=True)
    print(f"Wrote {len(question_marks)} question totals to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
