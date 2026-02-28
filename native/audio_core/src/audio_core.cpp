#include "audio_core.hpp"

#include <stdexcept>

namespace music_create::audio {

void AudioCore::Start(const EngineConfig& config) {
  if (config.sample_rate == 0 || config.buffer_size == 0) {
    throw std::invalid_argument("sample_rate and buffer_size must be non-zero");
  }
  current_config_ = config;
  running_ = true;
}

void AudioCore::Stop() { running_ = false; }

bool AudioCore::IsRunning() const noexcept { return running_; }

}  // namespace music_create::audio
