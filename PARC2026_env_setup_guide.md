# PARC2026 予選 環境構築ガイド

自宅デスクトップPCを開発サーバー化し、ノートPC（Zenbook）から SSH で操作して
PARC2026 予選の評価環境（Docker）と学習済みモデルの検証環境を構築するまでの全手順。

実際に 2026-08-02 に構築した際の手順・ハマりどころをそのまま記録したもの。

## 全体像

```
Zenbook (ノートPC)                     … 端末（画面とキーボード）
   │  ssh atsur@192.168.10.117 -p 2222
   ▼
デスクトップPC (Windows 11 / i5-10400 / RAM 32GB / GPU なし)
   └ WSL2 Ubuntu 24.04                 … コード編集・git 操作・docker build
      └ Docker イメージ parc2026       … 本番同一の評価環境
                                          (Ubuntu 22.04 + osmesa + Python 3.10)
```

役割分担の原則:

| 場所 | やること |
|---|---|
| WSL ホスト (`~/PARC2026_pre`) | コード編集、git 操作、docker build |
| コンテナ (`/workspace`) | 評価の実行のみ（`--rm` なので使い捨て） |
| Google Colab | GPU が要る学習のみ |

---

## Phase 1: デスクトップのサーバー化

### 1-1. WSL2 の確認

デスクトップの PowerShell（管理者）で:

```powershell
wsl --status
wsl --list -v
```

- 既に `Ubuntu`（24.04）と `docker-desktop` が入っていればそのまま使える
- 何も無ければ `wsl --install -d Ubuntu-22.04`（22.04 なら Python 3.10 がデフォルト）
- **24.04（Python 3.12）でも問題ない**。PARC 環境は Docker 内で完結するため

### 1-2. WSL 内に SSH サーバー

WSL の Ubuntu で（PowerShell から `wsl` と打てば入れる）:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo sed -i 's/^#\?Port .*/Port 2222/' /etc/ssh/sshd_config
```

**⚠ Ubuntu 24.04 の罠: socket activation**

24.04 の sshd は `ssh.socket` 経由で起動し、`sshd_config` の `Port` 設定が
無視されて 22 番で待ち受ける。2222 に接続すると `Connection reset` になる。
通常のサービス方式へ切り替える:

```bash
sudo systemctl disable --now ssh.socket
sudo systemctl enable --now ssh.service
sudo ss -tlnp | grep ssh     # *:2222 が出ていれば OK
```

### 1-3. Windows → WSL のポート転送

WSL は内部 IP を持つため、LAN から届くように Windows 側で転送する。
管理者 PowerShell で:

```powershell
$wslip = (wsl hostname -I).Trim().Split(" ")[0]
netsh interface portproxy add v4tov4 listenport=2222 listenaddress=0.0.0.0 connectport=2222 connectaddress=$wslip
New-NetFirewallRule -DisplayName "WSL SSH" -Direction Inbound -LocalPort 2222 -Protocol TCP -Action Allow
```

**⚠ WSL の IP は再起動ごとに変わる。** 繋がらなくなったら転送を張り直す:

```powershell
$wslip = (wsl hostname -I).Trim().Split(" ")[0]
netsh interface portproxy delete v4tov4 listenport=2222 listenaddress=0.0.0.0
netsh interface portproxy add v4tov4 listenport=2222 listenaddress=0.0.0.0 connectport=2222 connectaddress=$wslip
```

### 1-4. Zenbook から接続テスト

Zenbook の **64bit 版** PowerShell で:

```powershell
ssh atsur@192.168.10.117 -p 2222
```

初回は fingerprint の確認に `yes`、パスワードは **Ubuntu のもの**（Windows ではない）。

**ハマりどころ:**

| 症状 | 原因 | 対処 |
|---|---|---|
| `ssh` が認識されない | **PowerShell (x86)** を開いている | (x86) の付かない方を使う |
| `Connection reset` | socket activation で 22 番待ち受け | 1-2 の systemctl 切り替え |
| sudo パスワードを忘れた | — | `wsl -d Ubuntu -u root` で入り `passwd <ユーザー名>` |
| `apt` が無い / 「Sudo が無効」 | Git Bash (MINGW64) で実行している | `wsl` で Ubuntu に入る |

**プロンプトの見分け方**（迷子防止に最重要）:

| 表示 | 場所 |
|---|---|
| `PS C:\...>` | Windows PowerShell |
| `...MINGW64 ~$` | Git Bash（apt も service も無い） |
| `atsur@DESKTOP-XXXX:~$` | WSL Ubuntu |
| `root@xxxx:/workspace#` | Docker コンテナ内（`--rm` なので変更は消える） |

