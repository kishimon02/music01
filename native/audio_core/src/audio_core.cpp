#include "audio_core.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <utility>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#pragma comment(lib, "Winmm.lib")
#endif

namespace music_create::audio {

class IAudioBackend {
 public:
  virtual ~IAudioBackend() = default;
  virtual const char* Id() const noexcept = 0;
  virtual const char* Name() const noexcept = 0;
  virtual bool IsAvailable() const noexcept = 0;
  virtual bool Start(const EngineConfig& config) = 0;
  virtual void Stop() = 0;
  virtual bool PlayFile(const std::wstring& path) = 0;
  virtual bool StopPlayback() = 0;
};

namespace {

class WinMMBackend final : public IAudioBackend {
 public:
  const char* Id() const noexcept override { return "winmm"; }
  const char* Name() const noexcept override { return "cpp-winmm"; }

  bool IsAvailable() const noexcept override {
#ifdef _WIN32
    return true;
#else
    return false;
#endif
  }

  bool Start(const EngineConfig& config) override {
    if (!IsAvailable()) {
      return false;
    }
    if (config.sample_rate == 0 || config.buffer_size == 0) {
      return false;
    }
    running_ = true;
    return true;
  }

  void Stop() override {
    StopPlayback();
    running_ = false;
  }

  bool PlayFile(const std::wstring& path) override {
#ifdef _WIN32
    if (!IsAvailable() || path.empty()) {
      return false;
    }
    if (!running_) {
      const EngineConfig default_config{};
      if (!Start(default_config)) {
        return false;
      }
    }
    return PlaySoundW(path.c_str(), nullptr, SND_FILENAME | SND_ASYNC | SND_NODEFAULT) == TRUE;
#else
    (void)path;
    return false;
#endif
  }

  bool StopPlayback() override {
#ifdef _WIN32
    return PlaySoundW(nullptr, nullptr, 0) == TRUE;
#else
    return false;
#endif
  }

