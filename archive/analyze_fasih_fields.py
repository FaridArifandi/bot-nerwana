import re
from bs4 import BeautifulSoup

with open('recon_fasih.html', 'r', encoding='utf-8', errors='ignore') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("=== QUESTION 13 (KBLI & KATEGORI) ===")
for el in soup.find_all(string=re.compile(r'13\b|kbli|kategori', re.I)):
    p = el.parent
    text = p.get_text(" ", strip=True)
    if any(k in text.lower() for k in ['kode kbli', 'kategori lapangan usaha', '13g', '13h', '13.g', '13.h']):
        print(f"[{p.name}] {text[:150]}")
        # Find inputs nearby
        container = p
        for _ in range(5):
            if container:
                inps = container.find_all(['input', 'select', 'textarea'])
                if inps:
                    for inp in inps:
                        print(f"   -> Input: tag={inp.name} id={inp.get('id')} name={inp.get('name')} val={inp.get('value')}")
                    break
                container = container.parent

print("\n=== QUESTION 26 (PENGELUARAN / BIAYA) ===")
for el in soup.find_all(string=re.compile(r'26\.\s*[a-z]|biaya produksi|biaya operasional', re.I)):
    p = el.parent
    text = p.get_text(" ", strip=True)
    if any(k in text.lower() for k in ['biaya produksi', 'biaya operasional', 'biaya non-operasional', 'biaya pembelian', 'total pengeluaran']):
        print(f"\n[{p.name}] {text[:120]}")
        container = p
        for _ in range(6):
            if container:
                inps = container.find_all(['input', 'textarea'])
                if inps:
                    for inp in inps:
                        print(f"   -> Input: id={inp.get('id')} name={inp.get('name')} val={inp.get('value')} class={inp.get('class')}")
                    # Look for comment button in container
                    c_btns = container.find_all('button', title=re.compile('catatan', re.I))
                    for cb in c_btns:
                        print(f"   -> Comment Button: title={cb.get('title')} aria={cb.get('aria-label')} class={cb.get('class')}")
                    break
                container = container.parent

print("\n=== QUESTION 27 (PENDAPATAN) ===")
for el in soup.find_all(string=re.compile(r'27\.\s*[a-z]|nilai produksi|pendapatan lainnya', re.I)):
    p = el.parent
    text = p.get_text(" ", strip=True)
    if any(k in text.lower() for k in ['barang dan jasa', 'pendapatan lainnya', 'total pendapatan']):
        print(f"\n[{p.name}] {text[:120]}")
        container = p
        for _ in range(6):
            if container:
                inps = container.find_all(['input', 'textarea'])
                if inps:
                    for inp in inps:
                        print(f"   -> Input: id={inp.get('id')} name={inp.get('name')} val={inp.get('value')} class={inp.get('class')}")
                    c_btns = container.find_all('button', title=re.compile('catatan', re.I))
                    for cb in c_btns:
                        print(f"   -> Comment Button: title={cb.get('title')} aria={cb.get('aria-label')} class={cb.get('class')}")
                    break
                container = container.parent
