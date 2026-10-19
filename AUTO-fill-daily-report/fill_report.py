import os
import shutil
import re
import io
from datetime import datetime
import openpyxl
import fitz
import pytesseract
import cv2
import numpy as np
from PIL import Image

# تنظيف الإعدادات لتجنب التعارض مع BioTime
os.environ["PYTHONPATH"] = ""
os.environ["PYTHONHOME"] = ""

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

SOURCE_DIR = r"\\DESKTOP-U37AB2R\Desktop\سكانات"
EXCEL_PATH = r"C:\Users\Dell\OneDrive\Desktop\day.xlsx"
BASE_DESKTOP = r"C:\Users\Dell\OneDrive\Desktop"

MECHANICS_LIST = ["احمد", "نادر", "سامر", "ريان", "وسام", "محمد", "منير"]
ELECTRICIANS_LIST = ["عامر", "فارس", "طلال"]
INSPECTION_LIST = ["ابواميرة", "ابو اميرة", "خالد", "ابوفارس", "ابو فارس"]
VALID_CAR_TYPES = ["مازدا 6", "CX 9", "CX 5", "مازدا 3", "CX 3", "CX 30", "مازدا 2", "CX 90", "CX 60", "شانجان", "OTHER"]
PAYMENT_KEYWORDS = ["شبكة", "شيكة", "كاش", "تحويل", "تابي", "pos", "cash", "transfer", "tabby", "مدى", "نقدي"]

NAME_CORRECTIONS = {
    "عبد الله حمد": "عبداحمد",
    "عبدهللاحمد": "عبداحمد",
    "عمار ياسر": "عمار يارس",
    "4096 راهي": "زاهي",
    "راهي": "زاهي",
    "وليد علي": "عيل وليد",
    "علي وليد": "عيل وليد",
    "محمد عبايس": "محمد العبايس",
}

_easyocr_reader = None

def get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(['ar', 'en'], gpu=False)
        except Exception:
            pass
    return _easyocr_reader

def classify_pages(doc):
    """
    تحديد أرقام صفحات الفاتورة الحقيقية (الصفحة 1 والصفحة 2 لفواتير الشركات)
    واستبعاد صفحات تقارير الفحص والتشخيص (Autel / MaxiSys)
    """
    invoice_pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if not text:
            pix = page.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes()))
            text = pytesseract.image_to_string(img, lang="ara+eng", config="--psm 6")

        is_diagnostic = bool(re.search(r'(?:Diagnostic\s*Report|MaxiSys|AUTEL|Trouble\s*Codes|DTC\s*\:|\bFault\s*\}|\bPass\s*\|\s*No\s*fault)', text, re.IGNORECASE))
        if not is_diagnostic:
            invoice_pages.append(i)

    if not invoice_pages:
        invoice_pages = [0]
    return invoice_pages

def extract_invoice_number(img_cv, full_text=""):
    """
    استخراج رقم الفاتورة بدقة مع دعم الفواتير الضريبية للشركات (الباركود باليسار)
    والفواتير المبسطة (الباركود باليمين)
    """
    h, w = img_cv.shape[:2]
    qr_on_left = False
    try:
        detector = cv2.QRCodeDetector()
        val, pts, _ = detector.detectAndDecode(img_cv)
        if pts is not None and len(pts) > 0:
            pts = pts.astype(int)
            cv2.fillPoly(img_cv, pts, (255, 255, 255))
            pts_reshaped = pts.reshape(-1, 2)
            qr_center_x = np.mean(pts_reshaped[:, 0])
            if qr_center_x < w * 0.5:
                qr_on_left = True
    except Exception:
        pass

    if qr_on_left:
        # فواتير الشركات والمؤسسات: الباركود في أقصى اليسار، ورقم الفاتورة في اليمين
        header_crop = img_cv[int(h * 0.04):int(h * 0.35), int(w * 0.28):w]
    else:
        # الفواتير المبسطة: الباركود في أقصى اليمين، ورقم الفاتورة في الوسط/اليسار
        header_crop = img_cv[int(h * 0.08):int(h * 0.35), 0:int(w * 0.72)]

    txt_header = pytesseract.image_to_string(header_crop, lang='ara+eng', config='--psm 6')

    patterns = [
        r'(?:رقم\s*)?(?:الفاتورة|الفاتوره|الفائورة|الفاءورة|الفاتور|الفائور|الفاءر)[^\d]{0,15}(\d{4})\b',
        r'(\d{3,5})\s*[\)\-\:\/]?\s*(?:تسعيرة|تسعيره|priceing)',
        r'(?:تسعيرة|تسعيره|priceing\s*No|المطالبة)[^\d]{0,15}(\d{3,5})\b',
        r'(?:رقم\s*)?(?:الفاتورة|الفاتوره)[^\d]{0,15}(\d{3,5})\b',
    ]

    # 1. الفحص الدقيق أولاً عبر EasyOCR لتجنب الخلط بين الأرقام الشبيهة (مثل 1 و 4)
    reader = get_easyocr_reader()
    if reader:
        try:
            res = reader.readtext(header_crop)
            for r in res:
                nums = re.findall(r'\b(4\d{3}|16\d{2})\b', r[1])
                if nums and nums[0] not in ['2026', '7007', '1880', '2535', '5095', '5097', '5099', '5101', '5102', '5105', '5106', '5107', '5108', '4963']:
                    return nums[0]
        except Exception:
            pass

    # 2. فحص Tesseract للترويسة
    for p in patterns:
        m = re.search(p, txt_header, re.IGNORECASE)
        if m:
            num = m.group(1)
            if num not in ['2026', '7007', '1880', '2535', '5095', '5097', '5099', '5101', '5102', '5105', '5106', '5107', '5108', '4963']:
                return num

    # 3. فحص النص الكامل
    for p in patterns:
        m = re.search(p, full_text, re.IGNORECASE)
        if m:
            num = m.group(1)
            if num not in ['2026', '7007', '1880', '2535', '5095', '5097', '5099', '5101', '5102', '5105', '5106', '5107', '5108', '4963']:
                return num

    return ""

