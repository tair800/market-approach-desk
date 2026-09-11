"""What the model may say about an underwriter's reply, and — more importantly — what it may not.

**The containment here is structural, not procedural.** CLAUDE.md rule 3 forbids the model from
deciding who is approached, owning uniqueness, causing a send, or moving approach state. That rule
is only worth anything if a model *cannot express* those things, so the response type below carries:

- no identifier of any kind — no placement, market, approach or reply id. A classification that
  named its own subject could be pointed at a different one.
- no state, and no field whose name or type could be read as one.
- no boolean permission. There is no ``may_approach``, no ``allow``, no ``retry``. A caller cannot
  branch on a field that does not exist.
- no numeric type anywhere in the tree, so nothing can become a count, a score a rule thresholds on,
  or a delay.

A guard test walks this schema and fails the build if any of that appears. It is not optional and
must not be weakened: the moment a permission-shaped field exists, someone downstream will read it,
and the model will be deciding who gets approached.

The one thing the model *can* do that changes behaviour is classify a reply as ``declined``, which
starts a cooling period. That is a rule a human wrote, applied to a classification a human can see
and correct — not a decision the model makes about an approach.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ReplyClass", "ReplyClassification", "classification_wire_schema"]

#: Closed on every axis: no extra fields, frozen after validation.
_CLOSED = ConfigDict(extra="forbid", frozen=True, strict=True)


class ReplyClass(enum.StrEnum):
    """The closed vocabulary. Five values, and the fifth is not a failure.

    ``UNCLEAR`` exists so the model has somewhere honest to go. Without it, a reply that genuinely
    does not fit gets forced into one of the other four, and the wrong one will occasionally be
    ``DECLINED`` — which starts a thirty-day cooling period on a carrier who never declined.
    """

    #: The underwriter will quote, or has quoted.
    INTERESTED = "interested"

    #: The underwriter will not quote. **Starts the cooling period**, which is why a wrong one is
    #: expensive and why abstention exists.
    DECLINED = "declined"

    #: They need something before they can answer.
    NEEDS_INFORMATION = "needs_information"

    #: Passed to a colleague, another office, or a different underwriting team.
    REFERRED = "referred"

    #: Out of office, an acknowledgement, or anything that is not an answer.
    UNCLEAR = "unclear"


class ReplyClassification(BaseModel):
    """One reading of one reply. Four fields, and none of them can move anything.

    Note what an abstaining classification carries: ``UNCLEAR``. The implication runs one way — a
    model that declined to judge has not judged, so it may not also assert ``DECLINED``. Enforced
    below rather than documented, because a contradiction that only a docstring forbids is a
    contradiction that ships.
    """

    model_config = _CLOSED

    classification: ReplyClass

    #: Free text for a human reader. **Never parsed, never branched on, never searched for a
    #: number.** It is provenance: the reason a person can disagree with the model on the evidence.
    rationale: str = Field(min_length=1, max_length=2000)

    #: Whether the model declined to judge. Not derivable from the classification: an ``UNCLEAR``
    #: that was *chosen* and one that was a refusal to choose are different answers.
    abstained: bool

    #: A band, never a score. A number here would be the first numeric field in the tree, and the
    #: first thing a future rule would threshold on — at which point the model is deciding.
    confidence: str = Field(pattern="^(low|medium|high)$")

    def model_post_init(self, _context: object) -> None:
        if self.abstained and self.classification is not ReplyClass.UNCLEAR:
            raise ValueError(
                "an abstaining classification must carry 'unclear': a model that declined to judge "
                f"cannot also assert {self.classification.value!r}"
            )


def classification_wire_schema() -> dict[str, object]:
    """The contract as a provider receives it, with the prose stripped out.

    Pydantic folds every docstring in the tree into ``description`` keys, and the docstrings here
    are engineering notes — including the reasoning behind a commercial control. Three problems with
    shipping that to a vendor on every call: it is tokens of nothing the model needs, it hands a
    third party the reasoning behind the control, and the guard test that scans for forbidden field
    shapes would be scanning our own commentary about them.

    Structure is untouched: same properties, same enum, same ``additionalProperties: false``.
    """

    def strip(node: object, *, in_properties: bool = False) -> object:
        if isinstance(node, dict):
            if in_properties:
                return {key: strip(value) for key, value in node.items()}
            return {
                key: strip(value, in_properties=key in {"properties", "$defs"})
                for key, value in node.items()
                if key not in {"description", "title", "examples"}
            }
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    stripped = strip(ReplyClassification.model_json_schema())
    assert isinstance(stripped, dict)
    return stripped
