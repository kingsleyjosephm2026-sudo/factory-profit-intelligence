from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal["downtime", "quality", "energy", "material"]
Status = Literal["Open", "In progress", "Resolved", "Dismissed"]


class Page(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[dict[str, Any]]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: str
    entity_key: str
    entity_type: str
    entity_name: str
    title: str
    evidence: str
    metric: str
    metric_value: float | None
    threshold: float | None
    severity: str
    next_action: str
    estimated_opportunity: float | None
    opportunity_basis: str
    confidence: str
    calculation_method: str
    window_start: date | None
    window_end: date | None
    status: str
    notes: str
    active: bool
    created_at: datetime
    last_evaluated_at: datetime
    updated_at: datetime


class RecommendationPatch(BaseModel):
    status: Status | None = None
    notes: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def _something(self):
        if self.status is None and self.notes is None:
            raise ValueError("Provide status and/or notes")
        return self


class SavingsBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    category: Category
    scope_type: Literal["factory", "line", "machine"] = "factory"
    scope_id: int | None = None
    value_source: Literal["computed", "manual"] = "computed"
    baseline_start: date | None = None
    baseline_end: date | None = None
    intervention_date: date | None = None
    post_start: date | None = None
    post_end: date | None = None
    baseline_metric: str = Field("", max_length=120)
    baseline_value: float | None = None
    post_metric: str = Field("", max_length=120)
    post_value: float | None = None
    manual_volume: float | None = Field(None, ge=0)
    expected_savings: float | None = Field(None, ge=0)
    assumptions: str = Field("", max_length=4000)
    notes: str = Field("", max_length=4000)

    @model_validator(mode="after")
    def _check(self):
        if self.scope_type != "factory" and self.scope_id is None:
            raise ValueError("scope_id is required for line/machine scope")
        for a, b, label in ((self.baseline_start, self.baseline_end, "baseline"), (self.post_start, self.post_end, "post-intervention")):
            if a and b and a > b:
                raise ValueError(f"{label} start must not be after its end")
        return self


class SavingsCreate(SavingsBase):
    pass


class SavingsPatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    scope_type: Literal["factory", "line", "machine"] | None = None
    scope_id: int | None = None
    value_source: Literal["computed", "manual"] | None = None
    baseline_start: date | None = None
    baseline_end: date | None = None
    intervention_date: date | None = None
    post_start: date | None = None
    post_end: date | None = None
    baseline_metric: str | None = Field(None, max_length=120)
    baseline_value: float | None = None
    post_metric: str | None = Field(None, max_length=120)
    post_value: float | None = None
    manual_volume: float | None = Field(None, ge=0)
    expected_savings: float | None = Field(None, ge=0)
    assumptions: str | None = Field(None, max_length=4000)
    notes: str | None = Field(None, max_length=4000)


class SavingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    category: str
    scope_type: str
    scope_id: int | None
    value_source: str
    baseline_start: date | None
    baseline_end: date | None
    intervention_date: date | None
    post_start: date | None
    post_end: date | None
    baseline_metric: str
    baseline_value: float | None
    post_metric: str
    post_value: float | None
    manual_volume: float | None
    expected_savings: float | None
    calculated_savings: float | None
    assumptions: str
    notes: str
    evidence_status: str
    created_at: datetime
    updated_at: datetime
