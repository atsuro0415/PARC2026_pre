"""ポリシーサーバー（提出用テンプレート）

このファイルを編集して、自分のモデルを組み込んでください。
編集が必要なのは MyPolicy クラスの中身だけです。
それ以外のコード（サーバー部分、シリアライゼーション）は変更不可です。

ローカルテスト:
    pip install -r requirements.txt
    python policy_server.py                  # サーバー起動（port 8000）

    # 別ターミナルで評価実行
    python -m pipeline --server-url http://localhost:8000 --dry-run
"""

import argparse
from abc import ABC, abstractmethod

import msgpack
import numpy as np
import uvicorn
from fastapi import FastAPI, Request, Response


# ============================================================
# ポリシーのインターフェース定義（変更不可）
# MyPolicy が満たすべき get_action() / reset() の仕様を定める。
# ============================================================


class BasePolicy(ABC):
    """ポリシーの基底クラス。get_action() と reset() を実装してください。"""

    @abstractmethod
    def get_action(self, obs: dict[str, np.ndarray]) -> np.ndarray:
        """観測からアクションを推論する。

        Args:
            obs: 環境からの観測。以下のキーが含まれる:
                - "agentview_image": (128, 128, 3) uint8
                - "robot0_eye_in_hand_image": (128, 128, 3) uint8
                - "robot0_joint_pos": (7,) float
                - "robot0_eef_pos": (3,) float
                - "robot0_eef_quat": (4,) float
                - "robot0_gripper_qpos": (2,) float

        Returns:
            action: (7,) float32 — [dx, dy, dz, droll, dpitch, dyaw, gripper]
        """
        ...

    @abstractmethod
    def reset(self, instruction: str = "") -> None:
        """エピソード開始時に呼ばれる。内部状態をリセットしてください。

        Args:
            instruction: タスクの言語指示（例: "pick up the red mug and place it on the shelf"）
        """
        ...


# ============================================================
# ここを編集する（MyPolicy の中身だけを自分のモデルに置き換える）
# ============================================================

# ---- パス設定（zip レイアウトに合わせる）-------------------------------
# submission.zip
# ├── policy_server.py
# ├── requirements.txt
# └── model_weights/
#     ├── config.json, model.safetensors, policy_preprocessor_*.json/.safetensors ...
#     ├── vlm_tokenizer/   ← SmolVLM2-500M のトークナイザ一式
#     └── vendor/lerobot/  ← vendored lerobot v0.6.0 (Py3.10 パッチ済み)
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
MODEL_DIR = _ROOT / "model_weights"
TOKENIZER_DIR = MODEL_DIR / "vlm_tokenizer"
VENDOR_DIR = MODEL_DIR / "vendor"

if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

# --- Python 3.10 compat shim (grading env is 3.10; lerobot v0.6.0 uses 3.11 features) ---
if sys.version_info < (3, 11):
    import datetime as _dt
    import enum as _enum
    import typing as _typing
    import typing_extensions as _te
    if not hasattr(_typing, "Self"):
        _typing.Self = _te.Self
    for _name in ("Unpack", "Required", "NotRequired", "Never", "LiteralString",
                  "TypeVarTuple", "Unpack", "assert_never", "assert_type",
                  "dataclass_transform", "override"):
        if not hasattr(_typing, _name) and hasattr(_te, _name):
            setattr(_typing, _name, getattr(_te, _name))
    if not hasattr(_enum, "StrEnum"):
        class _StrEnum(str, _enum.Enum):
            pass
        _enum.StrEnum = _StrEnum
    if not hasattr(_dt, "UTC"):
        _dt.UTC = _dt.timezone.utc
# -----------------------------------------------------------------------

# 学習済み config の input_features と照合済み (2026-08-03 verify_state_order.py)
KEY_IMG_AGENT = "observation.images.front"   # ← agentview_image をここに割り当て
KEY_IMG_WRIST = "observation.images.wrist"   # ← robot0_eye_in_hand_image
KEY_STATE = "observation.state"

IMG_SIZE = 256  # 学習時解像度。観測は 128x128 で来るのでアップスケールする


def _quat_xyzw_to_axis_angle(q: np.ndarray) -> np.ndarray:
    """quaternion (x, y, z, w) → axis-angle (3,)。

    robosuite の T.quat2axisangle と同一の規約 (angle = 2*acos(w) ∈ [0, 2π]、
    [-π, π] への折り返しなし)。学習データの normalizer 統計で
    state dim 3 の max が +3.77 (> π) であることから、この規約で
    生成されたと確認済み。折り返すと π 近傍で符号反転し正規化が壊れる。
    """
    q = q.astype(np.float64)
    q = q / max(np.linalg.norm(q), 1e-12)
    w = float(np.clip(q[3], -1.0, 1.0))
    den = np.sqrt(max(1.0 - w * w, 0.0))
    if np.isclose(den, 0.0):
        return np.zeros(3, dtype=np.float32)
    return (q[:3] * (2.0 * np.arccos(w)) / den).astype(np.float32)


