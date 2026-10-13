import time
import urllib.parse
from database import get_connection, log_audit

NERWANA_BASE_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/dc-terkena-flag"
NERWANA_LANDING_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/landing"
NERWANA_LOGIN_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/login"
NERWANA_UPDATE_URL = "https://nerwana-aceh.web.bps.go.id/selancar2026/dc-terkena-flag/tindak-lanjut"

def get_sso_credentials():
    """Membaca kredensial SSO dari file sso di direktori proyek."""
    import os
    sso_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sso")
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

def pastikan_login_selancar(page):
    """
    Memastikan halaman Selancar login penuh.
    Jika mental ke halaman login Selancar atau SSO BPS, melakukan login otomatis (maksimal 1 kali per sesi).
    """
    global SSO_LOGIN_COUNT
    for loop in range(3):
        url = page.url.lower()

        # 1. Jika di SSO BPS
        if "sso.bps.go.id" in url or page.locator('#kc-login, button:has-text("Log In")').count() > 0:
            if SSO_LOGIN_COUNT >= 1:
                print("\n" + "!" * 65)
                print("[SSO ERROR] Sesi SSO meminta login ulang setelah 1 kali login otomatis.")
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

            import random
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
                time.sleep(0.3)

            print("[SELANCAR-SSO] Mengklik tombol Log In di SSO...")
            btn_login = page.locator('#kc-login, button:has-text("Log In"), input[type="submit"]').first
            btn_login.click()
            SSO_LOGIN_COUNT += 1

            print("[SELANCAR-SSO] Menunggu redirect kembali ke Selancar...")
            try:
                page.wait_for_url(lambda u: "sso.bps.go.id" not in u.lower(), timeout=30000)
            except Exception:
                pass
            time.sleep(3)
            continue

        # 2. Jika di Halaman Login Selancar Nerwana ("Login dengan SSO BPS")
        btn_sso_nerwana = page.locator('button:has-text("Login dengan SSO BPS"), a:has-text("Login dengan SSO BPS")')
        if "login" in url or (btn_sso_nerwana.count() > 0 and btn_sso_nerwana.first.is_visible()):
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

def buka_dan_siapkan_selancar(page):
    """
    Menjalankan alur navigasi alami:
    1. Masuk ke Selancar landing (https://nerwana-aceh.web.bps.go.id/selancar2026/landing)
    2. Selesaikan login SSO / tombol login jika diperlukan
    3. Dari landing, klik kartu/menu 'DC Terkena Flag'
    4. Di halaman DC Terkena Flag, pilih Kategori 'A'
    5. Tunggu tabel data dimuat penuh
    """
    print("\n" + "=" * 65)
    print("           MENYIAPKAN HALAMAN SELANCAR NERWANA")
    print("=" * 65)
    url = page.url.lower()

    # 1. Pastikan di domain Selancar
    if "selancar2026" not in url:
        print("[SELANCAR] Mengarahkan ke Landing Page Selancar...")
        try:
            page.goto(NERWANA_LANDING_URL, timeout=45000)
            page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            print(f"[INFO] Navigasi landing: {e}")

    # Selesaikan login SSO jika belum login
    pastikan_login_selancar(page)
    time.sleep(1)

    url = page.url.lower()
    # 2. Jika di landing atau bukan di dc-terkena-flag, klik menu 'DC Terkena Flag'
    if "landing" in url or "dc-terkena-flag" not in url:
        print("[SELANCAR] Berada di Landing. Mengklik menu 'DC Terkena Flag'...")
        try:
            card_dc = page.locator('a:has-text("DC Terkena Flag"), div:has-text("DC Terkena Flag"), [href*="dc-terkena-flag"]').first
            if card_dc.count() > 0:
                card_dc.click()
            else:
                page.goto(NERWANA_BASE_URL, timeout=45000)
            page.wait_for_url(lambda u: "dc-terkena-flag" in u.lower(), timeout=20000)
        except Exception as e:
            print(f"[INFO] Klik menu DC Terkena Flag: {e}")
            if "dc-terkena-flag" not in page.url.lower():
                page.goto(NERWANA_BASE_URL, timeout=45000)

    time.sleep(2)
    pastikan_login_selancar(page)

    # 3. Di halaman DC Terkena Flag, pastikan Kategori 'A' dipilih
    try:
        page.wait_for_selector('#filter_kategori, select[name="kategori"]', timeout=15000)
        select_kat = page.locator('#filter_kategori, select[name="kategori"]').first
        current_val = select_kat.input_value()
        if current_val != "A":
            print("[SELANCAR] Memilih 'Kategori A' pada dropdown filter...")
            select_kat.select_option("A")
            time.sleep(2)
    except Exception as e_sel:
        print(f"[SELANCAR-INFO] Pilihan kategori: {e_sel}")

    # 4. Tunggu tabel dimuat
    print("[SELANCAR] Menunggu tabel data Kategori A selesai dimuat...")
    try:
        page.wait_for_selector('#tableEvalProfil tbody tr', timeout=30000)
        try:
            page.locator('#loading-overlay').wait_for(state="hidden", timeout=15000)
        except Exception:
            pass
        print("[SELANCAR] Tabel data Kategori A siap di layar!")
        return True
    except Exception as e_wait:
        print(f"[SELANCAR-WARN] Menunggu tabel: {e_wait}")
        return False

