from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, validate_assignment=True)


class Source(StrictModel):
    document_id: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    region: tuple[float, float, float, float] | None = None

    @model_validator(mode='after')
    def location_required(self):
        if self.line is None and self.region is None:
            raise ValueError('A source needs a line or image region')
        if self.region:
            x1, y1, x2, y2 = self.region
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                raise ValueError('Region must use normalized ordered coordinates')
        return self


class ClinicalField(StrictModel):
    value: str | None
    status: Literal['present', 'missing', 'unreadable']
    sources: list[Source]

    @model_validator(mode='after')
    def consistent(self):
        if self.status == 'present' and (not self.value or not self.value.strip() or not self.sources):
            raise ValueError('Present fields require a value and evidence')
        if self.status != 'present' and self.value is not None:
            raise ValueError('Unknown clinical values must be null')
        if self.status == 'unreadable' and not self.sources:
            raise ValueError('Unreadable material requires a location')
        return self


class Medicine(StrictModel):
    name: ClinicalField
    dose: ClinicalField
    frequency: ClinicalField
    duration: ClinicalField


class Extraction(StrictModel):
    document_id: str
    medicines: list[Medicine]
    follow_up: list[ClinicalField]
    warning_signs: list[ClinicalField]
    unreadable_regions: list[Source]


class CaseInput(StrictModel):
    patient_alias: str = Field(min_length=1, max_length=100)
    summary: Extraction
    prescription: Extraction


class Decision(StrictModel):
    action: Literal['verified_value', 'verified_absent', 'escalate']
    value: str | None
    reason: str = Field(min_length=5)
    evidence: str = Field(min_length=3)

    @model_validator(mode='after')
    def valid_value(self):
        if self.action == 'verified_value' and (not self.value or not self.value.strip()):
            raise ValueError('A verified value is required')
        if self.action != 'verified_value' and self.value is not None:
            raise ValueError('Only verified_value accepts a value')
        return self
