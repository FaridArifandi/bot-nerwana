from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    try:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        print(f"Total pages in context: {len(context.pages)}")
        for idx, page in enumerate(context.pages):
            print(f"\n--- Page [{idx}]: {page.url} ---")
            buttons = page.locator('button, a[role="button"]')
            count = buttons.count()
            print(f"Total buttons: {count}")
            for i in range(count):
                btn = buttons.nth(i)
                t = btn.get_attribute('title') or ''
                a = btn.get_attribute('aria-label') or ''
                txt = btn.inner_text().strip()
                cls = btn.get_attribute('class') or ''
                has_svg = btn.locator('svg').count() > 0
                if any(k in f"{t} {a} {txt} {cls}".lower() for k in ['revoke', 'tarik', 'edit', 'kembali', 'info', 'primary', 'orange', 'round']) or has_svg:
                    print(f"  btn[{i}]: text='{txt}' title='{t}' aria='{a}' class='{cls[:60]}' svg={has_svg}")
        browser.close()
    except Exception as e:
        print("Error:", e)
