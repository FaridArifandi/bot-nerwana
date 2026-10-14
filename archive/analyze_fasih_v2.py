import re
from bs4 import BeautifulSoup

with open('recon_fasih.html', 'r', encoding='utf-8', errors='ignore') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("=== SEARCHING QUESTIONS / LABELS IN FASIH ===")
# Look for questions like 13g, 13h, 30, 31, 26, 27
found_questions = []
for el in soup.find_all(text=True):
    t = el.strip()
    if re.search(r'^(13[a-z]|30[a-z]|31[a-z]|26[a-z]|27[a-z])\b', t, re.I):
        if t not in found_questions and len(t) < 150:
            found_questions.append(t)

print("Found numbered questions:")
for q in found_questions:
    print(" ", q)

print("\n=== SEARCHING KEYWORDS IN TEXTS ===")
keywords = ['kbli', 'biaya produksi', 'biaya operasional', 'non-operasional', 'nilai produksi', 'pendapatan', 'pembelian']
for kw in keywords:
    matches = soup.find_all(text=re.compile(kw, re.I))
    print(f"Keyword '{kw}': {len(matches)} matches")
    for m in matches[:3]:
        p = m.parent
        print(f"   [{p.name}] {m.strip()[:100]}")

print("\n=== SEARCHING INPUT FIELDS AND THEIR ASSOCIATED LABELS/NAMES ===")
inputs = soup.find_all(['input', 'textarea', 'select'])
print(f"Total inputs: {len(inputs)}")
for inp in inputs:
    name = inp.get('name')
    inp_id = inp.get('id')
    placeholder = inp.get('placeholder')
    val = inp.get('value')
    # find closest label or parent container text
    parent = inp.parent
    context = ""
    for _ in range(4):
        if parent:
            context = parent.get_text(" ", strip=True)
            if len(context) > 20:
                break
            parent = parent.parent
    if any(k in context.lower() for k in ['kbli', 'biaya', 'pendapatan', 'produksi', 'operasional', 'pembelian', '13', '30', '31', '26', '27']):
        print(f"\n[INPUT] tag={inp.name} id={inp_id} name={name} val={val} type={inp.get('type')}")
        print(f"  Context: {context[:180]}")

print("\n=== SEARCHING COMMENT ICONS / BUTTONS ===")
# Look for comment icons (svg, button with comment / catatan)
comment_elements = []
for btn in soup.find_all(['button', 'a', 'span', 'svg']):
    text = btn.get_text(strip=True)
    aria = btn.get('aria-label', '')
    title = btn.get('title', '')
    classes = ' '.join(btn.get('class', [])) if btn.get('class') else ''
    if any(k in f"{text} {aria} {title} {classes}".lower() for k in ['comment', 'catatan', 'komentar']):
        print(f"Comment element: tag={btn.name} class={classes} title={title} aria={aria}")