 private:
  bool running_ = false;
};

class JuceBackendPlaceholder final : public IAudioBackend {
 public:
  const char* Id() const noexcept override { return "juce"; }
  const char* Name() const noexcept override { return "cpp-juce-placeholder"; }
  bool IsAvailable() const noexcept override { return false; }
  bool Start(const EngineConfig& config) override {
    (void)config;
    return false;
  }
  void Stop() override {}
  bool PlayFile(const std::wstring& path) override {
    (void)path;
    return false;
  }
  bool StopPlayback() override { return false; }
};

}  // namespace

AudioCore::AudioCore() = default;
AudioCore::~AudioCore() = default;

void AudioCore::Start(const EngineConfig& config) {
  if (config.sample_rate == 0 || config.buffer_size == 0) {
    throw std::invalid_argument("sample_rate and buffer_size must be non-zero");
  }
  current_config_ = config;
  if (!EnsureBackendInitialized()) {
    throw std::runtime_error("selected backend is unavailable");
  }
  if (!backend_->Start(config)) {
    throw std::runtime_error("failed to start selected backend");
  }
  running_ = true;
}

void AudioCore::Stop() {
  if (backend_) {
    backend_->Stop();
  }
  running_ = false;
}

bool AudioCore::IsRunning() const noexcept { return running_; }

bool AudioCore::PlayFile(const std::wstring& path) {
  if (path.empty()) {
    return false;
  }
  if (!running_) {
    try {
      const EngineConfig fallback = current_config_.sample_rate == 0 ? EngineConfig{} : current_config_;
      Start(fallback);
    } catch (...) {
      return false;
    }
  }
  if (!EnsureBackendInitialized()) {
    return false;
  }
  return backend_->PlayFile(path);
}

bool AudioCore::StopPlayback() {
  if (!EnsureBackendInitialized()) {
    return false;
  }
  return backend_->StopPlayback();
}

bool AudioCore::SetBackend(const std::string& backend_id) {
  const std::string normalized = NormalizeBackendId(backend_id);
  if (normalized != "auto" && normalized != "winmm" && normalized != "juce") {
    return false;
  }
  if (running_) {
    Stop();
  }
  selected_backend_id_ = normalized;
  backend_.reset();
  backend_id_cache_ = normalized;
  backend_name_cache_ = "uninitialized";
  return true;
}

bool AudioCore::IsBackendAvailable(const std::string& backend_id) const {
  const std::string normalized = NormalizeBackendId(backend_id);
  if (normalized.empty()) {
    return false;
  }
  const std::string effective = normalized == "auto" ? DefaultBackendId() : normalized;
  auto candidate = CreateBackendFor(effective);
  return candidate && candidate->IsAvailable();
}

const char* AudioCore::BackendName() const noexcept {
  try {
    if (backend_) {
      backend_name_cache_ = backend_->Name();
      backend_id_cache_ = backend_->Id();
      return backend_name_cache_.c_str();
    }
    auto resolved = ResolveBackend();
    if (resolved) {
      backend_name_cache_ = resolved->Name();
      backend_id_cache_ = resolved->Id();
    } else {
      backend_name_cache_ = "unavailable";
      backend_id_cache_ = selected_backend_id_;
    }
  } catch (...) {
    backend_name_cache_ = "unavailable";
  }
  return backend_name_cache_.c_str();
}

const char* AudioCore::BackendId() const noexcept {
  try {
    if (backend_) {
      backend_id_cache_ = backend_->Id();
      return backend_id_cache_.c_str();
    }
    auto resolved = ResolveBackend();
    if (resolved) {
      backend_id_cache_ = resolved->Id();
      backend_name_cache_ = resolved->Name();
    } else {
      backend_id_cache_ = selected_backend_id_;
    }
  } catch (...) {
    backend_id_cache_ = "unknown";
  }
  return backend_id_cache_.c_str();
}

std::string AudioCore::NormalizeBackendId(std::string backend_id) {
  if (backend_id.empty()) {
    return {};
  }
  std::transform(backend_id.begin(), backend_id.end(), backend_id.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return backend_id;
}

std::string AudioCore::DefaultBackendId() {
#ifdef _WIN32
  return "winmm";
#else
  return "juce";
#endif
}

std::unique_ptr<IAudioBackend> AudioCore::CreateBackendFor(const std::string& backend_id) const {
  if (backend_id == "winmm") {
    return std::make_unique<WinMMBackend>();
  }
  if (backend_id == "juce") {
    return std::make_unique<JuceBackendPlaceholder>();
  }
  return {};
}

std::unique_ptr<IAudioBackend> AudioCore::ResolveBackend() const {
  if (selected_backend_id_ == "auto") {
    auto preferred = CreateBackendFor(DefaultBackendId());
    if (preferred && preferred->IsAvailable()) {
      return preferred;
    }
    auto fallback = CreateBackendFor("juce");
    if (fallback) {
      return fallback;
    }
    return {};
  }
  return CreateBackendFor(selected_backend_id_);
}

bool AudioCore::EnsureBackendInitialized() {
  if (backend_) {
    backend_name_cache_ = backend_->Name();
    backend_id_cache_ = backend_->Id();
    return backend_->IsAvailable();
  }
  backend_ = ResolveBackend();
  if (!backend_) {
    backend_name_cache_ = "unavailable";
    backend_id_cache_ = selected_backend_id_;
    return false;
  }
  backend_name_cache_ = backend_->Name();
  backend_id_cache_ = backend_->Id();
  return backend_->IsAvailable();
}

}  // namespace music_create::audio

namespace {
music_create::audio::AudioCore g_audio_core;
}

extern "C" {

int mc_audio_start(unsigned int sample_rate, unsigned int buffer_size) {
  try {
    music_create::audio::EngineConfig cfg;
    cfg.sample_rate = sample_rate;
    cfg.buffer_size = buffer_size;
    g_audio_core.Start(cfg);
    return 1;
  } catch (...) {
    return 0;
  }
}

int mc_audio_stop() {
  g_audio_core.Stop();
  return 1;
}

int mc_audio_is_running() { return g_audio_core.IsRunning() ? 1 : 0; }

int mc_audio_play_file_w(const wchar_t* path) {
  if (path == nullptr) {
    return 0;
  }
  return g_audio_core.PlayFile(path) ? 1 : 0;
}

int mc_audio_stop_playback() { return g_audio_core.StopPlayback() ? 1 : 0; }

const char* mc_audio_backend_name() { return g_audio_core.BackendName(); }

const char* mc_audio_backend_id() { return g_audio_core.BackendId(); }

int mc_audio_set_backend(const char* backend_id) {
  if (backend_id == nullptr) {
    return 0;
  }
  return g_audio_core.SetBackend(backend_id) ? 1 : 0;
}

int mc_audio_is_backend_available(const char* backend_id) {
  if (backend_id == nullptr) {
    return 0;
  }
  return g_audio_core.IsBackendAvailable(backend_id) ? 1 : 0;
}

}  // extern "C"
