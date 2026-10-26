import time
import urllib.parse
import re
import os
import random
from database import get_connection, log_audit, upsert_kasus
from config import STATUS_FINAL

NERWANA_BASE_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/dc-terkena-flag"
NERWANA_LANDING_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/landing"
NERWANA_LOGIN_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/login"
NERWANA_UPDATE_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/dc-terkena-flag/tindak-lanjut"

def get_sso_credentials():
    """Membaca kredensial SSO dari file sso di direktori proyek."""
    folder = os.path.dirname(os.path.abspath(__file__))
    sso_path = next((os.path.join(folder, n) for n in ("sso", ".sso", "sso.txt")
                     if os.path.exists(os.path.join(folder, n))), os.path.join(folder, "sso"))
    if os.path.exists(sso_path):
        u, p = "", ""
        with open(sso_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if "user" in k or "uname" in k:
                        u = v
                    elif "pass" in k:
                        p = v
        if u and p:
            return u, p
    return None, None

SSO_LOGIN_COUNT = 0
SSO_LOGIN_GAGAL = 0   # login SSO berturut-turut yang tidak berhasil keluar dari halaman SSO

KABKOTA_AKTIF = None

def deteksi_kabkota(page):
    """
    Wilayah (kabkota) mengikuti AKUN yang login, bukan angka tetap.
    Urutan: parameter URL -> input/select/link di halaman Selancar -> cache terakhir -> None
    (None = parameter kabkota tidak dikirim, server memakai wilayah default akun).
    """
    global KABKOTA_AKTIF
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query).get('kabkota')
        if q and q[0]:
            KABKOTA_AKTIF = q[0]
            return KABKOTA_AKTIF
    except Exception:
        pass
    try:
        v = page.evaluate("""() => {
            const el = document.querySelector('input[name="kabkota"], select[name="kabkota"]');
            if (el && el.value) return el.value;
            const hrefs = [...document.querySelectorAll('a[href*="kabkota="]')].map(a => a.href);
            for (const h of hrefs) { const m = h.match(/kabkota=([0-9]+)/); if (m) return m[1]; }
            return null;
        }""")
        if v:
            KABKOTA_AKTIF = str(v)
    except Exception:
        pass
    return KABKOTA_AKTIF


def pastikan_login_selancar(page):
    """
    Memastikan halaman Selancar login penuh.
    Jika mental ke halaman login Selancar atau SSO BPS, melakukan login otomatis (maksimal 1 kali per sesi).
    """
    global SSO_LOGIN_COUNT, SSO_LOGIN_GAGAL
    for loop in range(3):
        url = page.url.lower()

        # 1. Jika di SSO BPS
        if "sso.bps.go.id" in url or page.locator('#kc-login, button:has-text("Log In")').count() > 0:
            if SSO_LOGIN_GAGAL >= 2:
                print("\n" + "!" * 65)
                print("[SSO ERROR] Login SSO otomatis gagal 2x berturut-turut (cek username/password di file sso).")
                print("Silakan lakukan login SSO secara manual di browser Chrome terlebih dahulu.")
                print("!" * 65 + "\n")
                raise Exception("SSO_MANUAL_LOGIN_REQUIRED")

            print("[SELANCAR-SSO] Terdeteksi halaman login SSO BPS...")
            uname, pwd = get_sso_credentials()
            if not uname or not pwd:
                raise Exception("SSO_CREDENTIALS_MISSING")
            
            page.keyboard.press("Escape")
            time.sleep(0.5)

            inp_user = page.locator('#username, input[name="username"], input[type="text"]').first
            inp_pass = page.locator('#password, input[name="password"], input[type="password"]').first

            if inp_user.count() > 0:
                inp_user.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(uname, delay=random.randint(60, 120))
                time.sleep(0.3)

            if inp_pass.count() > 0:
                inp_pass.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(pwd, delay=random.randint(60, 120))
                time.sleep(0.5)

            time.sleep(random.uniform(1.2, 1.8))
            print("[SELANCAR-SSO] Mengklik tombol Log In di SSO...")
            btn_login = page.locator('#kc-login, button:has-text("Log In"), input[type="submit"]').first
            btn_login.click()
            SSO_LOGIN_COUNT += 1

            print("[SELANCAR-SSO] Menunggu redirect kembali ke Selancar...")
            try:
                page.wait_for_url(lambda u: "sso.bps.go.id" not in u.lower(), timeout=30000)
                SSO_LOGIN_GAGAL = 0
            except Exception:
                SSO_LOGIN_GAGAL += 1
            time.sleep(3)
            continue

        # 2. Jika di Halaman Login Selancar Nerwana ("Login dengan SSO BPS")
        btn_sso_nerwana = page.locator('button:has-text("Login dengan SSO BPS"), a:has-text("Login dengan SSO BPS")')
        if "login" in url or (btn_sso_nerwana.count() > 0 and btn_sso_nerwana.first.is_visible()):
            time.sleep(random.uniform(1.2, 2.0))
            print("[SELANCAR] Terdeteksi halaman login Selancar. Mengklik 'Login dengan SSO BPS'...")
            btn_sso_nerwana.first.click()
            try:
                page.wait_for_url(lambda u: "login" not in u.lower() or "sso.bps.go.id" in u.lower(), timeout=15000)
            except Exception:
                pass
            time.sleep(2)
            continue

        # 3. Sudah masuk ke halaman Selancar
        if "selancar2026" in url and "login" not in url:
            return True

        time.sleep(2)

    return "selancar2026" in page.url.lower() and "login" not in page.url.lower()

