"""
cek_remark0.py
Fitur: CEK ULANG semua baris Selancar yang sudah diisi tindak lanjutnya (milik siapa saja)
dan pastikan remark di FASIH (isian 27a / 31a) sudah benar:
  A. "Sesuai lapangan"                 -> harus ada remark "#0"; kalau belum, ditulis "#0".
  B. "Sudah direvisi" / "Akan direvisi" -> cek nilai vs range threshold:
        - nilai sudah dalam range & belum ada remark  -> tulis "#1"
        - nilai di luar range     & belum ada remark  -> perbaiki nilai + tulis "#1"
        - sudah ada remark (#0 / #1 / #DC)            -> dilewati

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
# Khusus kelompok "sudah/akan direvisi" (remark #1)
S_SUDAH_REMARK = "SUDAH_ADA_REMARK"    # sudah ada remark -> dilewati
S_REMARK1 = "REMARK1_DITAMBAH"         # nilai sudah dalam range, #1 ditulis
S_KOREKSI = "DIKOREKSI"                # nilai diperbaiki + #1 ditulis
S_PERLU_REMARK1 = "PERLU_REMARK1"      # (audit) nilai OK tapi belum ada remark
S_PERLU_KOREKSI = "PERLU_KOREKSI"      # (audit) nilai di luar range & belum ada remark
S_READBACK = "READBACK_MISMATCH"

# Kelompok tindak lanjut di Selancar
TL_SESUAI = ("sesuai_lapangan", "sesuai_lapangan_fasih_belum")   # -> #0
TL_REVISI = ("sudah_direvisi", "akan_direvisi")                  # -> #1 / koreksi
LABEL_TL = {
    "sesuai_lapangan": "Sesuai lapangan",
    "sesuai_lapangan_fasih_belum": "Sesuai Lapangan & Fasih Belum",
    "akan_direvisi": "Akan direvisi",
    "sudah_direvisi": "Sudah direvisi",
}

STATUS_FINAL = {S_ADA, S_DITAMBAH, S_SUDAH_REMARK, S_REMARK1, S_KOREKSI}
STATUS_ERROR_TEKNIS = {S_REMARK_GAGAL, S_SUBMIT_GAGAL, S_FASIH_ERROR, S_GAGAL, S_READBACK}


# ======================================================================
#  UTILITAS MURNI (mudah diuji tanpa browser)
# ======================================================================

# "#0" berdiri sendiri: bukan bagian dari "#01", "#00", "##0", "a#0" dst.
_RE_REMARK0 = re.compile(r'(?<![\w#])#0(?!\d)')


def ada_remark0(teks):
    """True jika teks catatan mengandung remark '#0' (bukan '#01' / '#0123')."""
    return bool(_RE_REMARK0.search(teks or ""))


_RE_REMARK1 = re.compile(r'(?<![\w#])#1(?!\d)')
_RE_DC = re.compile(r'(?<![A-Za-z])(?:#DC|DC[_\s]?0\d)', re.I)


def ada_remark1(teks):
    """True jika ada remark '#1' (bukan '#10' / '#123')."""
    return bool(_RE_REMARK1.search(teks or ""))


def ada_remark_apapun(teks):
    """True jika sudah ada remark apa pun dari bot/reviewer: #0, #1, atau #DC / DC_01."""
    t = teks or ""
    return bool(_RE_REMARK0.search(t) or _RE_REMARK1.search(t) or _RE_DC.search(t))


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
            w.writerow(["assignment_id", "nama_usaha", "pengisi_selancar", "tindak_lanjut", "status", "detail", "waktu"])
            for k, v in hasil.items():
                aid = k.split("|", 1)[0]
                w.writerow([aid, v.get("nama", ""), v.get("oleh", ""), v.get("tl", ""), v.get("status", ""),
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
        rasio: b.getAttribute('data-rasio') || '',
        meta: b.getAttribute('data-meta') || '',
        stat: s ? (s.value || s.getAttribute('data-prev') || '') : '',
        oleh: o ? (o.textContent || '').trim() : ''
    };
}).filter(x => x)"""

def sel_chip(tl=TL_TARGET):
    """Selector chip tindak lanjut di ringkasan kanan atas (mis. st-sesuai_lapangan, st-sudah_direvisi)."""
    return f'.tl-summary a.st-{tl}'


_SEL_CHIP = sel_chip()


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


def baca_info_tabel(page, tl=TL_TARGET):
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
            t = page.locator(sel_chip(tl) + ' .jml').first.inner_text()
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


def siapkan_selancar(page, tl=TL_TARGET):
    """
    Buka DC Terkena Flag dengan filter wajib lalu klik chip tindak lanjut `tl`
    (sesuai_lapangan / sudah_direvisi / akan_direvisi / sesuai_lapangan_fasih_belum).
    Mengembalikan dict info {total, per_page, url} atau None jika gagal / tidak ada baris.
    """
    from updater_nerwana import (
        NERWANA_BASE_URL, NERWANA_LANDING_URL,
        pastikan_login_selancar, deteksi_kabkota,
    )

    print("\n" + "=" * 65)
    print("   [CEK-#0] MENYIAPKAN SELANCAR - DC TERKENA FLAG")
    print("   Filter : Flag Rasio 3 | Semua Kategori | Kode 1 | Spesifik: Semua")
    print(f"   Chip   : Tindak lanjut = '{LABEL_TL.get(tl, tl)}' (milik siapa saja)")
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
    chip = page.locator(sel_chip(tl)).first
    if chip.count() == 0:
        print(f"[CEK-#0] Chip '{LABEL_TL.get(tl, tl)}' tidak ditemukan di halaman.")
        return None
    try:
        if int(re.sub(r'\D', '', chip.locator('.jml').first.inner_text()) or 0) == 0:
            print(f"[CEK-#0] Chip '{LABEL_TL.get(tl, tl)}' berisi 0 baris. Dilewati.")
            return None
    except Exception:
        pass
    cls = chip.get_attribute("class") or ""
    if "aktif" not in cls.split():
        print(f"[CEK-#0] Mengklik chip '{LABEL_TL.get(tl, tl)}'...")
        chip.scroll_into_view_if_needed()
        time.sleep(0.4)
        chip.click()
        try:
            page.wait_for_selector(sel_chip(tl) + '.aktif', timeout=30000)
        except Exception:
            print("[CEK-#0] Chip tidak berubah aktif setelah diklik.")
            return None
    n_baris = _tunggu_tabel(page)

    # 3) Verifikasi akhir
    salah = _filter_dropdown_ok(page)
    chip_aktif = page.locator(sel_chip(tl) + '.aktif').count() > 0
    if salah or not chip_aktif:
        print(f"[CEK-#0] Verifikasi filter gagal. Dropdown salah={salah} chip_aktif={chip_aktif}")
        return None

    info = baca_info_tabel(page, tl)
    info["url"] = page.url
    info["tl"] = tl
    print(f"[CEK-#0] Siap. Total '{LABEL_TL.get(tl, tl)}': {info['total']} baris "
          f"({info['per_page']}/halaman, baris di halaman ini: {n_baris})")
    if info["total"] == 0 and n_baris == 0:
        return None
    if info["total"] == 0:
        info["total"] = n_baris
    return info


siapkan_selancar_sesuai_lapangan = siapkan_selancar  # alias lama


def pindah_halaman(page, nomor, info):
    """Pindah ke halaman tabel ke-N dengan filter tetap (URL-based, deterministik)."""
    from updater_nerwana import pastikan_login_selancar
    tl = info.get("tl", TL_TARGET)
    page.goto(url_halaman(info["url"], nomor, tl=tl), timeout=45000)
    page.wait_for_load_state("domcontentloaded")
    pastikan_login_selancar(page)
    _tunggu_tabel(page)
    if page.locator(sel_chip(tl) + '.aktif').count() == 0:
        print(f"[CEK-#0] Peringatan: chip '{LABEL_TL.get(tl, tl)}' tidak aktif di halaman {nomor}.")
        return False
    return True


# ======================================================================
#  FASIH: baca / tulis catatan #0 di isian 27a / 31a
# ======================================================================

def baca_status_remark(ef, page, container, pola=ada_remark0):
    """
    Membuka dialog Catatan 27a/31a dan mencocokkan `pola` (fungsi teks -> bool).
    Mengembalikan (state, cuplikan): state = 'ADA' | 'TIDAK_ADA' | 'TIDAK_BISA_DIBUKA'
    """
    dialog = ef.buka_dialog_catatan_pendapatan(page, container)
    if not dialog:
        return "TIDAK_BISA_DIBUKA", ""
    teks = ""
    try:
        teks = dialog.inner_text() or ""
        if not pola(teks):
            time.sleep(0.8)  # riwayat catatan kadang dimuat terlambat
            teks = dialog.inner_text() or teks
    except Exception as e:
        print(f"[CEK-#0] Gagal membaca dialog catatan: {e}")
    finally:
        ef.tutup_modal_dialog(page)
    return ("ADA" if pola(teks) else "TIDAK_ADA"), re.sub(r'\s+', ' ', teks).strip()[:160]


def baca_status_remark0(ef, page, container):
    return baca_status_remark(ef, page, container, ada_remark0)


def tambah_remark(ef, page, container, kode=KODE_REMARK, max_retry=2):
    """Tulis `kode` ('#0' / '#1') di dialog Catatan 27a/31a lalu verifikasi benar-benar tersimpan."""
    pola = ada_remark0 if kode == "#0" else ada_remark1
    print(f"[CEK-#0] Menulis catatan '{kode}'...")
    for percobaan in range(1, max_retry + 1):
        dialog = ef.buka_dialog_catatan_pendapatan(page, container)
        if not dialog:
            print(f"[WARN] Percobaan {percobaan}/{max_retry}: dialog catatan tidak terbuka.")
            time.sleep(1)
            continue
        try:
            if pola(dialog.inner_text()):
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
                if pola(dialog.inner_text()):
                    print(f"[CEK-#0] Catatan '{kode}' TERVERIFIKASI tersimpan.")
                    ef.tutup_modal_dialog(page)
                    return True
                print(f"[WARN] Percobaan {percobaan}/{max_retry}: '{kode}' belum muncul setelah Simpan.")
        except Exception as e:
            print(f"[WARN] Error saat menulis catatan (percobaan {percobaan}): {e}")
        ef.tutup_modal_dialog(page)
        time.sleep(1)
    return False


def tambah_remark0(ef, page, container, kode=KODE_REMARK, max_retry=2):
    return tambah_remark(ef, page, container, kode, max_retry)


# Pertanyaan yang diperiksa remark-nya: seluruh isian pengeluaran & pendapatan usaha
#   blok 'biasa'      -> 26.a-f (pengeluaran) dan 27.a-c (pendapatan)
#   blok 'usaha_2026' -> 30.a-f (pengeluaran) dan 31.a-c (pendapatan)
_JS_TANDAI_CATATAN = r"""(nums) => {
  const reLabel = /^\s*(\d{2})\s*\.\s*([a-f])\s*\./i;
  const visible = el => !!(el && el.offsetParent !== null);
  const countLabels = root => {
    let c = 0; const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) { if (reLabel.test(n.textContent)) c++; }
    return c;
  };
  document.querySelectorAll('[data-cek0]').forEach(e => e.removeAttribute('data-cek0'));
  const out = []; const seen = new Set(); let k = 0;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) {
    const m = reLabel.exec(n.textContent);
    if (!m || !nums.includes(m[1])) continue;
    const el = n.parentElement;
    if (!visible(el)) continue;
    const label = m[1] + '.' + m[2];
    if (seen.has(label)) continue;
    seen.add(label);
    let p = el, btn = null;
    for (let i = 0; i < 8 && p; i++) {
      const bs = [...p.querySelectorAll('button[title*="Catatan"], button[aria-label*="Catatan"]')].filter(visible);
      if (bs.length) { if (bs.length === 1 && countLabels(p) === 1) btn = bs[0]; break; }
      p = p.parentElement;
    }
    if (btn) { btn.setAttribute('data-cek0', String(k)); out.push({label: label, idx: k}); k++; }
    else { out.push({label: label, idx: -1}); }
  }
  return out;
}"""


def _buka_dialog_dari_tombol(ef, page, btn):
    ef.tutup_modal_dialog(page)
    try:
        btn.scroll_into_view_if_needed()
        time.sleep(0.2)
        btn.click(timeout=3000)
    except Exception:
        try:
            page.evaluate("el => el.click()", btn.element_handle())
        except Exception:
            return None
    time.sleep(1.0)
    d = page.locator('div[role="dialog"]').last
    try:
        if d.count() > 0 and d.is_visible():
            return d
    except Exception:
        pass
    return None


def baca_status_remark_semua(ef, page, blok, pola):
    """
    Periksa catatan di SEMUA isian pengeluaran & pendapatan usaha (26/27 atau 30/31).
    Mengembalikan (state, keterangan): 'ADA' (berhenti di isian pertama yang cocok) |
    'TIDAK_ADA' | 'TIDAK_BISA_DIBUKA'.
    """
    nums = ["30", "31"] if blok == "usaha_2026" else (["26", "27"] if blok == "biasa" else ["26", "27", "30", "31"])
    try:
        items = page.evaluate(_JS_TANDAI_CATATAN, nums) or []
    except Exception as e:
        print(f"[CEK-#0] Gagal memindai isian catatan: {e}")
        return "TIDAK_BISA_DIBUKA", ""
    punya = [it for it in items if it["idx"] >= 0]
    if not punya:
        return "TIDAK_BISA_DIBUKA", ""
    terbuka = 0
    for it in punya:
        btn = page.locator(f'[data-cek0="{it["idx"]}"]').first
        d = _buka_dialog_dari_tombol(ef, page, btn)
        if not d:
            continue
        terbuka += 1
        teks = ""
        try:
            teks = d.inner_text() or ""
            if not pola(teks):
                time.sleep(0.5)
                teks = d.inner_text() or teks
        except Exception:
            pass
        ef.tutup_modal_dialog(page)
        if pola(teks):
            return "ADA", f"{it['label']}: " + re.sub(r'\s+', ' ', teks).strip()[:140]
    if terbuka * 2 < len(punya):
        return "TIDAK_BISA_DIBUKA", f"hanya {terbuka}/{len(punya)} dialog terbuka"
    return "TIDAK_ADA", f"{terbuka}/{len(punya)} isian dicek ({', '.join(i['label'] for i in punya)})"


def _buka_dan_cek(ef, page, nama, pola=ada_remark0):
    """Buka Blok II -> baca remark di semua isian 26/27 (atau 30/31). Mengembalikan (state, ket, container_tulis, blok, idx)."""
    ok, idx = ef.buka_blok_ii(page, nama)
    if not ok:
        raise Exception("Gagal membuka Blok II")
    blok = ef.deteksi_blok(page)
    container = ef.cari_container_isian_27a(page, idx=idx)   # tempat menulis remark: 27a / 31a
    if container is None:
        raise Exception(f"Container isian 27a/31a tidak ditemukan (blok '{blok}', idx #{idx})")
    state, ket = baca_status_remark_semua(ef, page, blok, pola)
    if state == "TIDAK_BISA_DIBUKA":
        state, ket = baca_status_remark(ef, page, container, pola)   # cadangan: 27a/31a saja
    print(f"[CEK-#0] Blok '{blok}' (#{idx}) | status remark: {state} {('| ' + ket) if ket else ''}")
    return state, ket, container, blok, idx


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


def proses_satu_baris(ef, context, selancar_page, r, mode, grup="sesuai"):
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

        if grup == "sesuai":
            return _proses_di_fasih(ef, fasih_page, aid, nama, mode)
        return _proses_koreksi_di_fasih(ef, fasih_page, r, mode)

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
        state, cuplik, container, blok, _idx = _buka_dan_cek(ef, page, nama)
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
        state, cuplik, container, blok, _idx = _buka_dan_cek(ef, page, nama)
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
#  KELOMPOK "SUDAH / AKAN DIREVISI": cek range nilai + remark #1
# ======================================================================

def _parse_meta(meta):
    """'Kategori R · KBLI 86102 - Aktivitas Puskesmas' -> ('R', '86102')."""
    kat = kbli = ""
    m = re.search(r'Kategori\s*([A-Z])', meta or "", re.I)
    if m:
        kat = m.group(1).upper()
    m = re.search(r'KBLI\s*([0-9A-Z]+)', meta or "", re.I)
    if m:
        kbli = m.group(1)
    return kat, kbli


def _evaluasi_dari_fasih(ef, page, r, blok, idx):
    """Baca nilai di FASIH lalu evaluasi terhadap threshold. Mengembalikan (hasil|None, data, error)."""
    from kalkulator_usulan import evaluasi
    data = ef.baca_nilai_fasih(page, blok=blok, idx=idx)
    if not data.get("ok"):
        return None, data, data.get("error", "Gagal membaca nilai FASIH")
    kat_meta, kbli_meta = _parse_meta(r.get("meta", ""))
    kat = data.get("kategori") or kat_meta
    kbli = data.get("kbli") or kbli_meta
    nilai = {
        "pbj": data["pbj"], "prod": data["prod"], "ops": data["ops"],
        "beli": data.get("beli", 0.0),
        "bulan_beroperasi": data.get("bulan_beroperasi", 1),
        "aset_tanah": data.get("aset_tanah", 0.0),
    }
    print(f"[CEK-#1] Kategori {kat} | KBLI {kbli} | PBJ {nilai['pbj']:,.0f} | Prod {nilai['prod']:,.0f} | Ops {nilai['ops']:,.0f}")
    # rasio_selancar=None: data Selancar untuk baris yang sudah direvisi bisa usang, nilai FASIH yang jadi acuan
    hasil = evaluasi(nilai=nilai, kategori=kat, kbli=kbli, blok=blok, rasio_selancar=None, multi_field=True)
    print(f"[CEK-#1] Evaluasi: {hasil.aksi} | {hasil.alasan}")
    return hasil, data, ""


def _isi_koreksi(ef, page, hasil, data):
    """Isi field utama + tambahan dengan readback. Mengembalikan (ok, pesan_error)."""
    def _isi(field, nilai_baru, nilai_lama):
        loc = data["field_locators"].get(field)
        if not loc or loc.count() == 0:
            c = page.locator(f'[id*="{field}"]:visible, [id*="pendapatan"]:visible').first
            loc = c.locator('input[type="text"]').first if c.count() > 0 else None
        if not loc or loc.count() == 0:
            return False, f"Input locator field '{field}' tidak ditemukan"
        ok, val = ef.isi_field_dengan_readback(page, loc, nilai_baru, nilai_lama=nilai_lama)
        if not ok:
            return False, f"Readback mismatch {field}: terbaca '{val}' != target '{nilai_baru:,.0f}'"
        return True, ""

    print(f"[CEK-#1] Koreksi '{hasil.field}': {hasil.nilai_lama:,.0f} -> {hasil.nilai_baru:,.0f}")
    ok, err = _isi(hasil.field, hasil.nilai_baru, hasil.nilai_lama)
    if not ok:
        return False, err
    for tb in (hasil.get("tambahan") or []):
        time.sleep(0.3)
        ok, err = _isi(tb["field"], tb["nilai_baru"], tb["nilai_lama"])
        if not ok:
            return False, err
    return True, ""


def _proses_koreksi_di_fasih(ef, page, r, mode):
    aid, nama = r["aid"], r["nama"]
    tertinggal = " (assignment mungkin masih dalam mode edit, cek manual di FASIH)"

    # --- Tahap A: baca TANPA mengubah assignment ---
    state, cuplik, hasil = "TIDAK_BISA_DIBUKA", "", None
    try:
        state, cuplik, container, blok, idx = _buka_dan_cek(ef, page, nama, ada_remark_apapun)
        if state != "TIDAK_BISA_DIBUKA":
            hasil, _data, err = _evaluasi_dari_fasih(ef, page, r, blok, idx)
            if hasil is None:
                print(f"[CEK-#1] Nilai belum terbaca di mode lihat: {err}")
    except Exception as e:
        print(f"[CEK-#1] Cek di mode lihat tidak berhasil ({e}). Akan dicoba di mode edit bila perlu.")

    if state == "ADA":
        extra = ""
        if hasil is not None and hasil.aksi == "APPLY":
            extra = " | catatan: menurut evaluasi nilai masih di luar range"
        return S_SUDAH_REMARK, f"Sudah ada remark ({cuplik[:80]}){extra}"

    if hasil is not None:
        catat_saja = bool(hasil.get("catat_saja"))
        if hasil.aksi == "NEED_REVIEW" or (hasil.aksi == "SKIP" and not catat_saja):
            return S_NEED_REVIEW, str(hasil.alasan)[:200]

    if mode == MODE_AUDIT:
        if hasil is None:
            return S_TAK_TERCEK, "Nilai/catatan tidak terbaca di mode lihat (perlu mode edit untuk memastikan)"
        if hasil.get("catat_saja"):
            return S_PERLU_REMARK1, f"Nilai sudah dalam range, belum ada remark -> perlu '#1'. {hasil.alasan}"[:220]
        return S_PERLU_KOREKSI, (f"Belum ada remark; nilai di luar range -> koreksi {hasil.field} "
                                 f"{hasil.nilai_lama:,.0f} -> {hasil.nilai_baru:,.0f} + '#1'")[:220]

    if mode == MODE_INTERAKTIF:
        rencana = "tulis '#1'" if (hasil is not None and hasil.get("catat_saja")) else "koreksi nilai + tulis '#1'"
        jawab = input(f"   >> '{nama}' (AID {aid}) belum ada remark. Revoke/edit & {rencana}? [y/n]: ").strip().lower()
        if jawab != "y":
            return S_DIBATALKAN, "Dibatalkan oleh pengguna"

    # --- Tahap B: mode edit ---
    ef.lakukan_revoke_dan_edit(page)
    time.sleep(0.5)
    try:
        state, cuplik, container, blok, idx = _buka_dan_cek(ef, page, nama, ada_remark_apapun)
    except Exception as e:
        return S_GAGAL, f"Gagal membuka isian setelah masuk mode edit: {e}{tertinggal}"
    if state == "TIDAK_BISA_DIBUKA":
        return S_REMARK_GAGAL, f"Dialog catatan tidak terbuka{tertinggal}"

    ditulis = False
    dikoreksi = False
    if state == "TIDAK_ADA":
        hasil, data, err = _evaluasi_dari_fasih(ef, page, r, blok, idx)
        if hasil is None:
            return S_NEED_REVIEW, f"Nilai FASIH tidak terbaca: {err}{tertinggal}"
        catat_saja = bool(hasil.get("catat_saja"))
        if hasil.aksi == "NEED_REVIEW" or (hasil.aksi == "SKIP" and not catat_saja):
            return S_NEED_REVIEW, f"{str(hasil.alasan)[:160]}{tertinggal}"
        if hasil.aksi == "APPLY":
            ok, err = _isi_koreksi(ef, page, hasil, data)
            if not ok:
                return S_READBACK, f"{err}{tertinggal}"
            dikoreksi = True
        if not tambah_remark(ef, page, container, "#1"):
            return S_REMARK_GAGAL, f"Gagal menyimpan '#1'{tertinggal}"
        ditulis = True

    ef.proses_halaman_catatan_dan_tampilkan_anomali(page)
    ok_submit, err_submit = ef.submit_assignment(page)
    awalan = ("nilai dikoreksi + '#1' ditulis, " if dikoreksi else "'#1' ditulis, ") if ditulis else ""
    if ok_submit:
        if dikoreksi:
            return S_KOREKSI, f"{hasil.field} {hasil.nilai_lama:,.0f} -> {hasil.nilai_baru:,.0f}, '#1' ditulis, dikirim ulang"
        if ditulis:
            return S_REMARK1, "Nilai sudah dalam range; '#1' ditulis, dikirim ulang"
        return S_SUDAH_REMARK, "Remark ternyata sudah ada (terlihat di mode edit); assignment dikirim ulang"
    if err_submit and "GALAT" in str(err_submit):
        return S_NEED_REVIEW, f"{awalan}submit ditolak: {err_submit}{tertinggal}"
    return S_SUBMIT_GAGAL, f"{awalan}{err_submit}{tertinggal}"


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
    print("   CEK ULANG BARIS TERISI DI SELANCAR (REMARK #0 / #1)")
    print("   Filter: Flag Rasio 3 | Semua Kategori | Kode 1 | Spesifik Semua")
    print("=" * 65)

    ef.cleanup_old_screenshots(max_keep=30)
    if not ef.start_debug_chrome():
        return

    print("\nPilih Cakupan:")
    print("  [1] Semua yang sudah diisi: 'Sesuai lapangan' (#0) + 'Sudah direvisi' (cek range, #1) [Default]")
    print("  [2] Hanya 'Sesuai lapangan'  -> pastikan ada #0")
    print("  [3] Hanya 'Sudah direvisi'   -> pastikan nilai dalam range & ada #1")
    print("      (status 'Akan direvisi' dilewati: sedang dikerjakan orang/komputer lain)")
    cakupan = input("Masukkan pilihan [1/2/3] (default 1): ").strip() or "1"
    grup_list = []
    if cakupan in ("1", "2"):
        grup_list += [(tl, "sesuai") for tl in TL_SESUAI]
    if cakupan in ("1", "3"):
        grup_list += [("sudah_direvisi", "revisi")]
    if not grup_list:
        grup_list = [(tl, "sesuai") for tl in TL_SESUAI] + [("sudah_direvisi", "revisi")]

    print("\nPilih Mode:")
    print("  [1] Audit  - hanya cek & catat, TIDAK mengubah apa pun di FASIH [Default]")
    print("  [2] Isi    - cek, perbaiki/tulis remark bila perlu, kirim ulang (sungguhan)")
    print("  [3] Interaktif - seperti [2] tapi tanya y/n sebelum mengubah tiap baris")
    pilih = input("Masukkan pilihan [1/2/3] (default 1): ").strip() or "1"
    mode = {"1": MODE_AUDIT, "2": MODE_ISI, "3": MODE_INTERAKTIF}.get(pilih, MODE_AUDIT)

    lim_str = input("\nBerapa baris maksimal diproses PER KELOMPOK (Sesuai lapangan / Sudah direvisi)? (angka, 0 = semua, default 10): ").strip() or "10"
    try:
        limit = max(0, int(lim_str))
    except ValueError:
        limit = 10

    lewati = (input("Lewati baris yang sudah selesai (ADA/DITAMBAH/SUDAH_ADA_REMARK/dst) di run sebelumnya? [y/n] (default y): ").strip().lower() != "n")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("\n[CDP] Menghubungkan ke browser Chrome (port 9222)...")
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        from updater_nerwana import NerwanaManager
        mgr = NerwanaManager(context, kategori="A")
        selancar_page = mgr.get_or_create_page()

        hasil = muat_hasil()
        st = {"stat": {}, "diproses": 0, "err": 0, "berhenti": False}
        sesi = set()

        for tl, grup in grup_list:
            if st["berhenti"]:
                break
            st["dg"] = 0  # batas baris berlaku PER kelompok, supaya kelompok berikutnya tetap jalan
            info = siapkan_selancar(selancar_page, tl)
            if not info:
                continue
            n_hal = max(1, math.ceil(info["total"] / max(1, info["per_page"])))
            print(f"[CEK-#0] [{LABEL_TL.get(tl, tl)}] {info['total']} baris / {n_hal} halaman | mode={mode} | limit={limit or 'semua'}")

            for hal in range(1, n_hal + 1):
                if st["berhenti"]:
                    break
                if limit and st["dg"] >= limit:
                    break
                if hal > 1 and not pindah_halaman(selancar_page, hal, info):
                    print("[CEK-#0] Halaman tidak sesuai filter, grup ini dihentikan.")
                    break

                baris = selancar_page.evaluate(_JS_BARIS) or []
                print(f"\n[CEK-#0] [{LABEL_TL.get(tl, tl)}] Halaman {hal}/{n_hal}: {len(baris)} baris")

                for r in baris:
                    if limit and st["dg"] >= limit:
                        print(f"[CEK-#0] Batas {limit} baris untuk kelompok '{LABEL_TL.get(tl, tl)}' tercapai. Lanjut kelompok berikutnya (jika ada).")
                        break
                    if r["stat"] != tl:
                        continue  # pengaman bila filter bocor
                    k = kunci_baris(r["aid"], r["nama"])
                    if k in sesi:
                        continue
                    sesi.add(k)
                    if lewati and hasil.get(k, {}).get("status") in STATUS_FINAL:
                        st["stat"]["DILEWATI(run lalu)"] = st["stat"].get("DILEWATI(run lalu)", 0) + 1
                        continue

                    st["diproses"] += 1
                    st["dg"] += 1
                    print(f"\n>>> [{st['dg']}{('/' + str(limit)) if limit else ''}] [{LABEL_TL.get(tl, tl)}] '{r['nama']}' | AID {r['aid']} | pengisi: {r['oleh'] or '-'}")
                    status, detail = proses_satu_baris(ef, context, selancar_page, r, mode, grup=grup)
                    print(f"    => {status}: {detail}")

                    hasil[k] = {
                        "nama": r["nama"], "oleh": r["oleh"], "tl": tl, "status": status,
                        "detail": detail, "waktu": datetime.now().isoformat(timespec="seconds"),
                    }
                    simpan_hasil(hasil)
                    lbl = f"{LABEL_TL.get(tl, tl)[:12]}:{status}"
                    st["stat"][lbl] = st["stat"].get(lbl, 0) + 1

                    if status == S_WAF:
                        print("[WAF] Akses terblokir. Berhenti dulu, coba lagi nanti.")
                        st["berhenti"] = True
                        break
                    if status == S_SSO:
                        print("[SSO] Perlu login SSO manual di Chrome. Berhenti.")
                        st["berhenti"] = True
                        break
                    if status in STATUS_ERROR_TEKNIS:
                        st["err"] += 1
                        if st["err"] >= MAX_ERR_BERTURUT:
                            print(f"[STOP-LOSS] {st['err']} error teknis berturut-turut. Berhenti untuk keamanan.")
                            st["berhenti"] = True
                            break
                    else:
                        st["err"] = 0

                    time.sleep(random.uniform(JEDA_ANTAR_ASSIGNMENT_MIN, JEDA_ANTAR_ASSIGNMENT_MAX))

        tulis_csv(hasil)
        print("\n" + "=" * 65)
        print("RINGKASAN CEK REMARK #0 / #1:")
        print(f"Mode                : {mode}")
        print(f"Baris diproses      : {st['diproses']}")
        for k_s in sorted(st["stat"]):
            print(f"  {k_s:<38}: {st['stat'][k_s]}")
        print(f"Detail per baris    : {HASIL_JSON}")
        print(f"                      {HASIL_CSV}")
        print("=" * 65)


if __name__ == "__main__":
    main_cek_remark0()
