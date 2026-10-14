from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    try:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        page = browser.contexts[0].pages[0]
        print('Page URL:', page.url)
        
        # Cari tombol di toolbar kanan bawah
        # Cari semua button yang memiliki svg dan terletak di sisi kanan bawah
        buttons = page.locator('button').all()
        print(f"Total buttons on page: {len(buttons)}")
        
        for idx, b in enumerate(buttons):
            html = b.evaluate("el => el.outerHTML")
            box = b.bounding_box()
            # Jika terletak di sisi kanan layar (x > 1000) dan y > 400
            if box and box['x'] > 800 and box['y'] > 400:
                print(f"Pill candidate [{idx}]: at ({box['x']:.0f}, {box['y']:.0f}) | text='{b.inner_text().strip()}' | html={html[:200]}")
                
        browser.close()
    except Exception as e:
        print("Error:", e)
