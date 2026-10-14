import re
from bs4 import BeautifulSoup

with open('recon_nerwana.html', 'r', encoding='utf-8', errors='ignore') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')

print("=== CALCULATOR BUTTONS (DATA-* ATTRIBUTES) ===")
calc_btns = soup.find_all(lambda tag: tag.has_attr('data-aid'))
print(f"Total buttons with data-aid: {len(calc_btns)}")
if calc_btns:
    first = calc_btns[0]
    print(f"Sample Button Tag: {first.name}")
    for k, v in first.attrs.items():
        print(f"  {k}: {v}")

print("\n=== FASIH EXTERNAL LINK BUTTON ===")
fasih_links = soup.find_all('a', href=re.compile(r'fasih', re.I))
print(f"Total FASIH links: {len(fasih_links)}")
if fasih_links:
    first_link = fasih_links[0]
    print(f"Sample Link: href={first_link.get('href')}, class={first_link.get('class')}")
    print(f"Parent TD: {first_link.parent.prettify()[:400]}")

print("\n=== DROPDOWN TINDAK LANJUT ===")
selects = soup.find_all('select')
print(f"Total selects: {len(selects)}")
for sel in selects:
    name = sel.get('name')
    classes = sel.get('class')
    opts = [o.get_text(strip=True) for o in sel.find_all('option')]
    if any('direvisi' in o.lower() for o in opts):
        print(f"Dropdown found: id={sel.get('id')} name={name} class={classes}")
        print(f"  Parent: {sel.parent.prettify()[:500]}")
        print(f"  Options: {opts}")
        print(f"  Onchange / Attrs: {sel.attrs}")

print("\n=== JAVASCRIPT HANDLING DROPDOWN ===")
scripts = soup.find_all('script')
for sc in scripts:
    text = sc.string or sc.get_text()
    if text and ('tindak' in text.lower() or 'revisi' in text.lower() or 'csrf' in text.lower()):
        # Print relevant JS snippets
        for line in text.splitlines():
            if any(k in line.lower() for k in ['tindak', 'revisi', 'status', 'url:', 'post', 'ajax', 'fetch']):
                print("JS line:", line.strip()[:150])
