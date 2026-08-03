"""torchvision スタブ生成スクリプト

背景:
  採点イメージの torch は 2.11.0+cpu (PyTorch 公式 CPU ビルド) だが、PyPI の
  torchvision は ABI が合わず `operator torchvision::nms does not exist` で
  import 自体が失敗する。requirements.txt では --index-url が禁止のため
  CPU 版 torchvision は導入できない。

  vendored lerobot v0.6.0 が torchvision を import するのは以下の 3 箇所のみで、
  いずれも SmolVLA の推論経路では実行されない (学習用 transform / HIL 用):
    - lerobot/transforms/transforms.py:  from torchvision.transforms import v2
                                         from torchvision.transforms.v2 import Transform, functional
    - lerobot/processor/hil_processor.py: import torchvision.transforms.functional

  そこで import だけ成功する純 Python スタブを vendor/ 直下に置き、
  site-packages の壊れた torchvision を差し替える (vendor/ は sys.path 先頭)。

使い方 (WSL の ~/PARC2026_pre で):
    python3 make_torchvision_stub.py
    # → submission_template/model_weights/vendor/torchvision/ が生成される
"""

from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "submission_template" / "model_weights" / "vendor"

FILES = {
    "torchvision/__init__.py": '''\
"""torchvision スタブ (PARC2026 提出用)

採点環境の torch 2.11.0+cpu と PyPI 版 torchvision の ABI 不整合を回避するため、
import だけ成功する純 Python スタブに差し替えている。
vendored lerobot の SmolVLA 推論経路は torchvision を実行時に使用しない。
"""
__version__ = "0.0.0+parc2026stub"

from . import transforms  # noqa: F401
''',
    "torchvision/transforms/__init__.py": '''\
from . import functional  # noqa: F401
from . import v2  # noqa: F401
''',
    "torchvision/transforms/functional.py": '''\
"""hil_processor 用スタブ。属性アクセスは通るが、呼び出されたら明示的に失敗させる。"""


def __getattr__(name):
    def _unavailable(*args, **kwargs):
        raise NotImplementedError(
            f"torchvision stub: transforms.functional.{name} は本スタブでは利用できません"
        )
    return _unavailable
''',
    "torchvision/transforms/v2/__init__.py": '''\
"""lerobot/transforms/transforms.py が要求する最小 API のみ提供する。"""
import torch.nn as nn

from . import functional  # noqa: F401


class Transform(nn.Module):
    """クラス定義の基底としてのみ使用される (本経路では未インスタンス化)。"""


class Identity(Transform):
    def forward(self, *inputs):
        return inputs[0] if len(inputs) == 1 else inputs


def __getattr__(name):
    raise AttributeError(
        f"torchvision stub: transforms.v2.{name} は本スタブでは利用できません"
    )
''',
    "torchvision/transforms/v2/functional.py": '''\
def __getattr__(name):
    def _unavailable(*args, **kwargs):
        raise NotImplementedError(
            f"torchvision stub: v2.functional.{name} は本スタブでは利用できません"
        )
    return _unavailable
''',
}


def main():
    if not VENDOR.exists():
        raise SystemExit(f"vendor ディレクトリが見つかりません: {VENDOR}")
    for rel, content in FILES.items():
        path = VENDOR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path}")
    print("\n完了。requirements.txt から torchvision の行を削除するのを忘れずに。")


if __name__ == "__main__":
    main()