---

## Phase 2: PARC2026 評価環境（Docker）

WSL で:

```bash
cd ~
git clone https://github.com/matsuolab/PARC2026_pre
cd PARC2026_pre
docker build -t parc2026 .     # 10〜20分 + 数GBのダウンロード
```

- `docker: command not found` の場合は Docker Desktop → Settings →
  Resources → **WSL Integration** で Ubuntu を ON にして再起動
- Dockerfile は本番採点環境と同一構成（Ubuntu 22.04 + osmesa）で、
  ビルド時に `setup.sh` が torch(CPU)・mujoco・LIBERO-plus・アセットを導入する
- 完成イメージは約 23.5GB（ディスク使用量）

### 疎通確認（ランダムポリシー）

```bash
docker run -it --rm parc2026
# コンテナ内で:
python submission_template/policy_server.py --port 8000 &
sleep 5
python -m pipeline --server-url http://localhost:8000 --track track1 --n-episodes 1 --max-steps 100
```

4 タスクが完走し成功率 0%（ランダムなので正常）が出れば評価環境は完成。

### 開発時の実行形態

編集のたびに build し直さないよう、テンプレートをマウントして使う:

```bash
docker run -it --rm -v ~/PARC2026_pre/submission_template:/workspace/submission_template parc2026
```

---

## Phase 3: Git 環境（fork + ブランチ）

主催者リポジトリには push 権限が無いので、自分の GitHub に fork して繋ぎ替える。

1. ブラウザで `https://github.com/matsuolab/PARC2026_pre` → **Fork**

2. WSL で remote を整理:

```bash
cd ~/PARC2026_pre
git remote rename origin upstream
git remote add origin https://github.com/<自分のID>/PARC2026_pre.git
git remote set-url upstream https://github.com/matsuolab/PARC2026_pre.git
git remote -v    # origin=自分 / upstream=主催者 になっていること
```

3. 作業ブランチを切って push:

```bash
git switch -c feat/my-policy
git push -u origin feat/my-policy
```

4. 認証は **Personal Access Token**（パスワード認証は廃止済み）
   - GitHub → Settings → Developer settings → Personal access tokens →
     Tokens (classic) → `repo` スコープで発行
   - push 時の Password 欄にトークンを貼る（画面に何も表示されないのが正常）
   - `git config --global credential.helper store` で次回から省略可

5. 初コミット前に名前とメールを設定:

```bash
git config --global user.name "<GitHubのID>"
git config --global user.email "<数字>+<ID>@users.noreply.github.com"   # 非公開用
```

6. 大きいファイルを git 管理外へ:

```bash
echo -e "model_weights/\nresults/\nvenv/\nsandbox/" >> .gitignore
git add .gitignore && git commit -m "重み・評価結果をgit管理外に" && git push
```

**ハマりどころ:**

| 症状 | 原因 / 対処 |
|---|---|
| `Invalid username or token` | トークンが違う。再発行して貼り直す |
| `Repository not found` | 認証は通っている。**fork がまだ**なので先に fork する |
| push が `rejected (fetch first)` | Colab の「GitHub にコピーを保存」等でリモートが先行。`git pull --no-rebase origin <branch>` してから push |

---

## Phase 4: 学習済みモデルの配置

学習（Colab / GPU）で作ったマージ済み SmolVLA（約 900MB）をデスクトップへ運ぶ。

### 転送は scp が最速（685MB / 43 秒の実績）

Colab → Google Drive に退避 → Zenbook にダウンロード → scp:

```powershell
# Zenbook の 64bit PowerShell で
scp -P 2222 "C:\Users\<name>\Downloads\parc2026_model-xxxx.zip" atsur@192.168.10.117:~/
```

WSL 側で展開:

```bash
sudo apt install -y unzip
mkdir -p ~/PARC2026_pre/model_weights
cd ~/PARC2026_pre/model_weights
unzip ~/parc2026_model-xxxx.zip
mv parc2026_model/* . && rmdir parc2026_model   # 階層が挟まっていたら平らに
```

必要ファイル（6点）:

```
config.json
model.safetensors                                        # 906MB, VLM重み込み
policy_preprocessor.json
policy_preprocessor_step_5_normalizer_processor.safetensors
policy_postprocessor.json
policy_postprocessor_step_0_unnormalizer_processor.safetensors
```

