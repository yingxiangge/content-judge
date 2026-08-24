"""content-judge 测试公共配置。"""
import sys
from pathlib import Path

# 让 tests/ 下的模块能直接 `from content_judge import ...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
