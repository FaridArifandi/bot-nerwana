"""
dump_fasih_html.py
Skrip pembantu untuk mengambil dump HTML dari halaman aktif di Chrome (port 9222).
Digunakan untuk merekam struktur DOM FASIH:
- Blok II usaha biasa
- Blok II usaha beroperasi 2026
- Dialog Catatan dalam keadaan terbuka

Cara pakai:
1. Buka Chrome dengan port 9222 (atau jalankan eksekutor sampai halaman Blok II terbuka)
2. Buka halaman / dialog yang ingin di-dump di Chrome
3. Jalankan di terminal:
   python dump_fasih_html.py [nama_file.html]
"""

import sys
import os
from playwright.sync_api import sync_playwright

def dump_page(filename="fasih_dump.html"):
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception as e:
            print(f"[ERROR] Gagal terhubung ke Chrome port 9222: {e}")
            print("Pastikan Chrome debug aktif di port 9222.")
            return False

        contexts = browser.contexts
        if not contexts:
            print("[ERROR] Tidak ada browser context aktif.")
            return False

        pages = contexts[0].pages
        if not pages:
            print("[ERROR] Tidak ada tab aktif.")
            return False

        # Cari tab FASIH
        fasih_page = None
        for pg in pages:
            if "fasih" in pg.url.lower():
                fasih_page = pg
                break
        if not fasih_page:
            print("[PERINGATAN] Tidak ditemukan tab yang beralamat 'fasih'!")
            print("Daftar tab yang sedang terbuka:")
            for i, pg in enumerate(pages):
                print(f"  [{i+1}] {pg.url}")
            print("Dump tetap diambil dari tab aktif saat ini...")
            fasih_page = pages[-1]

        url = fasih_page.url
        print(f"[INFO] Mengambil dump dari tab: {url}")
        content = fasih_page.content()

        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"[SUKSES] Dump HTML ({len(content):,} bytes) tersimpan di:\n  {out_path}")
        return True

if __name__ == "__main__":
    out_name = sys.argv[1] if len(sys.argv) > 1 else "fasih_dump.html"
    dump_page(out_name)