def verifikasi_dan_set_dropdown_selancar(page, kat, flag="rasio_3", kode="1", filter_spesifik="none"):
    """
    Memastikan semua filter di halaman DC Terkena Flag sesuai:
    1. Kategori: pilihan pengguna (A, G, C, dll)
    2. Flag: Flag Rasio 3 (rasio_3)
    3. Kode: 1
    4. Spesifik: Semua (tanpa filter spesifik / none)
    Mengembalikan True jika ada dropdown yang diubah di UI.
    """
    changed = False

    # 1. Dropdown Kategori
    try:
        select_kat = page.locator('#filter_kategori, select[name="kategori"]').first
        if select_kat.count() > 0 and select_kat.is_visible():
            current_kat = (select_kat.input_value() or "").strip().upper()
            if current_kat != kat.upper():
                print(f"[SELANCAR] Memilih 'Kategori {kat}' pada dropdown...")
                select_kat.select_option(kat)
                changed = True
                time.sleep(0.5)
    except Exception as e_kat:
        print(f"[SELANCAR-INFO] Dropdown kategori: {e_kat}")

    # 2. Dropdown Flag (Flag 3 / rasio_3)
    try:
        select_flag = page.locator('#filter_flag, select[name="flag"]').first
        if select_flag.count() == 0:
            select_flag = page.locator('select:has(option[value="rasio_3"])').first
        if select_flag.count() > 0 and select_flag.is_visible():
            current_flag = (select_flag.input_value() or "").strip()
            if current_flag != flag:
                print(f"[SELANCAR] Memilih Flag 'Flag Rasio 3' (value: {flag}) pada dropdown...")
                try:
                    select_flag.select_option(value=flag)
                except Exception:
                    select_flag.select_option(label=re.compile(r'Rasio\s*3', re.I))
                changed = True
                time.sleep(0.5)
    except Exception as e_flag:
        print(f"[SELANCAR-INFO] Dropdown flag: {e_flag}")

    # 3. Dropdown Kode
    try:
        select_kode = page.locator('#filter_kode, select[name="kode"]').first
        if select_kode.count() > 0 and select_kode.is_visible():
            current_kode = (select_kode.input_value() or "").strip()
            if current_kode != kode:
                print(f"[SELANCAR] Memilih Kode '{kode}' pada dropdown...")
                select_kode.select_option(value=kode)
                changed = True
                time.sleep(0.5)
    except Exception as e_kode:
        print(f"[SELANCAR-INFO] Dropdown kode: {e_kode}")

    # 4. Dropdown Spesifik (Semua tanpa filter spesifik / none)
    try:
        select_spesifik = page.locator('#filter_spesifik, select[name="filter_spesifik"], select[name="spesifik"]').first
        if select_spesifik.count() == 0:
            select_spesifik = page.locator('select:has(option[value="none"])').first
        if select_spesifik.count() > 0 and select_spesifik.is_visible():
            current_spesifik = (select_spesifik.input_value() or "").strip()
            if current_spesifik != filter_spesifik:
                print(f"[SELANCAR] Memilih Spesifik 'Semua (tanpa filter spesifik)' (value: {filter_spesifik}) pada dropdown...")
                try:
                    select_spesifik.select_option(value=filter_spesifik)
                except Exception:
                    select_spesifik.select_option(label=re.compile(r'Semua\s*\(tanpa\s*filter', re.I))
                changed = True
                time.sleep(0.5)
    except Exception as e_spes:
        print(f"[SELANCAR-INFO] Dropdown spesifik: {e_spes}")

    return changed

