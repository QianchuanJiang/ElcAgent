"""pytest 公共夹具。

提供：
  - `config_dir`：仓库 config/ 目录
  - `registry`：已加载的注册表
  - `tmp_config`：把 config/ 复制到临时目录，便于注入非法配置做验收测试
    （**只复制，不生成新数据**——docs/11 §1 禁止写造数脚本）
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime.registry import Registry  # noqa: E402


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return ROOT / "config"


@pytest.fixture(scope="session")
def registry(config_dir: Path) -> Registry:
    return Registry.load(config_dir)


@pytest.fixture
def tmp_config(config_dir: Path, tmp_path: Path) -> Path:
    """config/ 的可写副本，用于注入非法配置。"""
    dst = tmp_path / "config"
    shutil.copytree(config_dir, dst)
    return dst
