# AI補助DTM設計書 v2

## 1. 目的

MVPの方針を維持しつつ、以下を段階的に実現する。

1. ミキシング自動化を安全に追加できる境界設計
2. 作曲支援AI（コード/メロディ/ドラム提案）の拡張
3. リアルタイム再生安定性を維持したUI/音声コア統合

本設計の運用原則は一貫して次を維持する。

- `Analyze -> 提案表示 -> 手動適用`
- 自動適用は行わない
- LLM失敗時はrule-basedへフォールバック

## 2. フェーズ構成

1. Phase A: ミキシング基盤（MixerGraph / BuiltinFX / Command / Migration）
2. Phase B: 解析・提案強化（特徴量拡張、複数候補、分析再利用）
3. Phase C: 提案比較UI（試聴、適用、履歴、巻き戻し）
4. Phase D: タイムライン統合UI（トラック、クリップ、プレイヘッド）
5. Phase E: 実波形入力 + C++音声コア再生
6. Phase F: 音声バックエンド抽象化（`auto` / `winmm` / `juce`）
7. Phase G: 再生同期 + 波形表示 + 提案エンジン切替（rule/LLM）
8. Phase H: 作曲支援AI基盤 + 量子化グリッド拡張

## 3. 技術構成

1. UI/制御: Python 3.12 + PySide6 Widgets / Qt Quick(QML) 段階移行
2. 音声コア: C++20
3. 連携: C API + `ctypes`
4. API: FastAPI
5. 既定OS優先: Windows（macOS対応は最終フェーズ）

## 4. ミキシング設計

### 4.1 MixerGraph

1. 固定構造: `Input -> BuiltinFXChain -> Fader/Pan -> Sends`
2. 目的: 提案適用先の一意化

### 4.2 BuiltinFX

1. `eq`, `compressor`, `gate`, `saturator`
2. パラメータID固定
3. `FXCapabilityRegistry.builtin_only=true` を既定

### 4.3 AnalysisSnapshot（トラック特徴量）

1. `lufs`
2. `peak_dbfs`
3. `rms_dbfs`
4. `crest_factor_db`
5. `spectral_centroid_hz`
6. `band_energy_low`
7. `band_energy_mid`
8. `band_energy_high`
9. `dynamic_range_db`
10. `loudness_range_db`
11. `transient_density`
12. `zero_crossing_rate`

### 4.4 SuggestionCommand

1. `preview` は一時反映（履歴非追加）
2. `apply` はコマンド履歴へ追加
3. `revert` は `before` へ巻き戻し

## 5. 作曲支援AI設計（Phase H）

### 5.1 対象機能

1. パート提案: `chord` / `melody` / `drum`
2. エンジン: `rule-based` / `llm-based`
3. フォールバック: `llm-based` 失敗時は `rule-based`

### 5.2 量子化グリッド仕様（確定）

サポートグリッドを次に固定する。

- `1`, `1/2`, `1/2T`, `1/4`, `1/4T`, `1/8`, `1/8T`, `1/16`, `1/16T`, `1/32`, `1/32T`, `1/64`

前提:

1. `T` は triplet（3連）
2. 拍子は初期 `4/4`
3. `ticks_per_beat = 960`

1ステップtick長:

1. `1`: `3840`
2. `1/2`: `1920`
3. `1/2T`: `1280`
4. `1/4`: `960`
5. `1/4T`: `640`
6. `1/8`: `480`
7. `1/8T`: `320`
8. `1/16`: `240`
9. `1/16T`: `160`
10. `1/32`: `120`
11. `1/32T`: `80`
12. `1/64`: `60`

量子化ルール:

1. `start_tick` と `length_tick` をグリッド単位に丸める
2. `length_tick` は最小1ステップ

### 5.3 作曲モジュール

1. `composition/models.py`
   - `Grid` 型、`ComposeRequest`、`ComposeSuggestion`
2. `composition/quantize.py`
   - `grid_to_step_ticks` / `quantize_tick` / `quantize_note`
3. `composition/rules.py`
   - rule-based候補生成（生成後必ず量子化）
4. `composition/llm.py`
   - LLMレスポンスを検証し、量子化を適用
   - 不正グリッドはエラー化してフォールバック対象
5. `composition/service.py`
   - `suggest` / `preview` / `apply_to_timeline` / `revert`

## 6. 公開インターフェース

### 6.1 ミキシングAPI

```python
Mixing.analyze(track_ids:list[str], mode:Literal["quick","full"]="quick") -> analysis_id
Mixing.get_snapshot(analysis_id:str) -> AnalysisSnapshot
Mixing.suggest(
    track_id:str,
    profile:Literal["clean","punch","warm"],
    analysis_id:str|None=None,
    mode:Literal["quick","full"]="quick",
    engine_mode:Literal["rule-based","llm-based"]|None=None,
) -> list[Suggestion]
Mixing.preview(track_id:str, suggestion_id:str, dry_wet:float=1.0) -> None
Mixing.cancel_preview(track_id:str) -> None
Mixing.apply(track_id:str, suggestion_id:str) -> command_id
Mixing.revert(command_id:str) -> None
```

### 6.2 作曲API

```python
Composition.suggest(request: ComposeRequest, engine_mode: Literal["rule-based","llm-based"]|None=None) -> list[ComposeSuggestion]
Composition.preview(suggestion_id: str) -> Path
Composition.apply_to_timeline(
    suggestion_id: str,
    phrase_start_bar: int|None=None,
    phrase_end_bar: int|None=None,
) -> tuple[str, list[str]]
Composition.revert(command_id: str) -> None
```