def buka_dan_siapkan_selancar(page, kategori="G"):
    """
    Menyiapkan halaman Selancar DC Terkena Flag:
    1. Pastikan sesi login aktif (SSO BPS / Selancar).
    2. Terapkan filter wajib untuk semua DC:
       - Flag            : Flag Rasio 3 (rasio_3, kode 1)
       - Filter Spesifik : Semua (tanpa filter spesifik / none)
       - Kategori        : Sesuai pilihan pengguna (A, G, C, dll)
    3. Tunggu tabel data dimuat penuh.
    """
    kat = (kategori or "G").upper().strip()
    print("\n" + "=" * 65)
    print(f"   MENYIAPKAN HALAMAN SELANCAR DC TERKENA FLAG (KATEGORI {kat})")
    print(f"   [FILTER OTOMATIS] Flag: Flag Rasio 3 | Spesifik: Semua (tanpa filter)")
    print("=" * 65)

    # 1. Pastikan di domain Selancar & login
    url = page.url.lower()
    if "selancar2026" not in url:
        print("[SELANCAR] Mengarahkan ke Landing Page Selancar...")
        try:
            page.goto(NERWANA_LANDING_URL, timeout=45000)
            page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            print(f"[INFO] Navigasi landing: {e}")

    pastikan_login_selancar(page)
    time.sleep(1)

    # 2. Periksa apakah URL saat ini sudah berada di dc-terkena-flag dengan filter yang tepat
    parsed = urllib.parse.urlparse(page.url)
    params = urllib.parse.parse_qs(parsed.query)
    kabkota = (deteksi_kabkota(page) or '')

    is_correct_filter = (
        "dc-terkena-flag" in parsed.path.lower() and
        params.get("kategori", [""])[0].upper() == kat and
        params.get("flag", [""])[0] == "rasio_3" and
        params.get("kode", [""])[0] == "1" and
        params.get("filter_spesifik", [""])[0] in ["none", ""]
    )

    if not is_correct_filter:
        target_url = f"{NERWANA_BASE_URL}?sort=nilai_tambah&dir=asc{('&kabkota=' + kabkota) if kabkota else ''}&kategori={kat}&flag=rasio_3&kode=1&filter_spesifik=none&cari=&per_page=50"
        print(f"[SELANCAR] Mengarahkan ke URL filter DC:")
        print(f"          -> Kategori : {kat}")
        print(f"          -> Flag     : Flag Rasio 3 (rasio_3, kode=1)")
        print(f"          -> Spesifik : Semua (tanpa filter spesifik / none)")
        try:
            page.goto(target_url, timeout=45000)
            page.wait_for_load_state("domcontentloaded")
        except Exception as e_nav:
            print(f"[INFO] Navigasi URL filter: {e_nav}")
        pastikan_login_selancar(page)
        time.sleep(1)

    # 3. Sinkronkan dan verifikasi dropdown di UI
    changed = verifikasi_dan_set_dropdown_selancar(page, kat, flag="rasio_3", kode="1", filter_spesifik="none")
    if changed:
        time.sleep(1.5)

    # 4. Tunggu tabel dimuat
    print(f"[SELANCAR] Menunggu tabel data Kategori {kat} (Flag 3, Semua Spesifik) dimuat...")
    try:
        page.wait_for_selector('#tableEvalProfil tbody tr', timeout=30000)
        try:
            page.locator('#loading-overlay').wait_for(state="hidden", timeout=15000)
        except Exception:
            pass
        n_baris = page.locator('#tableEvalProfil tbody tr').count()
        print(f"[SELANCAR] Tabel Kategori {kat} siap | wilayah(kabkota)={deteksi_kabkota(page) or 'default akun'} | baris di halaman ini={n_baris}")
        return True
    except Exception as e_wait:
        print(f"[SELANCAR-WARN] Menunggu tabel: {e_wait}")
        print(f"[SELANCAR-WARN] Wilayah(kabkota) terdeteksi: {deteksi_kabkota(page) or 'TIDAK TERDETEKSI'} | URL: {page.url}")
        return False

def refresh_selancar_realtime(page, kategori="G"):
    """
    Me-refresh halaman Selancar secara real-time agar sinkron dengan perubahan dari komputer lain.
    Memastikan tabel selesai dimuat dan kategori, Flag (rasio_3), serta Spesifik (none) tetap sesuai.
    """
    kat = (kategori or "G").upper().strip()
    try:
        print(f"[SELANCAR-SYNC] Merefresh halaman Selancar (Kategori {kat}, Flag 3) secara real-time...")
        
        parsed = urllib.parse.urlparse(page.url)
        params = urllib.parse.parse_qs(parsed.query)
        kabkota = (deteksi_kabkota(page) or '')

        is_correct_filter = (
            "dc-terkena-flag" in parsed.path.lower() and
            params.get("kategori", [""])[0].upper() == kat and
            params.get("flag", [""])[0] == "rasio_3" and
            params.get("kode", [""])[0] == "1" and
            params.get("filter_spesifik", [""])[0] in ["none", ""]
        )

        if not is_correct_filter:
            target_url = f"{NERWANA_BASE_URL}?sort=nilai_tambah&dir=asc{('&kabkota=' + kabkota) if kabkota else ''}&kategori={kat}&flag=rasio_3&kode=1&filter_spesifik=none&cari=&per_page=50"
            page.goto(target_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
        else:
            page.reload(wait_until="domcontentloaded", timeout=25000)

        # Verifikasi dropdown
        verifikasi_dan_set_dropdown_selancar(page, kat, flag="rasio_3", kode="1", filter_spesifik="none")

        page.wait_for_selector('#tableEvalProfil tbody tr', timeout=20000)
        try:
            page.locator('#loading-overlay').wait_for(state="hidden", timeout=10000)
        except Exception:
            pass
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"[SELANCAR-WARN] Gagal refresh real-time: {e}")
        return False

