"""
config.py
Konfigurasi terpusat untuk Bot Nerwana.
Semua parameter guardrail (PRD §6) dan konstanta operasional
didefinisikan di sini agar tidak tersebar di berbagai file.
"""

# ============================================================
#  GUARDRAIL EVALUASI (PRD §6)
# ============================================================

# G2: Toleransi selisih rasio hitungan vs rasio Selancar
TOL_RASIO_SELANCAR = 0.02

# G3: Kandidat koreksi hanya salah-nol (×10 atau ÷10)
#     Faktor yang diperbolehkan untuk koreksi salah-nol
FAKTOR_KALI = 10
FAKTOR_BAGI = 10

# G6: Cap nilai baru untuk field yang DINAIKKAN (×10)
CAP_NILAI_BARU = 250_000_000

# G11: Stop-loss — berhenti jika ada N error teknis berturut-turut
#      (READBACK_MISMATCH, REMARK_FAILED, FAILED)
#      NEED_REVIEW dan SKIP bukan error teknis
MAX_ERR_BERTURUT = 3

# G12: Jumlah baris pertama yang wajib konfirmasi interaktif y/n
#      setelah update ini dirilis
N_INTERAKTIF_AWAL = 10

# ============================================================
#  STATUS BARIS
# ============================================================

# Status yang dianggap FINAL (tidak perlu diproses ulang)
STATUS_FINAL = frozenset({
    'COMPLETED',
    'SKIP',
    'NEED_REVIEW',
    'KBLI_MISMATCH',
    'FASIH_FORBIDDEN',
    'REMARK_FAILED',
    'READBACK_MISMATCH',
})

# Status error teknis yang dihitung untuk stop-loss G11
STATUS_ERROR_TEKNIS = frozenset({
    'READBACK_MISMATCH',
    'REMARK_FAILED',
    'FAILED',
})

# ============================================================
#  OPERASIONAL
# ============================================================

# Jeda antar assignment dalam batch (detik, min dan max untuk random)
JEDA_ANTAR_ASSIGNMENT_MIN = 4.0
JEDA_ANTAR_ASSIGNMENT_MAX = 7.0

# Cooldown WAF (detik)
WAF_COOLDOWN_SECONDS = 30 * 60  # 30 menit

# Maksimal retry remark
MAX_RETRY_REMARK = 2

# Maksimal baris per batch
MAX_BATCH_SIZE = 50
