import os
import sys
import time
import socket
import subprocess
import random
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

from database import get_connection, log_audit

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_debug_profile")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def cleanup_old_screenshots(max_keep=30):
    """
    Menjaga folder screenshots agar tidak membengkak:
    Hanya mempertahankan sejumlah `max_keep` file screenshot terbaru,
    dan menghapus file screenshot lama secara otomatis.
    """
    try:
        files = [
            os.path.join(SCREENSHOTS_DIR, f)
            for f in os.listdir(SCREENSHOTS_DIR)
            if f.lower().endswith(".png")
        ]
        if len(files) > max_keep:
            files.sort(key=lambda p: os.path.getmtime(p))
            to_remove = files[:len(files) - max_keep]
            for fpath in to_remove:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
            print(f"[CLEANUP] Otomatis membersihkan {len(to_remove)} screenshot lama (menyimpan {max_keep} terbaru).")
    except Exception:
        pass

def is_port_open(port=9222):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_debug_chrome():
    if not is_port_open(9222):
        print(f"[CHROME] Menjalankan Chrome dengan mode debugging (port 9222)...")
        cmd = [
            CHROME_PATH,
            "--remote-debugging-port=9222",
            f"--user-data-dir={PROFILE_DIR}",
            "--start-maximized"
        ]
        subprocess.Popen(cmd)
        for _ in range(15):
            time.sleep(1)
            if is_port_open(9222):
                print("[CHROME] Port 9222 siap terhubung.")
                return True
        print("[ERROR] Gagal membuka Chrome pada port 9222.")
        return False
    return True

WAF_LOCK_FILE = os.path.join(BASE_DIR, ".waf_lock")
COOLDOWN_SECONDS = 30 * 60  # 30 menit
SSO_FASIH_LOGIN_COUNT = 0