def to_float(val, default=0.0):
    try:
        if val is None:
            return default
        s = str(val).replace(',', '').strip()
        return float(s) if s else default
    except Exception:
        return default

# Satu kali evaluate membaca SEMUA baris tabel (jauh lebih cepat daripada ratusan panggilan locator)
_JS_BACA_BARIS = """() => Array.from(document.querySelectorAll('#tableEvalProfil tbody tr')).map((tr, i) => {
    const b = tr.querySelector('.dc-sim-btn');
    if (!b) return null;
    const s = tr.querySelector('select.dc-tl-select');
    return {
        i: i,
        aid: b.getAttribute('data-aid') || '',
        nama: b.getAttribute('data-nama') || '',
        link: b.getAttribute('data-link') || '',
        rasio: b.getAttribute('data-rasio') || '',
        meta: b.getAttribute('data-meta') || '',
        stat: s ? (s.value || s.getAttribute('data-prev') || '') : '',
        terkunci: s ? s.getAttribute('data-terkunci') === '1' : false,
        kunci: s ? (s.getAttribute('data-kunci') || '') : ''
    };
}).filter(x => x)"""


def cari_target_di_tabel_selancar(page, conn, session_skip_aids=None, kategori="G", diag=None):
    """
    Mencari baris pertama di tabel Selancar yang masih bisa dikerjakan:
    - bukan 'sudah_direvisi' / 'akan_direvisi' / terkunci user lain,
    - belum dicoba di sesi ini, belum final di DB lokal, dan belum berkali-kali gagal dibuka.
    Nilai kuesioner TIDAK dihitung di sini: Selancar hanya antrean, nilai dibaca langsung dari FASIH.
    diag (dict) diisi alasan baris dilewati / error baca tabel untuk ringkasan.
    """
    kat = (kategori or "G").upper().strip()
    if session_skip_aids is None:
        session_skip_aids = set()
    if diag is None:
        diag = {}

    def _hitung(k):
        diag[k] = diag.get(k, 0) + 1

    try:
        # Sesi habis / dilempar ke login -> ini BUKAN "tabel kosong"
        u_now = page.url.lower()
        if "sso.bps.go.id" in u_now or "/login" in u_now:
            diag['error'] = "SESI_LOGIN: halaman Selancar/SSO meminta login ulang"
            return None

        try:
            page.wait_for_selector('#tableEvalProfil tbody tr', timeout=15000)
        except Exception as e_wait:
            try:
                kosong = page.locator('text="Tidak ada data"').count() > 0
            except Exception:
                kosong = False
            if kosong:
                diag['tabel_kosong'] = True
                return None
            diag['error'] = f"TABEL_TIDAK_MUNCUL: {str(e_wait)[:120]}"
            return None

        rows = page.evaluate(_JS_BACA_BARIS) or []
        _hitung('hal_dibaca')
        if len(rows) > 1:
            kepala = rows[:8]
            random.shuffle(kepala)   # beberapa akun jalan bersamaan: kurangi rebutan baris yang sama
            rows = kepala + rows[8:]

        for r in rows:
            aid = r['aid']
            nama = r['nama']
            if not aid:
                continue
            _hitung('baris_total')

            if aid in session_skip_aids:
                _hitung('skip_sesi_ini')
                continue

            stat = r['stat']
            if stat in ["sudah_direvisi", "akan_direvisi"] or r['terkunci']:
                if r['terkunci']:
                    _hitung('terkunci_user_lain')
                elif stat == "akan_direvisi":
                    _hitung('akan_direvisi_di_selancar')
                else:
                    _hitung('sudah_direvisi_di_selancar')
                session_skip_aids.add(aid)
                continue

            # Baris yang berulang kali tidak bisa dibuka di akun/komputer ini: jangan dicoba terus di tiap run
            try:
                n_gagal = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE assignment_id = ? "
                    "AND action IN ('FASIH_ERROR','EXECUTION_FAILED','FASIH_FORBIDDEN') "
                    "AND timestamp >= datetime('now','-1 day')", (aid,)
                ).fetchone()[0]
            except Exception:
                n_gagal = 0
            if n_gagal >= 2:
                _hitung('gagal_dibuka_2x_dalam_24jam')
                session_skip_aids.add(aid)
                continue

            existing = None
            if nama:
                existing = conn.execute(
                    "SELECT * FROM kasus_nerwana WHERE assignment_id = ? AND nama_usaha = ?",
                    (aid, nama)
                ).fetchone()
            if not existing:
                existing = conn.execute(
                    "SELECT * FROM kasus_nerwana WHERE assignment_id = ?",
                    (aid,)
                ).fetchone()

            db_row = None
            if existing:
                ex_stat = existing['status']
                if ex_stat in STATUS_FINAL or ex_stat == 'SUBMITTED':
                    _hitung(f'final_di_db_{ex_stat}')
                    session_skip_aids.add(aid)
                    continue
                if ex_stat == 'APPROVED' and existing['nilai_baru_pbj'] is not None:
                    db_row = dict(existing)

            if not db_row:
                kbli = ""
                deskripsi_kbli = ""
                m = re.search(r'KBLI\s*([0-9A-Z]+)\s*-\s*(.+)', r['meta'], re.I)
                if m:
                    kbli = m.group(1).strip()
                    deskripsi_kbli = m.group(2).strip()
                else:
                    kbli = r['meta'].strip()
                db_row = {
                    'assignment_id': aid,
                    'nama_usaha': nama,
                    'kabkota': KABKOTA_AKTIF or '',
                    'kategori': kat,
                    'kbli': kbli,
                    'deskripsi_kbli': deskripsi_kbli,
                    'link_fasih': r['link'],
                    'rasio_selancar': to_float(r['rasio']),
                    'tindak_lanjut': stat,
                    'data_kunci': r['kunci'],
                    'status': 'PENDING',
                }

            tr = page.locator('#tableEvalProfil tbody tr').nth(r['i'])
            link_btn = tr.locator('a.dc-link-btn').first
            if link_btn.count() == 0:
                link_btn = tr.locator('a[href*="assignment"]').first

            return {
                'tr': tr,
                'link_btn': link_btn,
                'tl_select': tr.locator('select.dc-tl-select').first,
                'aid': aid,
                'nama': nama,
                'stat': stat,
                'data_kunci': r['kunci'],
                'db_row': db_row,
                'rasio_selancar': db_row.get('rasio_selancar', to_float(r['rasio'])),
            }
    except Exception as e:
        diag['error'] = f"EXCEPTION: {str(e)[:150]}"
        print(f"[SELANCAR-ERROR] Gagal membaca baris tabel: {e}")
    return None


