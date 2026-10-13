import os
import sys
import time
import random
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from database import init_db, upsert_kasus, get_connection

USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_data")
BASE_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/dc-terkena-flag"

SPECIFIC_FILTERS = [
    ("ntb_negatif", "Nilai tambah negatif (< 0)"),
    ("ntb_nol", "Nilai tambah = 0"),
    ("ntb_250jt", "Nilai tambah di atas Rp 250 juta"),
    ("peng_250jt", "Pengeluaran (total) di atas Rp 250 juta"),
    ("pend_250jt", "Pendapatan total di atas Rp 250 juta"),
    ("pbj_lt_lain", "Pendapatan barang & jasa < Pendapatan lainnya"),
    ("pbj0_lain_pos", "Pendapatan barang & jasa = 0 dan lainnya > 0"),
    ("", "Semua (tanpa filter spesifik)")
]

def parse_and_save_page(html_content, filter_name=""):
    soup = BeautifulSoup(html_content, 'html.parser')
    calc_btns = soup.find_all(lambda tag: tag.has_attr('data-aid'))
    
    saved_count = 0
    for btn in calc_btns:
        tr = btn.find_parent('tr')
        
        # Dropdown status tindak lanjut di baris ini
        tl_select = tr.find('select', class_=lambda c: c and 'dc-tl-select' in c) if tr else None
        tindak_lanjut = ""
        data_kunci = ""
        if tl_select:
            selected_opt = tl_select.find('option', selected=True)
            tindak_lanjut = selected_opt.get('value', '') if selected_opt else tl_select.get('data-prev', '')
            data_kunci = tl_select.get('data-kunci', '')
        
        # Info nama pengisi tindak lanjut jika ada
        tl_box = tr.find('div', class_='dc-tl-box') if tr else None
        tl_oleh = ""
        if tl_box:
            oleh_div = tl_box.find('div', class_='dc-tl-oleh')
            if oleh_div:
                tl_oleh = oleh_div.get_text(' ', strip=True)

        meta_text = btn.get('data-meta', '').strip()
        # Parse KBLI & Deskripsi dari data-meta (contoh: "Kategori A · KBLI 01111 - Pertanian Jagung")
        kbli = ""
        deskripsi_kbli = ""
        m = re.search(r'KBLI\s*([0-9A-Z]+)\s*-\s*(.+)', meta_text, re.I)
        if m:
            kbli = m.group(1).strip()
            deskripsi_kbli = m.group(2).strip()
        else:
            kbli = meta_text

        row_data = {
            'assignment_id': btn.get('data-aid', '').strip(),
            'nama_usaha': btn.get('data-nama', '').strip(),
            'kabkota': '1175',
            'kategori': 'A',
            'kbli': kbli,
            'deskripsi_kbli': deskripsi_kbli,
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
            'filter_spesifik': filter_name or 'semua',
            'tindak_lanjut': tindak_lanjut,
            'tindak_lanjut_oleh': tl_oleh,
            'data_kunci': data_kunci
        }
        
        upsert_kasus(row_data)
        saved_count += 1
        
    return saved_count

def get_total_pages(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    page_links = soup.find_all('a', href=re.compile(r'[?&]page=(\d+)'))
    max_page = 1
    for a in page_links:
        m = re.search(r'[?&]page=(\d+)', a.get('href', ''))
        if m:
            p = int(m.group(1))
            if p > max_page:
                max_page = p
    return max_page

def scrape_filter(page, filter_code, filter_label, per_page=50):
    print(f"\n" + "=" * 60)
    print(f"Memproses Filter: [{filter_code or 'SEMUA'}] - {filter_label}")
    print("=" * 60)
    
    # Halaman 1
    url = f"{BASE_URL}?sort=nilai_tambah&dir=asc&kabkota=1175&kategori=A&flag=rasio_3&kode=1&filter_spesifik={filter_code}&cari=&per_page={per_page}&page=1"
    page.goto(url, timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(1)
    
    html = page.content()
    total_pages = get_total_pages(html)
    first_page_saved = parse_and_save_page(html, filter_code or "semua")
    print(f"-> Halaman 1/{total_pages}: Berhasil menyimpan {first_page_saved} baris.")
    
    if total_pages <= 1:
        return first_page_saved

    total_saved = first_page_saved
    for current_page in range(2, total_pages + 1):
        # Jeda santun antar halaman
        delay = random.uniform(1.0, 2.0)
        time.sleep(delay)
        
        next_url = f"{BASE_URL}?sort=nilai_tambah&dir=asc&kabkota=1175&kategori=A&flag=rasio_3&kode=1&filter_spesifik={filter_code}&cari=&per_page={per_page}&page={current_page}"
        print(f"-> Membuka Halaman {current_page}/{total_pages}...", end="\r")
        page.goto(next_url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        
        page_html = page.content()
        saved = parse_and_save_page(page_html, filter_code or "semua")
        total_saved += saved
        print(f"-> Halaman {current_page}/{total_pages}: +{saved} baris (Total filter ini: {total_saved})")

    return total_saved

def main():
    init_db()
    
    print("=" * 65)
    print("           FASE 1: SCRAPER NERWANA KE SQLITE")
    print("=" * 65)
    print("Menu Pilihan Scraping:")
    print("  [1] Scrape Semua Filter Spesifik Saja (NTB negatif, 0, >250jt, dll) [Cepat: ~238 baris]")
    print("  [2] Scrape Seluruh Data Lengkap (Semua 66 Halaman / 3.283 baris)   [Lengkap]")
    print("  [3] Scrape Keduanya Berurutan (Filter Spesifik + Seluruh Data)       [Rekomendasi]")
    print("=" * 65)
    
    choice = input("Pilih mode [1/2/3] (default 3): ").strip() or "3"
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            viewport={"width": 1366, "height": 768},
            args=["--start-maximized"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        # Buka Nerwana
        test_url = f"{BASE_URL}?sort=nilai_tambah&dir=asc&kabkota=1175&kategori=A&flag=rasio_3&kode=1&filter_spesifik=&cari=&per_page=50"
        print(f"\nMembuka halaman Nerwana...")
        page.goto(test_url)
        
        # Cek apakah butuh login SSO
        time.sleep(2)
        if "login" in page.url.lower():
            print("\n[PERHATIAN] Sesi SSO belum aktif atau kedaluwarsa.")
            print("Silakan login SSO BPS di jendela browser.")
            input("Tekan [ENTER] di terminal ini jika sudah login dan halaman tabel Nerwana tampil... ")
        
        # Jalankan scraping berdasarkan pilihan
        if choice == "1":
            for f_code, f_label in SPECIFIC_FILTERS:
                if f_code != "": # Hanya filter spesifik
                    scrape_filter(page, f_code, f_label)
        elif choice == "2":
            scrape_filter(page, "", "Semua Data Lengkap")
        elif choice == "3":
            # Filter spesifik dulu
            for f_code, f_label in SPECIFIC_FILTERS:
                scrape_filter(page, f_code, f_label)
                
        # Cek total di SQLite
        conn = get_connection()
        total_in_db = conn.execute("SELECT count(*) FROM kasus_nerwana").fetchone()[0]
        conn.close()
        
        print("\n" + "=" * 65)
        print(f"SCRAPING FASE 1 SELESAI!")
        print(f"Total baris unik di SQLite (kasus_nerwana): {total_in_db}")
        print("=" * 65)
        
        context.close()

if __name__ == "__main__":
    main()
