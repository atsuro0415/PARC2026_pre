"""state vector の次元順序を normalizer 統計から検証するスクリプト

使い方 (WSL の ~/PARC2026_pre で):
    python verify_state_order.py --model-dir model_weights

やること:
  1. config.json の input_features / output_features を表示
     → 画像キー名 (observation.images.xxx) と state の次元数を確認
  2. policy_preprocessor_step_5_normalizer_processor.safetensors を読み、
     observation.state の各次元の mean/std (または min/max) を表示
  3. 期待レンジと照合するためのガイドを表示

判定の目安 (想定順序 [eef_pos(3), axis_angle(3), gripper_qpos(2)]):
  - dim 0-2 (eef_pos): mean が位置っぽい値。x,y は ±0.3 程度、
    z はロボット座標系次第で ~1.0 前後 or 0.2-0.4 程度。std は 0.05-0.2 程度
  - dim 3-5 (axis_angle): mean は ±π 内。回転成分は std が大きめ (0.1-3.0)
    になりやすく、特に 1 次元だけ |mean| が π 近い (初期姿勢で反転) ことが多い
  - dim 6-7 (gripper_qpos): 0-0.04 程度の小さい値で、2 次元が互いに
    ほぼ対称 (mean が +0.02 / -0.02 など) になりやすい

もし dim 0-2 に π 級の値が来ていたら回転が先、gripper っぽい微小値が
先頭に来ていたら順序が違う、と判断できる。
"""

import argparse
import json
from pathlib import Path


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
    for key in ("vlm_model_name", "chunk_size", "n_action_steps", "max_state_dim", "max_action_dim"):
        if key in cfg:
            print(f"{key}: {cfg[key]}")

    # ---- 2. normalizer safetensors ----
    from safetensors import safe_open

    candidates = sorted(model_dir.glob("*normalizer*safetensors"))
    if not candidates:
        print("\n!! normalizer の safetensors が見つかりません")
        return
    print()
    print("=" * 70)
    print("[2] normalizer 統計")
    print("=" * 70)
    for path in candidates:
        print(f"\n--- {path.name} ---")
        with safe_open(str(path), framework="np") as f:
            for key in f.keys():
                t = f.get_tensor(key)
                flat = t.flatten()
                vals = ", ".join(f"{v:+.4f}" for v in flat[:16])
                print(f"{key}  shape={t.shape}")
                print(f"    [{vals}{' ...' if flat.size > 16 else ''}]")

    print()
    print("=" * 70)
    print("[3] 判定ガイド")
    print("=" * 70)
    print("""observation.state の mean/std を上の目安と照合:
  dim 0-2 が位置レンジ / dim 3-5 が回転レンジ / dim 6-7 が gripper 微小値
なら [eef_pos, axis_angle, gripper_qpos] の順序で確定。
ズレていたらこの出力を Claude に貼って相談してください。""")


if __name__ == "__main__":
    main()