def ringkas_diag(diag):
    """Ringkasan alasan baris dilewati, untuk dicetak saat bot menyimpulkan 'habis'."""
    if not diag:
        return "(tidak ada data diagnosa)"
    kunci = [k for k in diag if k not in ('error', 'tabel_kosong', 'hal_dibaca')]
    bagian = [f"{k}={diag[k]}" for k in sorted(kunci)]
    hal = diag.get('hal_dibaca', 0)
    return f"halaman dibaca={hal} | " + (", ".join(bagian) if bagian else "tidak ada baris terbaca")


def pulihkan_selancar(page, kategori="G"):
    """
    Pemulihan setelah gagal baca tabel: cek login ulang (SSO), buka ulang URL filter
    dari halaman 1, set dropdown, tunggu tabel. Mengembalikan True jika tabel siap.
    """
    kat = (kategori or "G").upper().strip()
    try:
        try:
            pastikan_login_selancar(page)
        except Exception as e_login:
            print(f"[PULIH] Login ulang bermasalah: {e_login}")
            if "SSO_MANUAL_LOGIN_REQUIRED" in str(e_login):
                raise
        parsed = urllib.parse.urlparse(page.url)
        params = urllib.parse.parse_qs(parsed.query)
        kabkota = (deteksi_kabkota(page) or '')
        target_url = (f"{NERWANA_BASE_URL}?sort=nilai_tambah&dir=asc{('&kabkota=' + kabkota) if kabkota else ''}&kategori={kat}"
                      f"&flag=rasio_3&kode=1&filter_spesifik=none&cari=&per_page=50")
        page.goto(target_url, timeout=45000)
        page.wait_for_load_state("domcontentloaded")
        pastikan_login_selancar(page)
        verifikasi_dan_set_dropdown_selancar(page, kat, flag="rasio_3", kode="1", filter_spesifik="none")
        page.wait_for_selector('#tableEvalProfil tbody tr', timeout=30000)
        try:
            page.locator('#loading-overlay').wait_for(state="hidden", timeout=10000)
        except Exception:
            pass
        time.sleep(1)
        return True
    except Exception as e:
        if "SSO_MANUAL_LOGIN_REQUIRED" in str(e):
            raise
        print(f"[PULIH] Gagal memulihkan Selancar: {e}")
        return False

