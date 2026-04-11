import os
from ocrmac import ocrmac
from pdf2image import convert_from_path

folders = ["ms", "qp"]

for folder in folders:
    if not os.path.isdir(folder): continue

    print(f"--- Processing folder: {folder} ---")
    files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]

    for filename in files:
        pdf_path = os.path.join(folder, filename)
        txt_path = os.path.join(folder, os.path.splitext(filename)[0] + ".txt")

        if os.path.exists(txt_path): continue

        print(f"OCR-ing: {filename}...")

        try:
            # 1. Convert PDF pages to images (at 200 DPI for good balance of speed/accuracy)
            images = convert_from_path(pdf_path, dpi=200)

            all_page_text = []

            # 2. Process each page image with ocrmac
            for i, image in enumerate(images):
                # We pass the image object directly to ocrmac
                annotations = ocrmac.OCR(image).recognize()
                page_text = "\n".join([line[0] for line in annotations])
                all_page_text.append(f"--- Page {i+1} ---\n{page_text}")

            # 3. Save the result
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(all_page_text))

        except Exception as e:
            print(f"Error processing {filename}: {e}")

print("\nDone!")