**転送のコツ:**
- SMB 共有はパス解決や資格情報で詰まりやすい。**動いている SSH 経路（scp）に乗るのが確実**
- ターミナルへの長文コード貼り付けは事故りやすい。長いファイルは
  **GitHub ブラウザで Create new file → commit → `git pull`** が確実
- 短いファイルなら `cat > file <<'EOF'` の heredoc 貼り付けでも可

---

## Phase 5: SmolVLA 検証環境（sandbox）

目的: 「lerobot v0.6.0 で学習したモデルを、本番同一の Python 3.10・オフライン環境で
ロードし、推論レイテンシを測る」。

### 背景となる制約（調査で確定した事実）

| 制約 | 内容 |
|---|---|
| lerobot のバージョン | 学習は v0.6.0（GitHub タグ）。**PyPI は 0.4.4 まで**しかない |
| Python | lerobot v0.6.0 は `requires-python>=3.12`。**コンテナは 3.10** |
| ネットワーク | 採点環境は外部通信遮断。`requirements.txt` に `git+` / `--index-url` 不可 |
| VLM 重み | `model.safetensors` に**含まれている**（`load_vlm_weights=false`） |
| tokenizer | HF に取りに行くので**同梱必須** |
| 提出物の依存 | 採点側で**専用 venv に隔離**される（評価側 numpy 1.26 と衝突しない） |

→ 結論: **lerobot v0.6.0 のソースを提出物に同梱（vendoring, 約7MB）し、
Python 3.10 で動くようパッチする**

### 5-1. vendoring と 3.10 互換パッチ

```bash
mkdir -p ~/PARC2026_pre/sandbox && cd ~/PARC2026_pre/sandbox
git clone --depth 1 --branch v0.6.0 -q https://github.com/huggingface/lerobot.git lerobot060
rm -rf vendor && mkdir vendor && cp -r lerobot060/src/lerobot vendor/lerobot
cd vendor/lerobot

# (1) PEP695 type 文 → 単純代入
sed -i 's/^type NameOrID = /NameOrID = /; s/^type Value = /Value = /' motors/motors_bus.py

# (2) PEP695 class Foo[T] → Generic[T]
#     pipeline.py は元から TypeVar 定義があるため import に Generic を足すだけ
sed -i 's/^from typing import Any, TypedDict, TypeVar, cast$/from typing import Any, Generic, TypedDict, TypeVar, cast/' processor/pipeline.py
sed -i 's/^class DataProcessorPipeline\[TInput, TOutput\](HubMixin):$/class DataProcessorPipeline(Generic[TInput, TOutput], HubMixin):/' processor/pipeline.py

sed -i '1i from typing import Generic, TypeVar\nT = TypeVar("T")' datasets/streaming_dataset.py
sed -i 's/class Backtrackable\[T\]:/class Backtrackable(Generic[T]):/' datasets/streaming_dataset.py

sed -i '1i from typing import TypeVar\nT = TypeVar("T")' utils/io_utils.py
sed -i 's/def deserialize_json_into_object\[T: JsonLike\](/def deserialize_json_into_object(/' utils/io_utils.py
```

(3) `typing.Self` 等（3.11+ の typing 機能）を `typing_extensions` へ書き換える
スクリプト `fix310.py` を実行（8 ファイルが書き換わる）:

```python
# fix310.py — from typing import の行から 3.11+ の名前を typing_extensions へ移す
import re, pathlib, sys

ROOT = pathlib.Path(sys.argv[1])
NEW = {"Self","LiteralString","Never","NotRequired","Required","assert_never","assert_type",
       "TypeVarTuple","Unpack","dataclass_transform","reveal_type","get_overloads",
       "clear_overloads","override","TypeAliasType","ReadOnly","TypeIs","Buffer"}

def rewrite_block(blob):
    names = [p.strip() for p in blob.replace("\n"," ").split(",") if p.strip()]
    base  = [n for n in names if n.split()[0] not in NEW]
    moved = [n for n in names if n.split()[0] in NEW]
    if not moved:
        return None
    out = []
    if base:
        out.append("from typing import " + ", ".join(base))
    out.append("from typing_extensions import " + ", ".join(moved))
    return "\n".join(out)

changed = []
for f in ROOT.rglob("*.py"):
    src = orig = f.read_text(errors="replace")
    def paren_sub(m):
        r = rewrite_block(m.group(1)); return r if r else m.group(0)
    src = re.sub(r"from typing import\s*\(([^)]*)\)", paren_sub, src)
    def line_sub(m):
        r = rewrite_block(m.group(1)); return (r + "\n") if r else m.group(0)
    src = re.sub(r"^from typing import ([^\n(]+)\n", line_sub, src, flags=re.M)
    if src != orig:
        f.write_text(src); changed.append(str(f.relative_to(ROOT)))

print(f"rewritten: {len(changed)} files")
for c in changed: print("  ", c)
```

