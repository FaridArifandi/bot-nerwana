"""
cek_remark0.py
Fitur: CEK ULANG baris Selancar berstatus "Sesuai lapangan" (milik siapa saja)
dan pastikan di FASIH sudah ada catatan/remark "#0" pada isian 27a / 31a.

Alur:
  1. Selancar -> DC Terkena Flag dengan filter tetap:
        Flag = Flag Rasio 3 | Kategori = Semua | Kode = 1 | Spesifik = Semua (tanpa filter)
     lalu klik chip "Sesuai lapangan" di kanan atas
     ("Tindak lanjut - Semua Kategori / Flag Rasio 3 - NTB / Output = 1 (Kena Flag)").
  2. Untuk tiap baris pada daftar itu (semua halaman, siapa pun pengisinya):
        buka assignment FASIH -> Blok II -> isian 27a (usaha biasa) / 31a (usaha beroperasi 2026)
        -> buka dialog Catatan:
             * sudah ada "#0"  -> SKIP (assignment tidak disentuh sama sekali)
             * belum ada       -> (mode isi) revoke/edit, tulis "#0", simpan, tampilkan anomali, kirim ulang
  3. Status "Tindak lanjut" di Selancar TIDAK diubah (baris tetap "Sesuai lapangan").

Hasil per baris disimpan di hasil_cek_remark0.json (+ .csv di akhir) sehingga bisa dilanjutkan:
baris yang sudah ADA / DITAMBAH dilewati pada run berikutnya.

Cara pakai:
  - Dari menu utama eksekutor_fasih.py -> pilihan [4]
  - atau langsung:  python cek_remark0.py
"""
import os
import re
import csv
import json
import math
import time
import random
import importlib
import urllib.parse
from datetime import datetime

from config import (
    JEDA_ANTAR_ASSIGNMENT_MIN,
    JEDA_ANTAR_ASSIGNMENT_MAX,
    MAX_ERR_BERTURUT,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASIL_JSON = os.path.join(BASE_DIR, "hasil_cek_remark0.json")
HASIL_CSV = os.path.join(BASE_DIR, "hasil_cek_remark0.csv")

KODE_REMARK = "#0"
TL_TARGET = "sesuai_lapangan"
PER_PAGE = 50

MODE_AUDIT = "audit"            # cek saja, TIDAK mengubah apa pun di FASIH
MODE_ISI = "isi"                # cek + isi "#0" + kirim ulang
MODE_INTERAKTIF = "interaktif"  # seperti isi, tapi tanya y/n sebelum mengubah tiap baris

# Status hasil
S_ADA = "ADA"                          # sudah ada #0 -> dilewati
S_DITAMBAH = "DITAMBAH"                # #0 berhasil ditulis + submit
S_BELUM_ADA = "BELUM_ADA"              # (audit) belum ada #0
S_TAK_TERCEK = "TIDAK_TERCEK"          # (audit) dialog catatan tidak terbuka di mode lihat
S_DIBATALKAN = "DIBATALKAN"
S_NEED_REVIEW = "NEED_REVIEW"          # submit ditolak karena galat kuesioner
S_REMARK_GAGAL = "REMARK_GAGAL"
S_SUBMIT_GAGAL = "SUBMIT_GAGAL"
S_FASIH_ERROR = "FASIH_ERROR"
S_GAGAL = "GAGAL"
S_WAF = "WAF_BLOCK"
S_SSO = "SSO_LIMIT_EXCEEDED"

STATUS_FINAL = {S_ADA, S_DITAMBAH}
STATUS_ERROR_TEKNIS = {S_REMARK_GAGAL, S_SUBMIT_GAGAL, S_FASIH_ERROR, S_GAGAL}


# ======================================================================
#  UTILITAS MURNI (mudah diuji tanpa browser)
# ======================================================================

# "#0" berdiri sendiri: bukan bagian dari "#01", "#00", "##0", "a#0" dst.
_RE_REMARK0 = re.compile(r'(?<![\w#])#0(?!\d)')


def ada_remark0(teks):
    """True jika teks catatan mengandung remark '#0' (bukan '#01' / '#0123')."""
    return bool(_RE_REMARK0.search(teks or ""))


def url_halaman(url_sekarang, nomor_halaman, tl=TL_TARGET):
    """Salin URL Selancar saat ini, ganti ?page=N dan pastikan tl=sesuai_lapangan."""
    p = urllib.parse.urlparse(url_sekarang)
    qs = urllib.parse.parse_qs(p.query, keep_blank_values=True)
    qs["page"] = [str(nomor_halaman)]
    if tl:
        qs["tl"] = [tl]
    return urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode(qs, doseq=True)))


