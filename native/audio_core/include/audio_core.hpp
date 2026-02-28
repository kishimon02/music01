#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace music_create::audio {

struct EngineConfig {
  std::uint32_t sample_rate = 48000;
  std::uint32_t buffer_size = 256;
  std::string device_id;
};

class IAudioBackend;

class AudioCore {
 public:
  AudioCore();
  ~AudioCore();
  void Start(const EngineConfig& config);
  void Stop();
  bool IsRunning() const noexcept;
  bool PlayFile(const std::wstring& path);
  bool StopPlayback();
  bool SetBackend(const std::string& backend_id);
  bool IsBackendAvailable(const std::string& backend_id) const;
  const char* BackendName() const noexcept;
  const char* BackendId() const noexcept;

 private:
  static std::string NormalizeBackendId(std::string backend_id);
  static std::string DefaultBackendId();
  std::unique_ptr<IAudioBackend> CreateBackendFor(const std::string& backend_id) const;
  std::unique_ptr<IAudioBackend> ResolveBackend() const;
  bool EnsureBackendInitialized();

  bool running_ = false;
  EngineConfig current_config_{};
  std::string selected_backend_id_ = "auto";
  std::unique_ptr<IAudioBackend> backend_;
  mutable std::string backend_name_cache_ = "unavailable";
  mutable std::string backend_id_cache_ = "auto";
};

}  // namespace music_create::audio

extern "C" {

#ifdef _WIN32
#define MC_AUDIO_EXPORT __declspec(dllexport)
#else
#define MC_AUDIO_EXPORT
#endif

MC_AUDIO_EXPORT int mc_audio_start(unsigned int sample_rate, unsigned int buffer_size);
MC_AUDIO_EXPORT int mc_audio_stop();
MC_AUDIO_EXPORT int mc_audio_is_running();
MC_AUDIO_EXPORT int mc_audio_play_file_w(const wchar_t* path);
MC_AUDIO_EXPORT int mc_audio_stop_playback();
MC_AUDIO_EXPORT const char* mc_audio_backend_name();
MC_AUDIO_EXPORT const char* mc_audio_backend_id();
MC_AUDIO_EXPORT int mc_audio_set_backend(const char* backend_id);
MC_AUDIO_EXPORT int mc_audio_is_backend_available(const char* backend_id);

}
