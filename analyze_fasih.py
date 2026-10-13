from bs4 import BeautifulSoup

with open('recon_fasih.html', 'r', encoding='utf-8', errors='ignore') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("=== BODY CHILDREN ===")
for ch in soup.body.find_all(recursive=False):
    print(f"Child: {ch.name} | id={ch.get('id')} | class={ch.get('class')}")

print("\n=== ALL TEXTS IN THE ENTIRE PAGE ===")
texts = [t.strip() for t in soup.find_all(string=True) if len(t.strip()) > 3]
# Filter out script/style
filtered_texts = []
for t in soup.body.find_all(string=True):
    parent = t.parent.name
    if parent not in ['script', 'style', 'noscript']:
        st = t.strip()
        if len(st) > 1:
            filtered_texts.append(st)

print("Total visible text items:", len(filtered_texts))
for t in filtered_texts[:50]:
    print(" ->", t)
