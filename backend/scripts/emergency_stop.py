"""显式关闭共享灰度入口；不删除资料和会话。API 故障时可单独运行。"""

import argparse

from sqlalchemy import select

from backend import db
from backend.models import PilotControl


def stop_pilot() -> None:
    db.init_engine()
    with db.SessionLocal() as session:
        row = session.scalar(select(PilotControl).where(PilotControl.id == 1).with_for_update())
        if row is None:
            session.add(PilotControl(id=1, percent=0))
        else:
            row.percent = 0
        session.commit()
    with db.SessionLocal() as session:
        if session.get(PilotControl, 1).percent != 0:
            raise RuntimeError("Failed to verify emergency stop")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅核对是否已关闭")
    args = parser.parse_args()
    if args.check:
        db.init_engine()
        with db.SessionLocal() as session:
            row = session.get(PilotControl, 1)
            if row is None or row.percent != 0:
                raise RuntimeError("Pilot is not explicitly stopped")
    else:
        stop_pilot()
    print("pilot_percent=0 verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