def cari_target_verifikasi_di_tabel_selancar(page, conn, pengisi="Farid Akbar Arifandi", session_skip_aids=None, kategori="A"):
    """
    Memeriksa baris pada tabel Selancar yang SUDAH direvisi oleh pengisi tertentu (Farid Akbar Arifandi).
    Digunakan untuk menu verifikasi ulang remark dan kesesuaian nilai di FASIH.
    """
    kat = (kategori or "A").upper().strip()
    if session_skip_aids is None:
        session_skip_aids = set()

    try:
        page.wait_for_selector('#tableEvalProfil tbody tr', timeout=15000)
        rows = page.locator('#tableEvalProfil tbody tr').all()
        for tr in rows:
            sim_btn = tr.locator('.dc-sim-btn').first
            if sim_btn.count() == 0:
                continue
            aid = sim_btn.get_attribute("data-aid")
            nama = sim_btn.get_attribute("data-nama") or ""
            if not aid:
                continue

            if aid in session_skip_aids:
                continue

            tl_select = tr.locator('select.dc-tl-select').first
            stat = tl_select.input_value() or tl_select.get_attribute("data-prev") or ""

            # Cari elemen teks pengisi tindak lanjut
            box = tl_select.locator('..')
            oleh_text = ""
            if box.locator('.dc-tl-oleh').count() > 0:
                oleh_text = box.locator('.dc-tl-oleh').first.inner_text().strip()
            elif tr.locator('.dc-tl-oleh').count() > 0:
                oleh_text = tr.locator('.dc-tl-oleh').first.inner_text().strip()

            title_info = tl_select.get_attribute("title") or ""
            gabungan_pengisi = f"{oleh_text} {title_info}".lower()

            # Hanya ambil yang cocok dengan nama pengisi (Farid Akbar Arifandi)
            if pengisi.lower() not in gabungan_pengisi:
                continue

            # Periksa DB lokal jika ada
            existing = None
            if aid and nama:
                existing = conn.execute(
                    "SELECT * FROM kasus_nerwana WHERE assignment_id = ? AND nama_usaha = ?",
                    (aid, nama)
                ).fetchone()
            if not existing and aid:
                existing = conn.execute(
                    "SELECT * FROM kasus_nerwana WHERE assignment_id = ?",
                    (aid,)
                ).fetchone()

            db_row = None
            if existing:
                db_row = dict(existing)
            else:
                link_fasih = sim_btn.get_attribute("data-link") or ""
                rasio_selancar = to_float(sim_btn.get_attribute("data-rasio"))
                meta_text = sim_btn.get_attribute("data-meta") or ""
                data_kunci = tl_select.get_attribute("data-kunci") or ""

                kbli = ""
                deskripsi_kbli = ""
                m = re.search(r'KBLI\s*([0-9A-Z]+)\s*-\s*(.+)', meta_text, re.I)
                if m:
                    kbli = m.group(1).strip()
                    deskripsi_kbli = m.group(2).strip()
                else:
                    kbli = meta_text.strip()

                db_row = {
                    'assignment_id': aid,
                    'nama_usaha': nama,
                    'kabkota': KABKOTA_AKTIF or '',
                    'kategori': kat,
                    'kbli': kbli,
                    'deskripsi_kbli': deskripsi_kbli,
                    'link_fasih': link_fasih,
                    'rasio_selancar': rasio_selancar,
                    'tindak_lanjut': stat,
                    'tindak_lanjut_oleh': oleh_text or pengisi,
                    'data_kunci': data_kunci,
                    'status': 'PENDING',
                }

            link_btn = tr.locator('a.dc-link-btn').first
            if link_btn.count() == 0:
                link_btn = tr.locator('a[href*="assignment"]').first

            return {
                'tr': tr,
                'link_btn': link_btn,
                'tl_select': tl_select,
                'aid': aid,
                'nama': nama,
                'stat': stat,
                'oleh': oleh_text,
                'data_kunci': tl_select.get_attribute("data-kunci") or "",
                'db_row': db_row,
                'rasio_selancar': db_row.get('rasio_selancar', to_float(sim_btn.get_attribute("data-rasio"))),
            }
    except Exception as e:
        print(f"[SELANCAR-ERROR] Gagal membaca baris verifikasi tabel: {e}")
    return None

def lanjut_halaman_berikutnya_selancar(page):
    """Mengecek tombol pagination berikutnya dan mengkliknya jika ada."""
    try:
        selector = (
            '.ep-pager .pages a[title="Berikutnya"], '
            '.ep-pager .pages a:has(.fa-chevron-right), '
            '.pagination li:not(.disabled) a:has-text("›"), '
            '.pagination li:not(.disabled) a:has-text(">"), '
            'a[rel="next"]'
        )
        btn_next = page.locator(selector).first
        if btn_next.count() > 0 and btn_next.is_visible():
            print("[SELANCAR] Berpindah ke halaman tabel berikutnya...")
            btn_next.click()
            page.wait_for_selector('#tableEvalProfil tbody tr', timeout=30000)
            try:
                page.locator('#loading-overlay').wait_for(state="hidden", timeout=10000)
            except Exception:
                pass
            time.sleep(0.8)
            return True
    except Exception as e:
        print(f"[SELANCAR-WARN] Gagal pindah halaman: {e}")
    return False

