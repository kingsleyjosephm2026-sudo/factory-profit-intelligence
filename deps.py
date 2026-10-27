from datetime import date
from typing import Annotated, Iterator, Literal

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from .services import analytics as A


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


DB = Annotated[Session, Depends(get_db)]


def get_filters(
    db: DB,
    date_from: date | None = None,
    date_to: date | None = None,
    line_id: Annotated[int | None, Query(ge=1)] = None,
    machine_id: Annotated[int | None, Query(ge=1)] = None,
    product_id: Annotated[int | None, Query(ge=1)] = None,
    shift: Literal["A", "B", "C"] | None = None,
) -> A.Filters:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")
    if (date_from and date_from.year < 2000) or (date_to and date_to.year > 2100):
        raise HTTPException(422, "dates must be between 2000 and 2100")
    base = A.default_filters(db)
    start, end = date_from or base.date_from, date_to or base.date_to
    if date_from and not date_to:
        end = max(start, base.date_to)
    if date_to and not date_from:
        start = min(base.date_from, end)
    return A.Filters(start, end, line_id, machine_id, product_id, shift)


F = Annotated[A.Filters, Depends(get_filters)]
Grain = Annotated[Literal["day", "week", "month"], Query()]
