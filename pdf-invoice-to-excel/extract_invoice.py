# -*- coding: utf-8 -*-
import sys
from batch_process_invoices import extract_invoice

if __name__ == '__main__':
    test_path = sys.argv[1] if len(sys.argv) > 1 else 'Day_test.pdf'
    result = extract_invoice(test_path)
    print('\nالنتيجة النهائية:')
    print(result)
