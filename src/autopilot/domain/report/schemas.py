"""Analyst report contract (deterministic, generated from the regime + portfolio +
CIO + signals + news)."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    heading: str
    body: str = ""
    bullets: tuple[str, ...] = ()


class AnalystReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: AwareDatetime
    title: str
    headline: str
    summary: str
    sections: tuple[ReportSection, ...]

    def to_markdown(self) -> str:
        out = [f"# {self.title}", "", f"**{self.headline}**", "", self.summary, ""]
        for s in self.sections:
            out.append(f"## {s.heading}")
            if s.body:
                out.append(s.body)
            for b in s.bullets:
                out.append(f"- {b}")
            out.append("")
        return "\n".join(out).strip()