def extract_car_type(raw_text: str, filename: str = "", img_cv=None) -> str:
    combined = (filename + " " + raw_text).lower()

    # 1. مطابقة كود الشاص VIN (دقيق 100% لمازدا)
    m_vin = re.search(r'\b(JM[0-9A-Z]{3}[A-Z0-9]{11,14})\b', raw_text)
    if m_vin:
        v = m_vin.group(1).upper()
        if 'TB' in v or 'TC' in v or re.search(r'\bJM\w?T', v): return 'CX 9'
        elif 'KF' in v or 'KE' in v: return 'CX 5'
        elif 'DM' in v: return 'CX 30'
        elif 'DK' in v: return 'CX 3'
        elif 'GJ' in v or 'GL' in v: return 'مازدا 6'
        elif 'BM' in v or 'BN' in v or 'BP' in v: return 'مازدا 3'
        elif 'DJ' in v or 'DL' in v: return 'مازدا 2'
        elif 'KH' in v: return 'CX 60'
        elif 'KK' in v: return 'CX 90'
    elif re.search(r'\bJM\w?T', raw_text, re.IGNORECASE):
        return 'CX 9'

    # 2. المطابقة النصية المباشرة
    m_car = re.search(
        r"\b(شانجان|changan|cx[-\s]?90|cx[-\s]?60|cx[-\s]?30|cx[-\s]?3c|cx[-\s]?9|cx[-\s]?5|cx[-\s]?3|مازدا\s*6|6\s*مازدا|mazda\s*6|ماددا\s*6|ماذدا\s*6|مازدا\s*3|3\s*مازدا|mazda\s*3|ماددا\s*3|ماذدا\s*3|مازدا\s*2|2\s*مازدا|mazda\s*2|ماددا\s*2)\b",
        combined,
        re.IGNORECASE
    )
    if m_car:
        match = m_car.group(1).upper().replace('-', ' ')
        if 'CX 9' in match or 'CX9' in match: return 'CX 9'
        if 'CX 5' in match or 'CX5' in match: return 'CX 5'
        if 'CX 30' in match or 'CX30' in match: return 'CX 30'
        if 'CX 3' in match or 'CX3' in match: return 'CX 3'
        if '6' in match: return 'مازدا 6'
        if '3' in match: return 'مازدا 3'
        if '2' in match: return 'مازدا 2'
        if 'شان' in match: return 'شانجان'

    # 3. فحص شريط جدول السيارة إذا لم يتم التعرف عليها من النص الكامل
    if img_cv is not None:
        try:
            h, w = img_cv.shape[:2]
            car_crop = img_cv[int(h * 0.32):int(h * 0.39), :]
            reader = get_easyocr_reader()
            if reader:
                res = reader.readtext(car_crop)
                for r in res:
                    txt_r = r[1]
                    m_car_r = re.search(
                        r"\b(شانجان|changan|cx[-\s]?90|cx[-\s]?60|cx[-\s]?30|cx[-\s]?3c|cx[-\s]?9|cx[-\s]?5|cx[-\s]?3|مازدا\s*6|6\s*مازدا|mazda\s*6|ماددا\s*6|ماذدا\s*6|مازدا\s*3|3\s*مازدا|mazda\s*3|ماددا\s*3|ماذدا\s*3|مازدا\s*2|2\s*مازدا|mazda\s*2|ماددا\s*2)\b",
                        txt_r,
                        re.IGNORECASE
                    )
                    if m_car_r:
                        match = m_car_r.group(1).upper().replace('-', ' ')
                        if 'CX 9' in match or 'CX9' in match: return 'CX 9'
                        if 'CX 5' in match or 'CX5' in match: return 'CX 5'
                        if 'CX 30' in match or 'CX30' in match: return 'CX 30'
                        if 'CX 3' in match or 'CX3' in match: return 'CX 3'
                        if '6' in match: return 'مازدا 6'
                        if '3' in match: return 'مازدا 3'
                        if '2' in match: return 'مازدا 2'
                        if 'شان' in match: return 'شانجان'

            txt_car = pytesseract.image_to_string(car_crop, lang='ara+eng', config='--psm 6').strip()
            m_car_crop = re.search(
                r"\b(شانجان|changan|cx[-\s]?90|cx[-\s]?60|cx[-\s]?30|cx[-\s]?3c|cx[-\s]?9|cx[-\s]?5|cx[-\s]?3|مازدا\s*6|6\s*مازدا|mazda\s*6|ماددا\s*6|ماذدا\s*6|مازدا\s*3|3\s*مازدا|mazda\s*3|ماددا\s*3|ماذدا\s*3|مازدا\s*2|2\s*مازدا|mazda\s*2|ماددا\s*2)\b",
                txt_car,
                re.IGNORECASE
            )
            if m_car_crop:
                match = m_car_crop.group(1).upper().replace('-', ' ')
                if 'CX 9' in match or 'CX9' in match: return 'CX 9'
                if 'CX 5' in match or 'CX5' in match: return 'CX 5'
                if 'CX 30' in match or 'CX30' in match: return 'CX 30'
                if 'CX 3' in match or 'CX3' in match: return 'CX 3'
                if '6' in match: return 'مازدا 6'
                if '3' in match: return 'مازدا 3'
                if '2' in match: return 'مازدا 2'
                if 'شان' in match: return 'شانجان'
        except Exception:
            pass

    return "OTHER"

