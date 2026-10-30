"""Expression contract for new 1.5 cards; validates decisions, not artistic truth."""
PROFILE = "implicit_relation"
MODES = ("relational_metaphor", "direct_depiction", "decorative", "unclear")
FIGURE_ROLES = ("none", "incidental", "primary")
REVIEW_BOUNDARY = (
    "本系列默认以可感知的状态或关系形成隐喻，不用人物活动、表情或情节演示句意。"
    "具象静物、空间、自然形态、摄影和抽象形式均可；无人物不等于合格，抽象也不自动合格。"
    "先如实记录可见内容，揭句后分别判断关联是否自然、表达是否符合系列边界。"
)

def nonempty(value):
    return isinstance(value, str) and bool(value.strip())

def policy_errors(data):
    if data.get("schema_version") != "1.5":
        return []
    policy = data.get("expression_policy")
    if not isinstance(policy, dict):
        return ["expression_policy is required for schema 1.5"]
    errors = []
    if policy.get("profile") != PROFILE:
        errors.append("expression_policy.profile must be implicit_relation")
    override = policy.get("user_override")
    if not isinstance(override, dict):
        return errors + ["expression_policy.user_override must be an object"]
    for key in ("allow_primary_figures", "allow_direct_depiction"):
        if type(override.get(key)) is not bool:
            errors.append(f"expression_policy.user_override.{key} must be boolean")
    if not isinstance(override.get("instruction"), str):
        errors.append("expression_policy.user_override.instruction must be a string")
    if any(override.get(k) is True for k in ("allow_primary_figures", "allow_direct_depiction")) and not nonempty(override.get("instruction")):
        errors.append("expression exception requires the actual explicit user instruction")
    return errors

def boundary_failures(row, data):
    """No keyword inference: semantic classification remains a reviewer responsibility."""
    policy = data.get("expression_policy") or {}
    if not isinstance(policy, dict):
        policy = {}
    override = policy.get("user_override") or {}
    if not isinstance(override, dict):
        override = {}
    failures = []
    mode = row.get("mode")
    if mode in ("decorative", "unclear"):
        failures.append("expression is decorative or unclear, not a perceptible transfer")
    if mode == "direct_depiction" and override.get("allow_direct_depiction") is not True:
        failures.append("direct depiction is outside the default metaphor boundary")
    if row.get("figure_role") == "primary" and override.get("allow_primary_figures") is not True:
        failures.append("primary human figures require explicit user authorization")
    return failures

def judgement_errors(row, label, decisions):
    if not isinstance(row, dict):
        return [f"{label} must be an object"]
    errors = []
    if row.get("mode") not in MODES:
        errors.append(f"{label}.mode is invalid")
    if row.get("figure_role") not in FIGURE_ROLES:
        errors.append(f"{label}.figure_role is invalid")
    if row.get("decision") not in decisions:
        errors.append(f"{label}.decision is invalid")
    if not nonempty(row.get("evidence")):
        errors.append(f"{label}.evidence requires concrete reasons")
    return errors

def concept_expression_errors(data):
    if data.get("schema_version") != "1.5":
        return []
    errors = policy_errors(data)
    competition = data.get("concept_competition") or {}
    if not isinstance(competition, dict):
        return errors
    concepts = competition.get("concepts") or []
    if not isinstance(concepts, list):
        return errors
    for index, concept in enumerate(concepts):
        if not isinstance(concept, dict):
            continue
        label = f"concepts[{index}].admission"
        row = concept.get("admission")
        errors += judgement_errors(row, label, ("admit", "reject"))
        if not nonempty(concept.get("metaphor_bridge")):
            errors.append(f"concepts[{index}].metaphor_bridge must explain the transfer or why it fails")
        if not isinstance(row, dict):
            continue
        if row.get("decision") == "admit":
            errors += [f"{label}: {failure}" for failure in boundary_failures(row, data)]
        if row.get("decision") == "reject" and concept.get("decision") != "rejected":
            errors.append(f"{label}: rejected admission cannot be selected or reserved")
        if concept.get("decision") == "selected" and row.get("decision") != "admit":
            errors.append(f"{label}: selected concept must be admitted")
    if competition.get("mode") == "standard":
        admitted = sum(isinstance(c, dict) and isinstance(c.get("admission"), dict)
                       and c["admission"].get("decision") == "admit" for c in concepts)
        if admitted < 2:
            errors.append("standard competition needs at least two admitted alternatives, not rejected strawmen")
    return errors

def expression_result_errors(result, data, require_pass=False):
    if data.get("schema_version") != "1.5":
        return []
    row = result.get("expression_review")
    errors = judgement_errors(row, "expression_review", ("pass", "fail"))
    if require_pass and isinstance(row, dict):
        if row.get("decision") != "pass":
            errors.append("expression_review must pass independently of natural connection")
        errors += boundary_failures(row, data)
    return errors
