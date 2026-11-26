"""Input validation for Travel Stories comments."""

from uuid import UUID


def validate_comment(payload):
    """
    Validate a comment or reply.

    Return (cleaned_values, error_message).
    """
    if not isinstance(payload, dict):
        return None, "Send a valid comment object."

    content = payload.get("content")

    if not isinstance(content, str):
        return None, "Comment content is required."

    content = content.strip()

    if not 1 <= len(content) <= 5000:
        return None, "Comment must contain between 1 and 5000 characters."

    raw_parent_id = payload.get("parent_id")
    parent_id = None

    if raw_parent_id not in (None, ""):
        try:
            parent_id = str(UUID(str(raw_parent_id)))
        except (ValueError, TypeError, AttributeError):
            return None, "Invalid parent comment ID."

    return {
        "content": content,
        "parent_id": parent_id,
    }, None
