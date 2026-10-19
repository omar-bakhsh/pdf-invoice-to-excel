import easyocr
import fitz
import os
from PIL import Image

# إزالة التعارض مع BioTime
os.environ["PYTHONPATH"] = ""
os.environ["PYTHONHOME"] = ""

def debug_ocr():
    print("--- 1. Initializing EasyOCR (This may take a moment) ---")
    reader = easyocr.Reader(['ar', 'en'], gpu=False)

    source_dir = r"\\DESKTOP-U37AB2R\Desktop\سكانات"
    files = [f for f in os.listdir(source_dir) if f.lower().endswith('.pdf')]

    if not files:
        print("No PDF files found in Scans.")
        return

    test_file = os.path.join(source_dir, files[0])
    print(f"--- 2. Inspecting: {files[0]} ---")
    
    try:
        doc = fitz.open(test_file)
        page = doc[0]
        pix = page.get_pixmap()
        img_path = "temp_debug.png"
        pix.save(img_path)
        doc.close()
        
        print("--- 3. Running OCR on first page ---")
        result = reader.readtext(img_path, detail=0)
        
        print("\n--- [RESULT] Extracted Text from Invoice ---")
        for i, word in enumerate(result):
            print(f"[{i}] {word}")
        print("--- [END RESULT] ---")
        
        if os.path.exists(img_path):
            os.remove(img_path)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_ocr()
