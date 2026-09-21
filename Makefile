# ElecAgent · 统一入口命令（docs/11 §3.2）
#
#   make check   启动自检：加载注册表、校验 schema、建最小表集
#   make falsify 证伪测试：破坏机制，验证它会立刻失败（docs/07 §4.1）
#   make test    单元测试
#   make verify  一键全量（M6 起合并 M1–M5 自检；当前 = check + falsify + test）
#   make fmt     代码格式化（如环境具备 ruff/black）

PY ?= python3
PYTEST ?= $(PY) -m pytest
SRC_PATH = src

.PHONY: help check falsify test verify clean fmt

help:
	@echo "ElecAgent make targets:"
	@echo "  make check    启动自检（加载注册表 / 校验 schema / 建最小表集）"
	@echo "  make falsify  证伪测试（破坏机制看是否报警）"
	@echo "  make test     运行单元测试"
	@echo "  make verify   一键全量自检"
	@echo "  make fmt      代码格式化"
	@echo "  make clean    清理缓存"

check:
	@PYTHONPATH=$(SRC_PATH) $(PY) scripts/check_registry.py --config config

falsify:
	@PYTHONPATH=$(SRC_PATH) $(PY) scripts/verify_m0.py

test:
	@PYTHONPATH=$(SRC_PATH) $(PYTEST) tests

verify: check falsify test
	@echo "== verify 完成 =="

fmt:
	-$(PY) -m ruff format $(SRC_PATH) tests scripts 2>/dev/null || \
	 $(PY) -m black $(SRC_PATH) tests scripts 2>/dev/null || \
	 echo "未安装 ruff/black，跳过格式化"

clean:
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "已清理缓存"
