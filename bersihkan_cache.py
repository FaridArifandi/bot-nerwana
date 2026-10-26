"""
bersihkan_cache.py
Membersihkan data lokal (cache) supaya salinan folder dari komputer lain (mis. zip) tidak membawa
riwayat, sesi login, atau kredensial pemilik sebelumnya.

- Otomatis (tanpa argumen): hanya membersihkan jika folder ini ternyata berasal dari komputer/akun Windows lain
  (dibandingkan dengan file .mesin_id). Pada pemakaian pertama di komputer ini hanya mencatat identitas.
- Manual: `python bersihkan_cache.py --paksa` (atau klik 3_bersihkan_cache.bat) membersihkan semuanya sekarang.

Yang dibersihkan: data_cleaning.db (riwayat & status lokal), __pycache__, screenshots, profil Chrome debug
(chrome_debug_profile, browser_data), dan -- hanya saat terdeteksi salinan dari komputer lain -- file kredensial sso.
"""
import os
import sys
import shutil
import socket
import getpass

BASE = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(BASE, ".mesin_id")


def _id_mesin():
    try:
        user = getpass.getuser()
    except Exception:
        user = "?"
    return f"{socket.gethostname()}|{user}"


def _port_terbuka(port=9222):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _hapus(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    return not os.path.exists(path)


def bersihkan(paksa=False):
    sekarang = _id_mesin()
    lama = None
    try:
        with open(ID_FILE, "r", encoding="utf-8") as f:
            lama = f.read().strip() or None
    except OSError:
        pass

    dari_komputer_lain = bool(lama) and lama != sekarang
    if not paksa and not dari_komputer_lain:
        if lama is None:   # pemakaian pertama di komputer ini
            try:
                with open(ID_FILE, "w", encoding="utf-8") as f:
                    f.write(sekarang)
            except OSError:
                pass
        return False

    alasan = "diminta manual" if paksa else f"folder ini berasal dari komputer/akun lain ({lama})"
    print(f"[BERSIH-CACHE] Membersihkan cache lokal: {alasan}")

    dihapus = []
    # 1) database & riwayat lokal
    for nama in ("data_cleaning.db", "data_cleaning.db-journal", "data_cleaning.db-wal", "data_cleaning.db-shm", ".waf_lock"):
        p = os.path.join(BASE, nama)
        if os.path.exists(p) and _hapus(p):
            dihapus.append(nama)
    # 2) __pycache__ di mana pun
    for root, dirs, _ in os.walk(BASE):
        for d in list(dirs):
            if d == "__pycache__":
                if _hapus(os.path.join(root, d)):
                    dihapus.append(os.path.relpath(os.path.join(root, d), BASE))
                dirs.remove(d)
    # 3) screenshot lama
    ss = os.path.join(BASE, "screenshots")
    if os.path.isdir(ss):
        for nama in os.listdir(ss):
            _hapus(os.path.join(ss, nama))
        dihapus.append("screenshots/*")
    # 4) profil Chrome (sesi login). Dilewati bila Chrome debug sedang berjalan memakai profil itu.
    if _port_terbuka(9222):
        print("[BERSIH-CACHE] Chrome debug sedang berjalan: profil Chrome tidak dihapus (tutup Chrome lalu jalankan 3_bersihkan_cache.bat bila perlu).")
    else:
        for nama in ("chrome_debug_profile", "browser_data"):
            p = os.path.join(BASE, nama)
            if os.path.exists(p) and _hapus(p):
                dihapus.append(nama)
    # 5) kredensial pemilik sebelumnya (hanya saat terdeteksi salinan dari komputer lain)
    if dari_komputer_lain:
        for nama in ("sso", ".sso", "sso.txt"):
            p = os.path.join(BASE, nama)
            if os.path.exists(p) and _hapus(p):
                dihapus.append(nama)
        print("[BERSIH-CACHE] File kredensial 'sso' milik komputer sebelumnya dihapus. Buat ulang: salin sso.example menjadi sso lalu isi akun SSO-mu.")

    try:
        with open(ID_FILE, "w", encoding="utf-8") as f:
            f.write(sekarang)
    except OSError:
        pass
    print(f"[BERSIH-CACHE] Selesai. Dibersihkan: {', '.join(dihapus) if dihapus else '(tidak ada yang perlu dihapus)'}")
    return True


if __name__ == "__main__":
    try:
        bersihkan(paksa=("--paksa" in sys.argv))
    except Exception as e:
        print(f"[BERSIH-CACHE] dilewati: {e}")