```bash
python3 fix310.py ~/PARC2026_pre/sandbox/vendor/lerobot   # → rewritten: 8 files
```

構文検証（0 になること）:

```bash
cd ~/PARC2026_pre/sandbox
python3 -c "
import ast,pathlib
bad=[]
for f in pathlib.Path('vendor/lerobot').rglob('*.py'):
    try: ast.parse(f.read_text(errors='replace'), feature_version=(3,10))
    except SyntaxError as e: bad.append((str(f),e.lineno,e.msg))
print('3.12-only remaining:', len(bad))
"
```

**⚠ 最大のハマりどころ: `sed '1i ...'` での先頭挿入**

ファイル先頭に import を挿入すると `from __future__ import annotations` が
先頭でなくなり `SyntaxError: from __future__ imports must occur at the beginning`。
`pipeline.py` はこれで壊れたため、**元ファイルを再コピーして
「既存 import 行への Generic 追加だけ」に留める**方式に変更した（上記 (2) が修正済みの手順）。

### 5-2. tokenizer の同梱

```python
# get_tok.py
from huggingface_hub import snapshot_download
snapshot_download(
    "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    allow_patterns=["*.json", "*.txt", "*.model", "tokenizer*", "merges.txt", "vocab.json"],
    ignore_patterns=["*.safetensors", "*.bin", "*.pth", "*.onnx"],   # 重みは除外
    local_dir="/work/vlm_tokenizer",
)
```

`config.json` が含まれることが重要（無いと transformers がローカルディレクトリと
認識せず HF repo id として解釈してエラーになる）。

### 5-3. 提出物相当の venv 構築（コンテナ内・初回のみ）

```bash
cd ~/PARC2026_pre
docker run --rm -i \
  -v ~/PARC2026_pre/sandbox:/work \
  -v ~/PARC2026_pre/model_weights:/work/model_weights:ro \
  parc2026 bash -lc '
cd /work
python3.10 -m venv venv_sub && venv_sub/bin/pip install -q --upgrade pip
venv_sub/bin/pip install -q "torch>=2.7,<2.12.0" "torchvision>=0.22.0,<0.27.0" \
 "numpy>=2.0.0,<2.3.0" opencv-python-headless Pillow "einops>=0.8.0,<0.9.0" \
 "draccus==0.10.0" "huggingface-hub>=1.0.0,<2.0.0" "safetensors>=0.4.3,<1.0.0" \
 packaging termcolor tqdm transformers "num2words>=0.5.14,<0.6.0" accelerate \
 "gymnasium>=1.1.1,<2.0.0" requests typing_extensions
'
```

- venv はマウント先（`sandbox/venv_sub`）に作るのでコンテナを消しても残る
- lerobot 本体は入れない（vendor から `sys.path` で読む）
- 素の pip だと torch は CUDA 版（数GB）が入るが動作に支障なし

### 5-4. ロードと推論の正しい呼び出し方（検証済みコード）

```python
import sys, os
sys.path.insert(0, "/work/vendor")          # vendoring した lerobot
os.environ["HF_HUB_OFFLINE"] = "1"          # 本番同条件（外部通信ゼロ）を強制
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.configs.policies import PreTrainedConfig
from lerobot.processor import (PolicyProcessorPipeline,
                               policy_action_to_transition,
                               transition_to_policy_action)

MODEL, TOK = "/work/model_weights", "/work/vlm_tokenizer"

cfg = PreTrainedConfig.from_pretrained(MODEL)
cfg.device = "cpu"
cfg.load_vlm_weights = False
cfg.vlm_model_name = TOK                    # tokenizer をローカルパスへ差し替え
policy = SmolVLAPolicy.from_pretrained(MODEL, config=cfg, strict=False)
policy.eval()

pre = PolicyProcessorPipeline.from_pretrained(
    MODEL, config_filename="policy_preprocessor.json",
    overrides={"tokenizer_processor": {"tokenizer_name": TOK},
               "device_processor": {"device": "cpu"}})
post = PolicyProcessorPipeline.from_pretrained(
    MODEL, config_filename="policy_postprocessor.json",
    overrides={"device_processor": {"device": "cpu"}},
    to_transition=policy_action_to_transition,      # ← 無いと post() で
    to_output=transition_to_policy_action)          #    ValueError になる

# 推論ループ（preprocessor がバッチ次元を足すので、渡す側はバッチ次元なし）
batch  = pre(obs_dict)                       # トークナイズ・正規化
action = post(policy.select_action(batch))   # チャンクをキャッシュしつつ (1,7) を返す
```

