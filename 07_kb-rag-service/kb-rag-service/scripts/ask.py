"""Quick CLI to ask a question without starting the API.

    python -m scripts.ask alice "how many days leave can I carry over?"
"""
import json
import sys

from app.query.graph import build_graph
from app.users import get_groups


def main():
    if len(sys.argv) < 3:
        print("usage: python -m scripts.ask <user_id> <question>")
        sys.exit(1)

    user_id, question = sys.argv[1], " ".join(sys.argv[2:])
    result = build_graph().invoke({
        "question": question,
        "user_id": user_id,
        "groups": get_groups(user_id),
        "timings": {},
    })
    print(result["answer"])
    print()
    print("sources:", json.dumps(result.get("citations", []), indent=2))
    print("timings:", result.get("timings"))


if __name__ == "__main__":
    main()
