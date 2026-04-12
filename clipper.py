import csv
import os

import fitz  # PyMuPDF
from PIL import Image, ImageDraw


RENDER_SCALE = 4
HEADER_CUTOFF = 52
FOOTER_CUTOFF = 48
LEFT_ANCHOR_LIMIT = 90
ANCHOR_PADDING = 6
NUMBER_MASK_PADDING = 5


def parse_page_range(row):
    try:
        start = int(row["start_page"]) - 1
        end = int(row["end_page"]) - 1
    except (ValueError, TypeError):
        return None, None
    return start, end


def get_page_words(page):
    return page.get_text("words", sort=True)


def find_question_anchor(words, q_num, page_height):
    q_num = str(q_num).strip()
    lower_bound = HEADER_CUTOFF
    upper_bound = page_height - FOOTER_CUTOFF

    candidates = [
        word
        for word in words
        if word[4] == q_num
        and word[0] <= LEFT_ANCHOR_LIMIT
        and lower_bound <= word[1] <= upper_bound
    ]

    if not candidates:
        return None

    return min(candidates, key=lambda word: (word[1], word[0]))


def build_clip_rect(page, words, q_num, is_first_page, is_last_page):
    page_rect = page.rect
    page_height = page_rect.height

    top = HEADER_CUTOFF
    bottom = page_height - FOOTER_CUTOFF
    start_anchor = None
    next_anchor = None

    if is_first_page:
        start_anchor = find_question_anchor(words, q_num, page_height)
        if start_anchor:
            top = max(HEADER_CUTOFF, start_anchor[1] - ANCHOR_PADDING)

    if is_last_page:
        next_anchor = find_question_anchor(words, int(q_num) + 1, page_height)
        if next_anchor:
            bottom = min(bottom, next_anchor[1] - ANCHOR_PADDING)

    if bottom <= top:
        top = HEADER_CUTOFF
        bottom = page_height - FOOTER_CUTOFF

    clip_rect = fitz.Rect(0, top, page_rect.width, bottom)
    return clip_rect, start_anchor


def render_cropped_page(page, clip_rect, start_anchor, is_first_page):
    pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE), clip=clip_rect)
    mode = "RGBA" if pix.alpha else "RGB"
    image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

    if image.mode != "RGB":
        image = image.convert("RGB")

    if is_first_page and start_anchor:
        draw = ImageDraw.Draw(image)
        x0, y0, x1, y1 = start_anchor[:4]
        mask_rect = (
            max(0, int((x0 - NUMBER_MASK_PADDING) * RENDER_SCALE)),
            max(0, int((y0 - clip_rect.y0 - NUMBER_MASK_PADDING) * RENDER_SCALE)),
            min(image.width, int((x1 + NUMBER_MASK_PADDING) * RENDER_SCALE)),
            min(image.height, int((y1 - clip_rect.y0 + NUMBER_MASK_PADDING) * RENDER_SCALE)),
        )
        draw.rectangle(mask_rect, fill="white")

    return image


def stitch_images(images):
    max_width = max(img.width for img in images)
    total_height = sum(img.height for img in images)
    master_canvas = Image.new("RGB", (max_width, total_height), "white")

    y_offset = 0
    for img in images:
        master_canvas.paste(img, (0, y_offset))
        y_offset += img.height

    return master_canvas


def extract_question_images(doc, start_page, end_page, q_num):
    page_images = []

    for page_index in range(start_page, end_page + 1):
        if page_index < 0 or page_index >= len(doc):
            continue

        page = doc[page_index]
        words = get_page_words(page)
        clip_rect, start_anchor = build_clip_rect(
            page,
            words,
            q_num,
            is_first_page=(page_index == start_page),
            is_last_page=(page_index == end_page),
        )

        page_image = render_cropped_page(
            page,
            clip_rect,
            start_anchor,
            is_first_page=(page_index == start_page),
        )
        page_images.append(page_image)

    return page_images


def run_bulletproof_clipper(csv_path):
    os.makedirs("static/crops/qp", exist_ok=True)
    os.makedirs("static/crops/ms", exist_ok=True)

    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, skipinitialspace=True)

        skipped = 0
        generated = 0

        for row in reader:
            current_file = row["filename"].strip()
            current_folder = row["folder"].strip()
            q_num = row["q_num"].strip()

            pdf_path = f"{current_folder}/{current_file}.pdf"
            output_path = f"static/crops/{current_folder}/{current_file}_q{q_num}.png"

            if os.path.exists(output_path):
                skipped += 1
                continue

            if not os.path.exists(pdf_path):
                print(f"!! File not found: {pdf_path}")
                continue

            start_page, end_page = parse_page_range(row)
            if start_page is None or end_page is None:
                print(f"!! Invalid page range for row {current_file} Q{q_num}")
                continue

            print(f">> Extracting {current_file} Q{q_num}...")

            doc = fitz.open(pdf_path)
            try:
                page_images = extract_question_images(doc, start_page, end_page, q_num)
            finally:
                doc.close()

            if not page_images:
                print(f"!! No pages rendered for {current_file} Q{q_num}")
                continue

            master_canvas = stitch_images(page_images)
            master_canvas.save(output_path, format="PNG")
            generated += 1
            print(f"   -> Saved: {output_path}")

    print("\n--- Processing Complete ---")
    print(f"New images created: {generated}")
    print(f"Existing images skipped: {skipped}")


if __name__ == "__main__":
    run_bulletproof_clipper("map.csv")
