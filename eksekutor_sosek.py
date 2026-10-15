"""
eksekutor_sosek.py
Modul Otomasi Verifikasi Inkonsistensi Sosek (Kasus sosek_33):
Tabel Mikro Penduduk dengan NIK Mengandung 6 Digit Kembar Berturut-turut.

Alur Kerja:
1. Membuka tabel kasus sosek_33 di Selancar Nerwana.
2. Membaca baris yang belum ditindaklanjuti dan tidak terkunci.
3. Membuka assignment FASIH secara read-only (tanpa revoke/edit).
4. Membuka SE2026 - L BLOK I (Keterangan Umum Keluarga).
5. Mencocokkan NIK target dengan NIK anggota keluarga di Blok I.
6. Memvalidasi apakah tahun lahir adalah 2000 (bulan Oktober) atau kode wilayah resmi (mis. 111111).
7. Jika terbukti valid:
   - Pada mode LIVE: ubah status tindak lanjut Selancar menjadi 'Sesuai lapangan' ('sesuai').
   - Pada mode DRY-RUN: tampilkan hasil verifikasi tanpa mengubah Selancar.
8. Tutup tab FASIH dan lanjut ke baris berikutnya sampai batas tercapai.
"""

import time
import os
import random
from playwright.sync_api import sync_playwright

from updater_nerwana import pastikan_login_selancar
from eksekutor_fasih import selesaikan_sso_pada_fasih

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

URL_SOSEK_33 = "https://nerwana-aceh.web.bps.go.id/selancar2026/inkonsistensi-sosek?kabkota=1175&kasus=sosek_33&per_page=50"