def cari_target_di_tabel_selancar(page, conn):
    """
    Memeriksa baris-baris pada tabel Selancar Kategori A yang tampil di layar:
    - Mencari baris yang tindak lanjutnya masih belum (bukan 'sudah_direvisi') dan tidak terkunci.
    - Mencocokkan dengan database lokal kasus_nerwana yang berstatus 'APPROVED'.
    Mengembalikan dict informasi target jika ditemukan, atau None.
    """
    try:
        page.wait_for_selector('#tableEvalProfil tbody tr', timeout=15000)
        rows = page.locator('#tableEvalProfil tbody tr').all()
        for tr in rows:
            sim_btn = tr.locator('.dc-sim-btn').first
            if sim_btn.count() == 0:
                continue
            aid = sim_btn.get_attribute("data-aid")
            nama = sim_btn.get_attribute("data-nama")
            if not aid:
                continue

            tl_select = tr.locator('select.dc-tl-select').first
            stat = tl_select.input_value() or tl_select.get_attribute("data-prev") or ""
            is_terkunci = tl_select.get_attribute("data-terkunci") == "1"

            if stat == "sudah_direvisi" or is_terkunci:
                continue

            # Cocokkan dengan database lokal kasus_nerwana berstatus APPROVED
            db_row = conn.execute("SELECT * FROM kasus_nerwana WHERE assignment_id = ? AND status = 'APPROVED'", (aid,)).fetchone()
            if not db_row and nama:
                db_row = conn.execute("SELECT * FROM kasus_nerwana WHERE nama_usaha = ? AND status = 'APPROVED'", (nama,)).fetchone()

            if db_row:
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
                    'data_kunci': tl_select.get_attribute("data-kunci") or "",
                    'db_row': dict(db_row)
                }
    except Exception as e:
        print(f"[SELANCAR-ERROR] Gagal membaca baris tabel: {e}")
    return None

def lanjut_halaman_berikutnya_selancar(page):
    """Mengecek tombol pagination berikutnya dan mengkliknya jika ada."""
    try:
        btn_next = page.locator('.pagination li:not(.disabled) a:has-text("›"), .pagination li:not(.disabled) a:has-text(">"), a[rel="next"]').first
        if btn_next.count() > 0 and btn_next.is_visible():
            print("[SELANCAR] Berpindah ke halaman tabel berikutnya...")
            btn_next.click()
            page.wait_for_selector('#tableEvalProfil tbody tr', timeout=30000)
            try:
                page.locator('#loading-overlay').wait_for(state="hidden", timeout=10000)
            except Exception:
                pass
            time.sleep(2)
            return True
    except Exception:
        pass
    return False

class NerwanaManager:
    def __init__(self, browser_context):
        self.context = browser_context
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
                buka_dan_siapkan_selancar(page)

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
                    conn.execute("""
                        UPDATE kasus_nerwana 
                        SET tindak_lanjut = ?, tindak_lanjut_oleh = ?, status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP 
                        WHERE assignment_id = ? AND nama_usaha = ?
                    """, (status, oleh, assignment_id, nama_usaha))
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