def url_filter(base_url, kabkota="", tl="", nomor_halaman=1, per_page=PER_PAGE):
    """URL DC Terkena Flag: Flag Rasio 3, Semua Kategori, Kode 1, Spesifik semua."""
    q = [("sort", "nilai_tambah"), ("dir", "asc")]
    if kabkota:
        q.append(("kabkota", kabkota))
    q += [("kategori", "all"), ("flag", "rasio_3"), ("kode", "1"),
          ("filter_spesifik", "none"), ("cari", "")]
    if tl:
        q.append(("tl", tl))
    q += [("per_page", str(per_page)), ("page", str(nomor_halaman))]
    return base_url + "?" + urllib.parse.urlencode(q)


def kunci_baris(aid, nama):
    return f"{aid}|{nama}"


def muat_hasil():
    try:
        with open(HASIL_JSON, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def simpan_hasil(hasil):
    tmp = HASIL_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(hasil, f, ensure_ascii=False, indent=1)
    os.replace(tmp, HASIL_JSON)


def tulis_csv(hasil):
    try:
        with open(HASIL_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["assignment_id", "nama_usaha", "pengisi_selancar", "status", "detail", "waktu"])
            for k, v in hasil.items():
                aid = k.split("|", 1)[0]
                w.writerow([aid, v.get("nama", ""), v.get("oleh", ""), v.get("status", ""),
                            v.get("detail", ""), v.get("waktu", "")])
    except Exception as e:
        print(f"[CEK-#0] Gagal menulis CSV: {e}")


# ======================================================================
#  SELANCAR: filter + chip "Sesuai lapangan" + baca baris
# ======================================================================

_JS_BARIS = """() => Array.from(document.querySelectorAll('#tableEvalProfil tbody tr')).map((tr, i) => {
    const b = tr.querySelector('.dc-sim-btn');
    if (!b) return null;
    const s = tr.querySelector('select.dc-tl-select');
    const o = tr.querySelector('.dc-tl-oleh');
    return {
        i: i,
        aid: b.getAttribute('data-aid') || '',
        nama: b.getAttribute('data-nama') || '',
        link: b.getAttribute('data-link') || '',
        stat: s ? (s.value || s.getAttribute('data-prev') || '') : '',
        oleh: o ? (o.textContent || '').trim() : ''
    };
}).filter(x => x)"""

_SEL_CHIP = '.tl-summary a.st-sesuai_lapangan'


def _tunggu_tabel(page, timeout=30000):
    """Tunggu tabel muncul ATAU tulisan 'Tidak ada data'. Mengembalikan jumlah baris."""
    try:
        page.wait_for_selector('#tableEvalProfil tbody tr, text="Tidak ada data"', timeout=timeout)
    except Exception:
        pass
    try:
        page.locator('#loading-overlay').wait_for(state="hidden", timeout=10000)
    except Exception:
        pass
    time.sleep(0.5)
    try:
        return page.locator('#tableEvalProfil tbody tr').count()
    except Exception:
        return 0


def baca_info_tabel(page):
    """Total baris & per_page dari halaman Selancar yang sedang terbuka."""
    info = {"total": 0, "per_page": PER_PAGE}
    try:
        t = page.locator('.ep-pager-info').first.inner_text()
        m = re.search(r'dari\s+([\d\.\,]+)\s+baris', t)
        if m:
            info["total"] = int(re.sub(r'\D', '', m.group(1)) or 0)
    except Exception:
        pass
    if not info["total"]:
        try:
            t = page.locator(_SEL_CHIP + ' .jml').first.inner_text()
            info["total"] = int(re.sub(r'\D', '', t) or 0)
        except Exception:
            pass
    try:
        v = page.locator('#filter_per_page').first.input_value()
        if v and v.isdigit():
            info["per_page"] = int(v)
    except Exception:
        pass
    return info


def _filter_dropdown_ok(page):
    """Cek 4 dropdown filter wajib: Kategori=all, Flag=rasio_3, Kode=1, Spesifik=none."""
    want = {"#filter_kategori": "all", "#filter_flag": "rasio_3",
            "#filter_kode": "1", "#filter_spesifik": "none"}
    salah = []
    for sel, val in want.items():
        try:
            cur = page.locator(sel).first.input_value()
        except Exception:
            cur = None
        if cur != val:
            salah.append(f"{sel}={cur!r} (harus {val!r})")
    return salah


def siapkan_selancar_sesuai_lapangan(page):
    """
    Buka DC Terkena Flag dengan filter wajib lalu klik chip 'Sesuai lapangan'.
    Mengembalikan dict info {total, per_page, url} atau None jika gagal / tidak ada baris.
    """
    from updater_nerwana import (
        NERWANA_BASE_URL, NERWANA_LANDING_URL,
        pastikan_login_selancar, deteksi_kabkota,
    )

    print("\n" + "=" * 65)
    print("   [CEK-#0] MENYIAPKAN SELANCAR - DC TERKENA FLAG")
    print("   Filter : Flag Rasio 3 | Semua Kategori | Kode 1 | Spesifik: Semua")
    print("   Chip   : Tindak lanjut = 'Sesuai lapangan' (milik siapa saja)")
    print("=" * 65)

    if "selancar2026" not in page.url.lower():
        try:
            page.goto(NERWANA_LANDING_URL, timeout=45000)
            page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            print(f"[INFO] Navigasi landing: {e}")
    pastikan_login_selancar(page)

    kabkota = deteksi_kabkota(page) or ""
    if not kabkota:
        try:
            page.goto(NERWANA_BASE_URL, timeout=45000)
            page.wait_for_load_state("domcontentloaded")
            pastikan_login_selancar(page)
            kabkota = deteksi_kabkota(page) or ""
        except Exception as e:
            print(f"[INFO] Deteksi kabkota: {e}")
    print(f"[CEK-#0] Wilayah (kabkota) akun: {kabkota or 'default akun'}")

    # 1) Terapkan 4 filter lewat URL (tanpa tl) lalu verifikasi dropdown di UI
    for percobaan in (1, 2):
        page.goto(url_filter(NERWANA_BASE_URL, kabkota, tl=""), timeout=45000)
        page.wait_for_load_state("domcontentloaded")
        pastikan_login_selancar(page)
        _tunggu_tabel(page)
        salah = _filter_dropdown_ok(page)
        if not salah:
            break
        print(f"[CEK-#0] Dropdown filter belum sesuai (percobaan {percobaan}): {', '.join(salah)}")
    else:
        print("[CEK-#0] Filter dropdown tidak sesuai setelah 2 percobaan. Dihentikan agar tidak salah sasaran.")
        return None

    # 2) Klik chip "Sesuai lapangan" (jangan klik kalau sudah aktif: klik ulang = MELEPAS filter)
    chip = page.locator(_SEL_CHIP).first
    if chip.count() == 0:
        print("[CEK-#0] Chip 'Sesuai lapangan' tidak ditemukan di halaman.")
        return None
    cls = chip.get_attribute("class") or ""
    if "aktif" not in cls.split():
        print("[CEK-#0] Mengklik chip 'Sesuai lapangan'...")
        chip.scroll_into_view_if_needed()
        time.sleep(0.4)
        chip.click()
        try:
            page.wait_for_selector(_SEL_CHIP + '.aktif', timeout=30000)
        except Exception:
            print("[CEK-#0] Chip tidak berubah aktif setelah diklik.")
            return None
    n_baris = _tunggu_tabel(page)

    # 3) Verifikasi akhir
    salah = _filter_dropdown_ok(page)
    chip_aktif = page.locator(_SEL_CHIP + '.aktif').count() > 0
    if salah or not chip_aktif:
        print(f"[CEK-#0] Verifikasi filter gagal. Dropdown salah={salah} chip_aktif={chip_aktif}")
        return None

    info = baca_info_tabel(page)
    info["url"] = page.url
    print(f"[CEK-#0] Siap. Total 'Sesuai lapangan': {info['total']} baris "
          f"({info['per_page']}/halaman, baris di halaman ini: {n_baris})")
    if info["total"] == 0 and n_baris == 0:
        return None
    if info["total"] == 0:
        info["total"] = n_baris
    return info


def pindah_halaman(page, nomor, info):
    """Pindah ke halaman tabel ke-N dengan filter tetap (URL-based, deterministik)."""
    from updater_nerwana import pastikan_login_selancar
    page.goto(url_halaman(info["url"], nomor), timeout=45000)
    page.wait_for_load_state("domcontentloaded")
    pastikan_login_selancar(page)
    _tunggu_tabel(page)
    if page.locator(_SEL_CHIP + '.aktif').count() == 0:
        print(f"[CEK-#0] Peringatan: chip 'Sesuai lapangan' tidak aktif di halaman {nomor}.")
        return False
    return True


# ======================================================================
#  FASIH: baca / tulis catatan #0 di isian 27a / 31a
# ======================================================================

def baca_status_remark0(ef, page, container):
    """
    Mengembalikan (state, cuplikan):
      state = 'ADA' | 'TIDAK_ADA' | 'TIDAK_BISA_DIBUKA'
    """
    dialog = ef.buka_dialog_catatan_pendapatan(page, container)
    if not dialog:
        return "TIDAK_BISA_DIBUKA", ""
    teks = ""
    try:
        teks = dialog.inner_text() or ""
        if not ada_remark0(teks):
            time.sleep(0.8)  # riwayat catatan kadang dimuat terlambat
            teks = dialog.inner_text() or teks
    except Exception as e:
        print(f"[CEK-#0] Gagal membaca dialog catatan: {e}")
    finally:
        ef.tutup_modal_dialog(page)
    return ("ADA" if ada_remark0(teks) else "TIDAK_ADA"), re.sub(r'\s+', ' ', teks).strip()[:160]


def tambah_remark0(ef, page, container, kode=KODE_REMARK, max_retry=2):
    """Tulis '#0' di dialog Catatan 27a/31a lalu verifikasi benar-benar tersimpan."""
    print(f"[CEK-#0] Menulis catatan '{kode}'...")
    for percobaan in range(1, max_retry + 1):
        dialog = ef.buka_dialog_catatan_pendapatan(page, container)
        if not dialog:
            print(f"[WARN] Percobaan {percobaan}/{max_retry}: dialog catatan tidak terbuka.")
            time.sleep(1)
            continue
        try:
            if ada_remark0(dialog.inner_text()):
                ef.tutup_modal_dialog(page)
                return True
            ta = dialog.locator('textarea:visible').first
            if ta.count() == 0:
                print("[WARN] Textarea catatan tidak ditemukan.")
            else:
                ta.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(kode, delay=random.randint(40, 80))
                time.sleep(0.5)
                btn = dialog.locator('button[title="Simpan"]:visible').first
                if btn.count() > 0:
                    btn.click(timeout=3000)
                else:
                    page.keyboard.press("Enter")
                time.sleep(1.5)
                if ada_remark0(dialog.inner_text()):
                    print(f"[CEK-#0] Catatan '{kode}' TERVERIFIKASI tersimpan.")
                    ef.tutup_modal_dialog(page)
                    return True
                print(f"[WARN] Percobaan {percobaan}/{max_retry}: '{kode}' belum muncul setelah Simpan.")
        except Exception as e:
            print(f"[WARN] Error saat menulis catatan (percobaan {percobaan}): {e}")
        ef.tutup_modal_dialog(page)
        time.sleep(1)
    return False


def _buka_dan_cek(ef, page, nama):
    """Buka Blok II -> container 27a/31a -> baca status #0. Mengembalikan (state, cuplikan, container, blok)."""
    ok, idx = ef.buka_blok_ii(page, nama)
    if not ok:
        raise Exception("Gagal membuka Blok II")
    blok = ef.deteksi_blok(page)
    container = ef.cari_container_isian_27a(page, idx=idx)
    if container is None:
        raise Exception(f"Container isian 27a/31a tidak ditemukan (blok '{blok}', idx #{idx})")
    state, cuplik = baca_status_remark0(ef, page, container)
    print(f"[CEK-#0] Blok '{blok}' (#{idx}) | status #0: {state} {('| ' + cuplik) if cuplik else ''}")
    return state, cuplik, container, blok


WAIT_FASIH_SIAP = 150   # detik menunggu kuesioner FASIH siap (FASIH sering lambat)


def _buka_tab_fasih(context, link_btn, link):
    """Buka tab FASIH: klik link di Selancar bila link_btn ada, kalau tidak (atau gagal) buka langsung."""
    page = None
    if link_btn is not None:
        try:
            link_btn.scroll_into_view_if_needed()
            time.sleep(0.8)
            with context.expect_page(timeout=20000) as info_pg:
                link_btn.click()
            page = info_pg.value
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            fp = [pg for pg in context.pages if "fasih" in pg.url.lower() and not pg.is_closed()]
            page = fp[-1] if fp else None
    if (page is None or page.is_closed()) and link:
        page = context.new_page()
        try:
            page.goto(link, timeout=60000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[CEK-#0] Navigasi FASIH: {e}")
    return page


def proses_satu_baris(ef, context, selancar_page, r, mode):
    """
    Membuka satu assignment FASIH dan memastikan remark #0 ada.
    Mengembalikan (status, detail).
    """
    aid, nama, link = r["aid"], r["nama"], r["link"]

    # Tutup tab FASIH sisa
    for pg in context.pages:
        try:
            if not pg.is_closed() and "fasih-sm.bps.go.id" in pg.url.lower():
                pg.close()
        except Exception:
            pass

    # Tombol link di tabel Selancar (dipakai juga oleh alur SSO FASIH bila perlu)
    link_btn = None
    try:
        tr = selancar_page.locator('#tableEvalProfil tbody tr').nth(r["i"])
        if tr.locator('.dc-sim-btn').first.get_attribute("data-aid") == aid:
            link_btn = tr.locator('a.dc-link-btn').first
    except Exception:
        link_btn = None

    fasih_page = None
    try:
        siap = False
        for percobaan, via_klik in enumerate((True, False), 1):
            # Bersihkan tab percobaan sebelumnya
            if fasih_page is not None:
                try:
                    if not fasih_page.is_closed():
                        fasih_page.close()
                except Exception:
                    pass
                fasih_page = None
            fasih_page = _buka_tab_fasih(context, link_btn if via_klik else None, link)
            if not fasih_page or fasih_page.is_closed():
                print(f"[CEK-#0] Tab FASIH tidak terbuka (percobaan {percobaan}/2).")
                continue

            # Login SSO / tunggu siap (FASIH kadang lambat, tunggu lama saja)
            sso_res, sso_bot = ef.selesaikan_sso_pada_fasih(fasih_page, selancar_page=selancar_page, link_btn=link_btn if via_klik else None)
            if sso_res == "WAF":
                return S_WAF, str(sso_bot)
            if sso_res == "SSO_LIMIT_EXCEEDED":
                return S_SSO, "Perlu login SSO manual"
            ready_res, ready_bot = ef.wait_fasih_ready(
                fasih_page, selancar_page=selancar_page,
                link_btn=link_btn if via_klik else None, timeout=WAIT_FASIH_SIAP)
            if ready_res == "WAF":
                return S_WAF, str(ready_bot)
            if ready_res == "SSO_LIMIT_EXCEEDED":
                return S_SSO, "Perlu login SSO manual"
            if ready_res == "READY":
                siap = True
                break
            # TIMEOUT tapi sudah di halaman assignment & tidak error: tetap coba lanjut
            try:
                if (ready_res == "TIMEOUT" and not fasih_page.is_closed()
                        and "assignment" in fasih_page.url.lower() and not ef.cek_fasih_error(fasih_page)):
                    print("[CEK-#0] Belum terdeteksi siap, tapi halaman assignment terbuka. Tetap dilanjutkan...")
                    siap = True
                    break
            except Exception:
                pass
            print(f"[CEK-#0] Akses FASIH {ready_res} (percobaan {percobaan}/2)." + (" Coba buka ulang lewat link langsung..." if percobaan == 1 else ""))
        if not siap:
            return S_FASIH_ERROR, "Akses FASIH gagal/timeout setelah 2 percobaan"

        return _proses_di_fasih(ef, fasih_page, aid, nama, mode)

    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            ss = os.path.join(ef.SCREENSHOTS_DIR, f"CEK0_FAILED_{aid}_{int(time.time())}.png")
            if fasih_page and not fasih_page.is_closed():
                fasih_page.screenshot(path=ss, timeout=5000)
                print(f"[SCREENSHOT] {ss}")
        except Exception:
            pass
        try:
            if fasih_page and ef.cek_fasih_error(fasih_page):
                return S_FASIH_ERROR, str(e)[:200]
        except Exception:
            pass
        return S_GAGAL, str(e)[:200]
    finally:
        try:
            if fasih_page and not fasih_page.is_closed():
                fasih_page.close()
        except Exception:
            pass


def _proses_di_fasih(ef, page, aid, nama, mode):
    # --- Tahap A: cek TANPA mengubah assignment (mode lihat) ---
    state = "TIDAK_BISA_DIBUKA"
    try:
        state, cuplik, container, blok = _buka_dan_cek(ef, page, nama)
    except Exception as e:
        print(f"[CEK-#0] Cek di mode lihat tidak berhasil ({e}). Akan dicoba di mode edit bila perlu.")

    if state == "ADA":
        return S_ADA, "Sudah ada #0 (assignment tidak disentuh)"

    if mode == MODE_AUDIT:
        if state == "TIDAK_ADA":
            return S_BELUM_ADA, "Belum ada #0 (mode audit: tidak diubah)"
        return S_TAK_TERCEK, "Dialog catatan tidak terbuka di mode lihat (perlu mode edit untuk memastikan)"

    if mode == MODE_INTERAKTIF:
        jawab = input(f"   >> '{nama}' (AID {aid}) belum terkonfirmasi ada #0. Revoke/edit & tulis '{KODE_REMARK}'? [y/n]: ").strip().lower()
        if jawab != "y":
            return S_DIBATALKAN, "Dibatalkan oleh pengguna"

    # --- Tahap B: mode edit (revoke bila perlu), tulis #0, kirim ulang ---
    ef.lakukan_revoke_dan_edit(page)
    time.sleep(0.5)
    catatan_tertinggal = " (assignment mungkin masih dalam mode edit, cek manual di FASIH)"
    try:
        state, cuplik, container, blok = _buka_dan_cek(ef, page, nama)
    except Exception as e:
        return S_GAGAL, f"Gagal membuka isian setelah masuk mode edit: {e}{catatan_tertinggal}"

    if state == "TIDAK_BISA_DIBUKA":
        return S_REMARK_GAGAL, f"Dialog catatan tidak terbuka{catatan_tertinggal}"

    ditambah = False
    if state == "TIDAK_ADA":
        if not tambah_remark0(ef, page, container):
            return S_REMARK_GAGAL, f"Gagal menyimpan '{KODE_REMARK}'{catatan_tertinggal}"
        ditambah = True

    # Tampilkan anomali lalu kirim ulang (mengembalikan assignment ke status terkirim)
    ef.proses_halaman_catatan_dan_tampilkan_anomali(page)
    ok_submit, err_submit = ef.submit_assignment(page)
    if ok_submit:
        if ditambah:
            return S_DITAMBAH, f"'{KODE_REMARK}' ditulis di blok '{blok}' dan assignment dikirim ulang"
        return S_ADA, "#0 ternyata sudah ada (terlihat di mode edit); assignment dikirim ulang"
    if err_submit and "GALAT" in str(err_submit):
        return S_NEED_REVIEW, f"{'#0 sudah ditulis, ' if ditambah else ''}submit ditolak: {err_submit}{catatan_tertinggal}"
    return S_SUBMIT_GAGAL, f"{'#0 sudah ditulis, ' if ditambah else ''}{err_submit}{catatan_tertinggal}"


# ======================================================================
#  MAIN
# ======================================================================

def main_cek_remark0(ef=None):
    """
    ef = modul eksekutor_fasih yang sedang berjalan (dioper dari menu supaya tidak ter-import dua kali).
    """
    if ef is None:
        ef = importlib.import_module("eksekutor_fasih")

    print("=" * 65)
    print("   CEK ULANG 'SESUAI LAPANGAN' -> PASTIKAN REMARK #0 (27a / 31a)")
    print("   Filter: Flag Rasio 3 | Semua Kategori | Kode 1 | Spesifik Semua")
    print("=" * 65)

    ef.cleanup_old_screenshots(max_keep=30)
    if not ef.start_debug_chrome():
        return

    print("\nPilih Mode:")
    print("  [1] Audit  - hanya cek & catat, TIDAK mengubah apa pun di FASIH [Default]")
    print("  [2] Isi    - cek, kalau belum ada tulis '#0' lalu kirim ulang (sungguhan)")
    print("  [3] Interaktif - seperti [2] tapi tanya y/n sebelum mengubah tiap baris")
    pilih = input("Masukkan pilihan [1/2/3] (default 1): ").strip() or "1"
    mode = {"1": MODE_AUDIT, "2": MODE_ISI, "3": MODE_INTERAKTIF}.get(pilih, MODE_AUDIT)

    lim_str = input("\nBerapa baris maksimal diproses? (angka, 0 = semua, default 10): ").strip() or "10"
    try:
        limit = max(0, int(lim_str))
    except ValueError:
        limit = 10

    lewati = (input("Lewati baris yang sudah berstatus ADA/DITAMBAH di run sebelumnya? [y/n] (default y): ").strip().lower() != "n")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("\n[CDP] Menghubungkan ke browser Chrome (port 9222)...")
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        from updater_nerwana import NerwanaManager
        mgr = NerwanaManager(context, kategori="A")
        selancar_page = mgr.get_or_create_page()

        info = siapkan_selancar_sesuai_lapangan(selancar_page)
        if not info:
            print("[CEK-#0] Tidak ada yang bisa diproses (filter/chip gagal atau 0 baris).")
            return

        hasil = muat_hasil()
        n_hal = max(1, math.ceil(info["total"] / max(1, info["per_page"])))
        print(f"[CEK-#0] {info['total']} baris / {n_hal} halaman | mode={mode} | limit={limit or 'semua'}")

        stat = {}
        diproses = 0
        err_berturut = 0
        sesi_aid = set()
        berhenti = False

        for hal in range(1, n_hal + 1):
            if berhenti:
                break
            if hal > 1 and not pindah_halaman(selancar_page, hal, info):
                print("[CEK-#0] Halaman tidak sesuai filter, dihentikan.")
                break

            baris = selancar_page.evaluate(_JS_BARIS) or []
            print(f"\n[CEK-#0] Halaman {hal}/{n_hal}: {len(baris)} baris")

            for r in baris:
                if limit and diproses >= limit:
                    berhenti = True
                    break
                if r["stat"] != TL_TARGET:
                    continue  # pengaman bila filter bocor
                k = kunci_baris(r["aid"], r["nama"])
                if k in sesi_aid:
                    continue
                sesi_aid.add(k)
                if lewati and hasil.get(k, {}).get("status") in STATUS_FINAL:
                    stat["DILEWATI(run lalu)"] = stat.get("DILEWATI(run lalu)", 0) + 1
                    continue

                diproses += 1
                print(f"\n>>> [{diproses}{('/' + str(limit)) if limit else ''}] '{r['nama']}' | AID {r['aid']} | pengisi: {r['oleh'] or '-'}")
                status, detail = proses_satu_baris(ef, context, selancar_page, r, mode)
                print(f"    => {status}: {detail}")

                hasil[k] = {
                    "nama": r["nama"], "oleh": r["oleh"], "status": status,
                    "detail": detail, "waktu": datetime.now().isoformat(timespec="seconds"),
                }
                simpan_hasil(hasil)
                stat[status] = stat.get(status, 0) + 1

                if status == S_WAF:
                    print("[WAF] Akses terblokir. Berhenti dulu, coba lagi nanti.")
                    berhenti = True
                    break
                if status == S_SSO:
                    print("[SSO] Perlu login SSO manual di Chrome. Berhenti.")
                    berhenti = True
                    break
                if status in STATUS_ERROR_TEKNIS:
                    err_berturut += 1
                    if err_berturut >= MAX_ERR_BERTURUT:
                        print(f"[STOP-LOSS] {err_berturut} error teknis berturut-turut. Berhenti untuk keamanan.")
                        berhenti = True
                        break
                else:
                    err_berturut = 0

                time.sleep(random.uniform(JEDA_ANTAR_ASSIGNMENT_MIN, JEDA_ANTAR_ASSIGNMENT_MAX))

        tulis_csv(hasil)
        print("\n" + "=" * 65)
        print("RINGKASAN CEK REMARK #0:")
        print(f"Mode                : {mode}")
        print(f"Baris diproses      : {diproses}")
        for k_s in sorted(stat):
            print(f"  {k_s:<22}: {stat[k_s]}")
        print(f"Detail per baris    : {HASIL_JSON}")
        print(f"                      {HASIL_CSV}")
        print("=" * 65)


if __name__ == "__main__":
    main_cek_remark0()
