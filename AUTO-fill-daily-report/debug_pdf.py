import fitz # PyMuPDF
import os

source_dir = r"\\DESKTOP-U37AB2R\Desktop\سكانات"
files = [f for f in os.listdir(source_dir) if f.lower().endswith('.pdf')]

if not files:
    print("No PDFs.")
else:
    for filename in files[:2]:
        path = os.path.join(source_dir, filename)
        print(f"\n--- Checking: {filename} ---")
        try:
            doc = fitz.open(path)
            for i, page in enumerate(doc):
                text = page.get_text()
                if text:
                    print(f"Page {i+1} Text:\n{text[:500]}")
                else:
                    # check for images
                    imgs = page.get_images()
                    print(f"Page {i+1} has no text but has {len(imgs)} images.")
        except Exception as e:
            print(f"Error: {e}")
