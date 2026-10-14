/** Plain operational labels — clear for any desk role; accurate for clinicians. */

export function coverageLabel(value: string | undefined): string {
  switch ((value || "").toUpperCase()) {
    case "COMPLETE":
      return "All checklist items have chart support";
    case "AVAILABLE":
      return "Some checklist items have chart support";
    case "NONE":
      return "No chart support found yet";
    default:
      return "Checklist coverage not checked yet";
  }
}

/** True only when scoring_path names a real LLM (not local/rules). */
export function isModelScoringPath(path: string | undefined): boolean {
  const value = (path || "").toLowerCase().trim();
  if (!value) return false;
  if (value.startsWith("rules") || value.startsWith("rule_check")) return false;
  if (value.startsWith("ai_clinical:")) {
    const provider = value.split(":")[1] || "";
    return provider !== "" && provider !== "local";
  }
  return false;
}

/** True for draft_source / senior assist that used a real LLM (not ai:local). */
export function isModelAssistSource(source: string | undefined): boolean {
  const value = (source || "").toLowerCase().trim();
  if (value.startsWith("ai:")) {
    const provider = value.slice(3);
    return provider !== "" && provider !== "local";
  }
  return false;
}

export function scoringLabel(path: string | undefined): string {
  if (isModelScoringPath(path)) {
    return "Prepared with AI check";
  }
  return "Prepared with rule check";
}

export function agentDisplayName(agent: string | undefined): string {
  switch (agent) {
    case "Orchestrator":
      return "Care coordinator";
    case "PolicyAgent":
      return "Policy checklist";
    case "ClinicalEvidenceAgent":
      return "Chart matcher";
    case "ImagingAgent":
      return "Imaging assist";
    case "EvidenceVerificationAgent":
      return "Evidence check";
    case "CriticAgent":
      return "Double-check";
    case "PathwayAgent":
      return "Next steps";
    case "AuthorizationAgent":
      return "Senior review";
    default:
      return (agent || "Evidence prep").replace(/Agent$/i, "").replace(/([a-z])([A-Z])/g, "$1 $2");
  }
}

export function agentRoleBlurb(agent: string | undefined): string {
  switch (agent) {
    case "Orchestrator":
      return "Runs the evidence-pack steps in order";
    case "PolicyAgent":
      return "Loads the payer checklist for this request";
    case "ClinicalEvidenceAgent":
      return "Looks for matching notes, labs, and meds in the chart";
    case "ImagingAgent":
      return "Adds imaging context from the chart (not a diagnosis)";
    case "EvidenceVerificationAgent":
      return "Checks that citations make sense and flags conflicts";
    case "CriticAgent":
      return "Flags weak or thin support before you send for review";
    case "PathwayAgent":
      return "Lists what to document next, in priority order";
    case "AuthorizationAgent":
      return "Holds the case for a senior clinician to confirm";
    default:
      return "";
  }
}