def jalankan_verifikasi_sosek(pilihan_mode="1", limit=1):
    dry_run = pilihan_mode in ["1", "3"]
    interaktif = pilihan_mode in ["1", "2"]
    
    print("\n" + "=" * 65)
    print("MODUL INKONSISTENSI SOSEK: KASUS sosek_33")
    print(f"Mode         : {'DRY-RUN (Simulasi)' if dry_run else 'LIVE (Submit Tindak Lanjut)'}")
    print(f"Interaktif   : {'YA' if interaktif else 'TIDAK (Batch Otomatis)'}")
    print(f"Target Baris : {limit}")
    print("=" * 65 + "\n")

    with sync_playwright() as p:
        print("[CDP] Menghubungkan ke browser Chrome debug (port 9222)...")
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]

        # 1. Buka atau temukan tab Selancar
        selancar_page = None
        for pg in context.pages:
            if "nerwana-aceh.web.bps.go.id" in pg.url and "inkonsistensi-sosek" in pg.url:
                selancar_page = pg
                break
        if not selancar_page:
            for pg in context.pages:
                if "nerwana-aceh.web.bps.go.id" in pg.url:
                    selancar_page = pg
                    break
        if not selancar_page:
            selancar_page = context.new_page()

        print(f"[SELANCAR] Menavigasi ke halaman kasus sosek_33...")
        selancar_page.bring_to_front()
        if "kasus=sosek_33" not in selancar_page.url:
            selancar_page.goto(URL_SOSEK_33, timeout=60000)
            selancar_page.wait_for_load_state("domcontentloaded")
            pastikan_login_selancar(selancar_page)

        # Tunggu tabel dimuat
        selancar_page.wait_for_selector("#tableIk tbody tr", timeout=30000)
        try:
            selancar_page.locator("#loading-overlay").wait_for(state="hidden", timeout=10000)
        except Exception:
            pass

        sukses = 0
        di_skip = 0
        gagal = 0
        skip_aids = set()

        while sukses < limit:
            rows = selancar_page.locator("#tableIk tbody tr").all()
            target_info = None

            for idx, tr in enumerate(rows):
                tds = tr.locator("td").all()
                if len(tds) < 8:
                    continue
                nik = tds[5].inner_text().strip()
                nama_kk = tds[6].inner_text().strip()
                tl_select = tr.locator("select.ik-tl-select").first
                if tl_select.count() == 0:
                    continue

                stat = tl_select.input_value() or tl_select.get_attribute("data-prev") or ""
                is_locked = tl_select.get_attribute("data-terkunci") == "1"
                data_row = tl_select.get_attribute("data-row") or ""
                link_btn = tr.locator("a.assignment-link").first
                aid = link_btn.inner_text().strip() if link_btn.count() > 0 else ""

                if aid in skip_aids:
                    continue

                # Kriteria baris yang dikerjakan: belum ditindaklanjuti dan tidak terkunci
                if not is_locked and stat not in ["sesuai", "akan_direvisi", "sudah_direvisi"]:
                    target_info = {
                        "row_num": idx + 1,
                        "nik": nik,
                        "nama_kk": nama_kk,
                        "tl_select": tl_select,
                        "link_btn": link_btn,
                        "data_row": data_row,
                        "aid": aid,
                        "tr": tr
                    }
                    break

            if not target_info:
                # Coba pagination berikutnya
                btn_next = selancar_page.locator('.ik-pager .pages a:has-text("›"), .ik-pager .pages a[rel="next"]').first
                if btn_next.count() > 0 and btn_next.is_visible():
                    print("[SELANCAR] Berpindah ke halaman berikutnya...")
                    btn_next.click()
                    time.sleep(3)
                    selancar_page.wait_for_selector("#tableIk tbody tr", timeout=30000)
                    continue
                else:
                    print("\n[INFO] Tidak ada lagi baris pending yang tersedia di tabel Selancar saat ini.")
                    break

            nik_target = target_info["nik"]
            nama_kk = target_info["nama_kk"]
            row_num = target_info["row_num"]
            aid = target_info["aid"]
            skip_aids.add(aid)

            print(f"\n>>> Memproses Target [{sukses + 1}/{limit}] (Baris {row_num}) <<<")
            print(f"[SELANCAR] KK: {nama_kk} | NIK Flag: {nik_target}")

            # 2. Buka assignment FASIH via link_btn
            print("[SELANCAR] Membuka assignment FASIH...")
            try:
                with context.expect_page() as new_page_info:
                    target_info["link_btn"].scroll_into_view_if_needed()
                    time.sleep(0.3)
                    target_info["link_btn"].click()
                fasih_page = new_page_info.value
            except Exception as e_open:
                print(f"[WARN] Gagal membuka tab assignment: {e_open}")
                gagal += 1
                continue

            fasih_page.wait_for_load_state("domcontentloaded")
            selesaikan_sso_pada_fasih(fasih_page, selancar_page=selancar_page)

            # 3. Tunggu hingga kuesioner siap atau error
            loaded = False
            for _ in range(30):
                time.sleep(1.5)
                if fasih_page.locator("text=\"There's some error\"").count() > 0:
                    print(f"[WARN] Assignment {aid} mengalami error 'There's some error' di server BPS. Dilewati.")
                    di_skip += 1
                    try:
                        fasih_page.close()
                    except Exception:
                        pass
                    break
                if fasih_page.locator('div[title*="BLOK"], div:has-text("BLOK")').count() > 0:
                    loaded = True
                    break

            if not loaded:
                try:
                    fasih_page.close()
                except Exception:
                    pass
                continue

            # 4. Masuk ke SE2026 - L BLOK I
            time.sleep(1.5)
            btn_blok_i = fasih_page.get_by_text("SE2026 - L BLOK I").first
            if btn_blok_i.count() == 0:
                print("[WARN] Menu SE2026 - L BLOK I tidak ditemukan di FASIH. Dilewati.")
                di_skip += 1
                fasih_page.close()
                continue

            btn_blok_i.scroll_into_view_if_needed()
            time.sleep(0.3)
            btn_blok_i.click()
            time.sleep(2)

            # 5. Ambil daftar anggota keluarga di bawah Blok I
            member_divs = fasih_page.locator('.fasih-form-sidebar div[title]:not([title^="SE2026"]):not([title*="Keterangan"]):not([title*="ANOMALI"]):not([title*="CATATAN"]):not([title*="PENGANTAR"]):not([title*="IDENTITAS"])').all()
            member_names = []
            for md in member_divs:
                t = md.get_attribute("title")
                if t and t not in member_names:
                    member_names.append(t)

            print(f"[FASIH] Anggota keluarga terdeteksi ({len(member_names)} orang): {member_names}")

            # 6. Cari anggota keluarga dengan NIK yang sama
            match_member = None
            match_thn = None
            match_tgl = None

            for m_name in member_names:
                m_elem = fasih_page.locator(f'.fasih-form-sidebar div[title="{m_name}"]').first
                m_elem.scroll_into_view_if_needed()
                time.sleep(0.3)
                m_elem.click()
                time.sleep(1.2)

                inputs = fasih_page.locator('input').all()
                vals = [inp.input_value().strip() for inp in inputs if inp.input_value().strip()]

                if nik_target in vals:
                    match_member = m_name
                    for v in vals:
                        if len(v) == 4 and v.isdigit() and (v.startswith("19") or v.startswith("20")):
                            match_thn = v
                        elif len(v) <= 2 and v.isdigit() and int(v) in range(1, 32):
                            match_tgl = v
                    print(f"[FASIH] NIK cocok dengan anggota: '{m_name}' (Tahun Lahir: {match_thn}, Tgl: {match_tgl})")
                    break

            # Tutup tab FASIH agar browser tetap ringan
            try:
                fasih_page.close()
            except Exception:
                pass

            # 7. Evaluasi Hasil Pemeriksaan
            # NIK valid jika lahir tahun 2000 (000000) atau kode wilayah resmi 111111
            is_valid = False
            alasan_valid = ""

            if match_member:
                if match_thn == "2000":
                    is_valid = True
                    alasan_valid = f"Anggota '{match_member}' terkonfirmasi lahir tahun 2000 (NIK mengandung '000000' sah dari Dukcapil)."
                elif nik_target.startswith("111111"):
                    is_valid = True
                    alasan_valid = f"NIK dimulai 111111 (Kode Wilayah sah Kec. Peusangan Siblah Krueng Bireuen)."
                else:
                    alasan_valid = f"Tahun lahir di FASIH ({match_thn}) tidak sesuai dengan pola tahun 2000."
            else:
                alasan_valid = "NIK tidak ditemukan pada form input anggota keluarga di kuesioner."

            print(f"[EVALUASI] Status: {'VALID / SESUAI LAPANGAN' if is_valid else 'PERLU REVIEW'}")
            print(f"[ALASAN] {alasan_valid}")

            if is_valid:
                if dry_run:
                    print("[DRY-RUN] Melewati perubahan status di Selancar (Simulasi sukses).")
                    sukses += 1
                else:
                    if interaktif:
                        jawab = input("\nTerapkan status 'Sesuai lapangan' ke Selancar? [y/n] (default y): ").strip().lower()
                        if jawab == "n":
                            print("[INFO] Dibatalkan oleh pengguna.")
                            di_skip += 1
                            continue

                    print("[SELANCAR] Mengubah status tindak lanjut menjadi 'Sesuai lapangan'...")
                    selancar_page.bring_to_front()
                    tl_select = target_info["tl_select"]
                    tl_select.scroll_into_view_if_needed()
                    time.sleep(0.4)
                    tl_select.select_option("sesuai")
                    time.sleep(2.0)
                    val_now = tl_select.input_value()
                    print(f"[BERHASIL] Tindak lanjut baris {row_num} telah diubah menjadi: '{val_now}'")
                    sukses += 1

                if sukses < limit:
                    jeda = random.uniform(2.0, 4.0)
                    time.sleep(jeda)
            else:
                di_skip += 1
                time.sleep(1.0)

        print("\n" + "=" * 65)
        print("RINGKASAN EKSEKUSI SOSEK 33:")
        print(f"Berhasil Sesuai : {sukses} / {limit}")
        print(f"Dilewati/Review : {di_skip}")
        print(f"Gagal           : {gagal}")
        print("=" * 65)

