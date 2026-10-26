"""Генерирует packages/contracts/schemas/*.json из моделей. Запуск: python packages/contracts/export_schema.py"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from aihub_contracts import CONTRACT_MODELS  # noqa: E402

out = pathlib.Path(__file__).parent / "schemas"
out.mkdir(exist_ok=True)
for model in CONTRACT_MODELS:
    schema = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
    (out / f"{model.__name__}.json").write_text(schema + "\n", encoding="utf-8")
print(f"exported {len(CONTRACT_MODELS)} schemas")
