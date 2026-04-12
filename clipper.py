import csv
import os
import re

import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageDraw


RENDER_SCALE = 4
HEADER_CUTOFF = 52
FOOTER_CUTOFF = 48
LEFT_ANCHOR_LIMIT = 90
ANCHOR_PADDING = 6
NUMBER_MASK_PADDING = 5
CONTENT_THRESHOLD = 230
MARGIN_STRIP_SCAN_WIDTH = 60
MARGIN_STRIP_MEAN_MAX = 245
MARGIN_STRIP_DARK_ROW_RATIO_MIN = 0.25
MARGIN_CLEAR_MEAN_MIN = 248
MARGIN_CLEAR_DARK_ROW_RATIO_MAX = 0.10
MARGIN_WORDS = {"DO", "NOT", "WRITE", "IN", "THIS", "MARGIN"}
FOOTER_WORDS = {"©", "UCLES", *MARGIN_WORDS}
PAPER_CODE_RE = re.compile(r"^\d{4}/\d{2}/[A-Z]/[A-Z]/\d{2}$")
EDGE_WORD_ZONE = 36
EDGE_CLIP_PADDING = 8
FOOTER_MARKER_BAND = 80
FOOTER_PADDING = 6
HEADER_SCAN_LIMIT = 112
HEADER_LINE_Y_SNAP = 4
HEADER_MIN_WORDS = 3
HEADER_MIN_ALPHA = 12
HEADER_PADDING = 4


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


def is_footer_marker(text):
    stripped = str(text).strip()
    if not stripped:
        return False
    if stripped in FOOTER_WORDS:
        return True
    if PAPER_CODE_RE.match(stripped):
        return True
    if "/" in stripped and stripped.count("/") >= 3:
        return True
    if not stripped.isascii() and len(stripped) >= 6:
        return True
    return False


def find_horizontal_clip_bounds(words, page_width):
    left = 0
    right = page_width

    left_margin_words = [
        word for word in words
        if word[2] <= EDGE_WORD_ZONE and str(word[4]).strip() in MARGIN_WORDS
    ]
    right_margin_words = [
        word for word in words
        if word[0] >= page_width - EDGE_WORD_ZONE and str(word[4]).strip() in MARGIN_WORDS
    ]

    if left_margin_words:
        left = max(word[2] for word in left_margin_words) + EDGE_CLIP_PADDING

    if right_margin_words:
        right = min(word[0] for word in right_margin_words) - EDGE_CLIP_PADDING

    if right <= left or (right - left) < (page_width * 0.7):
        return 0, page_width

    return left, right


def find_footer_cutoff(words, page_width, page_height):
    footer_markers = [
        word for word in words
        if word[1] >= page_height - FOOTER_MARKER_BAND
        and (
            is_footer_marker(word[4])
            or word[0] <= EDGE_WORD_ZONE
            or word[2] >= page_width - EDGE_WORD_ZONE
        )
    ]

    if not footer_markers:
        return None

    return min(word[1] for word in footer_markers) - FOOTER_PADDING


def content_word_score(text):
    stripped = str(text).strip()
    if not stripped:
        return 0
    if stripped in MARGIN_WORDS:
        return 0
    if is_footer_marker(stripped):
        return 0
    return sum(1 for char in stripped if char.isalpha())


def find_content_line_top(words, left_bound, right_bound):
    lines = {}

    for word in words:
        x0, y0, x1, y1, text = word[:5]
        if x1 <= left_bound or x0 >= right_bound:
            continue
        if y0 < (HEADER_CUTOFF - 6) or y0 > HEADER_SCAN_LIMIT:
            continue

        score = content_word_score(text)
        if score <= 0:
            continue

        line_key = int(y0 / HEADER_LINE_Y_SNAP) * HEADER_LINE_Y_SNAP
        stats = lines.setdefault(line_key, {"top": y0, "words": 0, "alpha": 0})
        stats["top"] = min(stats["top"], y0)
        stats["words"] += 1
        stats["alpha"] += score

    for line_key in sorted(lines):
        stats = lines[line_key]
        if stats["words"] >= HEADER_MIN_WORDS and stats["alpha"] >= HEADER_MIN_ALPHA:
            return max(HEADER_CUTOFF, stats["top"] - HEADER_PADDING)

    return None


