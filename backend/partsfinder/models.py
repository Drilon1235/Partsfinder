"""Data models (Pydantic). See docs/03_DATAMODEL.md."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

FILE_FORMATS = {
    "step", "stp", "stl", "obj", "iges", "igs", "dxf", "dwg",
    "sldprt", "sldasm", "f3d", "ipt", "iam", "catpart", "catproduct",
    "prt", "par", "asm", "3mf", "fcstd",
}


class PartFile(BaseModel):
    format: str
    path: str
    is_primary: bool = False

    @field_validator("format")
    @classmethod
    def _format(cls, v: str) -> str:
        v = v.lower().lstrip(".")
        if v not in FILE_FORMATS:
            raise ValueError(f"Unknown file format '{v}'")
        return v


class PartBase(BaseModel):
    company_id: str | None = None          # None = general library
    kind: Literal["part", "assembly"] = "part"
    name: str = Field(min_length=1)
    description: str = ""
    category_path: str
    sectors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    material: str | None = None
    color: str | None = None
    bbox_mm: tuple[float, float, float] | None = None
    volume_mm3: float | None = None
    mass_g: float | None = None
    standards: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    source: str = "upload"
    source_ref: str | None = None
    license: str | None = None
    thumbnail_path: str | None = None
    checksum: str | None = None
    files: list[PartFile] = Field(default_factory=list)
    access_group: str | None = None        # restricted group (company parts only); set by the import, never by a JSON

    @property
    def library(self) -> str:
        return "global" if self.company_id is None else "company"


class PartCreate(PartBase):
    id: str | None = None                  # generated automatically if empty


class Part(PartBase):
    id: str
    created_at: str
    updated_at: str


class AssemblyComponent(BaseModel):
    part: Part
    quantity: int = Field(default=1, ge=1)
