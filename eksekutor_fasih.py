import os
import sys
import time
import socket
import subprocess
import random
import re
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

from database import get_connection, log_audit
from config import (
    TOL_RASIO_SELANCAR,
    FAKTOR_KALI,
    FAKTOR_BAGI,
    CAP_NILAI_BARU,
    MAX_ERR_BERTURUT,
    N_INTERAKTIF_AWAL,
    STATUS_FINAL,
    STATUS_ERROR_TEKNIS,
    JEDA_ANTAR_ASSIGNMENT_MIN,
    JEDA_ANTAR_ASSIGNMENT_MAX,
    WAF_COOLDOWN_SECONDS,
)
from kalkulator_usulan import evaluasi

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
        try:
            if page.locator('div:has-text("Anda sedang mengedit assignment ini"), div:has-text("Mode Edit")').count() > 0:
                print("[FASIH] Berhasil masuk ke Mode Edit! Kuesioner siap diisi.")
                return True
        except Exception:
            pass
        time.sleep(0.5)


    return True

def buka_blok_ii(page, nama_usaha=""):
    """Buka Blok II Keterangan Usaha dan pilih usaha yang cocok. Mengembalikan (sukses: bool, idx_usaha: int)."""
    print("[FASIH] Membuka menu SE2026 - L BLOK II...")
    
    if cek_fasih_error(page):
        raise Exception("FASIH Error / Terdeteksi Bot WAF BPS")

    page.wait_for_selector('text="SE2026 - L BLOK II"', timeout=20000)
    blok_ii_elem = page.get_by_text("SE2026 - L BLOK II").first
    blok_ii_elem.click()
    time.sleep(1.5)

    # 1. Pastikan submenu Keterangan Usaha/Perusahaan terbuka jika berbentuk collapsible
    try:
        sub_ket = page.locator('.fasih-form-sidebar div[title*="Keterangan Usaha/Perusahaan"], div[title="Keterangan Usaha/Perusahaan"]').first
        if sub_ket.count() > 0 and sub_ket.is_visible():
            parent_col = sub_ket.locator('..')
            if parent_col.locator('[data-closed]').count() > 0:
                print("[FASIH] Membuka collapsible submenu Keterangan Usaha/Perusahaan...")
                sub_ket.click()
                time.sleep(1.0)
    except Exception:
        pass

    # 2. Cari item usaha yang cocok
    if nama_usaha:
        import re
        # Bersihkan nama usaha dari kurung sudut / kurung biasa < ... > atau ( ... )
        # Contoh: "USAHA PERTENAKAN KAMBING <CATUR SETIWAN>" -> "USAHA PERTENAKAN KAMBING"
        nama_tanpa_kurung = re.sub(r'<[^>]*>|\([^)]*\)|\[[^\]]*\]', '', nama_usaha).strip()
        # Ekstrak nama pengusaha di dalam kurung jika ada
        m_owner = re.search(r'<([^>]+)>|\(([^)]+)\)', nama_usaha)
        owner_name = (m_owner.group(1) or m_owner.group(2)).strip() if m_owner else ""

        print(f"[FASIH] Mencocokkan nama usaha: '{nama_tanpa_kurung}' (Nama lengkap: '{nama_usaha}')")
        usaha_target = None

        # Strategi A: Cari di sidebar dengan title mengandung nama_tanpa_kurung
        if nama_tanpa_kurung:
            loc = page.locator(f'.fasih-form-sidebar div[title*="{nama_tanpa_kurung}" i], div[role="button"][title*="{nama_tanpa_kurung}" i]').first
            if loc.count() > 0 and loc.is_visible():
                usaha_target = loc

        # Strategi B: Cari di sidebar dengan title nama lengkap
        if not usaha_target:
            loc = page.locator(f'.fasih-form-sidebar div[title*="{nama_usaha}" i]').first
            if loc.count() > 0 and loc.is_visible():
                usaha_target = loc

        # Strategi C: Cari di sidebar dengan nama pemilik (mis. CATUR SETIWAN)
        if not usaha_target and owner_name:
            loc = page.locator(f'.fasih-form-sidebar div[title*="{owner_name}" i]').first
            if loc.count() > 0 and loc.is_visible():
                usaha_target = loc

        # Strategi D: Gunakan kata kunci unik (abaikan stopwords umum seperti USAHA, TOKO, WARUNG, UTP, dsb.)
        if not usaha_target:
            stopwords = {"USAHA", "TOKO", "WARUNG", "PERTANIAN", "PERKEBUNAN", "PETERNAKAN", "PERTENAKAN", "UTP", "TANI", "KETERANGAN", "PERUSAHAAN"}
            words = [w.strip() for w in re.sub(r'[\<\>\(\)\[\]]', ' ', nama_usaha).split() if len(w.strip()) >= 4]
            unique_words = [w for w in words if w.upper() not in stopwords]
            search_words = unique_words if unique_words else words
            search_words.sort(key=len, reverse=True)

            for w in search_words:
                loc_w = page.locator(f'.fasih-form-sidebar div[title*="{w}" i]:not([title^="SE2026"]):not([title*="Keterangan Usaha/Perusahaan"])').first
                if loc_w.count() > 0 and loc_w.is_visible():
                    usaha_target = loc_w
                    break

        if usaha_target:
            txt_target = usaha_target.get_attribute("title") or usaha_target.inner_text()
            print(f"[FASIH] Memilih item usaha di Blok II: '{txt_target.strip()}'")
            usaha_target.click()
            time.sleep(2)
        else:
            # Fallback: Klik item usaha pertama di daftar usaha Blok II (bukan header menu)
            item_pertama = page.locator('.fasih-form-sidebar div[title]:not([title^="SE2026"]):not([title*="Keterangan Usaha"]):not([title*="KETERANGAN"])').first
            if item_pertama.count() > 0 and item_pertama.is_visible():
                txt_p = item_pertama.get_attribute("title") or ""
                print(f"[FASIH] Memilih item usaha pertama di sidebar Blok II: '{txt_p.strip()}'...")
                item_pertama.click()
                time.sleep(2)
            else:
                card_usaha = page.locator('div[role="button"]:has-text("KBLI"), tr:has-text("KBLI"), div:has-text("13. a. Nama Komersial")').first
                if card_usaha.count() > 0 and card_usaha.first.is_visible():
                    print("[FASIH] Memilih item card usaha pertama di konten Blok II...")
                    card_usaha.click()
                    time.sleep(2)


    # Tunggu render kuesioner usaha selesai dimuat
    for _ in range(12):
        try:
            if page.locator("[id^='nilai_pendapatan_bln#']:visible, [id^='biaya_produksi_bln#']:visible, [id^='kategori#']:visible").count() > 0:
                break
            if page.locator('div:has-text("31. a"), div:has-text("27. a")').count() > 0:
                break
        except Exception:
            pass
        time.sleep(0.5)

    # Deteksi idx usaha aktif dari container yang visible (misal #1, #2, #1001)
    idx = 1
    try:
        vis_cont = page.locator("[id^='nilai_pendapatan_bln#']:visible, [id^='biaya_produksi_bln#']:visible, [id^='kategori#']:visible").first
        if vis_cont.count() > 0:
            c_id = vis_cont.get_attribute("id") or ""
            m_idx = re.search(r'#(\d+)', c_id)
            if m_idx:
                idx = int(m_idx.group(1))
    except Exception:
        pass
    print(f"[FASIH] Indeks usaha aktif di Blok II terdeteksi: #{idx}")
    return True, idx

