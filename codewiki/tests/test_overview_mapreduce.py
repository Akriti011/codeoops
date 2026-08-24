"""Unit tests for overview_mapreduce._insert_architecture_section's
three-tier diagram-placement strategy (tier 1: match a Purpose heading,
tolerant of numbering/case; tier 2: fall back to position — insert before
the document's second '##' heading; tier 3: append at the end).

These cases reproduce a real regression: a reduce run titled its heading
"## 1. Purpose" instead of the usual "## Purpose", and the old single-regex
match missed it, silently dropping the diagram at the very end of the
document instead of right after Purpose.
"""

import pytest

from codewiki.src.be.overview_mapreduce import _insert_architecture_section

_DIAGRAM = '```mermaid\ngraph LR\n    a["a"]\n```'


@pytest.mark.parametrize(
    "first_heading,second_heading",
    [
        ("## Purpose", "## Next Section"),
        ("## 1. Purpose", "## 2. Next Section"),
        ("## 1) Purpose", "## 2) Next Section"),
        ("## purpose", "## Next Section"),
    ],
)
def test_diagram_lands_after_first_section_via_purpose_match(first_heading, second_heading):
    doc = f"# repo\n\n{first_heading}\nSome text.\n\n{second_heading}\nMore text.\n"
    result = _insert_architecture_section(doc, _DIAGRAM)

    first_pos = result.index(first_heading)
    arch_pos = result.index("## Architecture")
    second_pos = result.index(second_heading)
    assert first_pos < arch_pos < second_pos


def test_diagram_lands_after_first_section_when_neither_heading_is_purpose():
    """Tier 2: no heading matches Purpose at all, by name or number — the
    diagram must still land right after the document's actual first
    section, by position rather than by name."""
    doc = "# repo\n\n## Overview\nSome text.\n\n## Deep Dive\nMore text.\n\n## Appendix\nExtra.\n"
    result = _insert_architecture_section(doc, _DIAGRAM)

    first_pos = result.index("## Overview")
    arch_pos = result.index("## Architecture")
    second_pos = result.index("## Deep Dive")
    assert first_pos < arch_pos < second_pos