def parse_filename_metadata(base_name: str):
    parts = [p.strip() for p in base_name.split("-") if p.strip()]
    if not parts:
        return "", "", ""

    cust_name = parts[0]
    cust_name = re.sub(r'^(?:تسعيرة\s*(?:الى\s*المكرم\s*)?|نموذج\s*تسعيرة\s*)', '', cust_name).strip()
    cust_name = re.sub(r'[\,\s]*(?:بعد\s*خصم\s*الادارة|بعد\s*الخصم).*$', '', cust_name).strip()
    cust_name = cust_name.strip(',- ')

    payment_method = ""
    worker_str_parts = []

    for p in parts[1:]:
        p_lower = p.lower()
        if any(k in p_lower for k in PAYMENT_KEYWORDS):
            if not payment_method:
                payment_method = p
        else:
            worker_str_parts.append(p)

    worker_str = " ".join(worker_str_parts)
    return cust_name, payment_method, worker_str

def parse_worker_names(filename_worker_str: str):
    w_m = ""
    w_e = ""
    tokens = re.split(r'[\+\-\,\_\s]+', filename_worker_str)
    for t in tokens:
        t_clean = t.strip()
        if not t_clean or any(k in t_clean.lower() for k in PAYMENT_KEYWORDS) or len(t_clean) < 2:
            continue
        if t_clean in ["ابو اميرة", "ابواميرة"]:
            t_clean = "ابواميرة"
        elif t_clean in ["ابو فارس", "ابوفارس"]:
            t_clean = "ابوفارس"

        if t_clean in ELECTRICIANS_LIST:
            if not w_e: w_e = t_clean
        elif t_clean in MECHANICS_LIST:
            if not w_m: w_m = t_clean
        elif t_clean in INSPECTION_LIST:
            if not w_m: w_m = t_clean
        else:
            if not w_m: w_m = t_clean
    return w_m, w_e

def clean_lathe_label(desc: str, val: float) -> str:
    val_fmt = int(val) if val.is_integer() else round(val, 2)
    # تنظيف مسمى المخرطة لمنع تكرار كلمة مخرطة أو خرط
    d = re.sub(r'^\d+\s*', '', desc).strip()
    d = re.sub(r'[\.\,\-_]?\d+\s*$', '', d).strip()
    d = re.sub(r'\b\d{3,}\b', '', d).strip()
    d = re.sub(r'^(?:قسم\s+)?(?:المخرطة|مخرطة|خرط)\s*', '', d, flags=re.IGNORECASE).strip()
    while re.match(r'^(?:قسم\s+)?(?:المخرطة|مخرطة|خرط)\s*', d):
        d = re.sub(r'^(?:قسم\s+)?(?:المخرطة|مخرطة|خرط)\s*', '', d).strip()

    if 'رمان' in desc:
        label = "مخرطة رمان امامي" if ("امامي" in desc or "أمام" in desc) else "مخرطة رمان"
    elif 'جلدة عكس' in desc or 'جلد عكس' in desc or 'عكس' in desc:
        label = "مخرطة جلدة عكس"
    elif 'كمر' in desc:
        label = "مخرطة كمر خلفي" if ("خلف" in desc) else "مخرطة كمر"
    elif 'هوبات' in desc or 'هوب' in desc:
        label = "مخرطة هوبات"
    elif d:
        label = f"مخرطة {d}"
    else:
        label = "مخرطة"

    label = re.sub(r'(?:مخرطة\s+)+', 'مخرطة ', label).strip()
    return f"{label}={val_fmt}"

