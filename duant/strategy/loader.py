"""策略加载器"""

import importlib.util
import sys
from pathlib import Path

import yaml
from loguru import logger

from duant.strategy.base import StrategyBase
from duant.strategy.yaml_parser import YamlStrategyLoader


class StrategyLoader:
    """策略加载器，支持 YAML 声明式和 Python 编程式"""

    def __init__(self, yaml_dir: Path | None = None, python_dir: Path | None = None):
        self.yaml_dir = yaml_dir
        self.python_dir = python_dir
        self._yaml_loader = YamlStrategyLoader()

    def load(self, name: str) -> StrategyBase:
        """根据名称加载策略，先找 YAML，再找 Python"""
        # 尝试 YAML
        if self.yaml_dir:
            yaml_path = self.yaml_dir / f"{name}.yaml"
            if yaml_path.exists():
                logger.info(f"加载 YAML 策略: {yaml_path}")
                return self._yaml_loader.load(yaml_path)

        # 尝试 Python
        if self.python_dir:
            py_path = self.python_dir / f"{name}.py"
            if py_path.exists():
                logger.info(f"加载 Python 策略: {py_path}")
                return self._load_python(py_path, name)

        raise FileNotFoundError(f"未找到策略: {name}")

    def list_strategies(self) -> dict[str, str]:
        """列出所有可用策略 {name: type}"""
        result = {}
        if self.yaml_dir and self.yaml_dir.exists():
            for f in self.yaml_dir.glob("*.yaml"):
                result[f.stem] = "yaml"
        if self.python_dir and self.python_dir.exists():
            for f in self.python_dir.glob("*.py"):
                if f.stem != "__init__":
                    result[f.stem] = "python"
        return result

    def _load_python(self, path: Path, name: str) -> StrategyBase:
        """动态加载 Python 策略文件"""
        spec = importlib.util.spec_from_file_location(f"duant_strategy_{name}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载策略文件: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 查找 StrategyBase 的子类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, StrategyBase)
                and attr is not StrategyBase
            ):
                return attr()

        raise TypeError(f"策略文件 {path} 中未找到 StrategyBase 子类")
