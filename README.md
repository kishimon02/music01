# music-create

AI補助型DTMデスクトップアプリのための、アーキテクチャ先行スキャフォールドです。  
MVPを維持しつつ、後続のミキシング自動化を安全に追加できる境界を実装しています。

## 現在の実装範囲

### Phase A（基盤）

- 固定チェーン構造のミキサーグラフ  
  `Input -> BuiltinFXChain -> Fader/Pan -> Sends`
- 内蔵FX機能（EQ / Compressor / Gate / Saturator）と固定パラメータID
- `SuggestionCommand` の適用/巻き戻しモデル（手動適用のみ）
- `.mcpj` の `format_version: 1 -> 2` マイグレーション
- API契約
  - `POST /v1/mix/analyze`
  - `POST /v1/mix/suggest`

### Phase B（解析・提案強化）

- `quick / full` の解析モード分岐
- 拡張特徴量の追加
  - `crest_factor_db`
  - `loudness_range_db`
  - `transient_density`
  - `zero_crossing_rate`
- 提案候補を複数化（最大3件）
  - `variant` / `score` 付きで返却
- `analysis_id` 指定による解析結果の再利用

## クイックスタート

```bash
py -3.12 -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
pytest
uvicorn music_create.api.server:app --reload
```

起動後の確認:

- `http://127.0.0.1:8000/`（ステータス）
- `http://127.0.0.1:8000/docs`（Swagger UI）

## API例

```bash
curl -X POST "http://127.0.0.1:8000/v1/mix/analyze" ^
  -H "Content-Type: application/json" ^
  -d "{\"track_ids\":[\"t1\"],\"mode\":\"full\"}"
```

```bash
curl -X POST "http://127.0.0.1:8000/v1/mix/suggest" ^
  -H "Content-Type: application/json" ^
  -d "{\"track_id\":\"t1\",\"profile\":\"clean\",\"mode\":\"full\"}"
```

## ドキュメント

- 全体アーキテクチャ: `docs/architecture.md`
- 詳細設計書: `docs/design.md`

## 補足

- 本リポジトリはスキャフォールドであり、完全なDAW実装ではありません。
- リアルタイム音声処理は、今後の C++/JUCE 統合フェーズで実装します。
- 将来の JUCE + pybind11 連携に向けたネイティブ骨組みは `native/` にあります。