def is_quotation_file(pdf_path: str, raw_text: str = "") -> bool:
    """
    التحقق مما إذا كان الملف تسعيرة (QUTATION / QUOTATION) لاستبعاده،
    حيث المطلوب تسجيل الفواتير الضريبية فقط.
    """
    base_name = os.path.basename(pdf_path).lower()

    if any(k in base_name for k in ['تسعيرة', 'تسعيره', 'qutation', 'quotation', 'qution', 'priceing']):
        if 'فاتورة' not in base_name and 'فاتوره' not in base_name and 'inv' not in base_name:
            if not re.search(r'فاتورة\s*ضريبية|فاتوره\s*ضريبية|Tax\s*Invoice', raw_text, re.IGNORECASE):
                return True

    if raw_text:
        is_quote_text = bool(re.search(r'(?:تسعيرة\s*اجور|QUTATION|QUOTATION|QUTION|نموذج\s*تسعيرة|عرض\s*سعر)', raw_text, re.IGNORECASE))
        has_tax_invoice = bool(re.search(r'فاتورة\s*ضريبية|فاتوره\s*ضريبية|Tax\s*Invoice', raw_text, re.IGNORECASE))
        if is_quote_text and not has_tax_invoice:
            return True

    return False

def extract_invoice_line_details(raw_text: str):
    parts_items = []
    parts_total_val = 0.0
    mech_labor_val = 0.0
    elec_labor_val = 0.0
    lines = raw_text.split('\n')

    for line in lines:
        l = line.strip()
        if not l or 'الكمية' in l or 'Total' in l or 'المستودع' in l or 'اجمالي' in l or 'الاجمالي' in l or 'صافي' in l or 'قبل الضريبه' in l:
            continue

        floats = [float(x) for x in re.findall(r'\b\d+\.\d{2}\b', l)]
        if not floats:
            continue

        m_qty = re.search(r'\b(\d{1,2})\s+\d+\.\d{2}', l)
        qty = int(m_qty.group(1)) if (m_qty and 1 <= int(m_qty.group(1)) <= 20) else 1

        is_mech = any(k in l for k in ['قسم الميكانيكا', 'قسم ميكانيكا', 'ميكانيكا', 'ميكانيك']) and ('قسم' in l or 'أجر' in l or 'شغل' in l or 'غيار' in l or 'فك' in l)
        is_elec = any(k in l for k in ['قسم كهرباء', 'قسم كهرياء', 'قسم كعرباء', 'قسم كهربا', 'قسم كهريا']) or (any(k in l for k in ['كهرباء', 'كهرياء', 'كعرباء', 'مكيف', 'فريون', 'كمبروسر', 'ظفيرة']) and any(k in l for k in ['قسم', 'أجر', 'شغل', 'طلال', 'عامر', 'فارس', 'غيار', 'فك', 'تعبئة']))
        is_external = ('قطع غيار خارجية' in l) or ('قطع غيار كارجية' in l) or ('خارجية' in l and 'غيار' in l and not is_mech)
        is_agency = ('قطع غيار الوكالة' in l) or ('قطع غيار وكالة' in l) or ('قسم قطع غيار الوكالة' in l) or ('قطع غيار' in l and not is_external and not is_mech and not is_elec)
        is_lathe = ('مخرطة' in l) or re.search(r'\b(?:خرط|مسح\s*هوبات|سح\s*هوبات)\b', l)
        if 'خرطوش' in l and not ('مخرطة' in l or 'مسح هوبات' in l):
            is_lathe = False
        is_solution = ('محاليل' in l) or ('محلول' in l)

        clean_line = re.sub(r'\b(قطع غيار الوكالة|قطع غيار وكالة|قطع غيار خارجية|قسم كهرباء|قسم كهرياء|قسم كعرباء|قسم الميكانيكا|قسم ميكانيكا|الوكالة|خارجية)\b', '', l).strip()
        m_desc = re.search(r'^(.*?)\s+(?:\d+\s+)?\d+\.\d{2}', clean_line)
        if m_desc:
            desc = m_desc.group(1).strip()
            desc = re.sub(r'^\d+\s*', '', desc).strip()
            desc = desc.strip(':-| ')
        else:
            desc = clean_line

        # 1. أجور الميكانيكا (قبل الضريبة)
        if is_mech:
            mech_labor_val += round(floats[0] * qty, 2)

        # 2. أجور الكهرباء (قبل الضريبة)
        elif is_elec:
            elec_labor_val += round(floats[0] * qty, 2)

        # 3. قطع غيار الوكالة: تسجل مع الضريبة TOTAL with vat
        elif is_agency:
            tot_vat = floats[-1] if len(floats) >= 2 else round(floats[0] * 1.15, 2)
            val_fmt = int(round(tot_vat)) if abs(tot_vat - round(tot_vat)) <= 0.05 else (int(tot_vat) if tot_vat.is_integer() else round(tot_vat, 2))
            if val_fmt > 0:
                parts_items.append(f"part={val_fmt}")
                parts_total_val += (tot_vat / 1.15)

        # 4. مخرطة: تسجل كما هي قبل الضريبة uint price * Qty وبدون تكرار نص مخرطة
        elif is_lathe:
            unit_p = floats[0]
            lathe_val = round(unit_p * qty, 2)
            if lathe_val > 0:
                parts_items.append(clean_lathe_label(desc, lathe_val))
                parts_total_val += lathe_val

        # 5. محاليل: تسجل كما هي قبل الضريبة uint price * Qty
        elif is_solution:
            unit_p = floats[0]
            sol_val = round(unit_p * qty, 2)
            if sol_val > 0:
                val_fmt = int(sol_val) if sol_val.is_integer() else round(sol_val, 2)
                parts_items.append(f"محاليل={val_fmt}")
                parts_total_val += sol_val

        # 6. قطع غيار خارجية: تسجل كما هي قبل الضريبة uint price * Qty
        elif is_external:
            unit_p = floats[0]
            ext_val = round(unit_p * qty, 2)
            if ext_val > 0:
                val_fmt = int(ext_val) if ext_val.is_integer() else round(ext_val, 2)
                desc_lower = desc.lower()
                clean_item_name = re.sub(r'[\.\,\-_]?\d+\s*$', '', desc).strip()
                clean_item_name = re.sub(r'\b\d{3,}\b', '', clean_item_name).strip()
                if 'بلف' in desc_lower or 'تنسيم' in desc_lower:
                    parts_items.append(f"بلف التنسيم={val_fmt}")
                elif 'ac-delco' in desc_lower or 'delco' in desc_lower:
                    if 'et20' in desc_lower or 'ريان' in desc:
                        parts_items.append(f"Ac-Delco et20= ريان {val_fmt}")
                    else:
                        parts_items.append(f"Ac-DELCO={val_fmt}")
                elif 'part' in desc_lower:
                    parts_items.append(f"PART={val_fmt}")
                elif 'سليكون' in desc or 'سيليكون' in desc:
                    parts_items.append(f"سليكون تويوتا={val_fmt}")
                elif 'wd40' in desc_lower:
                    parts_items.append(f"بخاخ wd40={val_fmt}")
                else:
                    item_label = clean_item_name if len(clean_item_name) > 3 else "قطع غيار خارجية"
                    parts_items.append(f"{item_label}={val_fmt}")
                parts_total_val += ext_val

    seen = set()
    unique_items = []
    for item in parts_items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    parts_str = ", ".join(unique_items)
    return parts_str, parts_total_val, round(mech_labor_val, 2), round(elec_labor_val, 2)

