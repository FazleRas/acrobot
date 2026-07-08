"""Parse GitHub's per-file `patch` strings into reviewable chunks.

Gotcha this module encodes: the `patch` field from GET /pulls/{n}/files is a
bare hunk sequence *without* the `--- a/…` / `+++ b/…` file headers that the
unified-diff format (and the unidiff library) require. We wrap each patch in
synthetic headers before parsing.
"""

from dataclasses import dataclass, field

from unidiff import PatchSet


@dataclass
class Chunk:
    """One hunk of one file, plus the line map needed to anchor comments."""

    path: str
    hunk_header: str  # e.g. "@@ -10,7 +10,9 @@"
    content: str  # the hunk's unified-diff text (what the LLM sees)
    # new-file line number -> line text, for added/context lines only.
    # Used to validate finding anchors (side=RIGHT) and to build fingerprints.
    new_lines: dict[int, str] = field(default_factory=dict)

    def lines_for(self, start: int, end: int | None = None) -> str:
        end = end or start
        return "\n".join(self.new_lines[n] for n in range(start, end + 1) if n in self.new_lines)


def parse_patch(path: str, patch: str) -> list[Chunk]:
    """Split one file's GitHub patch string into per-hunk Chunks."""
    synthetic = f"--- a/{path}\n+++ b/{path}\n{patch}\n"
    patch_set = PatchSet.from_string(synthetic)
    chunks: list[Chunk] = []
    for patched_file in patch_set:
        for hunk in patched_file:
            new_lines: dict[int, str] = {}
            for line in hunk:
                if line.is_added or line.is_context:
                    if line.target_line_no is not None:
                        new_lines[line.target_line_no] = line.value.rstrip("\n")
            chunks.append(
                Chunk(
                    path=path,
                    hunk_header=str(hunk).splitlines()[0],
                    content=str(hunk),
                    new_lines=new_lines,
                )
            )
    return chunks
