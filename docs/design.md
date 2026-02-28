# AI補助DTM設計書 v2

## 1. 目的

本設計書は、MVPを維持しつつ、後続でトラック単位のミキシング自動化を安全に追加するための技術仕様を定義する。

ミキシング自動化の基本フローは以下とする。

1. Analyze実行
2. 提案候補表示
3. 手動適用（自動適用は行わない）

## 2. スコープ

### 2.1 MVPスコープ

1. 対象: プロ志向ユーザー
2. 対応: Windows + macOS（デスクトップ単体）
3. 主軸UI: 線形タイムライン
4. 作曲支援AI: コード/メロディ/ドラム提案
5. 録音: MIDI + オーディオ録音
6. プラグイン: VST3再生 + パラメータ保存
7. 書き出し: MIDI + WAV

### 2.2 MVP外（後続）

1. バス処理、マスタリング自動化
2. VST3全般の横断最適化
3. AU/CLAP対応

## 3. 技術構成

1. UI/制御: Python 3.12 + PySide6
2. 音声コア: C++20 + JUCE
3. 連携: pybind11
4. AI: ローカル（ONNX Runtime）+ クラウド（FastAPI）

## 4. 先行実装境界（Phase A）

1. `MixerGraph`
   - 固定構造: `Input -> BuiltinFXChain -> Fader/Pan -> Sends`
2. `BuiltinFXChain`
   - EQ / Compressor / Gate / Saturator
   - パラメータID固定
3. `AnalysisSnapshot`
   - トラック単位の解析特徴量を保持
4. `SuggestionCommand`
   - apply/revert可能な差分コマンド
5. `FeatureExtraction`
   - 非リアルタイムスレッドでAnalyze実行
6. `FXCapabilityRegistry`
   - MVPでは `builtin_only=true`

## 5. Phase B実装（今回反映）

1. 解析特徴量を拡張
   - `crest_factor_db`
   - `loudness_range_db`
   - `transient_density`
   - `zero_crossing_rate`
2. `quick/full` 解析分岐を明確化
   - quick: 高速近似
   - full: フレームRMSと帯域推定を含む詳細解析
3. 提案モデルを強化
   - 1候補から複数候補（最大3件）へ拡張
   - 候補ごとに `variant` と `score` を付与
4. Analyze結果の再利用
   - `analysis_id` 指定で提案生成可能

## 6. 公開インターフェース

### 6.1 Python API

```python
Mixing.analyze(track_ids:list[str], mode:Literal["quick","full"]="quick") -> analysis_id
Mixing.get_snapshot(analysis_id:str) -> AnalysisSnapshot
Mixing.suggest(
    track_id:str,
    profile:Literal["clean","punch","warm"],
    analysis_id:str|None=None,
    mode:Literal["quick","full"]="quick",
) -> list[Suggestion]
Mixing.preview(track_id:str, suggestion_id:str, dry_wet:float=1.0) -> None
Mixing.apply(track_id:str, suggestion_id:str) -> command_id
Mixing.revert(command_id:str) -> None
```

### 6.2 API契約

```http
POST /v1/mix/analyze
POST /v1/mix/suggest
```

`/v1/mix/suggest` リクエスト:

```json
{
  "track_id": "t1",
  "profile": "clean",
  "analysis_id": "optional",
  "mode": "quick"
}
```

レスポンス候補には以下を含む。

1. `suggestion_id`
2. `variant`
3. `score`
4. `param_updates`

### 6.3 プロジェクト形式（`.mcpj`）

`format_version: 2` を基準とする。

主な拡張キー:

1. `mixer_graph`
2. `builtin_fx_states`
3. `analysis_snapshots`
4. `suggestion_history`

互換方針:

1. `format_version: 1` 読込時に `v2` へ自動移行
2. 未設定FXはデフォルト値で補完

## 7. 非機能要件

1. 片道レイテンシ目標: 10ms以下
2. Analyze中も再生安定性を維持
3. quick解析目標: 30トラック/3分で15秒以内
4. full解析目標: 60秒以内
5. 提案適用/ロールバックのUI反映: 200ms以内

## 8. テスト方針

1. 回帰テスト: 提案未適用時のレンダリング不変性
2. 可逆テスト: apply/revertで状態復元
3. 特徴量テスト: full解析で拡張指標が有効範囲内に入ること
4. 互換テスト: `v1 -> v2` 移行整合性
5. API契約テスト: `/v1/mix/analyze`, `/v1/mix/suggest`
