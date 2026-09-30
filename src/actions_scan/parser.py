from __future__ import annotations

from dataclasses import dataclass

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from actions_scan.models import ParsedUse


class WorkflowParseError(ValueError):
    """Raised when a workflow is not valid YAML."""


@dataclass(frozen=True)
class Reference:
    kind: str
    target: str
    ref: str


def classify_reference(raw_uses: str, *, is_string: bool = True) -> Reference:
    value = raw_uses.strip()
    if not is_string or not value or "${{" in value:
        return Reference("unresolved", value, "")

    if value.startswith("./"):
        return Reference("local_action", value, "")

    if value.startswith("docker://"):
        image = value.removeprefix("docker://")
        if "@" in image:
            target, ref = image.rsplit("@", 1)
        else:
            slash = image.rfind("/")
            colon = image.rfind(":")
            if colon > slash:
                target, ref = image[:colon], image[colon + 1 :]
            else:
                target, ref = image, ""
        return Reference("docker_image", target, ref)

    if "@" not in value:
        return Reference("unresolved", value, "")

    target, ref = value.rsplit("@", 1)
    target_parts = target.split("/")
    if len(target_parts) < 2 or not all(target_parts[:2]) or not ref:
        return Reference("unresolved", target, ref)

    if "/.github/workflows/" in target:
        return Reference("reusable_workflow", target, ref)
    return Reference("remote_action", target, ref)


def parse_workflow(source: str) -> list[ParsedUse]:
    try:
        root = yaml.compose(source, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        message = str(exc).replace("\n", " ")
        raise WorkflowParseError(message) from exc

    if root is None:
        return []
    if not isinstance(root, MappingNode):
        raise WorkflowParseError("workflow root must be a YAML mapping")

    workflow_name_node = _mapping_value(root, "name")
    workflow_name = _scalar_text(workflow_name_node)
    jobs = _mapping_value(root, "jobs")
    if jobs is None:
        return []
    if not isinstance(jobs, MappingNode):
        raise WorkflowParseError("workflow 'jobs' value must be a YAML mapping")

    parsed: list[ParsedUse] = []
    for job_key, job_node in jobs.value:
        job_id = _scalar_text(job_key)
        if not isinstance(job_node, MappingNode):
            continue

        job_uses = _mapping_value(job_node, "uses")
        if job_uses is not None:
            parsed.append(
                _parsed_use(
                    source,
                    job_uses,
                    workflow_name=workflow_name,
                    job_id=job_id,
                    location_type="job",
                    step_index=None,
                    step_name="",
                )
            )

        steps = _mapping_value(job_node, "steps")
        if not isinstance(steps, SequenceNode):
            continue
        for index, step in enumerate(steps.value, start=1):
            if not isinstance(step, MappingNode):
                continue
            uses = _mapping_value(step, "uses")
            if uses is None:
                continue
            parsed.append(
                _parsed_use(
                    source,
                    uses,
                    workflow_name=workflow_name,
                    job_id=job_id,
                    location_type="step",
                    step_index=index,
                    step_name=_scalar_text(_mapping_value(step, "name")),
                )
            )
    return parsed


def _mapping_value(mapping: MappingNode, key_name: str) -> Node | None:
    for key, value in mapping.value:
        if isinstance(key, ScalarNode) and key.value == key_name:
            return value
    return None


def _scalar_text(node: Node | None) -> str:
    return node.value if isinstance(node, ScalarNode) else ""


def _parsed_use(
    source: str,
    node: Node,
    *,
    workflow_name: str,
    job_id: str,
    location_type: str,
    step_index: int | None,
    step_name: str,
) -> ParsedUse:
    is_string = isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:str"
    raw_uses = node.value if isinstance(node, ScalarNode) else "<non-scalar>"
    reference = classify_reference(raw_uses, is_string=is_string)
    if location_type == "job" and reference.kind == "local_action":
        reference = Reference("local_reusable_workflow", reference.target, reference.ref)
    return ParsedUse(
        workflow_name=workflow_name,
        job_id=job_id,
        location_type=location_type,
        step_index=step_index,
        step_name=step_name,
        line=node.start_mark.line + 1,
        reference_kind=reference.kind,
        target=reference.target,
        ref=reference.ref,
        inline_version_hint=_inline_comment(source, node),
        raw_uses=raw_uses,
    )


def _inline_comment(source: str, node: Node) -> str:
    if node.start_mark.line != node.end_mark.line:
        return ""
    lines = source.splitlines()
    if node.end_mark.line >= len(lines):
        return ""
    tail = lines[node.end_mark.line][node.end_mark.column :]
    marker = tail.find("#")
    return tail[marker + 1 :].strip() if marker >= 0 else ""
