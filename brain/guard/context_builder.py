"""
brain/guard/context_builder.py
Produces a compact markdown context block injected into Claude's prompt.
"""

from __future__ import annotations

from typing import Any


class ContextBuilder:
    """Builds a compact, truncated markdown context string for Claude."""

    HEADER = "## Brain Context\n"

    def build(
        self,
        activated_nodes: dict[str, Any],
        lessons: list[str],
        reflections: list[str],
        max_chars: int = 2000,
    ) -> str:
        """Render activated nodes, lessons, and reflections into a markdown snippet.

        Args:
            activated_nodes: Mapping of node_name -> content (str or dict with 'content' key).
            lessons:          List of lesson rule strings.
            reflections:      List of recent reflection strings.
            max_chars:        Hard character budget; output is truncated gracefully.

        Returns:
            A markdown string starting with '## Brain Context'.
        """
        sections: list[str] = [self.HEADER]

        # ---- Active Associations ----------------------------------------
        if activated_nodes:
            sections.append("### Active Associations\n")
            for name, payload in activated_nodes.items():
                if isinstance(payload, dict):
                    content = str(payload.get("content", ""))
                else:
                    content = str(payload)
                snippet = content[:100]
                sections.append(f"- **{name}**: {snippet}\n")

        # ---- Relevant Lessons -------------------------------------------
        if lessons:
            sections.append("### Relevant Lessons\n")
            for rule in lessons:
                sections.append(f"- {rule}\n")

        # ---- Recent Reflections -----------------------------------------
        if reflections:
            sections.append("### Recent Reflections\n")
            for reflection in reflections:
                sections.append(f"- {reflection}\n")

        # ---- Truncate to budget -----------------------------------------
        output = ""
        for chunk in sections:
            if len(output) + len(chunk) > max_chars:
                remaining = max_chars - len(output)
                if remaining > 4:
                    output += chunk[:remaining - 3] + "..."
                break
            output += chunk

        return output