class MyPolicy(BasePolicy):
    """SmolVLA (LoRA マージ済み) による VLA ポリシー。

    - モデル/プロセッサは __init__ で 1 回だけロード（起動 120 秒制限内）
    - action chunking は SmolVLAPolicy.select_action() 内部のキューに任せる
      （n_action_steps ごとに 1 回だけ重い推論が走り、他ステップはキューから
        取り出すだけなので 10 秒/リクエスト制限を満たす）
    """

    def __init__(self):
        import torch

        from lerobot.configs import PreTrainedConfig
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig  # noqa: F401  (registry 登録に必要)
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
        from lerobot.processor import PolicyProcessorPipeline
        from lerobot.processor.converters import (
            batch_to_transition,
            policy_action_to_transition,
            transition_to_batch,
            transition_to_policy_action,
        )

        self._torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # --- ポリシー本体（VLM はローカルのトークナイザ dir を参照させる）---
        # config.json の "type": "smolvla" は基底クラスの choice registry が
        # 消費するため、SmolVLAConfig ではなく PreTrainedConfig 経由でロードする
        cfg = PreTrainedConfig.from_pretrained(MODEL_DIR)
        cfg.vlm_model_name = str(TOKENIZER_DIR)
        self.policy = SmolVLAPolicy.from_pretrained(MODEL_DIR, config=cfg)
        self.policy.to(self.device)
        self.policy.eval()

        # --- 前処理/後処理パイプライン ---
        self.preprocessor = PolicyProcessorPipeline.from_pretrained(
            MODEL_DIR,
            config_filename="policy_preprocessor.json",
            overrides={
                "tokenizer_processor": {"tokenizer_name": str(TOKENIZER_DIR)},
                "device_processor": {"device": self.device},
            },
            to_transition=batch_to_transition,
            to_output=transition_to_batch,
        )
        self.postprocessor = PolicyProcessorPipeline.from_pretrained(
            MODEL_DIR,
            config_filename="policy_postprocessor.json",
            overrides={
                "device_processor": {"device": self.device},
            },
            to_transition=policy_action_to_transition,
            to_output=transition_to_policy_action,
        )

        self.instruction = ""

        # --- warmup: pay first-inference cost at startup, not on first /act ---
        dummy_obs = {
            "agentview_image": np.zeros((128, 128, 3), dtype=np.uint8),
            "robot0_eye_in_hand_image": np.zeros((128, 128, 3), dtype=np.uint8),
            "robot0_eef_pos": np.zeros(3, dtype=np.float32),
            "robot0_eef_quat": np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
            "robot0_gripper_qpos": np.zeros(2, dtype=np.float32),
        }
        self.instruction = "warmup"
        _ = self.get_action(dummy_obs)
        self.policy.reset()
        self.instruction = ""

    # ---------------- 観測 → モデル入力 ----------------

    def _prep_image(self, img_hwc_uint8: np.ndarray):
        """(128,128,3) uint8 → (1,3,256,256) float32 [0,1]"""
        torch = self._torch
        t = torch.from_numpy(np.ascontiguousarray(img_hwc_uint8[::-1, ::-1]))  # LiberoProcessor と同じ 180 度回転
        t = t.permute(2, 0, 1).unsqueeze(0).float() / 255.0
        t = torch.nn.functional.interpolate(
            t, size=(IMG_SIZE, IMG_SIZE), mode="bilinear", align_corners=False
        )
        return t

    def _build_batch(self, obs: dict[str, np.ndarray]) -> dict:
        torch = self._torch
        axis_angle = _quat_xyzw_to_axis_angle(obs["robot0_eef_quat"])
        state = np.concatenate(
            [
                obs["robot0_eef_pos"].astype(np.float32),      # (3,)
                axis_angle,                                     # (3,)
                obs["robot0_gripper_qpos"].astype(np.float32),  # (2,)
            ]
        )  # → (8,)  ※順序は verify_state_order.py で normalizer 統計と照合済みであること
        return {
            KEY_IMG_AGENT: self._prep_image(obs["agentview_image"]),
            KEY_IMG_WRIST: self._prep_image(obs["robot0_eye_in_hand_image"]),
            KEY_STATE: torch.from_numpy(state).unsqueeze(0),  # (1, 8)
            "task": self.instruction,
        }

    # ---------------- BasePolicy 実装 ----------------

    def get_action(self, obs: dict[str, np.ndarray]) -> np.ndarray:
        torch = self._torch
        with torch.no_grad():
            batch = self.preprocessor(self._build_batch(obs))
            action = self.policy.select_action(batch)  # キュー管理込み → (1, action_dim)
            action = self.postprocessor(action)
        action = action.squeeze(0).cpu().numpy().astype(np.float32)
        return action[:7]

    def reset(self, instruction: str = "") -> None:
        self.instruction = instruction
        self.policy.reset()  # action chunking のキューをクリア


# ============================================================
# 以下は変更不可
# ============================================================


def deserialize_obs(data: bytes) -> dict[str, np.ndarray]:
    unpacked = msgpack.unpackb(data, raw=False)
    obs = {}
    for key, val in unpacked.items():
        arr = np.frombuffer(val["data"], dtype=np.dtype(val["dtype"]))
        obs[key] = arr.reshape(val["shape"]).copy()
    return obs


def serialize_action(action: np.ndarray) -> bytes:
    return msgpack.packb(
        {"data": action.astype(np.float32).tobytes()},
        use_bin_type=True,
    )


app = FastAPI(title="VLA Policy Server")
_policy: BasePolicy | None = None


def set_policy(policy: BasePolicy) -> None:
    global _policy
    _policy = policy


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reset")
async def reset_policy(request: Request):
    body = await request.body()
    instruction = ""
    if body:
        import json
        data = json.loads(body)
        instruction = data.get("instruction", "")
    _policy.reset(instruction=instruction)
    return {"status": "ok"}


@app.post("/act")
async def act(request: Request):
    body = await request.body()
    obs = deserialize_obs(body)
    action = _policy.get_action(obs)
    return Response(
        content=serialize_action(action),
        media_type="application/x-msgpack",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    set_policy(MyPolicy())
    print(f"Policy server starting on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
