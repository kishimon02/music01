# ネイティブバインディング方針

このフォルダは将来の `pybind11` 統合向け予約領域です。

想定エクスポート:

1. `AudioEngine.start(config)`
2. `AudioEngine.stop()`
3. `Project.create_track(...)`
4. `Project.export_wav(...)`

現時点では、Python側契約と C API + `ctypes` ブリッジを実装しています。

現在のC API（主要）:

1. `mc_audio_start` / `mc_audio_stop`
2. `mc_audio_play_file_w` / `mc_audio_stop_playback`
3. `mc_audio_backend_name` / `mc_audio_backend_id`
4. `mc_audio_set_backend` / `mc_audio_is_backend_available`
