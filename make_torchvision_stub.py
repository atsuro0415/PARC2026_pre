"""torchvision スタブ生成スクリプト (v3)

v3: 全モジュールに PEP 562 の __getattr__ を実装した万能構造に変更。
    どのモジュールからどんなシンボルを import されても通り、実際に
    呼び出された時だけ NotImplementedError で明示的に失敗する。
    transformers 5.5.4 全体の torchvision import (v2.functional / io /
    ops.boxes.batched_nms / ops.masks_to_boxes 等) を一括カバー。

背景:
  採点イメージの torch 2.11.0+cpu に対し PyPI の torchvision は ABI 不整合で
  import 不能。requirements.txt は --index-url 禁止のため CPU 版を導入できない。
  lerobot / transformers とも SmolVLA 推論経路では torchvision を「import
  できること」しか要求しないため、純 Python スタブで差し替える。

使い方 (WSL の ~/PARC2026_pre で):
    python3 make_torchvision_stub.py
"""

import shutil
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "submission_template" / "model_weights" / "vendor"

# どの import 形式にも耐える汎用 __getattr__。
# `from module import name` も PEP 562 でこの関数を経由する。
LAZY_GETATTR = '''

def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)

    class _Unavailable:
        """import は通すが、使用 (呼出/継承/インスタンス化) されたら失敗させる。"""
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                f"torchvision stub: {__name__}.{name} は利用できません"
            )
        def __call__(self, *args, **kwargs):
            raise NotImplementedError(
                f"torchvision stub: {__name__}.{name} は利用できません"
            )
    _Unavailable.__name__ = name
    return _Unavailable
'''

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

from . import io  # noqa: F401
from . import models  # noqa: F401
from . import ops  # noqa: F401
from . import transforms  # noqa: F401
''' + LAZY_GETATTR,
    "torchvision/_interpolation.py": INTERPOLATION_MODE,
    "torchvision/io.py": '"""torchvision.io スタブ (read_image 等)。"""' + LAZY_GETATTR,
    "torchvision/transforms/__init__.py": '''\
from .._interpolation import InterpolationMode  # noqa: F401
from . import functional  # noqa: F401
from . import v2  # noqa: F401
''' + LAZY_GETATTR,
    "torchvision/transforms/functional.py": '''\
from .._interpolation import InterpolationMode  # noqa: F401
''' + LAZY_GETATTR,
    "torchvision/transforms/v2/__init__.py": '''\
import torch.nn as nn

from ..._interpolation import InterpolationMode  # noqa: F401
from . import functional  # noqa: F401


class Transform(nn.Module):
    """クラス定義の基底としてのみ使用される (本経路では未インスタンス化)。"""


class Identity(Transform):
    def forward(self, *inputs):
        return inputs[0] if len(inputs) == 1 else inputs
''' + LAZY_GETATTR,
    "torchvision/transforms/v2/functional.py": '''\
from ..._interpolation import InterpolationMode  # noqa: F401
''' + LAZY_GETATTR,
    "torchvision/models/__init__.py": 'from . import _utils  # noqa: F401\n' + LAZY_GETATTR,
    "torchvision/models/_utils.py": '"""IntermediateLayerGetter 等のスタブ。"""' + LAZY_GETATTR,
    "torchvision/ops/__init__.py": '''\
from . import boxes  # noqa: F401
from . import misc  # noqa: F401
''' + LAZY_GETATTR,
    "torchvision/ops/boxes.py": '"""batched_nms 等のスタブ。"""' + LAZY_GETATTR,
    "torchvision/ops/misc.py": '"""FrozenBatchNorm2d 等のスタブ。"""' + LAZY_GETATTR,
}


def main():
    if not VENDOR.exists():
        raise SystemExit(f"vendor ディレクトリが見つかりません: {VENDOR}")
    old = VENDOR / "torchvision"
    if old.exists():
        try:
            shutil.rmtree(old)
            print(f"removed old stub: {old}")
        except PermissionError:
            raise SystemExit(
                f"権限エラー: sudo rm -rf {old} を実行してから再度お試しください"
            )
    for rel, content in FILES.items():
        path = VENDOR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path}")
    print("\n完了。スモークテストを再実行してください。")


if __name__ == "__main__":
    main()