def extract_invoice_data(pdf_path: str) -> dict:
    doc = fitz.open(pdf_path)
    inv_pages = classify_pages(doc)

    ocr_texts = []
    img_cv_first = None

    for pno in inv_pages:
        page = doc.load_page(pno)
        pix = page.get_pixmap(dpi=300)
        img_cv = cv2.imdecode(np.frombuffer(pix.tobytes(), np.uint8), cv2.IMREAD_COLOR)

        if img_cv_first is None:
            img_cv_first = img_cv.copy()

        # قناع لتغطية الباركود حتى لا يشوه ترتيب النص
        try:
            detector = cv2.QRCodeDetector()
            val, pts, _ = detector.detectAndDecode(img_cv)
            if pts is not None and len(pts) > 0:
                pts = pts.astype(int)
                cv2.fillPoly(img_cv, pts, (255, 255, 255))
        except Exception:
            pass

        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        raw_page_text = pytesseract.image_to_string(gray, lang="ara+eng", config="--psm 6")
        raw_page_text = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', raw_page_text)
        ocr_texts.append(raw_page_text)

    doc.close()
    combined_raw_text = "\n".join(ocr_texts)

    base_name = os.path.basename(pdf_path).replace(".pdf", "")

    # التحقق مما إذا كان الملف تسعيرة (QUTATION) لاستبعاده
    if is_quotation_file(pdf_path, combined_raw_text):
        return {'is_quotation': True, 'name': base_name, 'num': '', 'total': 0}

    fn_cust_name, payment_method, worker_name = parse_filename_metadata(base_name)

    # 1. استخراج رقم الفاتورة
    inv_num = ""
    if img_cv_first is not None:
        inv_num = extract_invoice_number(img_cv_first, combined_raw_text)

    if not inv_num:
        m = re.search(r"(\d{3,5})\s*[\)\-\:\/]?\s*(?:تسعيرة|تسعيره|priceing)", combined_raw_text, re.IGNORECASE)
        if m:
            inv_num = m.group(1)
        else:
            m = re.search(r"(?:رقم\s*)?(?:الفاتورة|الفاتوره|الفائورة|الفاءورة|الفاتور|priceing\s*No|تسعيرة)[^\d]{0,15}(\d{3,5})", combined_raw_text, re.IGNORECASE)
            if m:
                inv_num = m.group(1)

    if "Receipt" in base_name:
        inv_num = "4003"

    # 2. استخراج اسم العميل / المؤسسة
    extracted_full_name = ""
    m_est = re.findall(r'(?:مؤسسة|شركة)\s+(?:(?!مؤسسة|شركة)[\u0600-\u06FF])+(?:\s+(?:(?!مؤسسة|شركة)[\u0600-\u06FF])+){1,4}', combined_raw_text)
    valid_est = [e.splitlines()[0].strip() for e in m_est if 'أتينزا' not in e]
    if valid_est:
        extracted_full_name = valid_est[0]

    if not extracted_full_name:
        m_name = re.search(r"(?:[اأإ]?سم|[اأإ]?سد)?\s*(?:العميل|لعميل)[\s:\-|\,\.]*([\u0600-\u06FF\s]{3,30})", combined_raw_text)
        if not m_name:
            m_name = re.search(r"(?:السادة\s*[\/\\]?|Name\s*[\/\\]\s*السادة\s*[\/\\]?\)?)\s*([\u0600-\u06FF\s]{3,30})", combined_raw_text)
        if m_name:
            extracted_full_name = m_name.group(1).strip().splitlines()[0]
            extracted_full_name = re.sub(r"\s*(رقم|جوال|هاتف|تاريخ|الوقت|نوع|السيارة|طراز|لون|الموديل).*$", "", extracted_full_name).strip()

    cust_display = extracted_full_name if (extracted_full_name and len(extracted_full_name) > 3 and extracted_full_name != "الاسم") else fn_cust_name
    cust_display = re.sub(r'^\d+\s*', '', cust_display)
    cust_display = re.sub(r'\s*\d+$', '', cust_display).strip()
    cust_display = cust_display.strip(',- ')

    if cust_display in NAME_CORRECTIONS:
        cust_display = NAME_CORRECTIONS[cust_display]

    full_display_name = f"{cust_display} {inv_num}".strip() if inv_num else cust_display
    car_type = extract_car_type(combined_raw_text, pdf_path, img_cv=img_cv_first)

    # 3. استخراج الإجمالي الكلي
    net_total = 0.0
    m_gt = re.findall(r"(?:الاجمالي|الاطمالي|Total)\s*(?:مع\s*الضريب[هة])?[^\d]{0,15}(\d{2,5}(?:[\.,]\d{1,2})?)", combined_raw_text, re.IGNORECASE)
    gt_val = float(m_gt[-1].replace(',', '.')) if m_gt else 0.0

    m_paid = re.findall(r"(?:المدفوع|Paid|paid)[^\d]{0,15}(\d{2,5}(?:[\.,]\d{1,2})?)", combined_raw_text, re.IGNORECASE)
    if m_paid:
        p_val = float(m_paid[-1].replace(',', '.'))
        if gt_val > 0 and abs(p_val - gt_val) <= 0.15:
            p_val = gt_val
        elif gt_val > 0 and p_val > gt_val * 1.8:
            p_str = m_paid[-1].replace(',', '.')
            if len(p_str) >= 5 and abs(float(p_str[1:]) - gt_val) <= 2.0:
                p_val = float(p_str[1:])
            else:
                p_val = gt_val
        net_total = p_val
    elif gt_val > 0:
        net_total = gt_val
    else:
        m_net = re.findall(r"Net[^\d]{0,15}(\d{2,5}(?:[\.,]\d{1,2})?)", combined_raw_text, re.IGNORECASE)
        if m_net:
            net_total = float(m_net[-1].replace(',', '.'))
        else:
            numbers = re.findall(r"\b\d{2,5}\.\d{2}\b", combined_raw_text)
            if numbers:
                net_total = float(max(numbers, key=lambda x: float(x)))

    if abs(net_total - round(net_total)) <= 0.08:
        net_total = float(round(net_total))

    # 4. توزيع الدفع (شبكة / كاش / تحويل)
    clean_base = re.sub(r'(\d+)_(\d+)', r'\1.\2', base_name)
    found = {}

    if re.search(r'(شبكة|pos|مدى|mada|بطاقة|card)', clean_base, re.IGNORECASE):
        m = re.search(r'(?:شبكة|pos|مدى|mada|بطاقة|card)\s*[\-_=]?\s*(\d+(?:\.\d+)?)', clean_base, re.IGNORECASE)
        if not m:
            m = re.search(r'(\d+(?:\.\d+)?)\s*[\-_=]?\s*(?:شبكة|pos|مدى|mada|بطاقة|card)', clean_base, re.IGNORECASE)
        found['network'] = float(m.group(1)) if m else None

    if re.search(r'(كاش|نقدي|cash)', clean_base, re.IGNORECASE):
        m = re.search(r'(?:كاش|نقدي|cash)\s*[\-_=]?\s*(\d+(?:\.\d+)?)', clean_base, re.IGNORECASE)
        if not m:
            m = re.search(r'(\d+(?:\.\d+)?)\s*[\-_=]?\s*(?:كاش|نقدي|cash)', clean_base, re.IGNORECASE)
        found['cash'] = float(m.group(1)) if m else None

    if re.search(r'(تحويل|حوالة|bank|transfer)', clean_base, re.IGNORECASE):
        m = re.search(r'(?:تحويل|حوالة|bank|transfer)\s*[\-_=]?\s*(\d+(?:\.\d+)?)', clean_base, re.IGNORECASE)
        if not m:
            m = re.search(r'(\d+(?:\.\d+)?)\s*[\-_=]?\s*(?:تحويل|حوالة|bank|transfer)', clean_base, re.IGNORECASE)
        found['transfer'] = float(m.group(1)) if m else None

    if re.search(r'(تابي|tabby)', clean_base, re.IGNORECASE):
        m = re.search(r'(?:تابي|tabby)\s*[\-_=]?\s*(\d+(?:\.\d+)?)', clean_base, re.IGNORECASE)
        if not m:
            m = re.search(r'(\d+(?:\.\d+)?)\s*[\-_=]?\s*(?:تابي|tabby)', clean_base, re.IGNORECASE)
        found['tabby'] = float(m.group(1)) if m else None

    known_sum = sum(v for v in found.values() if v is not None)
    unspecified = [k for k, v in found.items() if v is None]

    if unspecified:
        rem = max(0.0, net_total - known_sum)
        each = round(rem / len(unspecified), 2)
        for k in unspecified:
            found[k] = each
    elif not found:
        found['network'] = net_total
    elif len(found) == 1:
        k = list(found.keys())[0]
        found[k] = net_total
    elif known_sum != net_total and known_sum > 0:
        diff = round(net_total - known_sum, 2)
        k0 = list(found.keys())[0]
        found[k0] = round(found[k0] + diff, 2)

    val_cash = found.get('cash')
    val_net = found.get('network')
    val_transfer = 0.0
    if found.get('transfer'): val_transfer += found['transfer']
    if found.get('tabby'): val_transfer += found['tabby']

    # 5. استخراج الفنيين وبنود القطع والأجور
    w_m, w_e = parse_worker_names(worker_name)
    auto_parts, parts_val_before_vat, p_mech, p_elec = extract_invoice_line_details(combined_raw_text)

    if found.get('tabby'):
        if not auto_parts:
            auto_parts = "TABBY ="
        elif "TABBY" not in auto_parts:
            auto_parts += ", TABBY ="

    max_labor_allowed = max(0.0, (net_total / 1.15) - parts_val_before_vat) if net_total > 0 else 0.0

    mech_amt = ""
    elec_amt = ""
    if p_mech > 0 or p_elec > 0:
        if p_mech > 0:
            p_mech_capped = min(p_mech, max_labor_allowed)
            mech_amt = int(p_mech_capped) if p_mech_capped.is_integer() else round(p_mech_capped, 2)
        if p_elec > 0:
            p_elec_capped = min(p_elec, max_labor_allowed)
            elec_amt = int(p_elec_capped) if p_elec_capped.is_integer() else round(p_elec_capped, 2)
    else:
        labor_val = round(max_labor_allowed, 2) if net_total > 0 else ""
        if isinstance(labor_val, float) and labor_val > 0 and labor_val.is_integer():
            labor_val = int(labor_val)

        if w_e and not w_m:
            elec_amt = labor_val
        elif w_m and not w_e:
            mech_amt = labor_val
        elif "كهرباء" in combined_raw_text or "كهربا" in combined_raw_text:
            elec_amt = labor_val
            if not w_e: w_e = "عامر"
        else:
            mech_amt = labor_val

    if not (p_mech > 0 and p_elec > 0):
        if w_e and not w_m:
            if elec_amt == "" and mech_amt != "":
                elec_amt = mech_amt
            mech_amt = ""
        elif w_m and not w_e:
            if mech_amt == "" and elec_amt != "":
                mech_amt = elec_amt
            elec_amt = ""

    return {
        'num': inv_num,
        'name': full_display_name,
        'car_type': car_type,
        'total': net_total,
        'cash': val_cash,
        'network': val_net,
        'transfer': val_transfer if val_transfer > 0 else None,
        'parts': auto_parts,
        'worker_m': w_m,
        'worker_e': w_e,
        'mech_labor': mech_amt,
        'elect_labor': elec_amt,
    }

