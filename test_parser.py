import json
import base64
from bs4 import BeautifulSoup

with open('recon_nerwana.html', 'r', encoding='utf-8', errors='ignore') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

calc_btns = soup.find_all(lambda tag: tag.has_attr('data-aid'))
print(f"Total rows in recon_nerwana.html: {len(calc_btns)}")

records = []
for btn in calc_btns:
    # Find table row
    tr = btn.find_parent('tr')
    
    # Dropdown tindak lanjut in this row
    tl_select = tr.find('select', class_=lambda c: c and 'dc-tl-select' in c) if tr else None
    tindak_lanjut = tl_select.find('option', selected=True).get('value', '') if tl_select and tl_select.find('option', selected=True) else (tl_select.get('data-prev', '') if tl_select else '')
    data_kunci = tl_select.get('data-kunci', '') if tl_select else ''
    
    # Info pengisi
    tl_box = tr.find('div', class_='dc-tl-box') if tr else None
    tl_oleh = ""
    if tl_box:
        oleh_div = tl_box.find('div', class_='dc-tl-oleh')
        if oleh_div:
            tl_oleh = oleh_div.get_text(' ', strip=True)

    row = {
        'assignment_id': btn.get('data-aid', '').strip(),
        'nama_usaha': btn.get('data-nama', '').strip(),
        'meta': btn.get('data-meta', '').strip(),
        'link_fasih': btn.get('data-link', '').strip(),
        'pbj': float(btn.get('data-pbj', 0) or 0),
        'prod': float(btn.get('data-prod', 0) or 0),
        'ops': float(btn.get('data-ops', 0) or 0),
        'beli': float(btn.get('data-beli', 0) or 0),
        'nonops': float(btn.get('data-nonops', 0) or 0),
        'lain': float(btn.get('data-lain', 0) or 0),
        'output': float(btn.get('data-output', 0) or 0),
        'ntb': float(btn.get('data-ntb', 0) or 0),
        'rasio': float(btn.get('data-rasio', 0) or 0),
        'tindak_lanjut': tindak_lanjut,
        'tindak_lanjut_oleh': tl_oleh,
        'data_kunci': data_kunci
    }
    records.append(row)

print("Parsed successfully:", len(records))
print("Sample row 1:", json.dumps(records[0], indent=2))
print("Sample row 2:", json.dumps(records[1], indent=2))
