# AI補助DTM設計書 v2

## 1. 目的

MVPを維持しつつ、後続のトラック単位ミキシング自動化を安全に追加するための実装仕様を定義する。  
現在は、実波形入力・提案UI・タイムライン統合・C++音声コア再生まで実装している。

## 2. フェーズ構成

1. Phase A: ドメイン基盤（MixerGraph / BuiltinFX / Command / Migration）
2. Phase B: 解析・提案強化（特徴量拡張、複数候補、分析再利用）
3. Phase C: 提案比較UI（適用・履歴・巻き戻し）
4. Phase D: タイムライン統合UI（トラックレーン、クリップ配置、プレイヘッド）
5. Phase E: 実波形入力 + C++音声コア再生
6. Phase F: 音声バックエンド抽象化（`auto` / `winmm` / `juce`）

## 3. 技術構成

1. UI/制御: Python 3.12 + PySide6
2. 音声コア: C++20
3. 再生バックエンド: 抽象化レイヤ（既定`auto`、Windows実装はWinMM）
4. 連携: C API + `ctypes`
5. API: FastAPI

## 4. ドメイン設計

### 4.1 MixerGraph

1. 固定構造: `Input -> BuiltinFXChain -> Fader/Pan -> Sends`
2. 目的: 自動提案の適用先を一意にする

### 4.2 BuiltinFX

1. EQ / Compressor / Gate / Saturator
2. パラメータID固定
3. `FXCapabilityRegistry.builtin_only=true` をMVP既定とする

### 4.3 AnalysisSnapshot（保持指標）

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

### 4.4 Suggestion / Command

1. 提案候補は最大3件
2. 各候補に `variant` と `score` を付与
3. 適用は `SuggestionCommand` として保存
4. `revert` で巻き戻し可能
5. 履歴取得: `get_command_history(track_id=None)`

### 4.5 Timeline（Phase D）

1. `TimelineState` でトラック・クリップ・プレイヘッドを管理
2. `TimelineTrack` / `TimelineClip` の明示モデル化
3. トラック行選択とミキシング対象トラックIDを同期

### 4.6 Real Waveform Input（Phase E）

1. `WaveformRepository` でトラックごとにWAVを管理
2. `load_wav_mono_float32` でWAVをモノラルfloatに変換
3. 解析は `track_signal_provider` から実波形を取得

### 4.7 C++ Audio Core（Phase E）

1. C++側に `mc_audio_*` C APIを公開
2. Python側 `NativeAudioEngine` が `ctypes` でDLLをロード
3. 再生制御:
   - `mc_audio_play_file_w`
   - `mc_audio_stop_playback`
4. バックエンド切替制御:
   - `mc_audio_set_backend`
   - `mc_audio_backend_id`
   - `mc_audio_is_backend_available`
5. 既定は `auto`（WindowsではWinMM選択）、`juce` は差し替え用プレースホルダーを先行実装

## 5. 公開インターフェース

### 5.1 Python API

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
Mixing.cancel_preview(track_id:str) -> None
Mixing.apply(track_id:str, suggestion_id:str) -> command_id
Mixing.revert(command_id:str) -> None
Mixing.get_command_history(track_id:str|None=None) -> list[SuggestionCommand]
```

### 5.2 API契約

```http
POST /v1/mix/analyze
POST /v1/mix/suggest
```

## 6. UI仕様

### 6.1 提案UI（Phase C）

1. 解析実行
2. 提案候補一覧表示（score順）
3. 候補詳細表示（reason / param updates）
4. Dry/Wet試聴
5. 試聴取消
6. 適用
7. 履歴表示
8. 履歴選択リバート

### 6.2 タイムラインUI（Phase D）

1. トラックレーン表示（縦軸）
2. 小節グリッド表示（横軸）
3. MIDI/オーディオクリップ表示（色分け）
4. 再生位置スライダー（プレイヘッド）
5. トラック追加、MIDIクリップ追加、オーディオクリップ追加

### 6.3 実波形・再生UI（Phase E）

1. `WAV読込` でトラックにWAVを割り当て
2. `再生` / `停止` でC++音声コア再生制御
3. 読込WAVを解析対象へ自動切替

## 7. テスト方針

1. 提案適用/巻き戻し可逆性
2. full解析で拡張特徴量が有効範囲内に入ること
3. preview後applyがベースラインから適用されること
4. command history状態遷移
5. API契約テスト
6. Timelineモデルテスト
7. WAV読込・トラック紐付けテスト
8. ネイティブエンジンDLLのビルド/ロードテスト

## 8. 次フェーズ

1. `juce` プレースホルダーをJUCE本実装へ置換（C API契約は維持）
2. 実オーディオ再生中のプレイヘッド同期
3. 波形表示コンポーネント実装
4. 提案生成器を `rule-based` / `LLM-based` で切替可能にする（Phase F）
5. 初期既定は `rule-based` のまま維持し、設定または機能フラグで `LLM-based` を有効化する
6. `LLM-based` 失敗時は自動で `rule-based` にフォールバックし、提案生成を継続する
7. `Analyze -> 提案表示 -> 手動適用` の運用原則はLLM導入後も維持し、自動適用は行わない

## 9. 言語ポリシー

1. UI表示文言（ラベル、ボタン、ダイアログ、ステータス、ヘルプ）は日本語で統一する。
2. 新規作成・更新するドキュメント（`README.md`、`docs/`配下）は日本語で作成する。
3. API識別子やコード上の型名は互換性のため英語を維持してよいが、説明文・利用案内は日本語で記述する。