def deteksi_blok(page, timeout=8) -> str:
    """
    Mendeteksi jenis blok di Blok II FASIH (Tugas 1):
    - 'usaha_2026': terdapat container id nilai_pendapatan_bln#N atau biaya_produksi_bln#N (isian 30/31)
    - 'biasa': terdapat isian 27/28
    - 'unknown': tidak dapat dideteksi setelah batas timeout
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Usaha beroperasi 2026 (isian 30/31)
            if page.locator("[id^='nilai_pendapatan_bln#'], [id^='biaya_produksi_bln#']").count() > 0:
                return "usaha_2026"
            if page.locator('div:has-text("31. a"), div:has-text("31.a")').count() > 0:
                return "usaha_2026"
                
            # Usaha biasa (isian 26/27/28)
            if page.locator('div:has-text("27. a"), div:has-text("27.a"), div:has-text("26. a")').count() > 0:
                return "biasa"
        except Exception:
            pass
        time.sleep(0.5)

    return "unknown"



def baca_nilai_fasih(page, blok, idx=1) -> dict:
    """
    Membaca nilai dari isian FASIH berdasarkan nomor pertanyaan / ID container (PRD §5 FR-3 & Tugas 1).
    Mengembalikan dict:
    {
        'ok': bool,
        'pbj': float,
        'prod': float,
        'ops': float,
        'beli': float,
        'bulan_beroperasi': int,     # Khusus usaha 2026 (isian 31.e)
        'kategori': str,             # Dari isian 13.h
        'kbli': str,                 # Dari isian 13.g
        'error': str,
        'field_locators': dict       # Locator input untuk tiap field
    }
    Jika ada field wajib yang tidak terbaca -> ok = False, error diset.
    """
    res = {
        'ok': True,
        'pbj': 0.0,
        'prod': 0.0,
        'ops': 0.0,
        'beli': 0.0,
        'bulan_beroperasi': 1,
        'kategori': '',
        'kbli': '',
        'error': '',
        'field_locators': {}
    }

    def _clean_num(val_str):
        if not val_str:
            return 0.0
        c = re.sub(r'[^\d]', '', str(val_str).strip())
        return float(c) if c else 0.0

    # 1. Baca Kategori (13.h) dan KBLI (13.g)
    try:
        kat_loc = page.locator(f'[id="kategori#{idx}"], div:has-text("13. h. Kategori")').last
        if kat_loc.count() > 0:
            inp_kat = kat_loc.locator('input')
            if inp_kat.count() > 0:
                res['kategori'] = inp_kat.first.input_value().strip().upper()
            if not res['kategori']:
                txt = kat_loc.inner_text().upper()
                m_kat = re.search(r'KATEGORI\s*:?\s*([A-U])\b', txt)
                if m_kat:
                    res['kategori'] = m_kat.group(1)

        kbli_loc = page.locator(f'[id="kbli_genai#{idx}"], [id="kbli#{idx}"], div:has-text("13. g. Kode KBLI")').last
        if kbli_loc.count() > 0:
            checked_radio = kbli_loc.locator('input[type="radio"]:checked')
            if checked_radio.count() > 0:
                res['kbli'] = checked_radio.first.get_attribute('value') or ''
            if not res['kbli']:
                txt_kbli = kbli_loc.inner_text()
                m_kbli = re.search(r'\b(\d{5})\b', txt_kbli)
                if m_kbli:
                    res['kbli'] = m_kbli.group(1)
    except Exception as e:
        print(f"[WARN] Error membaca KBLI/Kategori: {e}")

    # 2. Baca angka berdasarkan jenis blok
    if blok == "usaha_2026":
        # Container ID spesifik dari blok_ii_opened.html (Tugas 1)
        # 31.a = nilai_pendapatan_bln#N
        # 30.b = biaya_produksi_bln#N
        # 30.d = operasional_bln#N
        # 30.c = biaya_pembelian_bln#N (Kategori G / barang dagangan)
        # 31.e = bln_operasi#N
        c_pbj = page.locator(f'[id="nilai_pendapatan_bln#{idx}"]')
        c_prod = page.locator(f'[id="biaya_produksi_bln#{idx}"]')
        c_ops = page.locator(f'[id="operasional_bln#{idx}"]')
        c_beli = page.locator(f'[id="biaya_pembelian_bln#{idx}"]')
        c_bln = page.locator(f'[id="bln_operasi#{idx}"]')

        if c_pbj.count() == 0:
            res['ok'] = False
            res['error'] = f"Container 31.a [id='nilai_pendapatan_bln#{idx}'] tidak ditemukan"
            return res

        if c_prod.count() == 0:
            res['ok'] = False
            res['error'] = f"Container 30.b [id='biaya_produksi_bln#{idx}'] tidak ditemukan"
            return res

        if c_ops.count() == 0:
            res['ok'] = False
            res['error'] = f"Container 30.d [id='operasional_bln#{idx}'] tidak ditemukan"
            return res

        try:
            inp_pbj = c_pbj.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
            inp_prod = c_prod.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
            inp_ops = c_ops.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first

            res['pbj'] = _clean_num(inp_pbj.input_value())
            res['prod'] = _clean_num(inp_prod.input_value())
            res['ops'] = _clean_num(inp_ops.input_value())

            res['field_locators']['pbj'] = inp_pbj
            res['field_locators']['prod'] = inp_prod
            res['field_locators']['ops'] = inp_ops

            # Field 30.c (pembelian barang untuk dijual):
            if c_beli.count() > 0:
                inp_beli = c_beli.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
                if inp_beli.count() > 0:
                    res['beli'] = _clean_num(inp_beli.input_value())
                    res['field_locators']['beli'] = inp_beli
            else:
                # TODO: Field 30.c (pembelian barang yang dijual, Kategori G) belum ada dumpnya.
                # Jika kategori adalah G tetapi 30.c tidak ada di DOM, tandai untuk verifikasi dump HTML.
                if res['kategori'] == 'G':
                    print("[TODO] Field 30.c (pembelian barang dagangan) Kategori G belum ada dump HTML-nya.")

            # Baca bulan beroperasi (31.e - Tugas 7)
            if c_bln.count() > 0:
                cbs = c_bln.locator('input[type="checkbox"]').all()
                checked_count = sum(1 for cb in cbs if cb.is_checked())
                res['bulan_beroperasi'] = max(1, checked_count)
            else:
                res['bulan_beroperasi'] = 1

            # Baca Nilai Aset Tanah dan Bangunan (32.a)
            c_tanah = page.locator(f'[id="aset_tanah_bln#{idx}"]')
            if c_tanah.count() > 0:
                inp_tanah = c_tanah.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
                if inp_tanah.count() > 0:
                    res['aset_tanah'] = _clean_num(inp_tanah.input_value())
                    res['field_locators']['aset_tanah'] = inp_tanah
            else:
                res['aset_tanah'] = 0.0

        except Exception as e:
            res['ok'] = False
            res['error'] = f"Gagal membaca input nilai usaha 2026: {e}"
            return res


    elif blok == "biasa":
        # TODO: Blok usaha biasa (isian 27/28) belum ada dump HTML-nya. Minta dump lewat dump_fasih_html.py.
        # Fallback sementara menggunakan label pencarian yang ada di kode:
        try:
            loc_pbj = page.locator('div:has-text("27. a"), div:has-text("27.a"), div:has-text("barang dan jasa")').last
            loc_prod = page.locator('div:has-text("Biaya produksi")').last
            loc_ops = page.locator('div:has-text("Biaya operasional")').last

            if loc_pbj.count() > 0:
                inp_pbj = loc_pbj.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
                res['pbj'] = _clean_num(inp_pbj.input_value())
                res['field_locators']['pbj'] = inp_pbj
            else:
                res['ok'] = False
                res['error'] = "TODO: Field 27.a usaha biasa tidak ditemukan (membutuhkan dump HTML)"
                return res

            if loc_prod.count() > 0:
                inp_prod = loc_prod.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
                res['prod'] = _clean_num(inp_prod.input_value())
                res['field_locators']['prod'] = inp_prod

            if loc_ops.count() > 0:
                inp_ops = loc_ops.locator('input[type="text"], input:not([type="checkbox"]):not([type="radio"])').first
                res['ops'] = _clean_num(inp_ops.input_value())
                res['field_locators']['ops'] = inp_ops

            res['bulan_beroperasi'] = 12
        except Exception as e:
            res['ok'] = False
            res['error'] = f"Gagal membaca input nilai usaha biasa: {e}"
            return res
    else:
        res['ok'] = False
        res['error'] = f"Blok '{blok}' tidak dikenali. Memerlukan dump HTML."
        return res

    return res

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

    # B1 fix: Jika kategori tidak terbaca atau tidak cocok, kembalikan False
    return False

def isi_field_dengan_readback(page, input_locator, nilai_baru, nilai_lama=None):
    """
    Mengisi field input dan memverifikasi dengan membaca ulang (Guardrail G9 & Tugas 3):
    1. Klik input, select all, ketik nilai_baru
    2. Baca ulang input_value()
    3. Jika sama persis -> return True, clean_readback
    4. Jika beda -> ketik ulang nilai_lama (jika ada), return False, clean_readback
    """
    try:
        input_locator.scroll_into_view_if_needed()
        time.sleep(0.3)
        target_str = str(int(nilai_baru))

        input_locator.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        time.sleep(0.2)
        page.keyboard.type(target_str, delay=random.randint(40, 90))
        time.sleep(0.5)

        # Readback (G9)
        raw_readback = input_locator.input_value()
        clean_readback = re.sub(r'[^\d]', '', raw_readback.strip())

        if clean_readback == target_str:
            print(f"  [READBACK-OK] Nilai terisi cocok: {clean_readback} == target {target_str}")
            return True, clean_readback
        else:
            print(f"  [READBACK-MISMATCH] Nilai terbaca: '{clean_readback}' != target '{target_str}'!")
            if nilai_lama is not None:
                old_str = str(int(nilai_lama))
                print(f"  [READBACK-RESTORE] Mengembalikan nilai lama: {old_str}")
                input_locator.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                time.sleep(0.2)
                page.keyboard.type(old_str, delay=random.randint(40, 90))
                time.sleep(0.5)
            return False, clean_readback
    except Exception as e:
        print(f"  [READBACK-ERROR] Gagal isi & readback: {e}")
        return False, str(e)

def cari_container_isian_27a(page):
    """
    Mencari container pertanyaan untuk isian 27a (atau 31a untuk usaha beroperasi 2026),
    yaitu 'Nilai produksi/pendapatan/penjualan barang dan jasa'.
    Di sinilah remark #DC_01 WAJIB diletakkan sesuai instruksi reviewer.
    """
    keywords = ["31. a", "31.a", "27. a", "27.a", "barang dan jasa"]
    for kw in keywords:
        containers = page.locator(f'div:has-text("{kw}")')
        count = containers.count()
        for i in range(count - 1, -1, -1):
            c = containers.nth(i)
            btn_cat = c.locator('button[title="Catatan"]:visible, button[aria-label="Catatan"]:visible')
            if btn_cat.count() > 0:
                return c
            inp = c.locator('input[type="text"], input:not([type="radio"]):not([type="checkbox"])')
            if inp.count() > 0 and inp.first.is_visible():
                return c
    return None

def buka_dialog_catatan_pendapatan(page, container=None):
    """
    Membuka modal dialog Catatan pada isian pendapatan (27.a atau 31.a).
    Mencari tombol Catatan yang visible di layar (desktop / mobile).
    Mengembalikan locator dialog jika berhasil terbuka, atau None jika gagal.
    """
    # 1. Cek apakah dialog sudah terbuka
    existing_dialog = page.locator('div[role="dialog"]').last
    if existing_dialog.count() > 0 and existing_dialog.is_visible():
        return existing_dialog

    # 2. Cari tombol catatan visible di container jika diberikan
    btn_catatan = None
    if container:
        all_btns = container.locator('button[title="Catatan"]:visible, button[aria-label="Catatan"]:visible').all()
        for b in all_btns:
            try:
                if b.is_visible():
                    btn_catatan = b
                    break
            except Exception:
                pass

    # 3. Fallback pencarian berbasis ancestor pertanyaan pendapatan via evaluate JS
    if not btn_catatan:
        try:
            btn_handle = page.evaluate_handle(r"""() => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                let targetTextNode = null;
                while (node = walker.nextNode()) {
                    if (/^(31\.\s*a|27\.\s*a|.*barang dan jasa)/i.test(node.textContent.trim())) {
                        targetTextNode = node;
                        break;
                    }
                }
                if (!targetTextNode) return null;
                let parent = targetTextNode.parentElement;
                for (let i = 0; i < 7; i++) {
                    if (!parent) break;
                    const btns = parent.querySelectorAll('button[title*="Catatan"], button[aria-label*="Catatan"]');
                    for (const b of btns) {
                        if (b.offsetParent !== null) return b;
                    }
                    parent = parent.parentElement;
                }
                return null;
            }""")
            if btn_handle and btn_handle.as_element():
                btn_catatan = btn_handle.as_element()
        except Exception:
            pass

    if not btn_catatan:
        return None

    try:
        btn_catatan.scroll_into_view_if_needed()
        time.sleep(0.3)
        btn_catatan.click(timeout=3000)
    except Exception:
        # Fallback klik langsung via JS jika terhalang backdrop/animasi
        try:
            page.evaluate("el => el.click()", btn_catatan)
        except Exception:
            pass

    time.sleep(1.0)
    dialog = page.locator('div[role="dialog"]').last
    if dialog.count() > 0 and dialog.is_visible():
        return dialog
    return None

def tambah_catatan_field(page, container, kode_catatan, max_retry=2):
    """
    Menambahkan catatan (#DC_01 dst) pada isian pendapatan dan MEMVERIFIKASI
    bahwa catatan benar-benar tersimpan (PRD §7.3):
    1. Buka dialog catatan
    2. Ketik catatan pada textarea
    3. KLIK TOMBOL SIMPAN spesifik: button[title="Simpan"] (bukan tombol Dismiss!)
    4. Tunggu catatan masuk ke daftar
    5. Verifikasi apakah teks kode_catatan sudah muncul di dalam dialog
    6. Tutup modal dialog
    Jika gagal verifikasi, ulangi maksimal max_retry kali.
    """
    if not kode_catatan:
        return True

    catatan_final = kode_catatan.strip()
    print(f"[FASIH] Menambahkan catatan '{catatan_final}'...")

    for percobaan in range(1, max_retry + 1):
        dialog = buka_dialog_catatan_pendapatan(page, container)
        if not dialog:
            print(f"[WARN] Percobaan {percobaan}/{max_retry}: Modal catatan tidak terbuka.")
            time.sleep(1)
            continue

        try:
            # 1. Cek apakah catatan sudah ada sebelumnya di dialog
            if catatan_final in dialog.inner_text():
                print(f"[FASIH] Catatan '{catatan_final}' sudah terverifikasi ada di dialog.")
                tutup_modal_dialog(page)
                return True

            # 2. Ketik catatan di textarea
            ta = dialog.locator('textarea:visible').first
            if ta.count() > 0:
                ta.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(catatan_final, delay=random.randint(40, 80))
                time.sleep(0.5)

                # 3. KLIK TOMBOL SIMPAN
                # PENTING: Cari button[title="Simpan"] spesifik (bukan Dismiss/Close!)
                btn_simpan = dialog.locator('button[title="Simpan"]:visible').first
                if btn_simpan.count() > 0:
                    btn_simpan.click(timeout=3000)
                    print(f"[FASIH] Tombol 'Simpan' berhasil diklik.")
                else:
                    # Fallback Enter jika tombol simpan tidak terjangkau
                    page.keyboard.press("Enter")
                    print(f"[FASIH] Menekan Enter untuk menyimpan catatan.")

                time.sleep(1.5)

                # 4. Verifikasi bahwa catatan telah masuk ke list komentar
                dialog_text = dialog.inner_text()
                if catatan_final in dialog_text:
                    print(f"[FASIH] Catatan '{catatan_final}' BERHASIL TERVERIFIKASI tersimpan di FASIH!")
                    tutup_modal_dialog(page)
                    return True
                else:
                    print(f"[WARN] Percobaan {percobaan}/{max_retry}: Catatan '{catatan_final}' belum muncul setelah klik simpan.")
            else:
                print(f"[WARN] Textarea catatan tidak ditemukan di dialog.")

        except Exception as e:
            print(f"[WARN] Error saat mengisi catatan (percobaan {percobaan}): {e}")

        tutup_modal_dialog(page)
        time.sleep(1)

    print(f"[ERROR] Gagal menyimpan dan memverifikasi catatan '{catatan_final}' setelah {max_retry} percobaan.")
    return False

def tutup_modal_dialog(page):
    """
    Menutup modal dialog Catatan dengan aman dan tuntas:
    1. Klik tombol Dismiss spesifik (X di sudut kanan atas modal dialog).
    2. Tekan tombol Escape.
    3. Klik backdrop jika masih terbuka.
    """
    try:
        dialog = page.locator('div[role="dialog"]').last
        if dialog.count() == 0 or not dialog.is_visible():
            return True

        # 1. Klik tombol dismiss spesifik (X di sudut kanan atas)
        btn_dismiss = dialog.locator('button[aria-label="Dismiss"]:visible, button:has-text("Close"):visible').first
        if btn_dismiss.count() > 0:
            try:
                btn_dismiss.click(timeout=1500)
            except Exception:
                pass

        time.sleep(0.3)
        # 2. Tekan Escape
        if dialog.count() > 0 and dialog.is_visible():
            page.keyboard.press("Escape")

        time.sleep(0.3)
        # 3. Klik backdrop di luar modal jika masih membandel
        if dialog.count() > 0 and dialog.is_visible():
            page.mouse.click(20, 20)

        time.sleep(0.3)
        return not dialog.is_visible()
    except Exception:
        try:
            page.keyboard.press("Escape")
        except:
            pass
        return True

def cek_catatan_eksisting_27a(page, container=None):
    """
    Memeriksa apakah pada Isian 27a / 31a sudah terdapat riwayat catatan '#DC' / 'DC'.
    Jika sudah ada, mengembalikan (True, isi_catatan) agar assignment dilewati
    dan tidak diedit ganda / bentrok antar 2 komputer.
    Jika kosong / tidak ada DC, modal PASTI ditutup kembali sebelum bot lanjut bekerja.
    """
    dialog = buka_dialog_catatan_pendapatan(page, container)
    if not dialog:
        return False, ""

    try:
        # KUNCI UTAMA: Baca seluruh teks di dalam modal dialog!
        # Riwayat chat catatan tersimpan di bubble teks dialog.
        dialog_text = dialog.inner_text().strip()

        # TUTUP MODAL DIALOG SECARA TUNTAS
        tutup_modal_dialog(page)

        # Periksa apakah ada riwayat catatan mengandung 'DC' (misal: #DC_01, DC_01, #DC)
        import re
        match = re.search(r'#?DC[_\s]*0?[1-9]?', dialog_text, re.I)
        if match or "#DC" in dialog_text.upper() or "DC_01" in dialog_text.upper() or "DC01" in dialog_text.upper():
            found_tag = match.group(0) if match else "#DC_01"
            return True, found_tag

        return False, ""
    except Exception as e:
        print(f"[INFO] Pengecekan catatan eksisting: {e}")
        tutup_modal_dialog(page)
        return False, ""

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
    b. Set status baris KEMBALI ke status sebelumnya (bukan APPROVED) - Tugas 5
    c. Simpan timestamp blokir ke .waf_lock
    d. Cetak pesan jelas dengan saran cooldown 30 menit
    """
    aid = row['assignment_id']
    nama = row['nama_usaha']
    bot_code = bot_code or "BOT-DETECTED"
    prev_status = row.get('status') or 'PENDING'
    conn = get_connection()
    try:
        ss_waf = os.path.join(SCREENSHOTS_DIR, f"WAF_BLOCK_{aid}_{bot_code}_{int(time.time())}.png")
        try:
            page.screenshot(path=ss_waf)
        except Exception:
            pass
        
        log_audit(aid, nama, "WAF_BOT_BLOCK", status_sebelumnya=prev_status, status_baru=prev_status, 
                  pesan=f"WAF bot detected: {bot_code}. Screenshot: {ss_waf}")
        
        # Status dikembalikan ke status sebelumnya (bukan APPROVED)
        conn.execute("UPDATE kasus_nerwana SET status = ?, alasan_review = NULL WHERE assignment_id = ? AND nama_usaha = ?", (prev_status, aid, nama))
        conn.commit()

        catat_waf_block(bot_code)

        print("\n" + "!" * 65)
        print("           [WAF BOT BLOCK TERDETEKSI!]")
        print("!" * 65)
        print(f"Kode BOT       : {bot_code}")
        print(f"Jam Kejadian   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Assignment     : {aid} ({nama})")
        print(f"Status Baris   : Dikembalikan ke '{prev_status}' (bukan kesalahan data)")
        print(f"Bukti Gambar   : {ss_waf}")
        print("TINDAKAN       : Menghentikan seluruh batch eksekusi segera!")
        print("SARAN          : Tunggu cooldown minimal 30 menit sebelum jalankan lagi.")
        print("!" * 65 + "\n")
    finally:
        conn.close()
    return "WAF_BLOCK", bot_code

def eksekusi_baris(page, row, dry_run=True, interaktif=False, isi_catatan=False, nerwana_updater=None, target_info=None, kategori="G"):
    """
    Menjalankan alur eksekusi baris kuesioner FASIH secara end-to-end:
    1. Buka Blok II & deteksi indeks usaha aktif (#N).
    2. Deteksi jenis blok ('usaha_2026' vs 'biasa').
    3. Cek catatan eksisting (#DC) pada pendapatan agar tidak terjadi tabrakan/edit ganda.
    4. Baca nilai isian langsung dari FASIH (bukan dari DB/Excel lama).
    5. Evaluasi usulan murni dengan evaluasi() (Guardrail G1-G8).
    6. Jika SKIP atau NEED_REVIEW -> tutup tab FASIH, kembalikan status Selancar, simpan status & alasan di DB.
    7. Jika APPLY:
       - Isi tepat satu field target dengan readback (G9).
       - Jika mismatch -> simpan READBACK_MISMATCH, kembalikan status Selancar.
       - Tambah remark terverifikasi pada Isian Pendapatan (27a/31a). Jika gagal -> REMARK_FAILED.
       - Selesaikan anomali di halaman Catatan.
       - Jika dry-run -> simpan APPLIED, kembalikan status Selancar ke semula.
       - Jika live submit -> submit FASIH, update Selancar 'sudah_direvisi', simpan COMPLETED.
         Jika update Selancar gagal -> simpan SYNC_FAILED & hentikan batch.
    """
    aid = row['assignment_id']
    nama = row['nama_usaha']
    kode_catatan = row.get('kode_catatan') or "#DC_01"
    
    print("\n" + "=" * 65)
    print(f"EKSEKUSI ASSIGNMENT: {aid} (TARGET KATEGORI {kategori})")
    print(f"Nama Usaha  : {nama}")
    print(f"Catatan     : {kode_catatan if isi_catatan else '(dilewati saat testing)'}")
    print(f"Mode        : {'DRY-RUN (TIDAK SUBMIT)' if dry_run else 'SUBMIT SUNGGUHAN'}")
    print("=" * 65)

    conn = get_connection()
    from updater_nerwana import set_tindak_lanjut_selancar

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
            log_audit(aid, nama, "FASIH_FORBIDDEN", status_sebelumnya="PENDING", status_baru="FASIH_FORBIDDEN", pesan="Forbidden di FASIH")
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return "SKIPPED_FASIH_ERROR", None

        # 2. Lakukan Revoke & Masuk Mode Edit (klik tombol pensil)
        lakukan_revoke_dan_edit(page)
        
        # Cek WAF setelah revoke
        is_waf, bot_code = cek_waf_bot(page)
        if is_waf:
            return handle_waf_block(page, row, bot_code)

        time.sleep(0.5)

        # 3. Buka Blok II & Deteksi indeks usaha aktif
        ok_blok, idx_usaha = buka_blok_ii(page, nama)
        if not ok_blok:
            raise Exception("Gagal membuka Blok II di FASIH")

        # 4. Deteksi jenis Blok (Tugas 1)
        blok_jenis = deteksi_blok(page)
        print(f"[FASIH] Blok terdeteksi: '{blok_jenis}' (Indeks usaha #{idx_usaha})")

        # 4.5 Anti-Tabrakan: Cek apakah Isian Pendapatan (27a/31a) sudah memiliki catatan #DC
        c_pendapatan_cek = cari_container_isian_27a(page)
        ada_dc, teks_dc = cek_catatan_eksisting_27a(page, c_pendapatan_cek)
        if ada_dc:
            print(f"\n[FASIH-SKIP] Isian Pendapatan SUDAH berisi catatan DC: '{teks_dc}'!")
            print("             Assignment ini sudah selesai diperbaiki sebelumnya.")
            conn.execute("UPDATE kasus_nerwana SET status = 'COMPLETED', tindak_lanjut = 'sudah_direvisi', alasan_review = ? WHERE assignment_id = ? AND nama_usaha = ?", (f"Sudah ada remark: {teks_dc}", aid, nama))
            conn.commit()
            log_audit(aid, nama, "ALREADY_HAS_DC_REMARK", status_sebelumnya="PENDING", status_baru="COMPLETED", pesan=f"Pendapatan sudah berisi remark '{teks_dc}'")
            return "ALREADY_COMPLETED", teks_dc

        # Pastikan modal dialog 100% tertutup sebelum membaca form
        tutup_modal_dialog(page)

        # 5. Baca nilai langsung dari FASIH (Tugas 1 & Tugas 2)
        data_fasih = baca_nilai_fasih(page, blok=blok_jenis, idx=idx_usaha)
        if not data_fasih['ok']:
            err_baca = data_fasih.get('error', 'Gagal membaca nilai di FASIH')
            print(f"[FASIH-NEED_REVIEW] Field tidak terbaca lengkap: {err_baca}")
            conn.execute("""
                UPDATE kasus_nerwana 
                SET status = 'NEED_REVIEW', alasan_review = ?, alasan_skip = ?, blok = ?, evaluasi_at = ?
                WHERE assignment_id = ? AND nama_usaha = ?
            """, (err_baca, err_baca, blok_jenis, datetime.now().isoformat(), aid, nama))
            conn.commit()
            log_audit(aid, nama, "NEED_REVIEW_BACA", status_sebelumnya="PENDING", status_baru="NEED_REVIEW", pesan=err_baca)
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return "NEED_REVIEW", err_baca

        # 6. Validasi KBLI / Kategori
        kat_fasih = data_fasih.get('kategori') or kategori
        kbli_fasih = data_fasih.get('kbli') or row.get('kbli', '')
        
        nilai_dict = {
            'pbj': data_fasih['pbj'],
            'prod': data_fasih['prod'],
            'ops': data_fasih['ops'],
            'beli': data_fasih.get('beli', 0.0),
            'bulan_beroperasi': data_fasih.get('bulan_beroperasi', 1),
            'aset_tanah': data_fasih.get('aset_tanah', 0.0)
        }
        
        print(f"[FASIH DATA] Kategori: {kat_fasih} | KBLI: {kbli_fasih} | Bulan Beroperasi: {nilai_dict['bulan_beroperasi']}")
        print(f"             PBJ : {nilai_dict['pbj']:,.0f}")
        print(f"             Prod: {nilai_dict['prod']:,.0f}")
        print(f"             Ops : {nilai_dict['ops']:,.0f}")
        if nilai_dict['beli'] > 0:
            print(f"             Beli: {nilai_dict['beli']:,.0f}")
        if nilai_dict['aset_tanah'] > 0:
            print(f"             Aset: {nilai_dict['aset_tanah']:,.0f} (Tanah & Bangunan 32.a)")

        # 7. Evaluasi Guardrail murni (Tugas 2)
        rasio_selancar = None
        if target_info:
            rasio_selancar = target_info.get('rasio_selancar')

        hasil = evaluasi(
            nilai=nilai_dict,
            kategori=kat_fasih,
            kbli=kbli_fasih,
            blok=blok_jenis,
            rasio_selancar=rasio_selancar
        )

        print(f"[EVALUASI] Aksi: {hasil.aksi} | Alasan: {hasil.alasan}")

        # 8. Tangani Hasil Evaluasi:
        if hasil.aksi in ["SKIP", "NEED_REVIEW"]:
            conn.execute("""
                UPDATE kasus_nerwana 
                SET status = ?, alasan_skip = ?, nilai_lama_fasih = ?, blok = ?, evaluasi_at = ?
                WHERE assignment_id = ? AND nama_usaha = ?
            """, (hasil.aksi, hasil.alasan, json.dumps(nilai_dict), blok_jenis, datetime.now().isoformat(), aid, nama))
            conn.commit()
            log_audit(aid, nama, f"EVALUASI_{hasil.aksi}", status_sebelumnya="PENDING", status_baru=hasil.aksi, pesan=hasil.alasan)
            # Kembalikan status Selancar ke status semula
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return hasil.aksi, hasil.alasan

        # Skenario APPLY: Ubah TEPAT SATU field
        faktor_txt = f" (Faktor: {hasil.faktor})" if hasil.faktor else f" ({hasil.operasi})"
        print(f"[APPLY] Field target: '{hasil.field}' dari {hasil.nilai_lama:,.0f} -> {hasil.nilai_baru:,.0f}{faktor_txt}")

        # 9. Mengisi Field dengan Readback (Tugas 3 / G9)
        input_loc = data_fasih['field_locators'].get(hasil.field)
        if not input_loc or input_loc.count() == 0:
            # Fallback jika locator dari baca_nilai tidak valid
            c_fallback = page.locator(f'[id*="{hasil.field}"]:visible, [id*="pendapatan"]:visible').first
            if c_fallback.count() > 0:
                input_loc = c_fallback.locator('input[type="text"]').first

        if not input_loc or input_loc.count() == 0:
            err_loc = f"Input locator untuk field '{hasil.field}' tidak ditemukan"
            print(f"[NEED_REVIEW] {err_loc}")
            conn.execute("""
                UPDATE kasus_nerwana 
                SET status = 'NEED_REVIEW', alasan_review = ?, nilai_lama_fasih = ?, blok = ?, evaluasi_at = ?
                WHERE assignment_id = ? AND nama_usaha = ?
            """, (err_loc, json.dumps(nilai_dict), blok_jenis, datetime.now().isoformat(), aid, nama))
            conn.commit()
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return "NEED_REVIEW", err_loc

        ok_rb, val_rb = isi_field_dengan_readback(page, input_loc, hasil.nilai_baru, nilai_lama=hasil.nilai_lama)
        if not ok_rb:
            err_rb = f"Readback mismatch pada {hasil.field}: terbaca '{val_rb}' != target '{hasil.nilai_baru:,.0f}'"
            print(f"[READBACK_MISMATCH] {err_rb}")
            conn.execute("""
                UPDATE kasus_nerwana 
                SET status = 'READBACK_MISMATCH', alasan_review = ?, nilai_lama_fasih = ?, blok = ?, evaluasi_at = ?
                WHERE assignment_id = ? AND nama_usaha = ?
            """, (err_rb, json.dumps(nilai_dict), blok_jenis, datetime.now().isoformat(), aid, nama))
            conn.commit()
            log_audit(aid, nama, "READBACK_MISMATCH", status_sebelumnya="PENDING", status_baru="READBACK_MISMATCH", pesan=err_rb)
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return "READBACK_MISMATCH", val_rb

        time.sleep(0.5)

        # 10. Tambah Catatan / Remark (Tugas 5 & PRD §7.3)
        c_pendapatan = c_pendapatan_cek or cari_container_isian_27a(page)
        catatan_final = kode_catatan or "#DC_01"
        remark_ok = False
        if isi_catatan:
            remark_ok = tambah_catatan_field(page, c_pendapatan, catatan_final)
            if not remark_ok:
                print(f"[FASIH-ABORT] Remark '{catatan_final}' GAGAL tersimpan. Mengembalikan nilai lama...")
                # Kembalikan nilai lama di input agar form bersih
                try:
                    input_loc.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(str(int(hasil.nilai_lama)))
                except Exception:
                    pass
                conn.execute("""
                    UPDATE kasus_nerwana 
                    SET status = 'REMARK_FAILED', alasan_review = ?, nilai_lama_fasih = ?, blok = ?, evaluasi_at = ?
                    WHERE assignment_id = ? AND nama_usaha = ?
                """, (f"Remark '{catatan_final}' gagal tersimpan di FASIH", json.dumps(nilai_dict), blok_jenis, datetime.now().isoformat(), aid, nama))
                conn.commit()
                log_audit(aid, nama, "REMARK_FAILED", status_sebelumnya="PENDING", status_baru="REMARK_FAILED", pesan=f"Remark '{catatan_final}' gagal")
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                return "REMARK_FAILED", None
        else:
            remark_ok = True

        # 11. Halaman Catatan: Tampilkan Anomali
        proses_halaman_catatan_dan_tampilkan_anomali(page)

        # 12. Konfirmasi Interaktif (Tugas 4 / G12)
        if interaktif:
            print("\n" + "-" * 60)
            print(f"[KONFIRMASI MANUAL] Usulan: Field '{hasil.field}' | {hasil.nilai_lama:,.0f} -> {hasil.nilai_baru:,.0f}")
            if dry_run:
                print("Mode: DRY-RUN (Tombol Kirim TIDAK akan ditekan)")
                jawab = input("Apakah nilai sudah sesuai dan ingin menyelesaikan dry-run? [y/n]: ").strip().lower()
                if jawab != 'y':
                    print("[INFO] Dibatalkan oleh reviewer.")
                    set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                    return "CANCELLED", None
            else:
                print("Mode: SUBMIT SUNGGUHAN (Akan kirim ke FASIH & update Selancar)")
                jawab = input("Apakah Anda yakin ingin submit baris ini ke FASIH dan Selancar? [y/n]: ").strip().lower()
                if jawab != 'y':
                    print("[INFO] Dibatalkan oleh reviewer.")
                    set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
                    return "CANCELLED", None

        time.sleep(0.5)

        # 13. Eksekusi Submit atau Dry-run (Tugas 5)
        nilai_baru_dict = {hasil.field: hasil.nilai_baru}
        if dry_run:
            try:
                ss_path = os.path.join(SCREENSHOTS_DIR, f"dryrun_{aid}_{int(time.time())}.png")
                page.screenshot(path=ss_path, timeout=5000)
                print(f"[DRY-RUN SUKSES] Screenshot bukti disimpan ke: {ss_path}")
            except Exception:
                pass
            print("[INFO] Sesuai mode dry-run, tombol Kirim TIDAK ditekan.")
            
            conn.execute("""
                UPDATE kasus_nerwana 
                SET status = 'APPLIED', nilai_lama_fasih = ?, nilai_baru_fasih = ?, remark_terverifikasi = ?, blok = ?, evaluasi_at = ?
                WHERE assignment_id = ? AND nama_usaha = ?
            """, (json.dumps(nilai_dict), json.dumps(nilai_baru_dict), 1 if remark_ok else 0, blok_jenis, datetime.now().isoformat(), aid, nama))
            conn.commit()
            log_audit(aid, nama, "DRY_RUN_APPLIED", 
                      nilai_lama=nilai_dict,
                      nilai_baru=nilai_baru_dict,
                      kode_catatan=catatan_final, status_sebelumnya="PENDING", status_baru="APPLIED")
            # Kembalikan status Selancar ke nilai semula agar tidak tertahan 'akan_direvisi'
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return "APPLIED", None
        else:
            submit_ok = submit_assignment(page)
            if submit_ok:
                try:
                    ss_path = os.path.join(SCREENSHOTS_DIR, f"submitted_{aid}_{int(time.time())}.png")
                    page.screenshot(path=ss_path, timeout=5000)
                except Exception:
                    pass
                
                # Update status di Selancar menjadi 'Sudah direvisi' (Tugas 5)
                print("[SELANCAR] Mengupdate tindak lanjut di Selancar menjadi 'Sudah direvisi'...")
                sync_ok = set_tindak_lanjut_selancar(target_info, nerwana_updater, status="sudah_direvisi")
                if not sync_ok:
                    print("\n[SYNC_FAILED] Update Selancar GAGAL setelah submit FASIH!")
                    conn.execute("""
                        UPDATE kasus_nerwana 
                        SET status = 'SYNC_FAILED', alasan_review = 'Submit FASIH sukses tapi update Selancar gagal',
                            nilai_lama_fasih = ?, nilai_baru_fasih = ?, remark_terverifikasi = 1, blok = ?, evaluasi_at = ?
                        WHERE assignment_id = ? AND nama_usaha = ?
                    """, (json.dumps(nilai_dict), json.dumps(nilai_baru_dict), blok_jenis, datetime.now().isoformat(), aid, nama))
                    conn.commit()
                    log_audit(aid, nama, "SYNC_FAILED", status_sebelumnya="PENDING", status_baru="SYNC_FAILED", pesan="Gagal update Selancar")
                    return "SYNC_FAILED", "Gagal update Selancar"

                # Submit FASIH + Update Selancar BERHASIL: tulis COMPLETED
                conn.execute("""
                    UPDATE kasus_nerwana 
                    SET status = 'COMPLETED', tindak_lanjut = 'sudah_direvisi',
                        nilai_lama_fasih = ?, nilai_baru_fasih = ?, remark_terverifikasi = 1, blok = ?, evaluasi_at = ?
                    WHERE assignment_id = ? AND nama_usaha = ?
                """, (json.dumps(nilai_dict), json.dumps(nilai_baru_dict), blok_jenis, datetime.now().isoformat(), aid, nama))
                conn.commit()
                log_audit(aid, nama, "COMPLETED", 
                          nilai_lama=nilai_dict,
                          nilai_baru=nilai_baru_dict,
                          kode_catatan=catatan_final, status_sebelumnya="PENDING", status_baru="COMPLETED")
                return "COMPLETED", None
            else:
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
            log_audit(aid, nama, "FASIH_FORBIDDEN", status_sebelumnya="PENDING", status_baru="FASIH_FORBIDDEN", pesan=str(e))
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
            return "SKIPPED_FASIH_ERROR", None

        conn.execute("UPDATE kasus_nerwana SET status = 'FAILED', alasan_review = ? WHERE assignment_id = ? AND nama_usaha = ?", (str(e), aid, nama))
        conn.commit()
        log_audit(aid, nama, "EXECUTION_FAILED", status_sebelumnya="PENDING", status_baru="FAILED", pesan=str(e))
        set_tindak_lanjut_selancar(target_info, nerwana_updater, status=target_info.get('stat', ''))
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

    # Tugas 6: Nonaktifkan sync_review sebagai sumber nilai
    print("[INFO] Mode LIVE ON-THE-FLY aktif: Nilai dibaca langsung dari kuesioner FASIH.")
    print("       File Excel lama dinonaktifkan sebagai sumber usulan eksekusi.")

    conn = get_connection()
    pending_count = conn.execute("SELECT COUNT(*) FROM kasus_nerwana WHERE status = 'PENDING'").fetchone()[0]
    completed_count = conn.execute("SELECT COUNT(*) FROM kasus_nerwana WHERE status = 'COMPLETED'").fetchone()[0]
    conn.close()

    print(f"\n[STATUS DATABASE] Antrean PENDING: {pending_count} | Selesai COMPLETED: {completed_count}")
    print("         Bot memeriksa langsung baris di tabel Selancar secara urut di layar.")

    print("\nPilih Kategori Lapangan Usaha:")
    print("  [1] Kategori G - Perdagangan (Master Threshold KBLI 5/3/2/Kat) [Default]")
    print("  [2] Kategori A - Pertanian (Threshold 0.51 - 0.94)")
    print("  [3] Kategori C - Industri Pengolahan (Master Threshold KBLI 2/Kat)")
    print("  [Atau ketik langsung huruf kategori: B, D, E, F, H, I, J, K, L, M, N, O, Q, R, S, T]")
    kat_choice = input("Masukkan pilihan kategori (default 1 - G): ").strip() or "1"
    if kat_choice == "1":
        kategori_aktif = "G"
    elif kat_choice == "2":
        kategori_aktif = "A"
    elif kat_choice == "3":
        kategori_aktif = "C"
    else:
        kategori_aktif = kat_choice.upper()

    from threshold_manager import get_threshold
    info_kat = get_threshold(kategori_aktif)
    print(f"[KATEGORI AKTIF] Menggunakan Kategori {kategori_aktif} ({info_kat.get('uraian', '')}) - Acuan Rasio: [{info_kat['min']:.2f} - {info_kat['max']:.2f}]")

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
        jawab_c = input("Sertakan penulisan catatan (#DC_01) pada isian 27.a / 31.a? [y/n] (default y): ").strip().lower()
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
            lanjut_halaman_berikutnya_selancar,
            refresh_selancar_realtime,
            set_tindak_lanjut_selancar
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
        consecutive_errors = 0  # Stop-loss counter (G11)
        total_submitted_count = 0  # Counter untuk konfirmasi awal (G12)

        fasih_page = None
        first_run = True

        while sukses < limit:
            # 1.5 Real-Time Sync: Refresh tabel Selancar agar update dari komputer lain langsung terdeteksi
            if not first_run:
                refresh_selancar_realtime(selancar_page, kategori=kategori_aktif)
            first_run = False

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
            print(f"[SELANCAR] Menandai assignment '{nama}' (AID: {aid}) menjadi 'Akan direvisi' sebelum membuka FASIH...")
            set_tindak_lanjut_selancar(target_info, nerwana_updater, status="akan_direvisi")
            time.sleep(0.8)

            # 3. Buka tab FASIH dari baris tabel di Selancar
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
                consecutive_errors += 1
                if consecutive_errors >= MAX_ERR_BERTURUT:
                    print(f"\n[CIRCUIT BREAKER G11] Menghentikan batch karena {MAX_ERR_BERTURUT} error teknis berturut-turut!")
                    break
                continue

            # Tunggu halaman FASIH selesai initial load/redirect
            try:
                fasih_page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            time.sleep(1.5)

            # Konfirmasi interaktif hanya aktif jika user memilih mode interaktif di menu utama (pilihan 1 atau 2)
            # Pada mode batch (pilihan 3 atau 4), bot langsung mengedit dan mengeksekusi secara otomatis
            baris_interaktif = interaktif


            # 4. Eksekusi form di tab FASIH
            hasil, info = eksekusi_baris(
                fasih_page, 
                row, 
                dry_run=dry_run, 
                interaktif=baris_interaktif, 
                isi_catatan=tanya_catatan, 
                nerwana_updater=nerwana_updater,
                target_info=target_info,
                kategori=kategori_aktif
            )

            # Selesai submit / selesai eksekusi, tutup tab FASIH
            try:
                if fasih_page and not fasih_page.is_closed():
                    print("[FASIH] Selesai eksekusi baris. Menutup tab FASIH...")
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

            # EVALUASI HASIL & STOP-LOSS (G11):
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

            elif hasil == "SYNC_FAILED":
                # Tugas 5: Jika update Selancar gagal, jangan tulis COMPLETED. Catat status SYNC_FAILED dan hentikan batch.
                gagal += 1
                consecutive_errors += 1
                session_skip_aids.add(aid)
                print(f"\n[SYNC_FAILED] Hentikan batch karena sinkronisasi Selancar gagal untuk '{nama}'!")
                break

            elif hasil in ["APPLIED", "COMPLETED"]:
                sukses += 1
                consecutive_errors = 0  # Reset stop-loss counter
                session_skip_aids.add(aid)
                if hasil == "COMPLETED":
                    total_submitted_count += 1
                if sukses < limit:
                    jeda = random.uniform(JEDA_ANTAR_ASSIGNMENT_MIN, JEDA_ANTAR_ASSIGNMENT_MAX)
                    print(f"[JEDA] Menunggu {jeda:.1f} detik sebelum assignment berikutnya...")
                    time.sleep(jeda)

            elif hasil == "ALREADY_COMPLETED":
                di_skip += 1
                consecutive_errors = 0
                session_skip_aids.add(aid)
                print(f"[SELANCAR] Memastikan status assignment '{nama}' menjadi 'Sudah direvisi' di Selancar...")
                set_tindak_lanjut_selancar(target_info, nerwana_updater, status="sudah_direvisi")
                conn = get_connection()
                conn.execute("UPDATE kasus_nerwana SET tindak_lanjut = 'sudah_direvisi', status = 'COMPLETED' WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama))
                conn.commit()
                conn.close()
                time.sleep(1.0)

            elif hasil in ["SKIP", "NEED_REVIEW", "SKIPPED_FASIH_ERROR", "KBLI_MISMATCH", "CANCELLED"]:
                di_skip += 1
                consecutive_errors = 0  # Evaluasi normal bukan error teknis sistem
                session_skip_aids.add(aid)
                if hasil == "CANCELLED":
                    print("[INFO] Eksekusi dihentikan oleh reviewer.")
                    break
                time.sleep(random.uniform(1.5, 3.0))

            elif hasil in STATUS_ERROR_TEKNIS:
                # Tugas 4 (G11): Error teknis (READBACK_MISMATCH, REMARK_FAILED, FAILED)
                gagal += 1
                consecutive_errors += 1
                session_skip_aids.add(aid)
                print(f"[STOP-LOSS CHECK] Error teknis berturut-turut: {consecutive_errors}/{MAX_ERR_BERTURUT} (Status: {hasil})")
                if consecutive_errors >= MAX_ERR_BERTURUT:
                    print(f"\n[CIRCUIT BREAKER G11] Menghentikan batch karena {MAX_ERR_BERTURUT} error teknis berturut-turut!")
                    break
                time.sleep(2.0)

            else:
                gagal += 1
                consecutive_errors += 1
                session_skip_aids.add(aid)
                if consecutive_errors >= MAX_ERR_BERTURUT:
                    print(f"\n[CIRCUIT BREAKER G11] Menghentikan batch karena {MAX_ERR_BERTURUT} error teknis berturut-turut!")
                    break
                if pilihan in ["1", "2"]:
                    break

        print("\n" + "=" * 65)
        print("RINGKASAN EKSEKUSI:")
        print(f"Target Berhasil : {sukses} / {limit}")
        print(f"Dilewati (Skip) : {di_skip} (Selesai sebelumnya / Evaluasi SKIP / NEED_REVIEW)")
        print(f"Gagal/Batal     : {gagal}")
        print(f"Berhenti WAF    : {'YA (' + waf_bot_code + ')' if waf_terdeteksi else 'TIDAK'}")
        if sukses >= limit and limit > 1 and not waf_terdeteksi:
            print(f"[INFO] Batch 1 sesi selesai (target {limit} baris terpenuhi).")
        print("=" * 65)

if __name__ == "__main__":
    main()