def set_tindak_lanjut_selancar(target_info, nerwana_updater=None, status="akan_direvisi"):
    """
    Mengubah status tindak lanjut di Selancar Nerwana:
    - status: 'akan_direvisi', 'sudah_direvisi', atau '' (belum)
    - Pertama mencoba via dropdown UI (select_option) agar trigger event asli halaman.
    - Kedua memastikan via AJAX API POST jika UI dropdown terkendala.
    """
    if not target_info:
        return False

    tl_select = target_info.get('tl_select')
    data_kunci = target_info.get('data_kunci')
    aid = target_info.get('aid')
    nama = target_info.get('nama')

    updated = False
    label_status = "Akan direvisi" if status == "akan_direvisi" else ("Sudah direvisi" if status == "sudah_direvisi" else "Belum")

    if tl_select:
        try:
            tl_select.scroll_into_view_if_needed()
            time.sleep(0.3)
            tl_select.select_option(status)
            updated = True
            time.sleep(0.8)
            print(f"[SELANCAR] Dropdown tindak lanjut berhasil diubah menjadi '{label_status}' via UI.")
        except Exception as e_ui:
            print(f"[INFO] Ubah dropdown UI terkendala: {e_ui}")

    if not updated and nerwana_updater and data_kunci:
        try:
            print(f"[SELANCAR] Mengubah status tindak lanjut menjadi '{label_status}' via AJAX API...")
            ok = nerwana_updater.update_tindak_lanjut(
                data_kunci=data_kunci,
                status=status,
                assignment_id=aid,
                nama_usaha=nama
            )
            updated = ok
        except Exception as e_api:
            print(f"[WARN] AJAX API tindak lanjut gagal: {e_api}")

    return updated

