"""Upload the JSON datasets in eval/datasets/ to LangSmith.

Usage:
    python -m eval.create_datasets            # create datasets that do not exist yet
    python -m eval.create_datasets --recreate # delete and upload again (after you edit the JSON)
"""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

DATASETS_DIR = Path(__file__).parent / "datasets"


def load_dataset_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for i, example in enumerate(data["examples"]):
        if "question" not in example.get("inputs", {}):
            raise ValueError(f"{path.name}: example {i} has no inputs.question")
    return data


def upload(client, data, recreate=False):
    name = data["name"]

    if client.has_dataset(dataset_name=name):
        if not recreate:
            print(f"'{name}' already exists. Skipping (use --recreate to replace it).")
            return
        client.delete_dataset(dataset_name=name)
        print(f"Deleted old '{name}'.")

    dataset = client.create_dataset(dataset_name=name, description=data.get("description", ""))
    client.create_examples(
        dataset_id=dataset.id,
        examples=[{"inputs": ex["inputs"], "outputs": ex["outputs"]} for ex in data["examples"]],
    )
    print(f"Created '{name}' with {len(data['examples'])} examples.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true", help="Delete and upload the datasets again.")
    args = parser.parse_args()

    load_dotenv()
    client = Client()

    for path in sorted(DATASETS_DIR.glob("*.json")):
        upload(client, load_dataset_file(path), recreate=args.recreate)


if __name__ == "__main__":
    main()
