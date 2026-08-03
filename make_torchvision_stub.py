"""torchvision スタブ生成スクリプト (v2)

v2: transformers 5.5.x が参照するシンボルを追加
  - torchvision.transforms.InterpolationMode (実 enum、モジュールレベルの
    マッピング辞書で使われるため本物と同じメンバーを持つ)
  - torchvision.transforms.functional.InterpolationMode
  - torchvision.models._utils.IntermediateLayerGetter / torchvision.ops.misc
    (lerobot 他モジュール向けの保険)

背景:
  採点イメージの torch 2.11.0+cpu に対し PyPI の torchvision は ABI 不整合で
  import 不能。requirements.txt は --index-url 禁止のため CPU 版を導入できない。
  lerobot / transformers とも推論経路では torchvision を「import できること」
  しか要求しないため、純 Python スタブで差し替える (vendor/ は sys.path 先頭)。

使い方 (WSL の ~/PARC2026_pre で):
    python3 make_torchvision_stub.py
"""

from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "submission_template" / "model_weights" / "vendor"

INTERPOLATION_MODE = '''\
from enum import Enum


class InterpolationMode(Enum):
    """torchvision.transforms.InterpolationMode 互換 enum。"""
    NEAREST = "nearest"
    NEAREST_EXACT = "nearest-exact"
    BILINEAR = "bilinear"
    BICUBIC = "bicubic"
    BOX = "box"
    HAMMING = "hamming"
    LANCZOS = "lanczos"
'''

FILES = {
    "torchvision/__init__.py": '''\
"""torchvision スタブ (PARC2026 提出用)

採点環境の torch 2.11.0+cpu と PyPI 版 torchvision の ABI 不整合を回避するため、
import だけ成功する純 Python スタブに差し替えている。
lerobot / transformers の SmolVLA 推論経路は torchvision を実行時に使用しない。
"""
__version__ = "0.0.0+parc2026stub"

from . import models  # noqa: F401
from . import ops  # noqa: F401
from . import transforms  # noqa: F401
''',
    "torchvision/_interpolation.py": INTERPOLATION_MODE,
    "torchvision/transforms/__init__.py": '''\
from .._interpolation import InterpolationMode  # noqa: F401
from . import functional  # noqa: F401
from . import v2  # noqa: F401


class ToPILImage:
    def __call__(self, *args, **kwargs):
        raise NotImplementedError("torchvision stub: ToPILImage は利用できません")
''',
    "torchvision/transforms/functional.py": '''\
from .._interpolation import InterpolationMode  # noqa: F401


def __getattr__(name):
    def _unavailable(*args, **kwargs):
        raise NotImplementedError(
            f"torchvision stub: transforms.functional.{name} は利用できません"
        )
    return _unavailable
''',
    "torchvision/transforms/v2/__init__.py": '''\
import torch.nn as nn

from ..._interpolation import InterpolationMode  # noqa: F401
from . import functional  # noqa: F401


class Transform(nn.Module):
    """クラス定義の基底としてのみ使用される (本経路では未インスタンス化)。"""


class Identity(Transform):
    def forward(self, *inputs):
        return inputs[0] if len(inputs) == 1 else inputs


def __getattr__(name):
    raise AttributeError(f"torchvision stub: transforms.v2.{name} は利用できません")
''',
    "torchvision/transforms/v2/functional.py": '''\
from ..._interpolation import InterpolationMode  # noqa: F401


def __getattr__(name):
    def _unavailable(*args, **kwargs):
        raise NotImplementedError(
            f"torchvision stub: v2.functional.{name} は利用できません"
        )
    return _unavailable
''',
    "torchvision/models/__init__.py": '''\
from . import _utils  # noqa: F401
''',
    "torchvision/models/_utils.py": '''\
class IntermediateLayerGetter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "torchvision stub: IntermediateLayerGetter は利用できません"
        )
''',
    "torchvision/ops/__init__.py": '''\
from . import misc  # noqa: F401
''',
    "torchvision/ops/misc.py": '''\
import torch.nn as nn


class FrozenBatchNorm2d(nn.Module):
    def __init__(self, *args, **kwargs):
        super().__init__()
        raise NotImplementedError(
            "torchvision stub: FrozenBatchNorm2d は利用できません"
        )
''',
}


def main():
    if not VENDOR.exists():
        raise SystemExit(f"vendor ディレクトリが見つかりません: {VENDOR}")
    # v1 の残骸を掃除してから生成
    import shutil
    old = VENDOR / "torchvision"
    if old.exists():
        shutil.rmtree(old)
        print(f"removed old stub: {old}")
    for rel, content in FILES.items():
        path = VENDOR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path}")
    print("\n完了。スモークテストを再実行してください。")


if __name__ == "__main__":
    main()
