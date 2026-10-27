"""Command line helpers:  python -m app.cli <command>

  init-db            apply Alembic migrations (creates all tables)
  seed [--if-empty]  generate the reproducible SIMULATED demo dataset (fixed seed)
  reset-db           wipe transactional data (keeps reference data) and re-seed
  export-samples     write template and example CSV files into ./sample_data
"""
import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from . import models as m
from .config import get_settings
from .database import SessionLocal
from .services import datagen, ingestion, recommendations

ROOT = Path(__file__).resolve().parents[1]


def init_db() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    print("Database schema is up to date.")


def seed(if_empty: bool = False) -> None:
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(m.ProductionRecord)):
            if if_empty:
                print("Data already present; skipping seed.")
                return
            sys.exit("Data already present. Use reset-db to wipe and regenerate.")
        print(datagen.generate_history(db, s.demo_days, None, s.seed))
        print(recommendations.refresh(db))


def reset_db() -> None:
    s = get_settings()
    with SessionLocal() as db:
        datagen.wipe_all_data(db)
        print(datagen.generate_history(db, s.demo_days, None, s.seed))
        print(recommendations.refresh(db))


def export_samples() -> None:
    out = ROOT.parent / "sample_data"
    out.mkdir(exist_ok=True)
    for ds in ingestion.SPECS:
        (out / f"{ds}_template.csv").write_text(ingestion.template_csv(ds), encoding="utf-8")
    start = datetime.combine(date.today() + timedelta(days=30), datetime.min.time()).replace(hour=6)
    with (out / "production_valid_example.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        spec = ingestion.SPECS["production"]
        cols = list(spec.columns) + list(spec.optional)
        w.writerow(cols)
        for i in range(6):
            ts = start + timedelta(hours=8 * i)
            w.writerow(["M-A1", "P-A01", ts.strftime("%Y-%m-%d %H:%M"), 480, 0, 20 + i, 1600 + 10 * i, 25, 1650, 47000, 16, 3680, "ABC"[i % 3]])
    with (out / "production_malformed_example.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        cols = list(ingestion.SPECS["production"].columns) + ["shift"]
        w.writerow(cols)
        ts = start + timedelta(days=2)
        w.writerow(["M-A1", "P-A01", ts.strftime("%Y-%m-%d %H:%M"), 480, 0, 20, 1600, 25, 1650, 47000, 16, 3680, "A"])  # valid
        w.writerow(["M-A1", "P-A01", "not-a-date", 480, 0, 20, 1600, 25, 1650, 47000, 16, 3680, "A"])  # bad timestamp
        w.writerow(["M-ZZ", "P-A01", ts.strftime("%Y-%m-%d %H:%M"), 480, 0, 20, 1600, 25, 1650, 47000, 16, 3680, "A"])  # unknown machine
        w.writerow(["M-A2", "P-A01", ts.strftime("%Y-%m-%d %H:%M"), 480, 0, 20, -5, 25, 1650, 47000, 16, 3680, "A"])  # negative units
        w.writerow(["M-A2", "P-A01", ts.strftime("%Y-%m-%d %H:%M"), 480, 0, 20, 100, 500, 1650, 47000, 16, 3680, "A"])  # defects > units
        w.writerow(["M-A1", "P-A01", ts.strftime("%Y-%m-%d %H:%M"), 480, 0, 20, 1600, 25, 1650, 47000, 16, 3680, "A"])  # duplicate of row 1
    print(f"Wrote sample files to {out}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sp = sub.add_parser("seed")
    sp.add_argument("--if-empty", action="store_true")
    sub.add_parser("reset-db")
    sub.add_parser("export-samples")
    a = p.parse_args(argv)
    {"init-db": init_db, "seed": lambda: seed(a.if_empty), "reset-db": reset_db, "export-samples": export_samples}[a.cmd]()


if __name__ == "__main__":
    main()
