import os
import sys
import time
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_data")

def main():
    print("=" * 65)
    print("           FASE 0: PANDUAN RECON LANGKAH-DEMI-LANGKAH")
    print("=" * 65)

    captured_requests = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            viewport=None,
            args=["--start-maximized"]
        )

        def handle_request(req):
            if req.resource_type in ["xhr", "fetch"]:
                info = f"[AJAX REQ] {req.method} {req.url}"
                if req.post_data:
                    info += f"\n  Payload: {req.post_data}"
                captured_requests.append(info)
                print(f"\n{info}")

        def handle_response(res):
            if res.request.resource_type in ["xhr", "fetch"]:
                try:
                    info = f"[AJAX RES] {res.status} {res.url}"
                    if "json" in res.headers.get("content-type", "") or res.status == 200:
                        text = res.text()
                        if len(text) < 500:
                            info += f"\n  Body: {text}"
                    print(f"{info}")
                except Exception:
                    pass

        # Pasang listener ke semua halaman baru yang terbuka
        context.on("page", lambda p: (
            p.on("request", handle_request),
            p.on("response", handle_response)
        ))

        page = context.pages[0] if context.pages else context.new_page()
        page.on("request", handle_request)
        page.on("response", handle_response)

        target_url = "https://nerwana-aceh.web.bps.go.id/selancar2026/dc-terkena-flag?sort=nilai_tambah&dir=asc&kabkota=1175&kategori=A&flag=rasio_3&kode=1&filter_spesifik=&cari=&per_page=50"
        print(f"\n[INFO] Membuka Nerwana di browser Chromium...")
        try:
            page.goto(target_url, timeout=60000)
        except Exception as e:
            print(f"[INFO] Navigasi awal: {e}")

        # LANGKAH 1
        print("\n" + "=" * 65)
        print(">>> LANGKAH 1: LOGIN SSO & BUKA NERWANA <<<")
        print("1. Di browser yang baru terbuka, klik 'Login dengan SSO BPS'.")
        print("2. Masukkan akun SSO Anda sampai halaman daftar kasus Nerwana terbuka.")
        print("3. JANGAN KETIK APA-APA dulu sebelum tabel Nerwana muncul di layar!")
        print("=" * 65)
        input("\n--> Jika tabel Nerwana SUDAH muncul di layar browser, TEKAN [ENTER] DI SINI... ")

        # Simpan HTML Nerwana
        active_page = context.pages[0]
        for pg in context.pages:
            if "nerwana" in pg.url:
                active_page = pg
                break
        
        nerwana_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon_nerwana.html")
        with open(nerwana_html_path, "w", encoding="utf-8") as f:
            f.write(active_page.content())
        print(f"\n[SUKSES] HTML Nerwana berhasil disimpan ke: {nerwana_html_path}")

        # LANGKAH 2
        print("\n" + "=" * 65)
        print(">>> LANGKAH 2: TES DROPDOWN STATUS NERWANA <<<")
        print("1. Di halaman Nerwana, coba ubah dropdown tindak lanjut di salah satu baris")
        print("   (misal ubah jadi 'Sudah direvisi' atau status lainnya).")
        print("2. Lihat apakah ada log [AJAX REQ] muncul di terminal ini.")
        print("=" * 65)
        input("\n--> Jika sudah mencoba klik/ubah dropdown, TEKAN [ENTER] DI SINI... ")

        # LANGKAH 3
        print("\n" + "=" * 65)
        print(">>> LANGKAH 3: BUKA FASIH <<<")
        print("1. Di baris Nerwana tadi, klik tombol biru 'buka assignment'.")
        print("2. Halaman FASIH akan terbuka di tab baru (lakukan login SSO jika diminta).")
        print("3. Di FASIH, klik tombol bulat oranye 'Edit Assignment' di kanan bawah.")
        print("4. Buka menu BLOK II, lalu scroll sampai form rincian biaya & pendapatan.")
        print("=" * 65)
        input("\n--> Jika form kuesioner FASIH SUDAH terbuka lengkap, TEKAN [ENTER] DI SINI... ")

        # Simpan HTML FASIH
        fasih_page = None
        for pg in context.pages:
            if "fasih" in pg.url.lower():
                fasih_page = pg
                break
        if not fasih_page:
            fasih_page = context.pages[-1]

        fasih_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon_fasih.html")
        with open(fasih_html_path, "w", encoding="utf-8") as f:
            f.write(fasih_page.content())
        print(f"\n[SUKSES] HTML FASIH berhasil disimpan ke: {fasih_html_path} (URL: {fasih_page.url})")

        # Simpan log network
        net_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recon_network.txt")
        with open(net_log_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(captured_requests))
        print(f"[SUKSES] Log Network disimpan ke: {net_log_path}")

        print("\n" + "=" * 65)
        print("RECON SELESAI! Jendela browser bisa ditutup.")
        print("=" * 65)
        time.sleep(2)
        context.close()

if __name__ == "__main__":
    main()
