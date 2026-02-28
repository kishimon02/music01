#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace music_create::audio {

struct EngineConfig {
  std::uint32_t sample_rate = 48000;
  std::uint32_t buffer_size = 256;
  std::string device_id;
};

class AudioCore {
 public:
  AudioCore() = default;
  void Start(const EngineConfig& config);
  void Stop();
  bool IsRunning() const noexcept;

 private:
  bool running_ = false;
  EngineConfig current_config_{};
};

}  // namespace music_create::audio
