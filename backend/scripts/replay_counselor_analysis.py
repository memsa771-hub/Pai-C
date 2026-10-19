"""Requeue failed analysis turns in place after correcting their failure.

Run on the backend host: python -m scripts.replay_counselor_analysis --workspace UUID
The worker processes the original events in order; no notebook data is edited.
"""
import argparse
from uuid import UUID

from app.database import new_session
from app.pai_c.deep.analysis import replay_failed_analyses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=UUID)
    args = parser.parse_args()
    with new_session() as db:
        count = replay_failed_analyses(db, str(args.workspace))
        db.commit()
    print(f'Requeued {count} failed counselor analyses')


if __name__ == '__main__':
    main()
