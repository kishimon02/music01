# music-create

AI補助型DTMデスクトップアプリのための、アーキテクチャ先行スキャフォールドです。

このリポジトリでは、v2計画の Phase A 境界を実装しています。

- 固定チェーン構造のミキサーグラフ:
  - `Input -> BuiltinFXChain -> Fader/Pan -> Sends`
- 内蔵FX機能と安定したパラメータID
- 将来のミキシング自動化に向けた `AnalysisSnapshot` スキーマ
- `SuggestionCommand` の適用/巻き戻しモデル（手動適用のみ）
- プロジェクト形式の移行 `format_version: 1 -> 2`
- 契約APIエンドポイント:
  - `POST /v1/mix/analyze`
  - `POST /v1/mix/suggest`

## クイックスタート

```bash
py -3.12 -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
pytest
uvicorn music_create.api.server:app --reload
```

## 補足

- これはスキャフォールドであり、完全なDAW実装ではありません。
- リアルタイム音声処理は、今後の C++/JUCE 統合フェーズで実装します。
- ミキシング自動化はMVP後の段階導入ですが、拡張ポイントは先行実装済みです。
- 将来の JUCE + pybind11 連携に向けたネイティブ骨組みは `native/` にあります。
