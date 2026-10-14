import re
from bs4 import BeautifulSoup

with open('recon_nerwana.html', 'r', encoding='utf-8', errors='ignore') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("=== SELECTS IN NERWANA ===")
for s in soup.find_all('select'):
    classes = s.get('class', [])
    name = s.get('name', '')
    s_id = s.get('id', '')
    opts = [(o.get('value', ''), o.get_text(strip=True)) for o in s.find_all('option')]
    if 'dc-tl-select' not in classes:
        print(f"Select: id='{s_id}' name='{name}' class={classes}")
        for val, txt in opts[:15]:
            print(f"   val='{val}' -> '{txt}'")

print("\n=== PAGINATION IN NERWANA ===")
pagination = soup.find(class_=re.compile(r'pagination', re.I))
if pagination:
    print(pagination.prettify()[:1000])
else:
    print("Pagination container search:")
    for a in soup.find_all('a', href=re.compile(r'page=', re.I)):
        print(f"  Page link: href={a.get('href')} text={a.get_text(strip=True)}")
