import tomllib
from pathlib import Path
from typing import Any


class Config:
    def __init__(self) -> None:
        self.base_dir: Path = Path(__file__).resolve().parents[3]
        self.config_path: Path = self.base_dir / "config" / "config.toml"
        self.data_path: Path = self.base_dir / "data"
        self.config_data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with self.config_path.open("rb") as f:
            self.config_data = tomllib.load(f)

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        支持嵌套读取：
        config.get("riot", "api_key")
        """
        value = self.config_data
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key)
            if value is None:
                return default
        return value

    @property
    def data(self) -> dict[str, Any]:
        return self.config_data


config = Config()

if __name__ == "__main__":
    config = Config()
    print(config.get("crawler", "timeout"))