### 6.3 HTTP API

```http
POST /v1/mix/analyze
POST /v1/mix/suggest
POST /v1/compose/suggest
```

`POST /v1/compose/suggest` の `grid` は12値のみ許可。

## 7. プロジェクト保存・互換

`.mcpj`（v2）で次を保持する。

1. `mixer_graph`
2. `builtin_fx_states`
3. `analysis_snapshots`
4. `suggestion_history`
5. `composition_settings`
6. `instrument_assignments`
7. `midi_clips`
8. `compose_history`

互換ルール:

1. `format_version:1` 読込時に v2へ移行
2. `composition_settings.default_grid` が不正値なら `1/16` に補正
3. 補正時は `compose_history` に警告を記録

## 8. UI仕様（現状）

1. 操作領域は単一ワークスペースとし、上部トランスポート/ヘッダー、中央アレンジャー、右インスペクタ、下部ユーティリティラックで構成する
2. 右インスペクタは `トラック` / `作曲` / `ミックス` の3タブ固定とする
3. 下部ユーティリティラックは `エディタ` / `ミックス提案` / `ミックス履歴` / `作曲提案` / `A/B比較` / `作曲履歴` の6タブとする
4. トランスポートとアレンジャーは Qt Quick(QML) で描画し、既存のインスペクタと下部ラックは当面 PySide6 Widgets を維持する
5. アレンジャー選択は下部 `エディタ` タブへの自動切替と同期を行い、必要ならラックを自動再展開する

### 8.1 ミキシングUI

1. `トラック` タブでトラックID、WAV、再生位置、選択クリップ概要を扱う
2. `ミックス` タブで profile / engine / mode / Dry-Wet / 解析 / 提案 / 試聴 / 適用 / 巻き戻しを扱う
3. 詳細結果は下部ラックの `ミックス提案` / `ミックス履歴` タブに表示する

### 8.2 作曲UI

1. 右インスペクタの `作曲` タブで次を指定可能
2. `挿入トラックID`
3. `パート`（`chord` / `melody` / `drum`）
4. `キー` / `スケール` / `スタイル`
5. `グリッド`（12項目、順序固定、既定 `1/16`）
6. `小節数`（1〜32）
7. `楽器`（Program選択、ドラム時は無効化）
8. `提案エンジン`（`rule-based` / `llm-based`）
9. `作曲提案` で候補生成
10. `作曲試聴` で試聴WAV再生
11. `部分適用開始小節` / `部分適用終了小節` のフレーズ範囲指定
12. `タイムライン挿入` でMIDIクリップ追加（部分適用可）
13. 下部 `作曲提案` タブで A/B スロット設定
14. 下部 `A/B比較` タブで比較表示、A試聴、B試聴
15. 下部 `作曲履歴` タブで作曲挿入履歴の一覧/詳細表示
16. `挿入を巻き戻し` で挿入取り消し

### 8.3 DAW UI

1. 上部ヘッダーにアプリ名、再生状態、現在トラック、engine/mode 状態、時刻付きステータスを集約する
2. 中央はアレンジャー優先表示とし、右インスペクタと下部ラックは個別に折りたたみ可能とする
3. アレンジャー領域はミニマップ、水平スクロール、ズーム、トラックレーン、クリップ表示、プレイヘッドをまとめて扱う
4. アレンジャーは `64小節` 開始、`64小節` 単位で自動拡張し、最大 `1000小節` まで扱う
5. 位置表示は `小節` / `時間` の全体切替を持ち、トランスポート、ルーラー、選択クリップ概要、再生位置表示へ一括反映する
6. アレンジャーには `選択` / `鉛筆` ツールを置き、鉛筆モードでは既存トラックへのMIDIリージョン描画と、空きレーンからの新規トラック同時作成を許可する
7. アレンジャーのズームは `- / + / combo` の3系統を同じ `4 / 8 / 16 / 32 / 64 px per bar` 段階に束ねる
8. `タイムライン挿入` 後は挿入クリップをアレンジャー上で選択状態にし、下部 `エディタ` タブへ同期する
9. 下部 `エディタ` タブは内部スクロールを持ち、既定ウィンドウサイズでも下端コントロールまで到達可能とする
10. ピアノロールは左の音名軸 + 右のノートグリッド + 縦スクロールで構成し、選択ノート帯域へ自動フォーカスする
11. 選択MIDIの手動編集（ノート単位ドラッグ）、半音シフト、楽器Program変更、編集済みMIDIの即時試聴を維持する

## 9. テスト方針

1. 量子化テーブル12値の一致テスト
2. triplet量子化テスト（`1/2T`〜`1/32T`）
3. 作曲APIグリッド許可/拒否テスト
4. ルールベース提案の全グリッド生成テスト
5. LLM不正グリッド時のフォールバックテスト
6. UIグリッド表示順序テスト
7. `default_grid` 互換補正テスト

## 10. 次フェーズ

1. 作曲UIの改善（ノート長変更、ノート追加/削除、拍単位スナップ切替）
2. LLM提案品質改善（制約強化、説明文改善）
3. JUCE本実装への置換
4. macOS対応（最終フェーズ）

## 11. 言語ポリシー

1. UI表示文言は日本語で統一する
2. `README.md` と `docs/` 配下のドキュメントは日本語で記述する
3. API識別子・型名は互換性のため英語を維持してよい
