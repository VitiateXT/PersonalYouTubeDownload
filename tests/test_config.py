"""Tests for configuration loading."""

from pathlib import Path

import pytest

from ytdl.config import Config, _deep_merge, load_config


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"section": {"a": 1, "b": 2}}
        override = {"section": {"b": 3}}
        result = _deep_merge(base, override)
        assert result == {"section": {"a": 1, "b": 3}}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        override = {"a": 2}
        _deep_merge(base, override)
        assert base == {"a": 1}


class TestLoadConfig:
    def test_load_defaults_when_no_file(self, tmp_path):
        """Loading config without a file should return defaults."""
        config = load_config(tmp_path / "nonexistent.toml")
        assert isinstance(config, Config)
        assert config.max_resolution == 1080
        assert config.video_format == "mp4"
        assert config.audio_format == "mp3"
        assert config.audio_bitrate == "192"
        assert config.transcode_crf == 25
        assert config.sleep_interval == 10

    def test_load_from_file(self, tmp_path):
        """Loading config from a valid TOML file."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[video]\nmax_resolution = 720\n\n[network]\nsleep_interval = 5\n'
        )
        config = load_config(config_file)
        assert config.max_resolution == 720
        assert config.sleep_interval == 5
        # Other values should be defaults
        assert config.video_format == "mp4"
        assert config.retries == 10

    def test_base_dir_resolved_relative_to_config(self, tmp_path):
        """base_dir='.' should resolve relative to config file location."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[general]\nbase_dir = "."\n')
        config = load_config(config_file)
        assert config.base_dir == tmp_path.resolve()

    def test_explicit_nonexistent_path_uses_defaults(self, tmp_path):
        """Explicit path to missing file should use defaults."""
        config = load_config(tmp_path / "missing.toml")
        assert config.max_resolution == 1080


class TestConfigDataclass:
    def test_default_values(self):
        config = Config()
        assert config.max_resolution == 1080
        assert config.video_format == "mp4"
        assert config.transcode_codec == "libx264"
        assert config.transcode_preset == "medium"

    def test_custom_values(self, tmp_path):
        config = Config(base_dir=tmp_path, max_resolution=720, transcode_crf=20)
        assert config.base_dir == tmp_path
        assert config.max_resolution == 720
        assert config.transcode_crf == 20