export function nodeDisplayName(node: string | undefined): string {
  const value = (node || "").toLowerCase().replace(/_/g, " ");
  const map: Record<string, string> = {
    start: "Started",
    load_case: "Open case",
    "load case": "Open case",
    load_policy: "Load checklist",
    "load policy": "Load checklist",
    retrieve_evidence: "Find chart evidence",
    "retrieve evidence": "Find chart evidence",
    evaluate_criteria: "Check checklist",
    "evaluate criteria": "Check checklist",
    a2a_consult: "Imaging assist",
    "a2a consult": "Imaging assist",
    imaging_a2a_consult: "Imaging assist",
    "imaging a2a consult": "Imaging assist",
    verify_evidence: "Verify citations",
    "verify evidence": "Verify citations",
    check_contradictions: "Check conflicts",
    "check contradictions": "Check conflicts",
    critic_reflect: "Double-check",
    "critic reflect": "Double-check",
    build_pathway: "Plan next steps",
    "build pathway": "Plan next steps",
    generate_report: "Write summary",
    "generate report": "Write summary",
    policy: "Policy checklist",
    clinical: "Chart evidence",
    imaging: "Imaging",
    verify: "Verification",
    "human review": "Senior review",
    human_review: "Senior review",
    finalize: "Evidence pack ready",
    end: "Complete",
  };
  if (map[value]) {
    return map[value];
  }
  const cleaned = value
    .replace(/\ba2a\b/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.replace(/\b\w/g, (ch) => ch.toUpperCase()) || "Step";
}

/** Hide internal scoring / MCP / backend detail from the clinician desk. */
export function productStepDetail(detail: string | undefined): string | null {
  const raw = (detail || "").trim();
  if (!raw) {
    return null;
  }
  const lower = raw.toLowerCase();
  if (
    /^(hits|scoring|count)=/.test(lower) ||
    /^ok:/.test(lower) ||
    /^llm_fallback:/.test(lower) ||
    lower.includes("ai_clinical") ||
    lower.includes("rule_check") ||
    lower.includes("rules_fallback") ||
    lower.includes("monai") ||
    lower.includes("numpy") ||
    lower.includes("a2a") ||
    lower === "paused" ||
    lower === "disabled" ||
    lower === "resumed"
  ) {
    return null;
  }
  return raw;
}

/** Soften AI/scoring jargon in reasons and summaries shown on the desk. */
export function deskFacingText(value: string | undefined): string {
  let text = (value || "").trim();
  if (!text) {
    return "";
  }
  text = text
    .replace(/AI clinical intelligence\s*\(local grounded\)\s*:?\s*/gi, "Rule check: ")
    .replace(/AI clinical intelligence\s*:?\s*/gi, "AI check: ")
    .replace(/AI chart check\s*:?\s*/gi, "Rule check: ")
    .replace(/Grounded evidence summary:/gi, "Chart check summary:")
    .replace(/\blisted outcomes are SUPPORTED\b/gi, "checklist items were found in the chart")
    .replace(/\boutcomes are SUPPORTED\b/gi, "items were found in the chart")
    .replace(/\bSUPPORTED:\s*/g, "Found in chart: ")
    .replace(/\bNOT_SUPPORTED:\s*/g, "Doesn't match checklist: ")
    .replace(/\bMISSING:\s*/g, "Not found in chart: ")
    .replace(/\bUNKNOWN:\s*/g, "Unclear: ")
    .replace(/\bcriterion\b/gi, "checklist item")
    .replace(/\bcriteria\b/gi, "checklist items")
    .replace(
      /AI clinical intelligence path used grounded local scoring over synthetic records\./gi,
      "Prepared with rule check over the stored chart.",
    )
    .replace(/Prepared with AI assist over the stored chart/gi, "Prepared with rule check over the stored chart")
    .replace(/\s+/g, " ")
    .trim();
  return text;
}

export function procedureDisplayName(value: string | undefined): string {
  const raw = (value || "").trim();
  if (!raw) {
    return "Evidence pack";
  }
  const lower = raw.toLowerCase();
  if (
    lower.includes("medication reconciliation") ||
    lower.includes("dynamic catalog") ||
    lower.includes("catalog evidence") ||
    lower.includes("depression screening") ||
    lower === "evidence pack documentation"
  ) {
    return "Evidence pack";
  }
  return raw;
}

export function criterionStatusLabel(status: string | undefined): string {
  switch ((status || "").toUpperCase()) {
    case "SUPPORTED":
      return "Found in chart";
    case "NOT_SUPPORTED":
      return "Doesn't match checklist";
    case "MISSING":
      return "Not found in chart";
    case "PENDING":
      return "Not checked yet";
    case "UNKNOWN":
      return "Unclear — needs clinician look";
    default:
      return "Unclear — needs clinician look";
  }
}

export function criterionStatusClass(status: string | undefined): string {
  const value = (status || "UNKNOWN").toUpperCase();
  if (value === "SUPPORTED") return "ok";
  if (value === "NOT_SUPPORTED") return "bad";
  if (value === "MISSING") return "miss";
  if (value === "PENDING") return "pending";
  return "unk";
}

export function caseStatusLabel(status: string | undefined): string {
  switch (status) {
    case "needs_documentation":
      return "Needs more chart notes";
    case "ready_for_human":
      return "Ready for clinician review";
    case "closed_as_draft":
      return "Closed (draft)";
    default:
      return "Waiting in queue";
  }
}

export function documentTypeLabel(documentType: string | undefined): string {
  const value = (documentType || "").toLowerCase();
  const labels: Record<string, string> = {
    clinical_note: "Clinical note",
    catalog_clinical_note: "Clinical note",
    lab_result: "Lab result",
    policy: "Policy document",
    imaging_metadata: "Imaging study",
    medication: "Medication",
    procedure: "Procedure",
    claim: "Claim",
    discharge_summary: "Discharge summary",
    final_bill: "Final bill",
    bill: "Bill",
    investigation_report: "Investigation report",
    implant_invoice: "Implant invoice",
    mlc: "MLC / police intimation",
    case: "Case record",
  };
  return labels[value] || "Attached document";
}

export function sourceDisplay(documentType: string | undefined, _documentId?: string): string {
  return documentTypeLabel(documentType);
}

export function noteTypeLabel(noteType: string | undefined): string {
  const value = (noteType || "").toLowerCase().replace(/_/g, " ");
  if (!value || value.includes("catalog")) {
    return "Clinical note";
  }
  return value.replace(/\b\w/g, (ch) => ch.toUpperCase());
}

/** Synthea seeds US payer names; never show them on an Indian TPA desk. */
const US_PAYER = /\b(medicare|medicaid|aetna|cigna|humana|anthem|blue cross|blue shield|unitedhealthcare|united health ?care|dual eligible|no_insurance|tricare)\b/i;

export function indianPayerName(name: string | undefined): string {
  const raw = (name || "").trim();
  return raw && !US_PAYER.test(raw) ? raw : "";
}

export function professionalPolicyTitle(title: string | undefined): string {
  const raw = (title || "").replace(US_PAYER, "").replace(/\s{2,}/g, " ").replace(/^[\s·:-]+|[\s·:-]+$/g, "").trim();
  if (!raw || /dynamic catalog|catalog evidence/i.test(raw)) {
    return "Prior authorization evidence checklist";
  }
  return raw;
}

export function policyOptionLabel(policy: {
  title: string;
  procedure: string;
  payer_name?: string;
}): string {
  const title = professionalPolicyTitle(policy.title);
  const payerName = indianPayerName(policy.payer_name);
  const payer = payerName ? ` · ${payerName}` : "";
  return `${title}${payer}`;
}

export function conditionLabel(value: string): string {
  return value
    .replace(
      /\s*\((?:disorder|situation|finding|procedure|body structure|morphologic abnormality|observable entity|qualifier value|organism|substance)\)\s*$/i,
      "",
    )
    .trim();
}

export function documentationRiskLabel(
  risk: string | undefined,
  fallback?: string,
): string {
  if (fallback) {
    return fallback;
  }
  switch ((risk || "").toLowerCase()) {
    case "high":
      return "High risk of return for more documentation — close open items first (not a denial).";
    case "moderate":
      return "Evidence pack incomplete or needs clinician review before handoff.";
    case "low":
      return "Checklist appears ready for review — not an approval decision.";
    default:
      return "Risk not assessed yet";
  }
}

export function documentationRiskClass(risk: string | undefined): string {
  switch ((risk || "").toLowerCase()) {
    case "high":
      return "bad";
    case "moderate":
      return "warn";
    case "low":
      return "ok";
    default:
      return "neutral";
  }
}

export function citationStrengthLabel(
  strength: string | undefined,
  fallback?: string,
): string {
  if (fallback) {
    return fallback;
  }
  switch ((strength || "").toLowerCase()) {
    case "strong":
      return "Strong chart support";
    case "mixed":
      return "Mixed chart support";
    case "weak":
      return "Weak chart support";
    default:
      return "Support not assessed yet";
  }
}

/** Essentials section status for non-technical desks. */
export function essentialsStatusLabel(status: string | undefined): string {
  switch ((status || "").toLowerCase()) {
    case "ok":
    case "complete":
      return "Looks complete";
    case "thin":
      return "Needs more detail";
    case "missing":
      return "Missing";
    case "unknown":
      return "Unclear";
    default:
      return status || "Unclear";
  }
}

/**
 * Synthea adds social-history "findings" (education, employment, housing…) that are not
 * clinical conditions. Hide them wherever conditions are listed.
 */
const SOCIAL_FINDING =
  /(education|employment|employed|labor force|labour force|criminal record|social (?:isolation|contact)|housing|transportation|stress|violence|abuse by|intimate partner|refugee|incarcerat|served in armed forces|medication review due|unhealthy alcohol|risk activity|received certificate|lack of access|not in labor|part-time|full-time|reports of)/i;

export function isClinicalCondition(value: string): boolean {
  const raw = value.trim();
  if (!raw) return false;
  const tagged = /\((?:finding|situation)\)\s*$/i.test(raw);
  return !(tagged && SOCIAL_FINDING.test(raw));
}

export function clinicalConditions(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    if (!isClinicalCondition(value)) continue;
    const label = conditionLabel(value);
    const key = label.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(label);
  }
  return out;
}
