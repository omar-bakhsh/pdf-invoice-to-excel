"""
وحدة قراءة ومعالجة كشوفات البنك لتسويات نقاط البيع
"""

import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
import pandas as pd

from constants import (
    FIELDS,
    CODE_DEPOSIT,
    CODE_FEE,
    TRANSACTION_TYPES,
    AUDIT_STATUS_VALID,
    AUDIT_STATUS_EXCLUDED,
    EXPECTED_HEADERS,
    DUPLICATE_KEYS
)


def money(value):
    """
    تحويل القيمة إلى Decimal بشكل آمن مع معالجة التنسيقات المالية المختلفة.
    يدعم الأرقام بالأقواس السالبة، فواصل الآلاف، ورموز العملة.
    """
    if pd.isna(value):
        return Decimal('0')
    
    val_str = str(value).strip()
    if val_str in ('', '-', 'None', 'nan'):
        return Decimal('0')

    # تنظيف الفواصل والمسافات والرموز الشائعة
    val_str = val_str.replace(',', '').replace('،', '')
    val_str = val_str.replace('ر.س', '').replace('SAR', '').replace('sar', '')
    val_str = val_str.replace('\u00a0', ' ').strip()

    # معالجة الأرقام السالبة بين قوسين مثل (123.45)
    if val_str.startswith('(') and val_str.endswith(')'):
        val_str = '-' + val_str[1:-1].strip()

    try:
        return Decimal(val_str)
    except (InvalidOperation, ValueError):
        return None


def settlement(description):
    """
    استخراج رمز الشبكة وتاريخ التسوية من وصف أو تفاصيل الحركة.
    يبحث عن حرفين إنجليزيين متبوعين بـ 6 أرقام (YYMMDD) مع دعم الفواصل المحتملة.
    """
    if not description:
        return '', None
        
    text = str(description).upper()
    # دعم صيغة الرمز والتاريخ: MD241025 أو MD-241025 أو MD/241025
    m = re.search(r'\b([A-Z]{2})[-/\s]?(\d{6})\b', text)
    if not m:
        return '', None

    network = m.group(1)
    date_str = m.group(2)
    try:
        settled_date = datetime.strptime(date_str, '%y%m%d').date()
        return network, settled_date
    except ValueError:
        return network, None


def extract_reference_and_recon(text):
    """
    استخراج رقم التسوية (RECON NO) والمرجع (REFERENCE) بمرونة مع اختلاف المسافات والفواصل.
    """
    recon_match = re.search(r'RECON(?:\s*NO\.?|\s*#)?\s*[:#-]?\s*(\d+)', text, re.IGNORECASE)
    recon_no = recon_match.group(1) if recon_match else ''

    ref_match = re.search(r'REF(?:ERENCE)?(?:\s*NO\.?|\s*#)?\s*[:#-]?\s*(\d+)', text, re.IGNORECASE)
    ref_no = ref_match.group(1) if ref_match else ''

    return recon_no, ref_no


def _find_header_and_columns(raw):
    """
    البحث عن صف العناوين في كشف البنك وتحديد مواقع الأعمدة بديناميكية مع دعم التراجع التلقائي.
    """
    header_idx = None
    for i, row in raw.iterrows():
        vals = [str(x).strip() for x in row.tolist()]
        # الشرط القياسي للعثور على صف العناوين
        has_proc_date = any(k in vals for k in EXPECTED_HEADERS['date'])
        has_debit = any(k in vals for k in EXPECTED_HEADERS['debit'])
        has_credit = any(k in vals for k in EXPECTED_HEADERS['credit'])
        
        if (has_proc_date and has_debit and has_credit) or ('[SA]Processing Date' in vals and 'مدين' in vals and 'دائن' in vals):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError('لم أجد صف عناوين كشف البنك (تاريخ التنفيذ، مدين، دائن).')

    header_names = [str(x).strip() for x in raw.iloc[header_idx].tolist()]

    # دالة مساعدة لتحديد رقم العمود بالاسم مع خيار افتراضي
    def get_col_index(aliases, default_fallback):
        for alias in aliases:
            if alias in header_names:
                return header_names.index(alias)
        return default_fallback

    debit_col = get_col_index(EXPECTED_HEADERS['debit'], 4 if len(header_names) > 4 else None)
    credit_col = get_col_index(EXPECTED_HEADERS['credit'], 5 if len(header_names) > 5 else None)

    if debit_col is None or credit_col is None:
        raise ValueError('تعذر تحديد عمودي (مدين / دائن) في كشف البنك.')

    date_col = get_col_index(EXPECTED_HEADERS['date'], 0)
    detail_col = get_col_index(EXPECTED_HEADERS['detail'], 1)
    desc_col = get_col_index(EXPECTED_HEADERS['desc'], 2)
    code_col = get_col_index(EXPECTED_HEADERS['code'], 3)

    return header_idx, {
        'date': date_col,
        'detail': detail_col,
        'desc': desc_col,
        'code': code_col,
        'debit': debit_col,
        'credit': credit_col
    }


