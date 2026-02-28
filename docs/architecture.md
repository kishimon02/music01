# アーキテクチャノート

関連する詳細設計書: `docs/design.md`

## 現在のフェーズ

1. Phase A: ドメイン基盤
2. Phase B: 解析・提案強化
3. Phase C: 提案比較/適用/履歴UI
4. Phase D: DAWタイムライン統合UI
5. Phase E: 実波形入力 + C++音声コア再生
6. Phase F: 音声バックエンド抽象化（`auto` / `winmm` / `juce`）
7. Phase G: 再生同期 + 波形表示 + 提案エンジン切替

## ドメイン境界

1. `music_create.mixing`
   - 実行時ミキシング状態
   - 解析・提案・適用/巻き戻しロジック
   - `rule-based` / `llm-based` 切替とLLM失敗時フォールバック
2. `music_create.project`
   - `.mcpj` スキーマと移行ルール
3. `music_create.api`
   - 解析/提案APIの契約エンドポイント
4. `music_create.ui`
   - デスクトップUI（タイムライン、提案、履歴）
5. `music_create.audio`
   - WAV読込
   - トラック波形リポジトリ
   - C++音声コアブリッジ
6. `music_create.ui.waveform`
   - 波形表示コンポーネント
   - プレイヘッド同期表示

## C++音声コア接続

1. `native/audio_core` が `mc_audio_*` C API を公開
2. `music_create.audio.native_engine` が `ctypes` でDLLを呼び出し
3. バックエンド抽象化: `auto` / `winmm` / `juce`（プレースホルダー）
4. 既定の `auto` はWindowsで `cpp-winmm` を選択
5. `mc_audio_set_backend` / `mc_audio_backend_id` / `mc_audio_is_backend_available` で切替・確認可能
6. UIは再生開始時刻ベースでプレイヘッド同期を実施（WinMM制約下の実装）

## 今後の統合ポイント

1. `juce` プレースホルダーをJUCE本実装へ置換
2. 実再生とプレイヘッド同期
3. 波形可視化と編集UI