観測の変換仕様:

| PARC の観測キー | lerobot 側 | 変換 |
|---|---|---|
| `agentview_image` (128×128×3 uint8) | `observation.images.front` | CHW float、**256×256 へアップスケール** |
| `robot0_eye_in_hand_image` | `observation.images.wrist` | 同上 |
| `robot0_eef_pos` (3) + `robot0_eef_quat` (4) + `robot0_gripper_qpos` (2) | `observation.state` (8) | **quat → axis-angle 変換**して `eef_pos + axis_angle + gripper_qpos` の順に連結 |
| 言語指示 | `task` (str) | preprocessor がトークナイズ |

エラーと対処の記録:

| エラー | 原因 | 対処 |
|---|---|---|
| `ImportError: cannot import name 'Self' from 'typing'` | 3.11+ の typing 機能 | fix310.py で typing_extensions へ |
| `SyntaxError: from __future__ imports must occur at the beginning` | sed の先頭挿入 | 元ファイル再コピー + 最小修正 |
| `HFValidationError: Repo id must be in the form ...` | tokenizer ディレクトリ未配置 | get_tok.py で同梱 |
| `KeyError: 'observation.language.tokens'` | `select_action` を直接呼んだ | preprocessor 経由に変更 |
| `ValueError: EnvTransition must be a dictionary. Got Tensor` | postprocessor のコンバータ未指定 | `to_transition` / `to_output` を渡す |

### 5-5. 計測結果（i5-10400, CPU）

```
[load]  18.2s          → 起動 120 秒制約に対し余裕
step 0:  5.15s         ← チャンク推論（重い）
step 1〜49: ほぼ 0s     ← キャッシュから返すだけ
step 50: 5.35s         ← 次のチャンク
[max] 5.35s / 10秒制約 PASS（余裕 4.6s）
[action] shape=(1,7)
```

`chunk_size=50` のため **50 ステップに 1 回だけ推論**すればよく、
CPU でも `/act` 10 秒制約をクリアできることを実証。
マージンが不足する場合は `cfg.num_steps`（flow matching 反復、既定 10）を
減らせば線形に短縮できる。

---

## 付録 A: 提出物の構成（設計）

```
submission.zip
├── policy_server.py        # MyPolicy 実装（テンプレートの3メソッドのみ編集可）
├── requirements.txt        # lerobot の依存のみ。lerobot 本体・git+ は書かない
├── lerobot/  (vendor)      # v0.6.0 + 3.10 パッチ済みソース（約 7MB）
├── model_weights/          # 906MB（VLM 重み込み）
└── vlm_tokenizer/          # SmolVLM2 の tokenizer 一式（数MB）
```

requirements.txt（検証済みの組み合わせ）:

```
torch>=2.7,<2.12.0
torchvision>=0.22.0,<0.27.0
numpy>=2.0.0,<2.3.0
opencv-python-headless>=4.9.0,<4.14.0
Pillow>=10.0.0,<13.0.0
einops>=0.8.0,<0.9.0
draccus==0.10.0
huggingface-hub>=1.0.0,<2.0.0
safetensors>=0.4.3,<1.0.0
packaging>=24.2,<26.0
termcolor
tqdm
transformers
num2words>=0.5.14,<0.6.0
accelerate
gymnasium>=1.1.1,<2.0.0
requests
typing_extensions
```

## 付録 B: Colab 学習ノートブックの注意

- `examples/smolvla_libero_spatial_lora.ipynb`（SmolVLA + LIBERO-Spatial LoRA）
- **セル 12（評価）は回さない**: 実値は 10 タスク × 10ep × 2 モデル = 200 rollout で
  T4 だと数時間〜十数時間。セッション切れで全ロスする
- セル 9（LoRA マージ）まで通れば重みは完成。**直後に Drive へ退避**:

```python
from google.colab import drive; drive.mount('/content/drive')
import shutil; shutil.copytree(MERGED_MODEL_DIR, '/content/drive/MyDrive/parc2026_model', dirs_exist_ok=True)
```

- 精度評価は Colab ではなくローカルの本番同一環境で行う
  （Colab 評価は Spatial タスク・256×256・衝突判定なしで本番と乖離する）
