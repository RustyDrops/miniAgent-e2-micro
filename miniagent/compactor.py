"""Zero-cost rule-based prompt compaction and whitespace stripper."""
import re

CONVERSATIONAL_PADDING_REGEX = re.compile(
    r'^(?:Sure(?: thing)?[!.,]?|Certainly[!.,]?|Of course[!.,]?|Here(?: is| are) (?:the )?[^:\n]+:)\s*',
    re.IGNORECASE
)


def compact_text(text: str) -> str:
    """Strip unnecessary whitespace, markdown decorations, and conversational padding."""
    if not isinstance(text, str) or not text.strip():
        return ''

    # Remove conversational preamble if present
    cleaned = CONVERSATIONAL_PADDING_REGEX.sub('', text.strip())

    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in cleaned.splitlines()]

    # Collapse multiple consecutive blank lines into at most one empty line
    collapsed = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                collapsed.append(line)
            prev_blank = True
        else:
            collapsed.append(line)
            prev_blank = False

    return '\n'.join(collapsed).strip()


def compact_messages(messages: list[dict]) -> list[dict]:
    """Compact text across a list of chat message objects without altering structure."""
    out = []
    for m in messages:
        if isinstance(m, dict) and 'content' in m and isinstance(m['content'], str):
            out.append({**m, 'content': compact_text(m['content'])})
        else:
            out.append(m)
    return out
