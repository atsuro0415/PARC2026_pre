"""state vector の次元順序を normalizer 統計から検証するスクリプト (v2)

v2: safetensors ライブラリ不要。numpy だけでファイルを直接パースする。

使い方 (WSL の ~/PARC2026_pre で):
    docker run --rm -v ~/PARC2026_pre:/repo -w /repo parc2026:latest \
        python3 verify_state_order.py --model-dir model_weights

判定の目安 (想定順序 [eef_pos(3), axis_angle(3), gripper_qpos(2)]):
  - dim 0-2 (eef_pos): 位置っぽい値。x,y は ±0.3 程度、z は座標系次第で
    ~1.0 前後 or 0.2-0.4 程度。std は 0.05-0.2 程度
  - dim 3-5 (axis_angle): ±π 内。1 次元だけ |mean| が π 近いことが多い
  - dim 6-7 (gripper_qpos): 0-0.04 程度の微小値で 2 次元がほぼ対称
"""

import argparse
import json
import struct
from pathlib import Path

import numpy as np

_DTYPES = {
    "F64": np.float64, "F32": np.float32, "F16": np.float16,
    "I64": np.int64, "I32": np.int32, "I16": np.int16, "I8": np.int8,
    "U8": np.uint8, "BOOL": np.bool_,
}


def read_safetensors(path: Path) -> dict[str, np.ndarray]:
    """safetensors を numpy だけで読む。BF16 のみ float32 に変換して返す。"""
    raw = path.read_bytes()
    (header_len,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + header_len])
    buf = raw[8 + header_len :]
    tensors = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        b, e = info["data_offsets"]
        dtype_str = info["dtype"]
        if dtype_str == "BF16":
            u16 = np.frombuffer(buf[b:e], dtype=np.uint16)
            arr = (u16.astype(np.uint32) << 16).view(np.float32)
        else:
            arr = np.frombuffer(buf[b:e], dtype=_DTYPES[dtype_str])
        tensors[name] = arr.reshape(info["shape"]).copy()
    return tensors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path("model_weights"))
    args = parser.parse_args()
    model_dir = args.model_dir

    # ---- 1. config.json ----
    cfg_path = model_dir / "config.json"
    print("=" * 70)
    print(f"[1] {cfg_path}")
    print("=" * 70)
    cfg = json.loads(cfg_path.read_text())
    for key in ("input_features", "output_features"):
        print(f"\n{key}:")
        print(json.dumps(cfg.get(key), indent=2, ensure_ascii=False))
    for key in ("vlm_model_name", "chunk_size", "n_action_steps"):
        if key in cfg:
            print(f"{key}: {cfg[key]}")

    # ---- 2. normalizer safetensors ----
    candidates = sorted(model_dir.glob("*normalizer*safetensors"))
    if not candidates:
        print("\n!! normalizer の safetensors が見つかりません")
        print("model_weights/ 内の一覧:")
        for p in sorted(model_dir.iterdir()):
            print(f"  {p.name}")
        return
    print()
    print("=" * 70)
    print("[2] normalizer 統計")
    print("=" * 70)
    for path in candidates:
        print(f"\n--- {path.name} ---")
        for key, t in read_safetensors(path).items():
            flat = t.flatten()
            vals = ", ".join(f"{v:+.4f}" for v in flat[:16])
            print(f"{key}  shape={t.shape} ")
            print(f"    [{vals}{' ...' if flat.size > 16 else ''}]")

    print()
    print("=" * 70)
    print("[3] 判定ガイド")
    print("=" * 70)
    print("""observation.state の統計を上の目安と照合:
  dim 0-2 が位置レンジ / dim 3-5 が回転レンジ / dim 6-7 が gripper 微小値
なら [eef_pos, axis_angle, gripper_qpos] の順序で確定。""")


if __name__ == "__main__":
    main()