def main():
    print("=" * 65)
    print("   BOT VERIFIKASI INKONSISTENSI SOSEK - KASUS sosek_33")
    print("   Pemeriksaan NIK 6 Digit Kembar (Tahun 2000 / Validitas Lapangan)")
    print("=" * 65)
    print("\nPilih Mode:")
    print("  [1] Uji 1 Baris Pertama - DRY-RUN (Cek FASIH tanpa simpan ke Selancar) [Default]")
    print("  [2] Uji 1 Baris Pertama - LIVE (Cek FASIH & update status Selancar ke 'Sesuai lapangan')")
    print("  [3] Eksekusi Batch DRY-RUN (Cek FASIH beberapa baris tanpa simpan)")
    print("  [4] Eksekusi Batch LIVE (Cek FASIH & otomatis update Selancar jika terbukti lahir 2000)")
    
    pilih = input("\nMasukkan pilihan [1/2/3/4] (default 1): ").strip() or "1"
    limit = 1
    if pilih in ["3", "4"]:
        limit_str = input("Berapa jumlah baris batch? (1-50, default 10): ").strip() or "10"
        limit = max(1, min(int(limit_str), 50))
        
    jalankan_verifikasi_sosek(pilihan_mode=pilih, limit=limit)

if __name__ == "__main__":
    main()