def build_clip_rect(page, words, q_num, is_first_page, is_last_page):
    page_rect = page.rect
    page_width = page_rect.width
    page_height = page_rect.height

    top = HEADER_CUTOFF
    bottom = page_height - FOOTER_CUTOFF
    left, right = find_horizontal_clip_bounds(words, page_width)
    start_anchor = None
    next_anchor = None
    content_line_top = find_content_line_top(words, left, right)

    if is_first_page:
        start_anchor = find_question_anchor(words, q_num, page_height)
        if start_anchor:
            top = max(HEADER_CUTOFF, start_anchor[1] - ANCHOR_PADDING)
    if content_line_top is not None:
        top = max(top, content_line_top)

    if is_last_page:
        next_anchor = find_question_anchor(words, int(q_num) + 1, page_height)
        if next_anchor:
            bottom = min(bottom, next_anchor[1] - ANCHOR_PADDING)

    footer_cutoff = find_footer_cutoff(words, page_width, page_height)
    if footer_cutoff is not None:
        bottom = min(bottom, footer_cutoff)

    if bottom <= top:
        top = HEADER_CUTOFF
        bottom = page_height - FOOTER_CUTOFF

    clip_rect = fitz.Rect(left, top, right, bottom)
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
            max(0, int((x0 - clip_rect.x0 - NUMBER_MASK_PADDING) * RENDER_SCALE)),
            max(0, int((y0 - clip_rect.y0 - NUMBER_MASK_PADDING) * RENDER_SCALE)),
            min(image.width, int((x1 - clip_rect.x0 + NUMBER_MASK_PADDING) * RENDER_SCALE)),
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


def content_bbox(image):
    grayscale = image.convert("L")
    mask = grayscale.point(
        lambda pixel: 255 if pixel < CONTENT_THRESHOLD else 0,
        mode="L",
    )
    return mask.getbbox()


def get_band_stats(grayscale, x0, x1):
    band = grayscale.crop((x0, 0, x1, grayscale.height))
    pixels = list(band.getdata())
    mean = sum(pixels) / max(1, len(pixels))

    dark_rows = 0
    for y in range(grayscale.height):
        row = band.crop((0, y, band.width, y + 1))
        if min(row.getdata()) < 120:
            dark_rows += 1

    return mean, dark_rows / max(1, grayscale.height)


def trim_page_edge_gutters(image):
    grayscale = image.convert("L")
    width, height = grayscale.size
    scan = min(MARGIN_STRIP_SCAN_WIDTH, width // 4)
    if scan <= 0:
        return image

    left_strip = get_band_stats(grayscale, 0, scan)
    left_inner = get_band_stats(grayscale, scan, min(width, scan * 2))
    right_strip = get_band_stats(grayscale, max(0, width - scan), width)
    right_inner = get_band_stats(grayscale, max(0, width - (scan * 2)), max(0, width - scan))

    left_crop = scan if (
        left_strip[0] <= MARGIN_STRIP_MEAN_MAX
        and left_strip[1] >= MARGIN_STRIP_DARK_ROW_RATIO_MIN
        and left_inner[0] >= MARGIN_CLEAR_MEAN_MIN
        and left_inner[1] <= MARGIN_CLEAR_DARK_ROW_RATIO_MAX
    ) else 0

    right_crop = scan if (
        right_strip[0] <= MARGIN_STRIP_MEAN_MAX
        and right_strip[1] >= MARGIN_STRIP_DARK_ROW_RATIO_MIN
        and right_inner[0] >= MARGIN_CLEAR_MEAN_MIN
        and right_inner[1] <= MARGIN_CLEAR_DARK_ROW_RATIO_MAX
    ) else 0

    return image.crop((left_crop, 0, max(left_crop + 1, width - right_crop), height))


def trim_outer_whitespace(image, padding=10):
    bbox = content_bbox(image)

    if not bbox:
        return image

    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((left, top, right, bottom))


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
        page_image = trim_page_edge_gutters(page_image)
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

            master_canvas = trim_outer_whitespace(stitch_images(page_images))
            master_canvas.save(output_path, format="PNG")
            generated += 1
            print(f"   -> Saved: {output_path}")

    print("\n--- Processing Complete ---")
    print(f"New images created: {generated}")
    print(f"Existing images skipped: {skipped}")


if __name__ == "__main__":
    run_bulletproof_clipper("map.csv")
