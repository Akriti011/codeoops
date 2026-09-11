#!/usr/bin/env python3
"""GPU / model-size advisor for the CodeOops HLD/LLD pipeline.

Run this on the machine you intend to generate on. It inspects the GPU and
memory actually present and prints:

  * detected hardware (GPU, VRAM, system RAM)
  * which model parameter sizes are feasible, at Q4 and Q8, with headroom
  * a recommended model for the OVERVIEW / HLD / LLD stages
  * the env vars to set for that recommendation

No dependencies beyond the standard library. Works on Linux (nvidia-smi),
macOS (Apple Silicon unified memory via system_profiler / sysctl), and falls
back to a CPU-only assessment elsewhere.

    python3 scripts/model_advisor.py            # human report
    python3 scripts/model_advisor.py --json     # machine-readable
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

# Rough loaded-weights footprint (GiB) by parameter count and quantization.
# Includes a small runtime overhead; KV-cache for the context window is added
# separately below.
_WEIGHTS_GIB = {
    #  params : (Q4_K_M, Q8_0, FP16)
    7:  (4.7, 7.7, 14.5),
    14: (9.0, 15.0, 28.0),
    32: (19.0, 34.0, 64.0),
    70: (40.0, 75.0, 140.0),
}

# KV-cache GiB per 1k tokens of context, by param size (Q8 kv, ballpark).
_KV_GIB_PER_1K = {7: 0.10, 14: 0.16, 32: 0.28, 70: 0.50}

_STAGE_CONTEXT = {"overview": 12, "hld": 24, "lld": 32}  # k tokens we target per stage


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""


def detect_hardware() -> dict:
    hw = {
        "os": platform.system(),
        "arch": platform.machine(),
        "gpu": None,
        "vram_gib": 0.0,
        "ram_gib": 0.0,
        "unified_memory": False,
        "accelerator": "cpu",
    }

    # System RAM
    if hw["os"] == "Darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out.strip().isdigit():
            hw["ram_gib"] = round(int(out.strip()) / 1024**3, 1)
    elif hw["os"] == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        hw["ram_gib"] = round(int(line.split()[1]) / 1024**2, 1)
        except OSError:
            pass

    # NVIDIA GPU
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        if out.strip():
            name, mem = out.strip().splitlines()[0].split(",")
            hw["gpu"] = name.strip()
            hw["vram_gib"] = round(float(mem) / 1024, 1)
            hw["accelerator"] = "cuda"

    # Apple Silicon: unified memory acts as VRAM for Metal/Ollama.
    if hw["gpu"] is None and hw["os"] == "Darwin" and hw["arch"] == "arm64":
        chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Apple Silicon"
        hw["gpu"] = f"{chip} (integrated, Metal)"
        hw["unified_memory"] = True
        # Ollama can use most of unified memory; keep a floor for the OS.
        hw["vram_gib"] = round(max(hw["ram_gib"] - 3.0, 0.0), 1)
        hw["accelerator"] = "metal"

    # AMD ROCm
    if hw["gpu"] is None and shutil.which("rocm-smi"):
        out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram"])
        if out:
            hw["gpu"] = "AMD GPU (ROCm)"
            hw["accelerator"] = "rocm"

    return hw


def feasibility(hw: dict) -> list[dict]:
    budget = hw["vram_gib"] if hw["accelerator"] != "cpu" else hw["ram_gib"]
    rows = []
    for params, (q4, q8, _fp16) in _WEIGHTS_GIB.items():
        kv_overview = _KV_GIB_PER_1K[params] * _STAGE_CONTEXT["hld"]  # use HLD ctx as the demand
        need_q4 = q4 + kv_overview
        need_q8 = q8 + kv_overview
        rows.append(
            {
                "params_b": params,
                "q4_need_gib": round(need_q4, 1),
                "q8_need_gib": round(need_q8, 1),
                "q4_fits": need_q4 <= budget * 0.92,
                "q8_fits": need_q8 <= budget * 0.92,
            }
        )
    return rows


def recommend(hw: dict, rows: list[dict]) -> dict:
    fits_q4 = [r["params_b"] for r in rows if r["q4_fits"]]
    fits_q8 = [r["params_b"] for r in rows if r["q8_fits"]]
    largest_q4 = max(fits_q4) if fits_q4 else 0
    largest_q8 = max(fits_q8) if fits_q8 else 0

    if largest_q4 == 0:
        return {
            "overview": "7B (CPU / very constrained — expect slow generation)",
            "hld": "7B",
            "lld": "7B",
            "note": "No configuration comfortably fits a >7B model here. Keep the "
            "7B development setup; move HLD/LLD to a GPU machine for a real upgrade.",
        }

    hld_lld = max(largest_q8 or largest_q4, 14) if largest_q4 >= 14 else 7
    overview = 7 if largest_q4 >= 7 else 7
    quant = "Q8" if (largest_q8 and hld_lld <= largest_q8) else "Q4_K_M"
    return {
        "overview": f"{overview}B (Q4_K_M) — deterministic-heavy stage, model size matters least here",
        "hld": f"{hld_lld}B ({quant})",
        "lld": f"{hld_lld}B ({quant})",
        "largest_feasible_q4_b": largest_q4,
        "largest_feasible_q8_b": largest_q8,
        "note": f"HLD/LLD reasoning improves markedly from 7B -> {hld_lld}B. "
        f"32B is preferred for complex designs when it fits ({quant}).",
    }


def env_hint(rec: dict) -> list[str]:
    hld = rec["hld"].split("B")[0].strip()
    return [
        "# suggested .env for this machine (adjust MODEL names to what `ollama list` shows)",
        "OVERVIEW_MODEL=qwen2.5-coder:7b",
        "OVERVIEW_NUM_CTX=12288",
        f"HLD_MODEL=qwen2.5-coder:{hld}b" if hld.isdigit() else "HLD_MODEL=qwen2.5-coder:14b",
        "HLD_NUM_CTX=24576",
        "HLD_MAX_TOKENS=6000",
        f"LLD_MODEL=qwen2.5-coder:{hld}b" if hld.isdigit() else "LLD_MODEL=qwen2.5-coder:14b",
        "LLD_NUM_CTX=32768",
        "LLD_MAX_TOKENS=8000",
    ]


def main() -> int:
    hw = detect_hardware()
    rows = feasibility(hw)
    rec = recommend(hw, rows)

    if "--json" in sys.argv:
        print(json.dumps({"hardware": hw, "feasibility": rows, "recommendation": rec,
                          "env_hint": env_hint(rec)}, indent=2))
        return 0

    print("=" * 68)
    print("CodeOops model advisor")
    print("=" * 68)
    print(f"  OS / arch     : {hw['os']} / {hw['arch']}")
    print(f"  GPU           : {hw['gpu'] or 'none detected'}")
    print(f"  Accelerator   : {hw['accelerator']}")
    print(f"  VRAM (usable) : {hw['vram_gib']} GiB"
          + ("  (unified memory)" if hw["unified_memory"] else ""))
    print(f"  System RAM    : {hw['ram_gib']} GiB")
    print()
    print("  Feasible model sizes (weights + HLD-context KV cache, 8% headroom):")
    print(f"    {'params':>7} | {'Q4 need':>8} | {'Q4 fits':>7} | {'Q8 need':>8} | {'Q8 fits':>7}")
    for r in rows:
        print(f"    {str(r['params_b']) + 'B':>7} | {r['q4_need_gib']:>6} G | "
              f"{'yes' if r['q4_fits'] else 'no':>7} | {r['q8_need_gib']:>6} G | "
              f"{'yes' if r['q8_fits'] else 'no':>7}")
    print()
    print("  Recommendation:")
    print(f"    OVERVIEW : {rec['overview']}")
    print(f"    HLD      : {rec['hld']}")
    print(f"    LLD      : {rec['lld']}")
    print(f"    {rec['note']}")
    print()
    for line in env_hint(rec):
        print("  " + line)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