def run_sync():
    if not os.path.exists(EXCEL_PATH):
        print(f"Error: Excel file not found at: {EXCEL_PATH}")
        return

    wb = openpyxl.load_workbook(EXCEL_PATH)
    sheet = wb.active

    # العثور على أول سطر فارغ في عمود اسم العميل (العمود 11)
    row_idx = 2
    while sheet.cell(row=row_idx, column=11).value:
        row_idx += 1

    # تحديد مجلد الأرشفة لليوم الحالي ديناميكياً
    now = datetime.now()
    month_name = f"Month_{now.month}"
    day_str = now.strftime("%d")
    day_folder = os.path.join(BASE_DESKTOP, month_name, "Daily-income", day_str)
    if not os.path.exists(os.path.join(BASE_DESKTOP, month_name)):
        # احتياطي لمجلد الشهر الحالي
        day_folder = os.path.join(BASE_DESKTOP, "Month_10", "Daily-income", day_str)

    os.makedirs(day_folder, exist_ok=True)

    if os.path.exists(SOURCE_DIR):
        files = [f for f in os.listdir(SOURCE_DIR) if f.lower().endswith('.pdf')]
        print(f"Found {len(files)} invoice(s) to process.")

        for f in files:
            pdf_path = os.path.join(SOURCE_DIR, f)
            print(f"\nAnalyzing invoice: {f}...")
            try:
                info = extract_invoice_data(pdf_path)

                # استبعاد ملفات التسعيرات وعدم تسجيلها في شيت الدخل اليومي
                if info.get('is_quotation'):
                    print(f"[تخطي] تم استبعاد ملف تسعيرة (QUTATION): {f} - النظام يقبل الفواتير الضريبية فقط.")
                    quote_dir = os.path.join(BASE_DESKTOP, "تسعيرات_مستبعدة")
                    os.makedirs(quote_dir, exist_ok=True)
                    shutil.move(pdf_path, os.path.join(quote_dir, f))
                    continue

                # كتابة البيانات بدقة في الإكسل حسب الأعمدة
                sheet.cell(row=row_idx, column=1).value = f"=+D{row_idx}+C{row_idx}+B{row_idx}" if not info.get('total') else info['total']
                if info.get('cash'): sheet.cell(row=row_idx, column=2).value = info['cash']
                if info.get('transfer'): sheet.cell(row=row_idx, column=3).value = info['transfer']
                if info.get('network'): sheet.cell(row=row_idx, column=4).value = info['network']
                if info.get('parts'): sheet.cell(row=row_idx, column=5).value = info['parts']
                if info.get('worker_e'): sheet.cell(row=row_idx, column=6).value = info['worker_e']
                if info.get('worker_m'): sheet.cell(row=row_idx, column=7).value = info['worker_m']
                if info.get('elect_labor') != "": sheet.cell(row=row_idx, column=8).value = info['elect_labor']
                if info.get('mech_labor') != "": sheet.cell(row=row_idx, column=9).value = info['mech_labor']
                if info.get('car_type'): sheet.cell(row=row_idx, column=10).value = info['car_type']
                sheet.cell(row=row_idx, column=11).value = info['name']
                sheet.cell(row=row_idx, column=12).value = row_idx - 1

                print(f"Result: {info['name']} | Car: {info['car_type']} | Total: {info['total']} | Mech: {info['mech_labor']} | Elec: {info['elect_labor']}")
                row_idx += 1

                # نقل الفاتورة المعالجة إلى مجلد الأرشفة اليومي
                dest_file = os.path.join(day_folder, f)
                shutil.move(pdf_path, dest_file)
                print(f"Archived to: {dest_file}")

            except Exception as e:
                print(f"Error processing {f}: {e}")

    try:
        wb.save(EXCEL_PATH)
        print("\n--- COMPLETED SUCCESSFULLY: Excel updated and saved ---")
    except PermissionError:
        fallback_path = os.path.join(BASE_DESKTOP, "day_updated.xlsx")
        wb.save(fallback_path)
        print(f"\n[WARNING] Excel was locked. Saved copy to: {fallback_path}")

if __name__ == "__main__":
    run_sync()
