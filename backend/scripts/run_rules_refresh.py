"""Run the rules and calendar refresh now and print the proposal file.

Run on the backend host: python -m scripts.run_rules_refresh [--max-calls N]
Same work as the monthly `counselor.rules_refresh` job (BETA_CONVERSATION_SPEC
3.3): it reads sources and calls the `researcher` model, writes
app/pai_c/policy/refresh_proposals/<date>.json and changes no policy file.
Review the file, then apply it with scripts/apply_refresh.py.
"""
import argparse
import asyncio
import sys

from app.inference import usage
from app.research.rules_refresh import run_refresh


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-calls", type=int, default=None)
    args = parser.parse_args(argv)
    if not usage.role_allowed("rules_refresh"):
        print("skipped: the monthly model cap has paused research")
        return 1
    target = asyncio.run(run_refresh(max_calls=args.max_calls))
    print(f"proposal: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
