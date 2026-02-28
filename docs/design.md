# AI補助DTM設計書 v2

## 1. 目的

本設計書は、MVPを維持しつつ、後続でトラック単位のミキシング自動化を安全に追加できるようにするための技術仕様を定義する。

後続の自動化フローは以下を基本とする。

1. Analyze実行
2. 提案表示
3. 手動適用（自動適用はしない）

## 2. スコープ

### 2.1 MVPスコープ

1. 対象: プロ志向ユーザー
2. 対応: Windows + macOS（デスクトップ単体）
3. 主軸UI: 線形タイムライン
4. 作曲支援AI: コード / メロディ / ドラム提案
5. 録音: MIDI + オーディオ録音
6. プラグイン: VST3再生 + パラメータ保存
7. 書き出し: MIDI + WAV

### 2.2 MVP外（後続）

1. ミキシング自動化の高度化（バス処理、マスタリング）
2. VST3全般の横断最適化
3. AU/CLAP対応

## 3. アーキテクチャ

1. UI/制御: Python 3.12 + PySide6
2. 音声コア: C++20 + JUCE
3. 連携: pybind11
4. AI: ローカル（ONNX Runtime）+ クラウド（FastAPI）

## 4. 先行実装する拡張境界（Phase A）

1. `MixerGraph`
   - 固定構造: `Input -> BuiltinFXChain -> Fader/Pan -> Sends`
2. `BuiltinFXChain`
   - 最小セット: EQ / Compressor / Gate / Saturator
   - パラメータID固定
3. `AnalysisSnapshot`
   - LUFS、Peak、RMS、スペクトル重心、帯域エネルギー、ダイナミクスを保持
4. `SuggestionCommand`
   - 差分コマンド方式（apply/revert）
5. `FeatureExtraction`
   - 非リアルタイムスレッドでAnalyze実行
6. `FXCapabilityRegistry`
   - MVPは `builtin_only=true`

## 5. 公開インターフェース

### 5.1 Python API

```python
Mixing.analyze(track_ids:list[str], mode:Literal["quick","full"]="quick") -> analysis_id
Mixing.get_snapshot(analysis_id:str) -> AnalysisSnapshot
Mixing.suggest(track_id:str, profile:Literal["clean","punch","warm"]) -> list[Suggestion]
Mixing.preview(track_id:str, suggestion_id:str, dry_wet:float=1.0) -> None
Mixing.apply(track_id:str, suggestion_id:str) -> command_id
Mixing.revert(command_id:str) -> None
```

### 5.2 API契約

```http
POST /v1/mix/analyze
POST /v1/mix/suggest
```

### 5.3 プロジェクト形式

`.mcpj` の `format_version: 2` を基準とする。

主な拡張キー:

1. `mixer_graph`
2. `builtin_fx_states`
3. `analysis_snapshots`
4. `suggestion_history`

互換方針:

1. `format_version: 1` 読込時に `v2` へ自動移行
2. 未設定FXはデフォルト値で補完

## 6. 非機能要件

1. 片道レイテンシ目標: 10ms以下（既存要件）
2. Analyze中も再生安定性を維持
3. quick解析目標: 30トラック/3分で15秒以内
4. full解析目標: 60秒以内
5. 提案適用/ロールバックのUI反映: 200ms以内

## 7. フェーズ計画

1. Phase A（実装済み）
   - MixerGraph / BuiltinFX / AnalysisSnapshot / SuggestionCommand の土台
2. Phase B
   - Analyzeジョブと特徴抽出の強化
   - トラック単位ミキシング提案モデル実装
3. Phase C
   - 提案比較UI、適用/巻き戻し履歴UI
4. Phase D
   - 品質強化（プロファイル拡張、提案説明改善、障害フォールバック）

## 8. テスト方針

1. 回帰テスト: 提案未適用時のレンダリング不変性
2. 可逆テスト: apply/revertで状態復元
3. 解析精度テスト: 既知素材で許容誤差検証
4. 互換テスト: `v1 -> v2` 移行整合性
5. API契約テスト: `/v1/mix/analyze`, `/v1/mix/suggest`