def parse_bank_date(val):
    """
    تحليل تاريخ البنك بدقة: يكتشف تلقائياً ما إذا كان التنسيق يبدأ بالسنة (ISO)
    أو يبدأ باليوم (DD/MM/YYYY) لتجنب قلب الأيام والأشهر.
    """
    if pd.isna(val):
        return pd.NaT
    if isinstance(val, (datetime, pd.Timestamp)):
        return pd.Timestamp(val)
    val_str = str(val).strip()
    if not val_str:
        return pd.NaT
    # إذا كانت السنة 4 أرقام في البداية (مثل 2024-10-02 أو 2024/10/02)
    if re.match(r'^\d{4}[-/]', val_str):
        return pd.to_datetime(val_str, errors='coerce')
    # إذا كان التاريخ يبدأ باليوم (مثل 02/10/2024 أو 02-10-2024)
    return pd.to_datetime(val_str, errors='coerce', dayfirst=True)


def read_bank(data):
    """
    قراءة كشف البنك من بايتات ملف Excel واستخراج الحركات الخاصة بنقاط البيع مع التحقق والتدقيق.
    """
    raw = pd.read_excel(io.BytesIO(data), header=None)
    header_idx, col_map = _find_header_and_columns(raw)

    records = []
    for i in range(header_idx + 1, len(raw)):
        row = raw.iloc[i]

        # قراءة تاريخ البنك بدقة
        raw_bank_date = row.iloc[col_map['date']]
        bank_ts = parse_bank_date(raw_bank_date)
        if pd.isna(bank_ts):
            continue

        # قراءة رمز الحركة
        code_val = row.iloc[col_map['code']]
        code = str(code_val).strip().upper() if pd.notna(code_val) else ''
        if code not in (CODE_DEPOSIT, CODE_FEE):
            continue

        desc = str(row.iloc[col_map['desc']]) if pd.notna(row.iloc[col_map['desc']]) else ''
        detail = str(row.iloc[col_map['detail']]) if pd.notna(row.iloc[col_map['detail']]) else ''
        combined_text = f'{desc} {detail}'

        debit = money(row.iloc[col_map['debit']])
        credit = money(row.iloc[col_map['credit']])

        network, settled = settlement(combined_text)
        recon_no, ref_no = extract_reference_and_recon(combined_text)

        notes = []
        if debit is None or credit is None:
            notes.append('مبلغ غير قابل للقراءة')
            
        debit_val = debit if debit is not None else Decimal('0')
        credit_val = credit if credit is not None else Decimal('0')

        direction_ok = (
            (code == CODE_DEPOSIT and credit_val > 0 and debit_val == 0) or
            (code == CODE_FEE and debit_val > 0 and credit_val == 0)
        )
        if not direction_ok:
            notes.append('اتجاه المبلغ غير صحيح أو المبلغ صفر')

        if settled is None:
            notes.append('تعذر استخراج تاريخ التسوية')

        bank_date = bank_ts.date()
        lag = (bank_date - settled).days if settled else None
        if lag is not None and lag != 1:
            notes.append(f'فارق النزول {lag} يوم (قد يكون عطلة)')

        if not recon_no:
            notes.append('رقم التسوية غير موجود')
        if not ref_no:
            notes.append('المرجع غير موجود')

        amount = float(credit_val if code == CODE_DEPOSIT else debit_val)
        audit_status = AUDIT_STATUS_VALID if direction_ok and settled else AUDIT_STATUS_EXCLUDED

        records.append({
            'صف المصدر': i + 1,
            'تاريخ نزول البنك': bank_date,
            'تاريخ التسوية': settled,
            'أيام التأخير': lag,
            'النوع': TRANSACTION_TYPES.get(code, code),
            'رمز البنك': code,
            'رمز الشبكة': network,
            'رقم التسوية': recon_no,
            'المرجع': ref_no,
            'المبلغ': amount,
            'مدين': float(debit_val),
            'دائن': float(credit_val),
            'التفاصيل': detail,
            'الوصف': desc,
            'حالة التدقيق': audit_status,
            'ملاحظات': '؛ '.join(notes)
        })

    df = pd.DataFrame(records, columns=FIELDS)
    if df.empty:
        raise ValueError('لا توجد حركات XZ أو FZ في كشف البنك.')

    # كشف التكرارات المحتملة
    duplicated = df.duplicated(subset=DUPLICATE_KEYS, keep=False)
    for idx in df.index[duplicated]:
        existing_note = df.at[idx, 'ملاحظات']
        df.at[idx, 'ملاحظات'] = (existing_note + '؛ ' if existing_note else '') + 'تكرار محتمل: راجع المرجع والتسوية'

    return df