class NerwanaManager:
    def __init__(self, browser_context, kategori="G"):
        self.context = browser_context
        self.kategori = (kategori or "G").upper().strip()
        self.page = None
        self.csrf_token = None

    def get_or_create_page(self):
        """Mendapatkan tab Nerwana yang masih aktif atau membuat baru jika belum ada."""
        if self.page:
            try:
                if self.page.is_closed():
                    self.page = None
            except Exception:
                self.page = None

        if not self.page:
            for p in self.context.pages:
                try:
                    if not p.is_closed() and "nerwana-aceh.web.bps.go.id" in p.url:
                        self.page = p
                        return self.page
                except Exception:
                    pass

        if not self.page or self.page.is_closed():
            self.page = self.context.new_page()

        return self.page

    def ambil_csrf_token(self):
        try:
            token = self.page.evaluate("""() => {
                const meta = document.querySelector('meta[name="csrf-token"]');
                if (meta) return meta.getAttribute('content');
                const inp = document.querySelector('input[name="_token"]');
                if (inp) return inp.value;
                if (window.dcTlCsrf) return window.dcTlCsrf;
                return null;
            }""")
            if token:
                self.csrf_token = token
                return token
        except Exception:
            pass
        return None

    def cek_status_sebelum_eksekusi(self, row):
        """
        1. Buka Selancar Nerwana dan cari nama usaha / assignment.
        2. Cek status tindak lanjut:
           - Jika sudah 'sudah_direvisi' -> kembalikan boleh_eksekusi = False (SKIP).
           - Jika diisi orang lain (terkunci) -> kembalikan boleh_eksekusi = False (SKIP).
           - Jika masih '' (belum) atau 'akan_direvisi' -> kembalikan boleh_eksekusi = True (GAS).
           - Jika jaringan Selancar reset / error -> graceful fallback (GAS ke FASIH).
        """
        import re
        nama_usaha = row['nama_usaha']
        aid = row['assignment_id']
        data_kunci = row['data_kunci']

        try:
            page = self.get_or_create_page()
            
            # Bersihkan tanda kurung dan karakter < > agar tidak memicu blocking/WAF
            clean_nama = re.sub(r'[\(\[\<].*?[\)\]\>]', '', nama_usaha)
            clean_nama = re.sub(r'[<>\(\)\[\]]', '', clean_nama).strip()
            query_str = clean_nama if len(clean_nama) >= 3 else nama_usaha.strip()

            print(f"\n[SELANCAR] Memeriksa status di UI Selancar untuk: '{nama_usaha}'...")
            
            # Pastikan berada di halaman dc-terkena-flag tanpa reload jika sudah terbuka
            if "dc-terkena-flag" not in page.url.lower():
                buka_dan_siapkan_selancar(page, kategori=self.kategori)

            # Gunakan kolom pencarian di UI yang sudah terbuka (bukan page.goto URL berparameter)
            try:
                inp_cari = page.locator('#filter_cari, input[name="cari"]').first
                if inp_cari.count() > 0 and inp_cari.is_visible():
                    inp_cari.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    import random
                    page.keyboard.type(query_str, delay=random.randint(40, 90))
                    page.keyboard.press("Enter")
                    time.sleep(1.5)
            except Exception as e_cari:
                print(f"[INFO] Pencarian UI: {e_cari}")

            self.ambil_csrf_token()

            # Tunggu tabel dimuat
            try:
                page.wait_for_selector('#tableEvalProfil, select.dc-tl-select, text="Tidak ada data"', timeout=10000)
            except Exception:
                pass

            # Cari dropdown tindak lanjut baris ini
            select_elem = None
            if data_kunci:
                select_by_kunci = page.locator(f'select.dc-tl-select[data-kunci="{data_kunci}"]')
                if select_by_kunci.count() > 0:
                    select_elem = select_by_kunci.first

            if not select_elem or select_elem.count() == 0:
                all_selects = page.locator('select.dc-tl-select')
                if all_selects.count() > 0:
                    select_elem = all_selects.first

            if not select_elem or select_elem.count() == 0:
                print(f"[SELANCAR] Baris '{nama_usaha}' tidak ditemukan di tabel hasil filter.")
                print("[SELANCAR] Status aman untuk diproses.")
                return {"boleh_eksekusi": True, "status": "belum", "alasan": "Baris belum diisi"}

            # Ambil status dan info pengisi
            status_val = select_elem.input_value() or select_elem.get_attribute("data-prev") or ""
            is_terkunci = select_elem.get_attribute("data-terkunci") == "1"
            title_info = select_elem.get_attribute("title") or ""
            
            box = select_elem.locator('..')
            oleh_text = ""
            if box.locator('.dc-tl-oleh').count() > 0:
                oleh_text = box.locator('.dc-tl-oleh').first.inner_text().strip()

            print(f"[SELANCAR] Status terkini di server: '{status_val or 'Belum'}' | Pengisi: {oleh_text or title_info}")

            if status_val == "sudah_direvisi":
                print(f"[SELANCAR-SKIP] Baris ini SUDAH DIREVISI di Selancar ({oleh_text}). TIDAK PERLU DIUBAH LAGI.")
                conn = get_connection()
                conn.execute("UPDATE kasus_nerwana SET status = 'COMPLETED', tindak_lanjut = 'sudah_direvisi' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama_usaha))
                conn.commit()
                conn.close()
                return {"boleh_eksekusi": False, "status": "sudah_direvisi", "alasan": f"Sudah direvisi oleh {oleh_text}"}

            if is_terkunci:
                print(f"[SELANCAR-SKIP] Baris ini TERKUNCI oleh pengguna lain ({oleh_text}). Dilewati.")
                return {"boleh_eksekusi": False, "status": status_val, "alasan": f"Terkunci oleh {oleh_text}"}

            print(f"[SELANCAR] Status aman ('{status_val or 'Belum'}'). GAS lanjut proses kuesioner ke FASIH!")
            return {"boleh_eksekusi": True, "status": status_val, "alasan": "Aman untuk direvisi"}

        except Exception as e_outer:
            print(f"[SELANCAR-WARN] Pengecekan Selancar dilewati karena: {e_outer}. Melanjutkan ke FASIH...")
            return {"boleh_eksekusi": True, "status": "belum", "alasan": "Pengecekan Selancar dilewati"}

    def update_tindak_lanjut(self, data_kunci, status="sudah_direvisi", assignment_id="", nama_usaha=""):
        """Mengirim AJAX request ke Nerwana untuk mengubah status tindak lanjut menjadi 'sudah_direvisi'."""
        if not data_kunci:
            print("[ERROR] data_kunci kosong, tidak dapat update Nerwana.")
            return False

        page = self.get_or_create_page()
        pastikan_login_selancar(page)
        
        token = self.ambil_csrf_token()
        if not token:
            print("[ERROR] CSRF token Selancar tidak ditemukan.")
            return False

        print(f"[SELANCAR] Mengupdate status tindak lanjut menjadi '{status}' untuk {nama_usaha}...")
        
        script = """([url, token, kunci, stat]) => {
            return new Promise((resolve) => {
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-CSRF-TOKEN': token,
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: new URLSearchParams({
                        _token: token,
                        kunci: kunci,
                        status: stat
                    })
                })
                .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data: data })))
                .then(res => resolve(res))
                .catch(err => resolve({ ok: false, status: 0, error: err.toString() }));
            });
        }"""

        try:
            res = page.evaluate(script, [NERWANA_UPDATE_URL, token, data_kunci, status])
            
            if res.get("ok"):
                data = res.get("data", {})
                label = data.get("label", status)
                oleh = data.get("oleh", "")
                waktu = data.get("waktu", "")
                print(f"[SELANCAR SUKSES] Status berhasil diubah menjadi: '{label}' ({oleh}, {waktu})")
                
                # Update status di database lokal
                if assignment_id and nama_usaha:
                    conn = get_connection()
                    new_db_stat = 'COMPLETED' if status == 'sudah_direvisi' else 'IN_PROGRESS'
                    conn.execute("""
                        UPDATE kasus_nerwana 
                        SET tindak_lanjut = ?, tindak_lanjut_oleh = ?, status = ?, updated_at = CURRENT_TIMESTAMP 
                        WHERE assignment_id = ? AND nama_usaha = ?
                    """, (status, oleh, new_db_stat, assignment_id, nama_usaha))
                    conn.commit()
                    conn.close()
                    
                    log_audit(assignment_id, nama_usaha, "UPDATE_NERWANA_TL", 
                              status_sebelumnya="SUBMITTED", status_baru="COMPLETED", 
                              pesan=f"Tindak lanjut Selancar diubah menjadi {label} oleh {oleh}")
                return True
            else:
                err_msg = res.get("data", {}).get("message") or res.get("error") or "Unknown error"
                print(f"[SELANCAR GAGAL] HTTP {res.get('status')}: {err_msg}")
                return False
        except Exception as e:
            print(f"[SELANCAR ERROR] Exception saat AJAX: {e}")
            return False
