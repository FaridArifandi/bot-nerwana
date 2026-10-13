from bs4 import BeautifulSoup

with open('recon_fasih.html', 'r', encoding='utf-8', errors='ignore') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("=== SEARCHING FLOATING BUTTONS / REVOKE / EDIT ===")
for btn in soup.find_all(['button', 'a']):
    title = btn.get('title', '')
    aria = btn.get('aria-label', '')
    txt = btn.get_text(strip=True)
    all_text = f"{title} {aria} {txt}".lower()
    if any(k in all_text for k in ['revoke', 'tarik', 'edit', 'kembali', 'refresh', 'info']):
        print(f"Tag: {btn.name} | title='{title}' | aria='{aria}' | text='{txt}' | class={btn.get('class')}")
