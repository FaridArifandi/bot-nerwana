"""
threshold_manager.py
Modul terpusat untuk mengelola dan mengambil acuan threshold rasio NTB/Output dan COGS
berdasarkan Master Threshold resmi Selancar Nerwana BPS Aceh.
Mendukung resolusi hierarkis:
1. KBLI 5-Digit (Kategori G)
2. KBLI 3-Digit (Kategori G)
3. KBLI 2-Digit (Kategori C & G)
4. Kategori Utama (A - T)
"""

import os
import json

MASTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "master_threshold.json")

_DATA = None

def _load_master():
    global _DATA
    if _DATA is None:
        if os.path.exists(MASTER_PATH):
            with open(MASTER_PATH, "r", encoding="utf-8") as f:
                _DATA = json.load(f)
        else:
            _DATA = {"kategori": {}, "kategori_c_kbli2": {}, "kategori_g_kbli2": {}, "kategori_g_kbli3": {}, "kategori_g_kbli5": {}}
    return _DATA

def get_threshold(kategori, kbli="", skala="mikro_kecil"):
    """
    Mengembalikan acuan threshold (min, max, target, level, metadata).
    
    Parameters:
    - kategori (str): Huruf kategori, misal 'A', 'C', 'G', dll.
    - kbli (str): Kode KBLI (2, 3, atau 5 digit).
    - skala (str): Skala usaha untuk Kategori C ('mikro_kecil' atau 'besar_sedang').
    
    Returns:
    dict: {
        'min': float,
        'max': float,
        'target': float, # Rata-rata atau titik tengah optimal
        'level': str,    # 'KBLI_5', 'KBLI_3', 'KBLI_2', atau 'KATEGORI'
        'uraian': str,
        'cogs_min': float or None,
        'cogs_max': float or None,
        'cogs_target': float or None
    }
    """
    data = _load_master()
    kat = str(kategori or "").strip().upper()
    kbli_str = str(kbli or "").strip().replace(".", "")
    
    # 1. KATEGORI G (PERDAGANGAN) - Hirarki: 5 Digit -> 3 Digit -> 2 Digit -> Kategori
    if kat == "G":
        # 1a. Cek 5 Digit
        if len(kbli_str) >= 5 and kbli_str[:5] in data.get("kategori_g_kbli5", {}):
            item = data["kategori_g_kbli5"][kbli_str[:5]]
            ntb = item["ntb_output"]
            cogs = item["cogs"]
            level = f"KBLI_5 ({kbli_str[:5]})"
            # Lampiran threshold: "NTB/Output rentang nol - pakai acuan Kategori G"
            if ntb["min"] is None or ntb["max"] is None or ntb["min"] == ntb["max"]:
                kat_g = data.get("kategori", {}).get("G", {})
                t_min = kat_g.get("min", 0.64)
                t_max = kat_g.get("max", 0.78)
                t_target = round((t_min + t_max) / 2, 4)
                level += " NTB:acuan Kat.G"
            else:
                t_min = ntb["min"]
                t_max = ntb["max"]
                t_target = ntb["avg"] if ntb["avg"] is not None else round((t_min + t_max) / 2, 4)
            # Lampiran threshold: "COGS rentang nol - tidak dipakai"
            if cogs.get("min") is None or cogs.get("max") is None or cogs["min"] == cogs["max"]:
                c_min = c_max = c_target = None
            else:
                c_min, c_max, c_target = cogs.get("min"), cogs.get("max"), cogs.get("avg")
            return {
                "min": t_min,
                "max": t_max,
                "target": t_target,
                "level": level,
                "uraian": item.get("uraian", ""),
                "cogs_min": c_min,
                "cogs_max": c_max,
                "cogs_target": c_target
            }

        # 1b. Cek 3 Digit
        if len(kbli_str) >= 3 and kbli_str[:3] in data.get("kategori_g_kbli3", {}):
            item = data["kategori_g_kbli3"][kbli_str[:3]]
            ntb = item["ntb_output"]
            cogs = item["cogs"]
            t_min = ntb["min"] if ntb["min"] is not None else 0.64
            t_max = ntb["max"] if ntb["max"] is not None else 0.78
            t_target = ntb["avg"] if ntb["avg"] is not None else round((t_min + t_max) / 2, 4)
            return {
                "min": t_min,
                "max": t_max,
                "target": t_target,
                "level": f"KBLI_3 ({kbli_str[:3]})",
                "uraian": f"Kelompok KBLI {kbli_str[:3]}",
                "cogs_min": cogs.get("min"),
                "cogs_max": cogs.get("max"),
                "cogs_target": cogs.get("avg")
            }
            
        # 1c. Cek 2 Digit
        if len(kbli_str) >= 2 and kbli_str[:2] in data.get("kategori_g_kbli2", {}):
            item = data["kategori_g_kbli2"][kbli_str[:2]]
            ntb = item["ntb_output"]
            cogs = item["cogs"]
            t_min = ntb["min"] if ntb["min"] is not None else 0.64
            t_max = ntb["max"] if ntb["max"] is not None else 0.78
            t_target = ntb["avg"] if ntb["avg"] is not None else round((t_min + t_max) / 2, 4)
            return {
                "min": t_min,
                "max": t_max,
                "target": t_target,
                "level": f"KBLI_2 ({kbli_str[:2]})",
                "uraian": "Perdagangan Besar (46)" if kbli_str[:2] == "46" else "Perdagangan Eceran (47)",
                "cogs_min": cogs.get("min"),
                "cogs_max": cogs.get("max"),
                "cogs_target": cogs.get("avg")
            }

    # 2. KATEGORI C (INDUSTRI PENGOLAHAN) - Hirarki: 2 Digit -> Kategori
    if kat == "C":
        k2 = kbli_str[:2] if len(kbli_str) >= 2 else ""
        c_map = data.get("kategori_c_kbli2", {})
        if k2 in c_map:
            c_item = c_map[k2]
            key_skala = "besar_sedang" if "besar" in skala.lower() else "mikro_kecil"
            scale_data = c_item.get(key_skala, {})
            t_min = scale_data.get("min")
            t_max = scale_data.get("max")
            if t_min is not None and t_max is not None:
                return {
                    "min": t_min,
                    "max": t_max,
                    "target": round((t_min + t_max) / 2, 4),
                    "level": f"KBLI_2 ({k2} - {key_skala})",
                    "uraian": c_item.get("deskripsi", ""),
                    "cogs_min": None,
                    "cogs_max": None,
                    "cogs_target": None
                }
        # Fallback Kategori C Nasional
        if "C" in c_map:
            c_item = c_map["C"]
            key_skala = "besar_sedang" if "besar" in skala.lower() else "mikro_kecil"
            scale_data = c_item.get(key_skala, {})
            t_min = scale_data.get("min") or 0.34
            t_max = scale_data.get("max") or 0.62
            return {
                "min": t_min,
                "max": t_max,
                "target": round((t_min + t_max) / 2, 4),
                "level": f"KATEGORI_C_NASIONAL ({key_skala})",
                "uraian": "Kategori C Standar Nasional",
                "cogs_min": None,
                "cogs_max": None,
                "cogs_target": None
            }

    # 3. FALLBACK: THRESHOLD KATEGORI UTAMA (A - T)
    kat_master = data.get("kategori", {}).get(kat)
    if kat_master and kat_master.get("min") is not None and kat_master.get("max") is not None:
        t_min = kat_master["min"]
        t_max = kat_master["max"]
        return {
            "min": t_min,
            "max": t_max,
            "target": round((t_min + t_max) / 2, 4),
            "level": f"KATEGORI ({kat})",
            "uraian": kat_master.get("uraian", ""),
            "cogs_min": None,
            "cogs_max": None,
            "cogs_target": None
        }

    # 4. DEFAULT AMAN
    return {
        "min": 0.50,
        "max": 0.85,
        "target": 0.70,
        "level": "DEFAULT_GENERIC",
        "uraian": "Default Rentang Moderat",
        "cogs_min": None,
        "cogs_max": None,
        "cogs_target": None
    }

if __name__ == "__main__":
    print("=== PENGUJIAN THRESHOLD MANAGER ===")
    sample_tests = [
        ("A", "01121"),
        ("C", "10710", "mikro_kecil"),
        ("C", "10710", "besar_sedang"),
        ("C", "99999", "mikro_kecil"),
        ("G", "46201"),
        ("G", "46999"),
        ("G", "47111"),
        ("G", "47999"),
        ("I", "56101"),
        ("T", "96999"),
    ]
    for kat, kbli, *opt in sample_tests:
        skala = opt[0] if opt else "mikro_kecil"
        res = get_threshold(kat, kbli, skala)
        print(f"[{kat}] KBLI: {kbli:5s} ({skala}) -> Rentang: [{res['min']:.4f} - {res['max']:.4f}], Target: {res['target']:.4f} | Resolusi: {res['level']} - {res['uraian']}")