def catat_waf_block(bot_code=""):
    """Menyimpan timestamp terjadinya WAF block ke file .waf_lock."""
    try:
        with open(WAF_LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(f"{time.time()}|{bot_code}|{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"[WARN] Gagal menulis .waf_lock: {e}")

def cek_waf_cooldown():
    """
    Memeriksa apakah saat ini masih dalam masa cooldown WAF block (< 30 menit).
    Mengembalikan (is_locked, sisa_detik, bot_code, jam_blokir).
    """
    if os.path.exists(WAF_LOCK_FILE):
        try:
            with open(WAF_LOCK_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    parts = content.split("|")
                    ts = float(parts[0])
                    bot_code = parts[1] if len(parts) > 1 else "BOT-UNKNOWN"
                    jam_blokir = parts[2] if len(parts) > 2 else ""
                    elapsed = time.time() - ts
                    if elapsed < COOLDOWN_SECONDS:
                        sisa_detik = int(COOLDOWN_SECONDS - elapsed)
                        return True, sisa_detik, bot_code, jam_blokir
        except Exception:
            pass
    return False, 0, "", ""

def get_sso_credentials():
    sso_file = os.path.join(BASE_DIR, "sso")
    if os.path.exists(sso_file):
        u, p = "", ""
        with open(sso_file, "r", encoding="utf-8") as f:
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

def cek_waf_bot(page):
    r"""
    HANYA mendeteksi halaman WAF BPS:
    Teks 'mendeteksi koneksi anda sebagai bot', 'perilaku yang tidak wajar',
    atau pola regex r"BOT-\d+" / r"BOT-[A-Za-z0-9]+".
    Mengembalikan (True, bot_code) jika terdeteksi, atau (False, None).
    """
    try:
        if page.is_closed():
            return False, None
        content = page.content()
        if "mendeteksi koneksi anda sebagai bot" in content or \
           "perilaku yang tidak wajar" in content or \
           "BOT-" in content:
            match = re.search(r"BOT-[A-Za-z0-9]+", content)
            bot_code = match.group(0) if match else "BOT-DETECTED"
            return True, bot_code
    except Exception:
        pass
    return False, None

def cek_fasih_error(page):
    """
    Mengecek apakah halaman FASIH menampilkan error Forbidden, There's some error, atau 403 biasa.
    DIPISAHKAN dari WAF bot agar ditangani berbeda.
    """
    try:
        if page.is_closed():
            return False
        if page.locator('text="There\'s some error"').count() > 0 or \
           page.locator('text="Forbidden"').count() > 0 or \
           page.locator('text="403"').count() > 0 or \
           page.locator('text="Access Denied"').count() > 0:
            return True
    except Exception:
        pass
    return False

def ulang_buka_assignment_dari_selancar(fasih_page, selancar_page=None, link_btn=None):
    """
    Jika setelah login SSO FASIH mendarat di halaman awal/dashboard FASIH (/app/)
    dan bukan langsung ke kuesioner assignment, ulangi proses klik link assignment dari Selancar.
    """
    print("\n[SELANCAR] Mengecek tab Selancar untuk menekan ulang link assignment...")
    try:
        if fasih_page and not fasih_page.is_closed():
            fasih_page.evaluate("() => { window.name = 'tab_fasih_nerwana'; }")
    except Exception:
        pass

    # Jika selancar_page belum dioper, cari dari context fasih_page
    if not selancar_page or selancar_page.is_closed():
        try:
            for p in fasih_page.context.pages:
                if not p.is_closed() and "nerwana-aceh.web.bps.go.id" in p.url.lower():
                    selancar_page = p
                    break
        except Exception:
            pass

    if selancar_page and not selancar_page.is_closed():
        try:
            selancar_page.bring_to_front()
            time.sleep(1.0)
        except Exception:
            pass

    # Ambil href target jika ada
    target_url = None
    if link_btn:
        try:
            target_url = link_btn.get_attribute("href")
        except Exception:
            pass

    # Jika link_btn belum ada atau invalid, cari dari tabel di selancar_page
    if not link_btn and selancar_page and not selancar_page.is_closed():
        try:
            link_candidate = selancar_page.locator('a.dc-link-btn, a[href*="assignment"]').first
            if link_candidate.count() > 0:
                link_btn = link_candidate
                target_url = link_btn.get_attribute("href")
        except Exception:
            pass

    # Jika target_url ada, arahkan tab FASIH langsung tanpa jeda cross-window!
    if target_url and "assignment" in target_url:
        print(f"[FASIH] Membuka URL assignment target secara langsung: {target_url}")
        try:
            fasih_page.bring_to_front()
            fasih_page.goto(target_url, timeout=30000)
            fasih_page.wait_for_load_state("domcontentloaded")
            time.sleep(1)
            return True
        except Exception as e_goto:
            print(f"[FASIH-WARN] Navigasi goto: {e_goto}")

    # Fallback klik via tabel Selancar
    if selancar_page and not selancar_page.is_closed() and link_btn:
        try:
            selancar_page.bring_to_front()
            link_btn.scroll_into_view_if_needed()
            time.sleep(0.3)
            link_btn.click()
            print("[SELANCAR] Tombol link assignment di Selancar berhasil diklik.")
            time.sleep(1)
            fasih_page.bring_to_front()
        except Exception as e:
            print(f"[SELANCAR-WARN] Gagal klik link di Selancar: {e}")

    return "assignment" in fasih_page.url.lower()

def selesaikan_sso_pada_fasih(page, selancar_page=None, link_btn=None, max_wait_sec=40):
    """
    Menyelesaikan login SSO BPS jika tab FASIH berada di halaman SSO atau Selamat Datang Kembali.
    Setelah login berhasil, jika FASIH mendarat di halaman awal/dashboard FASIH (/app/)
    bukan langsung ke assignment, fungsi ini akan mengulang klik tombol link assignment dari Selancar.
    Login otomatis maksimal 1 kali per sesi untuk mencegah pembatasan akun/IP.
    """
    global SSO_FASIH_LOGIN_COUNT
    start = time.time()
    while time.time() - start < max_wait_sec:
        try:
            if page.is_closed():
                return False, None
            url = page.url.lower()

            # 0. Cek apakah langsung terkena WAF
            is_waf, bot_code = cek_waf_bot(page)
            if is_waf:
                return "WAF", bot_code

            # 1. KONDISI: Berada di SSO BPS (sso.bps.go.id)
            if "sso.bps.go.id" in url or page.locator('#kc-login, button:has-text("Log In")').count() > 0:
                if SSO_FASIH_LOGIN_COUNT >= 1:
                    print("\n" + "!" * 65)
                    print("[SSO ERROR] Tab FASIH meminta login ulang setelah 1 kali login otomatis.")
                    print("Silakan lakukan login SSO secara manual di browser Chrome terlebih dahulu.")
                    print("!" * 65 + "\n")
                    return "SSO_LIMIT_EXCEEDED", None

                print("[SSO] Terdeteksi form SSO BPS di tab FASIH...")
                uname, pwd = get_sso_credentials()
                if not uname or not pwd:
                    print("[SSO ERROR] Kredensial SSO tidak ditemukan di file sso.")
                    return "SSO_NO_CREDENTIALS", None
                
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
                    time.sleep(0.3)

                print("[SSO] Mengklik tombol Log In di SSO...")
                btn_login = page.locator('#kc-login, button:has-text("Log In"), input[type="submit"]').first
                btn_login.click()
                SSO_FASIH_LOGIN_COUNT += 1
                
                print("[SSO] Menunggu redirect selesai...")
                try:
                    page.wait_for_url(lambda u: "sso.bps.go.id" not in u.lower(), timeout=20000)
                    print("[SSO] Berhasil keluar dari SSO!")
                except Exception:
                    time.sleep(3)
                time.sleep(2.5)

                # PENTING: Begitu selesai login SSO, FASIH selalu ke /app/ awal.
                # Langsung cek Selancar dan tekan lagi link assignment!
                if "assignment" not in page.url.lower():
                    print("[SSO] FASIH mendarat di beranda/awal pasca login SSO.")
                    ulang_sukses = ulang_buka_assignment_dari_selancar(page, selancar_page, link_btn)
                    if ulang_sukses:
                        return True, None
                continue

            # 2. KONDISI: Berada di halaman Selamat Datang Kembali (FASIH /app/)
            btn_sso = page.locator('button:has-text("Lanjutkan dengan SSO"), a:has-text("Lanjutkan dengan SSO")')
            is_login_screen = (btn_sso.count() > 0 and btn_sso.first.is_visible()) or page.locator('text="Selamat Datang Kembali"').count() > 0
            if is_login_screen:
                print("[SSO] Terdeteksi halaman login 'Selamat Datang Kembali'. Mengklik tombol 'Lanjutkan dengan SSO'...")
                btn_sso_click = page.locator('button:has-text("Lanjutkan dengan SSO"), a:has-text("Lanjutkan dengan SSO")').filter(has_not_text="Eksternal")
                if btn_sso_click.count() > 0 and btn_sso_click.first.is_visible():
                    btn_sso_click.first.click()
                elif btn_sso.count() > 0:
                    btn_sso.first.click()
                time.sleep(2.5)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                time.sleep(1)

                # Jika setelah klik SSO langsung kembali ke /app/ karena sudah punya sesi
                if "sso.bps.go.id" not in page.url.lower() and "assignment" not in page.url.lower():
                    btn_sso_cek = page.locator('button:has-text("Lanjutkan dengan SSO"), a:has-text("Lanjutkan dengan SSO")')
                    if btn_sso_cek.count() == 0 or not btn_sso_cek.first.is_visible():
                        print("[SSO] Sesi SSO langsung aktif. Mengulang buka assignment dari Selancar...")
                        ulang_sukses = ulang_buka_assignment_dari_selancar(page, selancar_page, link_btn)
                        if ulang_sukses:
                            return True, None
                continue

            # 3. KONDISI: Sudah di assignment dan BUKAN di login screen
            btn_sso_cek = page.locator('button:has-text("Lanjutkan dengan SSO"), a:has-text("Lanjutkan dengan SSO")')
            is_login = (btn_sso_cek.count() > 0 and btn_sso_cek.first.is_visible()) or page.locator('text="Selamat Datang Kembali"').count() > 0
            if "assignment" in url and not is_login and "sso.bps.go.id" not in url:
                return True, None

            # 4. KONDISI: Berada di FASIH awal / Dashboard (/app/) setelah login (bukan assignment)
            if "fasih-sm.bps.go.id" in url and "assignment" not in url:
                if not is_login and page.locator('text="Loading Page..."').count() == 0:
                    print("[FASIH] Terdeteksi berada di halaman awal FASIH (/app/ dashboard) dan bukan di assignment.")
                    ulang_sukses = ulang_buka_assignment_dari_selancar(page, selancar_page, link_btn)
                    if ulang_sukses:
                        return True, None

        except Exception:
            pass
        time.sleep(random.uniform(2.0, 3.0))

    return True, None

def selesaikan_sso_dan_buka_target(page, target_link):
    """Fallback navigasi jika diperlukan."""
    selesaikan_sso_pada_fasih(page)
    if "assignment" not in page.url.lower():
        try:
            page.goto(target_link, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
    return True

def wait_fasih_ready(page, selancar_page=None, link_btn=None, timeout=30):
    """
    Menunggu FASIH selesai memuat sampai kuesioner siap di layar.
    Langsung return READY begitu salah satu kondisi terpenuhi:
    1. Modal Revoke / Konfirmasi sudah terbuka
    2. Sudah dalam Mode Edit / Anda sedang mengedit
    3. Toolbar floating (3 tombol = Revoke, 4-5 tombol = Edit) sudah siap di layar
    4. Tombol Edit Assignment sudah muncul
    """
    print("[FASIH] Memeriksa kesiapan kuesioner di layar...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            if page.is_closed():
                return "CLOSED", None

            # 1. CEK WAF BOT (PRIORITAS UTAMA)
            is_waf, bot_code = cek_waf_bot(page)
            if is_waf:
                return "WAF", bot_code

            # 2. Cek apakah di SSO atau layar 'Selamat Datang Kembali' / 'Lanjutkan dengan SSO'
            btn_sso = page.locator('button:has-text("Lanjutkan dengan SSO"), a:has-text("Lanjutkan dengan SSO")')
            is_login_screen = (btn_sso.count() > 0 and btn_sso.first.is_visible()) or page.locator('text="Selamat Datang Kembali"').count() > 0
            if is_login_screen or "sso.bps.go.id" in page.url.lower():
                print("[FASIH] Terdeteksi layar login SSO / 'Lanjutkan dengan SSO'. Menyelesaikan SSO...")
                sso_res, sso_bot = selesaikan_sso_pada_fasih(page, selancar_page=selancar_page, link_btn=link_btn)
                if sso_res == "WAF":
                    return "WAF", sso_bot
                elif sso_res == "SSO_LIMIT_EXCEEDED":
                    return "SSO_LIMIT_EXCEEDED", None
                start = time.time()
                continue

            # 2b. Cek jika mendarat di Dashboard (/app/) bukan assignment dan bukan loading
            if "fasih-sm.bps.go.id" in page.url.lower() and "assignment" not in page.url.lower():
                if page.locator('text="Loading Page..."').count() == 0 and not is_login_screen:
                    print("[FASIH] Halaman berada di dashboard (/app/) bukan assignment. Membuka ulang assignment...")
                    ulang_buka_assignment_dari_selancar(page, selancar_page=selancar_page, link_btn=link_btn)
                    start = time.time()
                    continue

            # 3. Cek error FASIH biasa (Forbidden / 403 biasa)
            if cek_fasih_error(page):
                print("[FASIH] Terdeteksi halaman error FASIH biasa (Forbidden / 403)!")
                return "ERROR", None

            # 4. Cek loading spinner
            loading = page.locator('text="Loading Page..."')
            if loading.count() > 0 and loading.first.is_visible():
                time.sleep(1)
                continue

            # 5. CEK APAKAH SUDAH SIAP DI LAYAR:
            # - Modal Konfirmasi Revoke
            if page.locator('button:has-text("Konfirmasi")').count() > 0:
                print("[FASIH] Modal Konfirmasi Revoke siap di layar!")
                return "READY", None

            # - Sudah Mode Edit / Menu Blok II
            if page.locator('text="Mode Edit", text="Anda sedang mengedit", text="SE2026 - L BLOK"').count() > 0:
                print("[FASIH] Kuesioner (Mode Edit) siap di layar!")
                return "READY", None

            # - Floating Pill Buttons di kanan bawah (3 tombol = Revoke dlu, 4-5 tombol = Langsung Edit)
            pill_btns = get_floating_pill_buttons(page)
            if len(pill_btns) >= 3:
                tipe_toolbar = "Langsung Edit" if len(pill_btns) >= 4 else "Revoke dlu"
                print(f"[FASIH] Assignment sudah terbuka di layar ({len(pill_btns)} tombol: {tipe_toolbar})!")
                return "READY", None

            # - Tombol Edit teks
            if page.locator('button:has-text("Edit Assignment"), button:has-text("Edit"), [title*="Edit" i]').count() > 0:
                print("[FASIH] Tombol Edit siap di layar!")
                return "READY", None

        except Exception:
            pass

        time.sleep(1)

    # Cek akhir WAF sebelum return
    is_waf, bot_code = cek_waf_bot(page)
    if is_waf:
        return "WAF", bot_code

    if len(get_floating_pill_buttons(page)) >= 3:
        return "READY", None

    return "TIMEOUT", None

def get_floating_pill_buttons(page):
    """Mengambil tombol-tombol yang berada di floating toolbar kanan bawah."""
    try:
        floating_buttons = page.locator('div[class*="fixed"] button, div[class*="sticky"] button, div[class*="bottom-"] button').all()
        pill_buttons = []
        for btn in floating_buttons:
            try:
                box = btn.bounding_box()
                if box and box['x'] > 800 and box['y'] > 200 and btn.is_visible():
                    pill_buttons.append((box['y'], btn))
            except Exception:
                pass
        # Urutkan dari atas ke bawah berdasarkan koordinat Y
        pill_buttons.sort(key=lambda x: x[0])
        return [b[1] for b in pill_buttons]
    except Exception:
        return []

def tunggu_proses_revoke_selesai(page, timeout=90):
    """
    Menunggu proses Revoke selesai di backend FASIH.
    Revoke di FASIH memicu request backend yang memakan waktu (10-40 detik),
    lalu menampilkan 'Loading Page...' dan reload halaman.
    Fungsi ini aman dari 'Execution context was destroyed'.
    """
    print("[FASIH] Menunggu proses Revoke di backend FASIH & reload halaman (bisa memakan waktu 15-40 detik)...")
    start = time.time()
    
    # Tunggu modal Konfirmasi tertutup / menghilang
    try:
        page.locator('button:has-text("Konfirmasi")').wait_for(state="hidden", timeout=15000)
    except Exception:
        pass

    # Beri jeda 3 detik agar proses reload/spinner Loading Page dimulai di browser
    time.sleep(3)

    saw_loading = False
    while time.time() - start < timeout:
        try:
            if page.is_closed():
                return False

            # 1. Cek apakah ada spinner 'Loading Page...'
            loading = page.locator('text="Loading Page..."')
            if loading.count() > 0 and loading.first.is_visible():
                saw_loading = True
                print("[FASIH] Server FASIH sedang memproses penarikan (Loading Page...)...")
                time.sleep(3)
                continue

            # 2. Cek apakah sudah dalam Mode Edit
            if page.locator('text="Anda sedang mengedit assignment ini"').count() > 0 or \
               page.locator('text="Mode Edit"').count() > 0:
                print("[FASIH] Sudah otomatis berada dalam Mode Edit!")
                return True

            # 3. Cek jumlah tombol toolbar sekarang
            btns = get_floating_pill_buttons(page)
            if len(btns) >= 4:
                print(f"[FASIH] Proses Revoke SELESAI! Toolbar sekarang memiliki {len(btns)} tombol (siap Edit).")
                time.sleep(2)
                return True
            elif len(btns) == 3 and not saw_loading:
                # Belum mulai reload atau server masih proses
                time.sleep(2)
                continue

            # 4. Cek menu kuesioner utama
            if page.locator('text="SE2026 - L BLOK II"').count() > 0:
                if len(btns) >= 4:
                    return True
        except Exception:
            # Mengabaikan 'Execution context was destroyed, most likely because of a navigation' saat reload
            time.sleep(2)
            continue

        time.sleep(2)

    return True

def lakukan_revoke_dan_edit(page):
    """
    Menangani 2 skenario status assignment:
    A. Butuh Revoke:
       - Toolbar ada 3 tombol (tombol terbawah = panah melingkar Revoke).
       - Klik Revoke -> Muncul modal 'Revoke Assignment?' -> Klik tombol oranye 'Konfirmasi'.
       - Tunggu dialog hilang, 'Loading Page...' selesai, dan toolbar berubah jadi 5 tombol.
       - Klik tombol terbawah (Pensil / Edit).
    B. Langsung Edit:
       - Toolbar sudah ada 5 tombol atau tombol Pensil / Edit sudah tersedia.
       - Langsung klik tombol Pensil / Edit.
    """
    # 1. Cek apakah sudah dalam Mode Edit
    try:
        if page.locator('text="Anda sedang mengedit assignment ini"').count() > 0 or \
           page.locator('text="Mode Edit"').count() > 0:
            print("[FASIH] Sudah berada dalam Mode Edit. Langsung lanjut isi form!")
            return True
    except Exception:
        pass

    print("[FASIH] Memeriksa status assignment & floating toolbar di kanan bawah...")
    pill_buttons = get_floating_pill_buttons(page)
    print(f"[FASIH] Terdeteksi {len(pill_buttons)} tombol pada floating toolbar.")

    # SKENARIO A: Butuh Revoke (3 tombol) atau Modal Konfirmasi sudah terbuka
    modal_konfirm = False
    try:
        btn_konfirm_existing = page.locator('button:has-text("Konfirmasi")')
        if btn_konfirm_existing.count() > 0 and btn_konfirm_existing.first.is_visible():
            print("[FASIH] Modal 'Revoke Assignment?' sudah terbuka di layar. Mengklik tombol 'Konfirmasi'...")
            btn_konfirm_existing.first.click()
            modal_konfirm = True
    except Exception:
        pass

    if modal_konfirm:
        tunggu_proses_revoke_selesai(page)
    elif len(pill_buttons) == 3:
        tombol_revoke = pill_buttons[-1]
        print("[FASIH] Skenario BUTUH REVOKE (3 tombol: Back, Info, Revoke). Mengklik tombol Revoke...")
        try:
            tombol_revoke.click()
        except Exception:
            time.sleep(0.5)
            pill_buttons = get_floating_pill_buttons(page)
            if pill_buttons:
                pill_buttons[-1].click()
        time.sleep(1.0)

        # Tunggu modal Revoke dan tombol Konfirmasi muncul
        print("[FASIH] Menunggu modal 'Revoke Assignment?' dan mengklik tombol 'Konfirmasi'...")
        try:
            page.wait_for_selector('button:has-text("Konfirmasi")', timeout=8000)
            btn_konfirm = page.locator('button:has-text("Konfirmasi")').first
            if btn_konfirm.count() > 0 and btn_konfirm.is_visible():
                btn_konfirm.click()
                print("[FASIH] Tombol 'Konfirmasi' Revoke BERHASIL DIKLIK!")
        except Exception as ek:
            print(f"[WARN] Menunggu tombol Konfirmasi: {ek}")
            btn_fallback = page.locator('[role="dialog"] button:has-text("Konfirmasi"), .fixed button:has-text("Konfirmasi"), button:has-text("Konfirmasi")').first
            if btn_fallback.count() > 0 and btn_fallback.is_visible():
                btn_fallback.click()
        
        # Tunggu proses Revoke di backend FASIH & reload selesai
        tunggu_proses_revoke_selesai(page)

    # SETELAH REVOKE (atau SKENARIO B: Langsung Edit):
    # Cek apakah sudah otomatis dalam mode edit
    try:
        if page.locator('text="Anda sedang mengedit assignment ini"').count() > 0 or \
           page.locator('text="Mode Edit"').count() > 0:
            print("[FASIH] Sudah berada dalam Mode Edit! Kuesioner siap diisi.")
            return True
    except Exception:
        pass

    # Ambil toolbar tombol (jika Skenario B dan pill_buttons >= 4 sudah ada, gunakan langsung tanpa tunggu!)
    pill_buttons_after = get_floating_pill_buttons(page)
    if len(pill_buttons_after) < 4 and len(pill_buttons) >= 4:
        pill_buttons_after = pill_buttons

    if len(pill_buttons_after) < 4:
        for _ in range(5):
            time.sleep(1)
            pill_buttons_after = get_floating_pill_buttons(page)
            if len(pill_buttons_after) >= 4:
                break

    print(f"[FASIH] Memeriksa tombol Edit: Toolbar memiliki {len(pill_buttons_after)} tombol.")

    # Tombol PALING BAWAH (pada toolbar 4-5 tombol) adalah tombol PENSIL (EDIT)!
    if len(pill_buttons_after) >= 4:
        tombol_pensil_edit = pill_buttons_after[-1]
        print("[FASIH] Mengklik tombol PENSIL (Edit Assignment) di toolbar kanan bawah...")
        try:
            tombol_pensil_edit.click()
        except Exception:
            time.sleep(1)
            try:
                get_floating_pill_buttons(page)[-1].click()
            except Exception:
                pass
        time.sleep(1.5)
    else:
        # Fallback tombol teks Edit Assignment
        edit_btn = page.locator('button:has-text("Edit Assignment"), button:has-text("Edit"), [title*="Edit" i]')
        if edit_btn.count() > 0 and edit_btn.first.is_visible():
            print("[FASIH] Mengklik tombol Edit Assignment teks...")
            edit_btn.first.click()
            time.sleep(1.5)
        elif len(pill_buttons_after) > 0:
            print("[FASIH] Mengklik tombol terbawah toolbar sebagai Edit...")
            pill_buttons_after[-1].click()
            time.sleep(1.5)

    # Tunggu Mode Edit aktif (maks 10 detik, poll tiap 0.5s)
    for _ in range(20):
        if page.locator('text="Anda sedang mengedit assignment ini", text="Mode Edit"').count() > 0:
            print("[FASIH] Berhasil masuk ke Mode Edit! Kuesioner siap diisi.")
            return True
        time.sleep(0.5)

    return True

def buka_blok_ii(page, nama_usaha=""):
    """Buka Blok II Keterangan Usaha dan pilih usaha yang cocok."""
    print("[FASIH] Membuka menu SE2026 - L BLOK II...")
    
    if cek_fasih_error(page):
        raise Exception("FASIH Error / Terdeteksi Bot WAF BPS")

    page.wait_for_selector('text="SE2026 - L BLOK II"', timeout=20000)
    blok_ii_elem = page.get_by_text("SE2026 - L BLOK II").first
    blok_ii_elem.click()
    time.sleep(2)

    if nama_usaha:
        # Bersihkan nama usaha dari kurung / karakter panah < ... >
        import re
        clean_nama = re.sub(r'[\<\>\(\)\[\]]', ' ', nama_usaha).strip()
        usaha_target = None
        
        # Coba nama lengkap
        loc = page.get_by_text(nama_usaha, exact=False)
        if loc.count() > 0 and loc.first.is_visible():
            usaha_target = loc.first
        else:
            # Coba kata-kata penting (panjang > 3 karakter)
            words = [w.strip() for w in clean_nama.split() if len(w.strip()) > 3]
            for w in words:
                loc_w = page.get_by_text(w, exact=False)
                if loc_w.count() > 0 and loc_w.first.is_visible():
                    usaha_target = loc_w.first
                    break

        if usaha_target:
            print(f"[FASIH] Memilih usaha: {nama_usaha}")
            usaha_target.click()
            time.sleep(2)
        else:
            # Jika nama spesifik tidak ditemukan, klik item/card usaha pertama di Blok II
            card_usaha = page.locator('div[role="button"]:has-text("KBLI"), tr:has-text("KBLI"), div:has-text("13. a. Nama Komersial")')
            if card_usaha.count() > 0 and card_usaha.first.is_visible():
                print("[FASIH] Memilih item usaha pertama di Blok II...")
                card_usaha.first.click()
                time.sleep(2)

def cek_kbli_kategori(page, kategori_target="G"):
    """
    Cek apakah kategori usaha sesuai dengan kategori target di FASIH:
    - Kategori G (Perdagangan): Kategori Lapangan Usaha 'G', KBLI berawalan 45, 46, 47.
    - Kategori A (Pertanian): Kategori Lapangan Usaha 'A', KBLI berawalan 01, 02, 03.
    """
    target = (kategori_target or "G").upper().strip()
    kategori_container = page.locator('div:has-text("13. h. Kategori Lapangan Usaha")').last
    if kategori_container.count() > 0:
        inp = kategori_container.locator('input')
        if inp.count() > 0:
            val = inp.input_value().strip().upper()
            if val:
                return val == target
        txt = kategori_container.inner_text().upper()
        if f"KATEGORI: {target}" in txt or f" {target} " in txt:
            return True

    kbli_container = page.locator('div:has-text("13. g. Kode KBLI")').last
    if kbli_container.count() > 0:
        txt_kbli = kbli_container.inner_text().strip()
        if target == "A":
            if any(txt_kbli.startswith(prefix) for prefix in ["01", "02", "03"]):
                return True
        elif target == "G":
            if any(txt_kbli.startswith(prefix) for prefix in ["45", "46", "47"]):
                return True

    return True

def cari_dan_isi_field(page, keyword_label, nilai_baru):
    """Mencari container pertanyaan berdasarkan teks label dan mengisi input di dalamnya."""
    containers = page.locator(f'div:has-text("{keyword_label}")')
    target_input = None
    target_container = None
    
    count = containers.count()
    for i in range(count - 1, -1, -1):
        c = containers.nth(i)
        inp = c.locator('input[type="text"], input:not([type="radio"]):not([type="checkbox"])')
        if inp.count() > 0:
            for j in range(inp.count()):
                single_inp = inp.nth(j)
                if single_inp.is_visible() and not single_inp.is_disabled():
                    target_input = single_inp
                    target_container = c
                    break
        if target_input:
            break

    # Jika input belum ditemukan atau masih ter-disable, ambil input pertama yang terlihat
    if not target_input:
        for i in range(count - 1, -1, -1):
            c = containers.nth(i)
            inp = c.locator('input')
            if inp.count() > 0 and inp.first.is_visible():
                target_input = inp.first
                target_container = c
                break

    if not target_input:
        print(f"[ERROR] Tidak dapat menemukan field input untuk: {keyword_label}")
        return False, None

    target_input.scroll_into_view_if_needed()
    time.sleep(0.5)

    nilai_lama = target_input.input_value()
    nilai_str = str(int(nilai_baru))
    
    target_input.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    time.sleep(0.2)
    page.keyboard.type(nilai_str, delay=random.randint(60, 140))
    time.sleep(0.5)

    nilai_terisi = target_input.input_value()
    print(f"  -> [{keyword_label}] Lama: {nilai_lama} -> Baru: {nilai_terisi} (Target: {nilai_str})")
    
    return True, target_container

def cari_container_isian_27a(page):
    """
    Mencari container pertanyaan untuk isian 27a (atau 31a untuk usaha beroperasi 2026),
    yaitu 'Nilai produksi/pendapatan/penjualan barang dan jasa'.
    Di sinilah remark #DC_01 WAJIB diletakkan sesuai instruksi reviewer.
    """
    keywords = ["27. a", "27.a", "27 a", "31. a", "31.a", "barang dan jasa"]
    for kw in keywords:
        containers = page.locator(f'div:has-text("{kw}")')
        count = containers.count()
        for i in range(count - 1, -1, -1):
            c = containers.nth(i)
            btn_cat = c.locator('button[title="Catatan"], button[aria-label="Catatan"]')
            if btn_cat.count() > 0 and btn_cat.first.is_visible():
                return c
            inp = c.locator('input[type="text"], input:not([type="radio"]):not([type="checkbox"])')
            if inp.count() > 0 and inp.first.is_visible():
                return c
    return None

def tambah_catatan_field(page, container, kode_catatan):
    """Menambahkan catatan (#DC_01 dst) pada pertanyaan yang diubah dengan aman (non-blocking)."""
    if not kode_catatan or not container:
        return True

    print(f"[FASIH] Mencoba menambahkan catatan '{kode_catatan}'...")
    try:
        # Cari tombol catatan yang benar-benar visible
        btn_catatan = None
        all_btns = container.locator('button[title="Catatan"], button[aria-label="Catatan"]').all()
        for b in all_btns:
            try:
                if b.is_visible():
                    btn_catatan = b
                    break
            except Exception:
                pass

        if not btn_catatan:
            print("[INFO] Tombol Catatan yang visible tidak ditemukan di field ini (dilewati).")
            return False

        btn_catatan.click(timeout=3000)
        time.sleep(1)

        dialog = page.locator('div[role="dialog"]').last
        if dialog.count() == 0 or not dialog.is_visible():
            print("[INFO] Modal catatan tidak terbuka (dilewati).")
            return False

        textarea = dialog.locator('textarea')
        if textarea.count() > 0 and textarea.first.is_visible():
            textarea.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(kode_catatan, delay=random.randint(60, 140))
            time.sleep(0.5)
            
            btn_simpan = dialog.locator('button:has-text("Simpan"), button[title="Simpan"]').first
            if btn_simpan.count() > 0 and btn_simpan.is_visible():
                btn_simpan.click(timeout=3000)
                time.sleep(1)
                print(f"[FASIH] Catatan '{kode_catatan}' tersimpan.")
                
            btn_close = dialog.locator('button[title="Dismiss"], button:has-text("Close")')
            if btn_close.count() > 0 and btn_close.first.is_visible():
                btn_close.first.click()
            else:
                page.keyboard.press("Escape")
            time.sleep(1)
            return True
    except Exception as e:
        print(f"[INFO] Catatan dilewati karena kendala UI: {e}")
        try:
            page.keyboard.press("Escape")
        except:
            pass
        return False

    return False

def buka_menu_catatan(page):
    """Navigasi ke menu CATATAN."""
    print("[FASIH] Navigasi ke menu CATATAN...")
    try:
        sidebar_catatan = page.locator('.fasih-form-sidebar [title="CATATAN"], div[title="CATATAN"]')
        if sidebar_catatan.count() > 0 and sidebar_catatan.first.is_visible():
            sidebar_catatan.first.click()
            time.sleep(2)
            return True
        
        c_text = page.get_by_text("CATATAN", exact=True)
        if c_text.count() > 0:
            for i in range(c_text.count()):
                el = c_text.nth(i)
                if el.is_visible():
                    el.click()
                    time.sleep(2)
                    return True

        btn_next = page.locator('button:has-text("BERIKUTNYA")')
        if btn_next.count() > 0 and btn_next.first.is_visible():
            if "CATATAN" in btn_next.first.inner_text().upper():
                btn_next.first.click()
                time.sleep(2)
                return True
    except Exception as e:
        print(f"[WARN] Kendala navigasi ke CATATAN: {e}")
    return False

def aktifkan_switch_anomali(page):
    """
    Memastikan toggle 'Tampilkan Anomali Usaha dan Keluarga' dalam posisi ON.
    HANYA mengaktifkan switch 'Tampilkan Anomali', TIDAK menyentuh switch 'anomali diselesaikan admin'.
    Menggunakan Playwright locator klik pada visual control div [id$="-control"].
    """
    print("[FASIH] Memeriksa switch 'Tampilkan Anomali Usaha dan Keluarga'...")
    try:
        for attempt in range(3):
            # 1. Cek status aria-checked pada input switch di baris tersebut
            status = page.evaluate('''() => {
                const allElements = Array.from(document.querySelectorAll('div, label, section, tr'));
                const targetContainer = allElements.reverse().find(el => {
                    const txt = el.textContent || '';
                    return txt.includes('Tampilkan Anomali') && !txt.includes('diselesaikan') && !txt.includes('admin');
                });
                if (targetContainer) {
                    const sw = targetContainer.querySelector('[role="switch"], input[type="checkbox"]');
                    if (sw) return sw.getAttribute("aria-checked") || "false";
                }
                return null;
            }''')

            if status == "true":
                print("[FASIH] Switch 'Tampilkan Anomali Usaha dan Keluarga' SUDAH AKTIF (aria-checked='true')!")
                return True

            print(f"[FASIH] Switch masih non-aktif (status: {status}). Mengklik kontrol switch (percobaan {attempt+1})...")

            # 2. Cari kontrol visual yang dapat diklik
            clicked = False
            ctrl = page.locator('div, section').filter(has_text="Tampilkan Anomali Usaha dan Keluarga").filter(has_not_text="admin").locator('[id$="-control"]').first
            if ctrl.count() > 0 and ctrl.is_visible():
                ctrl.click()
                clicked = True
            
            if not clicked:
                ctrl_global = page.locator('[id$="-control"]').first
                if ctrl_global.count() > 0 and ctrl_global.is_visible():
                    ctrl_global.click()
                    clicked = True

            if not clicked:
                grp = page.locator('[role="group"][id*="switch"]').first
                if grp.count() > 0 and grp.is_visible():
                    grp.click()
                    clicked = True

            time.sleep(1)

            # Cek status setelah klik
            status_after = page.evaluate('''() => {
                const allElements = Array.from(document.querySelectorAll('div, label, section, tr'));
                const targetContainer = allElements.reverse().find(el => {
                    const txt = el.textContent || '';
                    return txt.includes('Tampilkan Anomali') && !txt.includes('diselesaikan') && !txt.includes('admin');
                });
                if (targetContainer) {
                    const sw = targetContainer.querySelector('[role="switch"], input[type="checkbox"]');
                    if (sw) return sw.getAttribute("aria-checked") || "false";
                }
                return null;
            }''')

            if status_after == "true":
                print("[FASIH] Switch 'Tampilkan Anomali Usaha dan Keluarga' BERHASIL DIAKTIFKAN & TERVERIFIKASI!")
                return True

        print("[WARN] Switch anomali telah dicoba diklik, namun belum terkonfirmasi 'true'.")
        return False
    except Exception as e:
        print(f"[WARN] Kendala saat mengaktifkan switch anomali: {e}")
        return False

def proses_halaman_catatan_dan_tampilkan_anomali(page):
    """
    Rangkaian di halaman CATATAN sesuai instruksi user:
    1. Buka CATATAN
    2. Langsung tampilkan anomali usaha & keluarga (switch ON)
       - TIDAK PERLU klik 'Perbarui Waktu' / 'Ambil Waktu'!
       - TIDAK MENYENTUH switch 'anomali diselesaikan admin'!
    3. Selesai dan langsung siap submit.
    """
    print("\n" + "-" * 50)
    print("[FASIH] Halaman CATATAN: Langsung tampilkan anomali usaha & keluarga...")
    print("-" * 50)

    # 1. Buka CATATAN
    buka_menu_catatan(page)
    time.sleep(1)

    # 2. Hidupkan switch anomali (tanpa ambil waktu)
    aktifkan_switch_anomali(page)
    time.sleep(1)

    print("[FASIH] Pengaturan CATATAN selesai. Langsung siap kirim di halaman ini!")
    return True

def submit_assignment(page, max_retries=2):
    """
    Langsung cari tombol Kirim:
    - Cek di navbar atas
    - Jika tidak ada, cek tombol Kirim di kanan bawah
    - Klik Kirim -> modal ringkasan (klik Kirim) -> modal konfirmasi (klik Konfirmasi).
    """
    import re
    
    for attempt in range(1, max_retries + 1):
        print(f"\n[FASIH] Memulai proses submit assignment (Percobaan {attempt}/{max_retries})...")

        # 1. Cari tombol Kirim: Cek navbar atas dulu, jika tidak ada cari di kanan bawah
        klik_kirim_sukses = False

        # Opsi A: Di navbar / header atas
        nav_kirim = page.locator('nav button:has-text("Kirim"), header button:has-text("Kirim")')
        if nav_kirim.count() > 0 and nav_kirim.first.is_visible():
            print("[FASIH] Menemukan tombol Kirim di navbar atas. Mengklik tombol Kirim...")
            nav_kirim.first.click()
            klik_kirim_sukses = True
        else:
            # Opsi B: Di kanan bawah atau manapun yang terlihat di layar
            all_kirim = page.locator('button:has-text("Kirim")').all()
            for b in all_kirim:
                try:
                    if b.is_visible():
                        box = b.bounding_box()
                        pos = f"di posisi ({int(box['x'])}, {int(box['y'])})" if box else ""
                        print(f"[FASIH] Menemukan tombol Kirim {pos}. Mengklik tombol Kirim...")
                        b.click()
                        klik_kirim_sukses = True
                        break
                except Exception:
                    pass

        if not klik_kirim_sukses:
            print("[ERROR] Tombol Kirim tidak ditemukan di navbar maupun di kanan bawah.")
            if attempt == max_retries:
                return False
            time.sleep(2)
            continue

        time.sleep(2)

        # 2. Tunggu dialog Kirim muncul
        dialog = page.locator('div[role="dialog"]').last
        if dialog.count() == 0 or not dialog.is_visible():
            dialog = page.locator('.tw\\:fixed, .fixed, [role="dialog"]').last

        # 3. Periksa apakah ada Galat
        txt_dialog = dialog.inner_text().upper() if dialog.count() > 0 and dialog.is_visible() else ""
        ada_galat = False
        jumlah_galat = 0
        
        m = re.search(r'GALAT\s*[:\s]*(\d+)', txt_dialog)
        if m:
            jumlah_galat = int(m.group(1))
            if jumlah_galat > 0:
                ada_galat = True
                print(f"[PERINGATAN] Terdeteksi GALAT: {jumlah_galat} di dialog Kirim FASIH!")

        if ada_galat:
            print("[FASIH] Terdeteksi galat, membatalkan submit...")
            try:
                page.keyboard.press("Escape")
                time.sleep(1)
            except:
                pass
            return False

        # 4. Jika Galat == 0, klik tombol Kirim yang ada di dalam dialog modal
        print("[FASIH] Modal Kirim terbuka (GALAT: 0). Mengklik tombol Kirim di dalam dialog...")
        btns_in_dialog = dialog.locator('button:has-text("Kirim")')
        if btns_in_dialog.count() > 0:
            btns_in_dialog.last.click()
        else:
            btn_alter = dialog.locator('button:has-text("Ya"), button:has-text("Lanjutkan")').first
            if btn_alter.count() > 0 and btn_alter.is_visible():
                btn_alter.click()

        time.sleep(1.5)

        # 5. Cek popup konfirmasi lanjutan: 'Apakah Anda yakin ingin mengirim...?' -> Klik tombol 'Konfirmasi'
        print("[FASIH] Menunggu modal konfirmasi pengiriman ('Apakah Anda yakin ingin mengirim?')...")
        time.sleep(1.5)
        
        for _ in range(5):
            btn_konfirmasi_akhir = page.locator('div[role="dialog"] button:has-text("Konfirmasi"), button:has-text("Konfirmasi")').first
            if btn_konfirmasi_akhir.count() > 0 and btn_konfirmasi_akhir.is_visible():
                print("[FASIH] Tombol 'Konfirmasi' pengiriman ditemukan! Mengklik tombol 'Konfirmasi'...")
                btn_konfirmasi_akhir.click()
                time.sleep(3)
                break
            
            btn_ya2 = page.locator('div[role="dialog"] button:has-text("Ya"), div[role="dialog"] button:has-text("Lanjutkan")').first
            if btn_ya2.count() > 0 and btn_ya2.is_visible():
                print("[FASIH] Mengklik tombol 'Ya' konfirmasi pengiriman...")
                btn_ya2.click()
                time.sleep(3)
                break
            time.sleep(1)

        time.sleep(3)
        
        # 6. Verifikasi submit
        if page.locator('div[role="dialog"]:has-text("Kirim")').count() == 0:
            print("[FASIH] Assignment berhasil disubmit ke FASIH!")
            return True
        else:
            time.sleep(2)
            if page.locator('div[role="dialog"]:has-text("Kirim")').count() == 0:
                print("[FASIH] Assignment berhasil disubmit ke FASIH!")
                return True

    return False

def handle_waf_block(page, row, bot_code):
    """
    Menangani situasi ketika WAF BPS memblokir koneksi:
    a. Simpan screenshot + catat kode BOT ke tabel audit log
    b. Set status baris KEMBALI ke 'APPROVED' (bukan FAILED/FASIH_FORBIDDEN)
    c. Simpan timestamp blokir ke .waf_lock
    d. Cetak pesan jelas dengan saran cooldown 30 menit
    """
    aid = row['assignment_id']
    nama = row['nama_usaha']
    bot_code = bot_code or "BOT-DETECTED"
    conn = get_connection()
    try:
        ss_waf = os.path.join(SCREENSHOTS_DIR, f"WAF_BLOCK_{aid}_{bot_code}_{int(time.time())}.png")
        try:
            page.screenshot(path=ss_waf)
        except Exception:
            pass
        
        log_audit(aid, nama, "WAF_BOT_BLOCK", status_sebelumnya="APPROVED", status_baru="APPROVED", 
                  pesan=f"WAF bot detected: {bot_code}. Screenshot: {ss_waf}")
        
        # Status dikembalikan ke APPROVED agar bisa dieksekusi lagi nanti
        conn.execute("UPDATE kasus_nerwana SET status = 'APPROVED', alasan_review = NULL WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
        conn.commit()

        catat_waf_block(bot_code)

        print("\n" + "!" * 65)
        print("           [WAF BOT BLOCK TERDETEKSI!]")
        print("!" * 65)
        print(f"Kode BOT       : {bot_code}")
        print(f"Jam Kejadian   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Assignment     : {aid} ({nama})")
        print("Status Baris   : Dikembalikan ke 'APPROVED' (bukan kesalahan data)")
        print(f"Bukti Gambar   : {ss_waf}")
        print("TINDAKAN       : Menghentikan seluruh batch eksekusi segera!")
        print("SARAN          : Tunggu cooldown minimal 30 menit sebelum jalankan lagi.")
        print("!" * 65 + "\n")
    finally:
        conn.close()
    return "WAF_BLOCK", bot_code

def eksekusi_baris(page, row, dry_run=True, interaktif=False, isi_catatan=False, nerwana_updater=None, target_info=None, kategori="G"):
    aid = row['assignment_id']
    nama = row['nama_usaha']
    
    pbj_baru = row['nilai_baru_pbj']
    prod_baru = row['nilai_baru_prod']
    ops_baru = row['nilai_baru_ops']
    kode_catatan = row['kode_catatan'] or "#DC_01"
    
    print("\n" + "=" * 65)
    print(f"EKSEKUSI ASSIGNMENT: {aid} (KATEGORI {kategori})")
    print(f"Nama Usaha  : {nama}")
    print(f"PBJ Baru    : {pbj_baru:,.0f} (Lama: {row['pbj']:,.0f})")
    print(f"Prod Baru   : {prod_baru:,.0f} (Lama: {row['prod']:,.0f})")
    print(f"Ops Baru    : {ops_baru:,.0f} (Lama: {row['ops']:,.0f})")
    print(f"Catatan     : {kode_catatan if isi_catatan else '(dilewati saat testing)'}")
    print(f"Mode        : {'DRY-RUN (TIDAK SUBMIT)' if dry_run else 'SUBMIT SUNGGUHAN'}")
    print("=" * 65)

    conn = get_connection()
    try:
        # 0. Cek awal WAF bot
        is_waf, bot_code = cek_waf_bot(page)
        if is_waf:
            return handle_waf_block(page, row, bot_code)

        # 1. Pastikan tab FASIH selesai memuat & tidak ada SSO tertahan
        sel_pg = nerwana_updater.page if nerwana_updater else None
        l_btn = target_info.get('link_btn') if target_info else None
        sso_res, sso_bot = selesaikan_sso_pada_fasih(page, selancar_page=sel_pg, link_btn=l_btn)
        if sso_res == "WAF":
            return handle_waf_block(page, row, sso_bot)
        elif sso_res == "SSO_LIMIT_EXCEEDED":
            return "SSO_LIMIT_EXCEEDED", None

        ready_res, ready_bot = wait_fasih_ready(page, selancar_page=sel_pg, link_btn=l_btn)
        if ready_res == "WAF":
            return handle_waf_block(page, row, ready_bot)
        elif ready_res in ["ERROR", "TIMEOUT", "CLOSED"] or cek_fasih_error(page):
            print(f"[SKIP] Assignment '{aid}' ({nama}) menampilkan error FASIH biasa (Forbidden / 403). Dilewati!")
            conn.execute("UPDATE kasus_nerwana SET status = 'FASIH_FORBIDDEN', alasan_review = 'Forbidden / Error akses FASIH' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
            conn.commit()
            log_audit(aid, nama, "FASIH_FORBIDDEN", status_sebelumnya="APPROVED", status_baru="FASIH_FORBIDDEN", pesan="Forbidden di FASIH")
            return "SKIPPED_FASIH_ERROR", None

        # 2. Lakukan Revoke & Masuk Mode Edit (klik tombol pensil)
        lakukan_revoke_dan_edit(page)
        
        # Cek WAF setelah revoke
        is_waf, bot_code = cek_waf_bot(page)
        if is_waf:
            return handle_waf_block(page, row, bot_code)

        # JEDA SINGKAT 0.5 detik setelah revoke
        time.sleep(0.5)

        # 3. Buka Blok II
        buka_blok_ii(page, nama)

        # 4. Validasi KBLI / Kategori (G atau A)
        is_kat_cocok = cek_kbli_kategori(page, kategori_target=kategori)
        if not is_kat_cocok:
            print(f"[ABORT] KBLI/Kategori terdeteksi BUKAN Kategori {kategori}. Menghentikan baris ini.")
            conn.execute("UPDATE kasus_nerwana SET status = 'KBLI_MISMATCH' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
            conn.commit()
            log_audit(aid, nama, "KBLI_CHECK", status_sebelumnya="APPROVED", status_baru="KBLI_MISMATCH", pesan=f"Kategori di FASIH bukan {kategori}")
            return "KBLI_MISMATCH", None

        # 5. Isi Nilai Baru (dengan event keyboard natural)
        c_pbj_found = None
        if prod_baru != row['prod']:
            cari_dan_isi_field(page, "Biaya produksi", prod_baru)

        if ops_baru != row['ops']:
            cari_dan_isi_field(page, "Biaya operasional", ops_baru)

        if pbj_baru != row['pbj']:
            ok_pbj, c_pbj = cari_dan_isi_field(page, "barang dan jasa", pbj_baru)
            if ok_pbj: c_pbj_found = c_pbj

        # JEDA SINGKAT 0.5 detik setelah isi nilai
        time.sleep(0.5)

        # 6. Tambah Catatan jika diaktifkan (WAJIB DI ISIAN 27a)
        if isi_catatan:
            catatan_final = kode_catatan or "#DC_01"
            c_target_27a = c_pbj_found or cari_container_isian_27a(page)
            if c_target_27a:
                print(f"[FASIH] Menambahkan remark '{catatan_final}' pada Isian 27a (Nilai Produksi/PBJ)...")
                tambah_catatan_field(page, c_target_27a, catatan_final)
            else:
                print(f"[WARN] Container Isian 27a tidak ditemukan untuk menambahkan catatan '{catatan_final}'.")
        elif not isi_catatan:
            print("[INFO] Pengisian catatan dilewati sesuai opsi testing (fokus isi form nilai).")

        # 7. Selesaikan di halaman Catatan: Tampilkan Anomali Usaha dan Keluarga
        proses_halaman_catatan_dan_tampilkan_anomali(page)

        # 8. Konfirmasi Interaktif (jika diaktifkan)
        if interaktif:
            print("\n" + "-" * 60)
            print("[KONFIRMASI MANUAL] Form telah terisi di browser!")
            if dry_run:
                print("PENTING: Ini mode DRY-RUN, tombol Kirim TIDAK akan ditekan!")
                print("Silakan cek browser Chrome Anda untuk memastikan nilainya benar.")
                jawab = input("Apakah nilai sudah sesuai dan ingin menyelesaikan dry-run? [y/n]: ").strip().lower()
                if jawab != 'y':
                    print("[INFO] Dibatalkan oleh reviewer.")
                    return "CANCELLED", None
            else:
                print("PERHATIAN: Ini mode SUBMIT SUNGGUHAN!")
                print("Tombol Kirim di FASIH akan ditekan & status di Selancar Nerwana akan diubah menjadi 'Sudah direvisi'!")
                jawab = input("Apakah Anda yakin ingin submit baris ini ke FASIH dan Selancar? [y/n]: ").strip().lower()
                if jawab != 'y':
                    print("[INFO] Dibatalkan oleh reviewer.")
                    return "CANCELLED", None

        # JEDA SINGKAT 0.5 detik sebelum Kirim / Finalisasi
        time.sleep(0.5)

        # 9. Submit atau Dry-run
        if dry_run:
            try:
                ss_path = os.path.join(SCREENSHOTS_DIR, f"dryrun_{aid}_{int(time.time())}.png")
                page.screenshot(path=ss_path, timeout=5000)
                print(f"[DRY-RUN SUKSES] Screenshot bukti disimpan ke: {ss_path}")
            except Exception:
                pass
            print("[INFO] Sesuai mode dry-run, tombol Kirim TIDAK ditekan.")
            
            conn.execute("UPDATE kasus_nerwana SET status = 'APPLIED' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
            conn.commit()
            log_audit(aid, nama, "DRY_RUN_APPLIED", 
                      nilai_lama={'pbj': row['pbj'], 'prod': row['prod'], 'ops': row['ops']},
                      nilai_baru={'pbj': pbj_baru, 'prod': prod_baru, 'ops': ops_baru},
                      kode_catatan=kode_catatan, status_sebelumnya="APPROVED", status_baru="APPLIED")
            return "APPLIED", None
        else:
            submit_ok = submit_assignment(page)
            if submit_ok:
                try:
                    ss_path = os.path.join(SCREENSHOTS_DIR, f"submitted_{aid}_{int(time.time())}.png")
                    page.screenshot(path=ss_path, timeout=5000)
                except Exception as e_ss:
                    print(f"[INFO] Melewati screenshot bukti (halaman sedang reload pasca submit): {e_ss}")
                
                conn.execute("UPDATE kasus_nerwana SET status = 'SUBMITTED' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
                conn.commit()
                log_audit(aid, nama, "SUBMIT_FASIH", 
                      nilai_lama={'pbj': row['pbj'], 'prod': row['prod'], 'ops': row['ops']},
                      nilai_baru={'pbj': pbj_baru, 'prod': prod_baru, 'ops': ops_baru},
                      kode_catatan=kode_catatan, status_sebelumnya="APPROVED", status_baru="SUBMITTED")

                # Otomatis Update Tindak Lanjut ke Selancar Nerwana menjadi 'sudah_direvisi'
                from updater_nerwana import set_tindak_lanjut_selancar
                print("[SELANCAR] Menyelesaikan tindak lanjut di tabel Selancar menjadi 'Sudah direvisi'...")
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status="sudah_direvisi")
                conn.execute("UPDATE kasus_nerwana SET tindak_lanjut = 'sudah_direvisi', status = 'COMPLETED' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
                conn.commit()

                return "SUBMITTED", None
            else:
                # Periksa apakah gagal karena WAF
                is_waf, bot_code = cek_waf_bot(page)
                if is_waf:
                    return handle_waf_block(page, row, bot_code)
                raise Exception("Gagal klik / verifikasi submit FASIH")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Eksekusi gagal: {e}")
        ss_fail = os.path.join(SCREENSHOTS_DIR, f"FAILED_{aid}_{int(time.time())}.png")
        try: page.screenshot(path=ss_fail)
        except: pass
        print(f"[SCREENSHOT] Bukti kegagalan disimpan ke: {ss_fail}")
        
        # 1. Cek WAF bot TERLEBIH DAHULU
        is_waf, bot_code = cek_waf_bot(page)
        if is_waf or "bot" in str(e).lower():
            return handle_waf_block(page, row, bot_code)

        # 2. Cek Forbidden biasa
        if cek_fasih_error(page) or "forbidden" in str(e).lower():
            print(f"[SKIP] Assignment '{aid}' ({nama}) tidak dapat diakses di FASIH (Forbidden). Dilewati!")
            conn.execute("UPDATE kasus_nerwana SET status = 'FASIH_FORBIDDEN', alasan_review = ? WHERE assignment_id = ? AND nama_usaha = ?", (str(e), aid, nama))
            conn.commit()
            log_audit(aid, nama, "FASIH_FORBIDDEN", status_sebelumnya="APPROVED", status_baru="FASIH_FORBIDDEN", pesan=str(e))
            return "SKIPPED_FASIH_ERROR", None

        conn.execute("UPDATE kasus_nerwana SET status = 'FAILED', alasan_review = ? WHERE assignment_id = ? AND nama_usaha = ?", (str(e), aid, nama))
        conn.commit()
        log_audit(aid, nama, "EXECUTION_FAILED", status_sebelumnya="APPROVED", status_baru="FAILED", pesan=str(e))
        return "FAILED", None
    finally:
        conn.close()

def main():
    print("=" * 65)
    print("           FASE 3: EKSEKUTOR FASIH (PLAYWRIGHT)")
    print("=" * 65)
    
    # Bersihkan screenshot lama agar disk tetap ramping
    cleanup_old_screenshots(max_keep=30)
    
    # 0. PERIKSA APAKAH SEDANG DALAM COOLDOWN WAF
    is_locked, sisa_detik, bot_code, jam_blokir = cek_waf_cooldown()
    if is_locked:
        menit = sisa_detik // 60
        detik = sisa_detik % 60
        print("\n" + "!" * 65)
        print("           [WAF COOLDOWN AKTIF - EKSEKUSI DITOLAK]")
        print("!" * 65)
        print(f"Blokir Terakhir: {bot_code} pada {jam_blokir}")
        print(f"Sisa Cooldown  : {menit} menit {detik} detik.")
        print("Saran: Tunggu sampai cooldown selesai sebelum menjalankan bot kembali")
        print("       agar sesi browser dan koneksi aman dari pembatasan WAF.")
        print("!" * 65 + "\n")
        return

    if not start_debug_chrome():
        return

    try:
        from sync_review import sync_excel_to_db
        sync_excel_to_db()
    except Exception as e_sync:
        print(f"[INFO] Sinkronisasi Excel dilewati / opsional: {e_sync}")

    conn = get_connection()
    approved_count = conn.execute("SELECT COUNT(*) FROM kasus_nerwana WHERE status = 'APPROVED'").fetchone()[0]
    conn.close()

    print(f"\n[STATUS] Database lokal memiliki {approved_count} baris APPROVED tersimpan.")
    if approved_count == 0:
        print("[PERINGATAN] Belum ada data berstatus 'APPROVED' di database lokal!")
        print("             Pastikan file 'review_usulan.xlsx' ada di folder bot dan")
        print("             kolom 'Approved (Y/N)' sudah diisi 'Y' agar dapat dieksekusi.")
    print("         Mode LIVE ON-THE-FLY aktif: Bot memeriksa langsung baris di tabel Selancar")
    print("         secara urut di layar (tanpa scraping awal & tanpa lompat-lompat).")

    print("\nPilih Kategori Lapangan Usaha:")
    print("  [1] Kategori G - Perdagangan (Threshold 0.64 - 0.78) [Default]")
    print("  [2] Kategori A - Pertanian (Threshold 0.51 - 0.94)")
    kat_choice = input("Masukkan pilihan kategori [1/2] (default 1 - G): ").strip() or "1"
    kategori_aktif = "A" if kat_choice == "2" else "G"
    print(f"[KATEGORI AKTIF] Menggunakan Kategori {kategori_aktif}")

    print("\nPilih Mode Operasi:")
    print("  [1] Uji 1 Baris Pertama - DRY-RUN (Isi form tapi TIDAK submit, konfirmasi manual)")
    print("  [2] Uji 1 Baris Pertama - SUBMIT SUNGGUHAN (Kirim ke server FASIH & update Selancar)")
    print("  [3] Eksekusi Batch DRY-RUN (Batas 1-50 baris, tanpa submit)")
    print("  [4] Eksekusi Batch SUBMIT SUNGGUHAN (Batas 1-50 baris, submit)")
    
    pilihan = input("\nMasukkan pilihan [1/2/3/4] (default 1): ").strip() or "1"
    
    dry_run = True
    interaktif = False
    limit = 1

    if pilihan == "1":
        dry_run = True
        interaktif = True
        limit = 1
    elif pilihan == "2":
        dry_run = False
        interaktif = True
        limit = 1
    elif pilihan == "3":
        dry_run = True
        interaktif = False
        limit_str = input(f"Berapa jumlah baris batch dry-run? (1-50, default 10, maks 50): ").strip() or "10"
        limit = max(1, min(int(limit_str), 50))
    elif pilihan == "4":
        dry_run = False
        interaktif = False
        limit_str = input(f"Berapa jumlah baris batch submit? (1-50, default 10, maks 50): ").strip() or "10"
        limit = max(1, min(int(limit_str), 50))

    tanya_catatan = True
    if pilihan in ["1", "3"]:
        jawab_c = input("Sertakan penulisan catatan (#DC_01) pada isian 27.a? [y/n] (default y): ").strip().lower()
        tanya_catatan = (jawab_c != "n")
    else:
        tanya_catatan = True

    with sync_playwright() as p:
        print(f"\n[CDP] Menghubungkan ke browser Chrome (port 9222)...")
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]

        from updater_nerwana import (
            NerwanaManager, 
            buka_dan_siapkan_selancar, 
            cari_target_di_tabel_selancar, 
            lanjut_halaman_berikutnya_selancar
        )
        nerwana_updater = NerwanaManager(context)
        selancar_page = nerwana_updater.get_or_create_page()

        # 1. Buka dan siapkan Selancar: Landing -> DC Terkena Flag -> Kategori Aktif
        buka_dan_siapkan_selancar(selancar_page, kategori=kategori_aktif)

        session_skip_aids = set()
        sukses = 0
        gagal = 0
        di_skip = 0
        waf_terdeteksi = False
        waf_bot_code = ""

        # Pakai ulang SATU tab FASIH (tidak buka tutup tab per assignment)
        fasih_page = None

        while sukses < limit:
            conn = get_connection()
            # 2. Cari baris di tabel Selancar secara urut (baris 1, 2, dst)
            target_info = cari_target_di_tabel_selancar(selancar_page, conn, session_skip_aids=session_skip_aids, kategori=kategori_aktif)
            conn.close()

            while not target_info:
                pindah = lanjut_halaman_berikutnya_selancar(selancar_page)
                if not pindah:
                    break
                conn = get_connection()
                target_info = cari_target_di_tabel_selancar(selancar_page, conn, session_skip_aids=session_skip_aids, kategori=kategori_aktif)
                conn.close()

            if not target_info:
                print(f"\n[INFO] Tidak ada lagi baris yang perlu dikerjakan di tabel Selancar Kategori {kategori_aktif} saat ini.")
                break

            row = target_info['db_row']
            link_btn = target_info['link_btn']
            nama = target_info['nama']
            aid = target_info['aid']

            print(f"\n>>> Memproses Target [{sukses + 1}/{limit}] (Total dicek: {sukses + gagal + di_skip + 1}) <<<")
            print(f"[SELANCAR] Target ditemukan di tabel: '{nama}' (AID: {aid})")

            # 2.5 Ubah status di Selancar menjadi 'Akan direvisi' sebelum membuka tab FASIH
            from updater_nerwana import set_tindak_lanjut_selancar
            print(f"[SELANCAR] Menandai assignment '{nama}' (AID: {aid}) menjadi 'Akan direvisi' sebelum membuka FASIH...")
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status="akan_direvisi")
            time.sleep(0.8)

            # 3. Buka tab FASIH dari baris tabel di Selancar
            # Bersihkan tab FASIH lama jika masih ada yang terbuka
            for pg in context.pages:
                try:
                    if not pg.is_closed() and "fasih-sm.bps.go.id" in pg.url.lower():
                        pg.close()
                except Exception:
                    pass
            fasih_page = None

            print("[SELANCAR] Membuka tab FASIH dari baris tabel Selancar...")
            link_btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            try:
                with context.expect_page(timeout=20000) as new_page_info:
                    link_btn.click()
                fasih_page = new_page_info.value
            except Exception as e_click:
                print(f"[WARN] Tab baru tidak tertangkap via expect_page: {e_click}. Mencari tab FASIH...")
                fasih_pages = [pg for pg in context.pages if "fasih" in pg.url.lower() and not pg.is_closed()]
                if fasih_pages:
                    fasih_page = fasih_pages[-1]

            if not fasih_page or fasih_page.is_closed():
                print("[ERROR] Gagal membuka/menghubungkan tab FASIH. Mencoba baris berikutnya...")
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                gagal += 1
                continue

            # Tunggu halaman FASIH selesai initial load/redirect
            try:
                fasih_page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            time.sleep(1.5)

            # 4. Eksekusi form di tab FASIH
            hasil, info = eksekusi_baris(
                fasih_page, 
                row, 
                dry_run=dry_run, 
                interaktif=interaktif, 
                isi_catatan=tanya_catatan, 
                nerwana_updater=nerwana_updater,
                target_info=target_info,
                kategori=kategori_aktif
            )

            # Sesuai instruksi: selesai submit / selesai eksekusi, tutup tab FASIH
            try:
                if fasih_page and not fasih_page.is_closed():
                    print("[FASIH] Selesai submit / eksekusi. Menutup tab FASIH...")
                    fasih_page.close()
            except Exception as e_close:
                print(f"[WARN] Gagal menutup tab FASIH: {e_close}")
            fasih_page = None

            # Kembalikan fokus ke tab Selancar
            try:
                if selancar_page and not selancar_page.is_closed():
                    selancar_page.bring_to_front()
            except Exception:
                pass

            # EVALUASI HASIL:
            if hasil == "WAF_BLOCK":
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                waf_terdeteksi = True
                waf_bot_code = info or "BOT-DETECTED"
                print("\n[CIRCUIT BREAKER] Program dihentikan total karena WAF bot terdeteksi.")
                break
            elif hasil == "SSO_LIMIT_EXCEEDED":
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                print("\n[SSO STOP] Batch dihentikan karena SSO memerlukan intervensi login manual.")
                break
            elif hasil in ["APPLIED", "SUBMITTED"]:
                sukses += 1
                session_skip_aids.add(aid)
                if sukses < limit:
                    # JEDA WAJAR: 4-7 detik acak antar assignment
                    jeda = random.uniform(4.0, 7.0)
                    print(f"[JEDA] Menunggu {jeda:.1f} detik sebelum assignment berikutnya...")
                    time.sleep(jeda)
            elif hasil in ["SKIPPED_FASIH_ERROR", "KBLI_MISMATCH", "CANCELLED"]:
                di_skip += 1
                session_skip_aids.add(aid)
                print(f"[SELANCAR] Mengembalikan status assignment '{nama}' ke semula karena tidak disubmit...")
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                if hasil == "CANCELLED":
                    print("[INFO] Eksekusi dihentikan oleh reviewer.")
                    break
                time.sleep(random.uniform(1.5, 3.0))
            else:
                gagal += 1
                session_skip_aids.add(aid)
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                if pilihan in ["1", "2"]:
                    break

        print("\n" + "=" * 65)
        print("RINGKASAN EKSEKUSI:")
        print(f"Target Berhasil : {sukses} / {limit}")
        print(f"Dilewati (Skip) : {di_skip} (Sudah selesai di Selancar / KBLI mismatch / Forbidden biasa)")
        print(f"Gagal/Batal     : {gagal}")
        print(f"Berhenti WAF    : {'YA (' + waf_bot_code + ')' if waf_terdeteksi else 'TIDAK'}")
        if sukses >= limit and limit > 1 and not waf_terdeteksi:
            print(f"[INFO] Batch 1 sesi selesai (target {limit} baris terpenuhi). Silakan jalankan lagi nanti.")
        print("=" * 65)

if __name__ == "__main__":
    main()
