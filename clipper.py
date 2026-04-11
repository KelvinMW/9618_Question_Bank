import fitz  # PyMuPDF
from PIL import Image
import os
import csv

def run_bulletproof_clipper(csv_path):
    # 1. Create output directories
    os.makedirs("static/crops/qp", exist_ok=True)
    os.makedirs("static/crops/ms", exist_ok=True)

    # 2. Read the Map
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    with open(csv_path, mode='r') as f:
        reader = csv.DictReader(f, skipinitialspace=True)

        skipped = 0
        generated = 0

        for row in reader:
            current_file = row['filename'].strip()
            current_folder = row['folder'].strip()
            q_num = row['q_num'].strip()

            pdf_path = f"{current_folder}/{current_file}.pdf"
            output_path = f"static/crops/{current_folder}/{current_file}_q{q_num}.png"

            # --- SKIP LOGIC ---
            if os.path.exists(output_path):
                skipped += 1
                continue

            if not os.path.exists(pdf_path):
                print(f"!! File not found: {pdf_path}")
                continue

            print(f">> Extracting {current_file} Q{q_num}...")

            doc = fitz.open(pdf_path)
            # Ensure start/end pages exist and are valid numbers
            try:
                start = int(row['start_page']) - 1
                end = int(row['end_page']) - 1
            except (ValueError, TypeError):
                print(f"!! Invalid page range for row {current_file} Q{q_num}")
                continue

            # 3. Extract pages as PIL Images
            page_images = []
            for p_num in range(start, end + 1):
                if p_num < 0 or p_num >= len(doc):
                    continue

                page = doc[p_num]
                # 2x zoom for crisp text
                pix = page.get_pixmap(matrix=fitz.Matrix(4, 4))

                # Convert PyMuPDF Pixmap to a Pillow Image
                mode = "RGBA" if pix.alpha else "RGB"
                img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                page_images.append(img)

            doc.close()

            # 4. Stitch Images with Pillow
            if not page_images:
                continue

            # Calculate total canvas size
            max_width = max(img.width for img in page_images)
            total_height = sum(img.height for img in page_images)

            # Create a blank white canvas
            master_canvas = Image.new("RGB", (max_width, total_height), "white")

            # Paste each image sequentially
            y_offset = 0
            for img in page_images:
                master_canvas.paste(img, (0, y_offset))
                y_offset += img.height

            # 5. Save the final product
            master_canvas.save(output_path, format="PNG")
            generated += 1
            print(f"   -> Saved: {output_path}")

    print(f"\n--- Processing Complete ---")
    print(f"New images created: {generated}")
    print(f"Existing images skipped: {skipped}")

if __name__ == "__main__":
    run_bulletproof_clipper("map.csv")
