"""
تطبيق تسويات نقاط البيع - واجهة Streamlit المحسنة
"""

import sys
from pathlib import Path
from datetime import datetime, date
import pandas as pd
import streamlit as st

# ضمان التعرف على الوحدات المجاورة سواء تم التشغيل من المجلد الحالي أو الرئيسي
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from parser import read_bank
from exporter import daily_table, excel_report

# إعداد الصفحة
st.set_page_config(
    page_title='تسويات نقاط البيع',
    layout='wide',
    initial_sidebar_state='collapsed'
)

st.title('تقرير إيداعات وخصومات تسويات نقاط البيع')
st.caption('XZ = إيداع، FZ = خصم رسوم | التصفية حسب تاريخ التسوية، مع حفظ تاريخ النزول البنكي')


@st.cache_data(show_spinner=False)
def load_bank_statement(file_bytes):
    """
    قراءة ومعالجة كشف البنك مع التخزين المؤقت لتجنب إعادة التحليل عند تغيير الفلاتر.
    """
    return read_bank(file_bytes)


@st.cache_data(show_spinner=False)
def generate_excel_cached(selected_df, daily_df, bank_daily_df, start_date, end_date, unknown_count):
    """
    توليد ملف Excel مع التخزين المؤقت لتفادي إعادة بناء المصنف الثقيل في كل تفاعل.
    """
    return excel_report(selected_df, daily_df, bank_daily_df, start_date, end_date, unknown_count)


# رفع الملف
uploaded = st.file_uploader('ارفع كشف البنك Excel', type=['xlsx'])

if uploaded is not None:
    try:
        with st.spinner('جاري قراءة وتدقيق حركات كشف البنك...'):
            all_df = load_bank_statement(uploaded.getvalue())

        known = all_df['تاريخ التسوية'].dropna()
        if known.empty:
            st.error('لا توجد تواريخ تسوية صالحة في الكشف؛ راجع وصف وتفاصيل الحركات.')
            st.stop()

        first_date, last_date = known.min(), known.max()

        with st.container(border=True):
            st.subheader('فلتر فترة التسوية')
            mode = st.segmented_control(
                'عرض التقرير',
                options=['جميع الأيام', 'فترة مخصصة'],
                default='جميع الأيام',
                selection_mode='single'
            ) or 'جميع الأيام'

            start, end = first_date, last_date
            if mode == 'فترة مخصصة':
                left, right = st.columns(2)
                with left:
                    start = st.date_input('من تاريخ', value=first_date, min_value=first_date, max_value=last_date)
                with right:
                    end = st.date_input('إلى تاريخ', value=last_date, min_value=first_date, max_value=last_date)

        if start > end:
            st.error('تاريخ البداية أكبر من تاريخ النهاية.')
            st.stop()

        # تصفية الحركات ضمن نطاق التسوية المحدد
        is_in_range = all_df['تاريخ التسوية'].apply(lambda d: d is not None and start <= d <= end)
        selected = all_df[is_in_range].copy()
        unknown = int(all_df['تاريخ التسوية'].isna().sum())

        # حساب جداول التسويات
        daily = daily_table(selected, 'تاريخ التسوية', start, end)
        bank_daily = daily_table(selected, 'تاريخ نزول البنك')

        # توليد تقرير الإكسل المخزن مؤقتاً
        result, deposits, fees = generate_excel_cached(
            selected,
            daily,
            bank_daily,
            start,
            end,
            unknown
        )

        st.caption(f'من {start:%Y-%m-%d} إلى {end:%Y-%m-%d} — حسب تاريخ التسوية')

        # بطاقات المؤشرات المالية والتدقيق
        with st.container(border=True):
            a, b, c, d = st.columns(4)
            a.metric('إجمالي الإيداعات', f'{deposits:,.2f} ر.س')
            b.metric('إجمالي الخصومات', f'{fees:,.2f} ر.س')
            c.metric('الصافي للمقارنة', f'{(deposits - fees):,.2f} ر.س')
            review_count = int(selected['ملاحظات'].ne('').sum()) + unknown
            d.metric('حركات تحتاج مراجعة', review_count)

        if unknown > 0:
            st.warning(f'هناك {unknown} حركة بلا تاريخ تسوية؛ لم تدخل في إجمالي الفترة المحددة. راجع أصل الكشف.')

        # جدول التسويات اليومية
        st.subheader('التسويات اليومية (تشمل الأيام بدون حركات)')
        st.dataframe(
            daily,
            width='stretch',
            hide_index=True,
            column_config={
                'تاريخ التسوية': st.column_config.DateColumn('تاريخ التسوية', format='YYYY-MM-DD'),
                'إجمالي الإيداعات': st.column_config.NumberColumn('إجمالي الإيداعات', format='%.2f'),
                'إجمالي الخصومات': st.column_config.NumberColumn('إجمالي الخصومات', format='%.2f'),
                'صافي الإيداعات بعد الرسوم (للمقارنة)': st.column_config.NumberColumn('صافي الإيداعات بعد الرسوم (للمقارنة)', format='%.2f')
            }
        )

        # جدول تفاصيل الحركات
        st.subheader('تفاصيل الحركات')
        st.dataframe(
            selected,
            width='stretch',
            hide_index=True,
            column_config={
                'المبلغ': st.column_config.NumberColumn('المبلغ', format='%.2f'),
                'مدين': st.column_config.NumberColumn('مدين', format='%.2f'),
                'دائن': st.column_config.NumberColumn('دائن', format='%.2f')
            }
        )

        # زر التنزيل
        st.download_button(
            label='تنزيل تقرير Excel',
            data=result,
            file_name=f'تقرير_التسويات_{start:%Y%m%d}_{end:%Y%m%d}.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            type='primary'
        )

    except Exception as exc:
        st.error(f'تعذر معالجة الكشف: {exc}')
