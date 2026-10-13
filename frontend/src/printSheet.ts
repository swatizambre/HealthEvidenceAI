/** Browser print sheets for visit summary + evidence pack (not bills). */

function escapeHtml(value: string | undefined | null): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function linesToHtml(text: string): string {
  return escapeHtml(text)
    .split(/\r?\n/)
    .map((line) => (line.trim() ? `<p>${line}</p>` : "<br/>"))
    .join("");
}

const SHEET_CSS = `
  @page { margin: 16mm; }
  body {
    font-family: "Segoe UI", Georgia, "Times New Roman", serif;
    color: #122;
    font-size: 11pt;
    line-height: 1.45;
    margin: 0;
  }
  .sheet { max-width: 780px; margin: 0 auto; }
  .brand { font-size: 10pt; letter-spacing: 0.04em; text-transform: uppercase; color: #456; }
  h1 { font-size: 18pt; margin: 4px 0 8px; font-weight: 700; }
  h2 { font-size: 12pt; margin: 18px 0 6px; border-bottom: 1px solid #ccc; padding-bottom: 3px; }
  .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; margin: 10px 0 14px; }
  .meta div { border-bottom: 1px dotted #ddd; padding: 2px 0; }
  .meta span { color: #567; font-size: 9pt; display: block; }
  .meta strong { font-size: 11pt; }
  .meta-note { margin: 0 0 10px; color: #567; font-size: 9.5pt; }
  ul, ol { margin: 6px 0 6px 1.2em; padding: 0; }
  li { margin: 3px 0; }
  .box { border: 1px solid #ccc; padding: 8px 10px; margin: 8px 0; }
  .foot {
    margin-top: 22px;
    padding-top: 8px;
    border-top: 1px solid #999;
    font-size: 8.5pt;
    color: #445;
  }
  .sig { margin-top: 28px; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .sig .line { border-top: 1px solid #333; margin-top: 36px; padding-top: 4px; font-size: 9pt; }
  @media print {
    .no-print { display: none !important; }
  }
`;

export function openPrintSheet(title: string, bodyHtml: string): void {
  const win = window.open("", "_blank", "noopener,noreferrer,width=900,height=1000");
  if (!win) {
    window.alert("Allow pop-ups to print this sheet.");
    return;
  }
  win.document.open();
  win.document.write(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>${SHEET_CSS}</style>
</head>
<body>
  <div class="sheet">
    ${bodyHtml}
    <p class="no-print" style="margin-top:16px">
      <button onclick="window.print()">Print / Save as PDF</button>
      <button onclick="window.close()">Close</button>
    </p>
  </div>
  <script>window.addEventListener("load", function () { setTimeout(function () { window.print(); }, 250); });</script>
</body>
</html>`);
  win.document.close();
}

export type VisitPrintInput = {
  facilityName: string;
  doctorName: string;
  roleLabel: string;
  patientId: string;
  patientName?: string;
  sex?: string;
  dob?: string;
  visitNumber: string;
  department: string;
  chiefComplaint: string;
  hpi?: string;
  assessmentPlan?: string;
  diagnoses: { display: string; code?: string }[];
  labName?: string;
  labValue?: string;
  labUnit?: string;
  medName?: string;
  vitals?: { bp?: string; hr?: string; temp?: string };
  caseId?: string;
  printedAt?: string;
};

export function printVisitSummary(input: VisitPrintInput): void {
  const when = input.printedAt || new Date().toLocaleString();
  const dx = input.diagnoses.filter((d) => d.display.trim());
  const vitalsBits = [
    input.vitals?.bp ? `BP ${input.vitals.bp}` : "",
    input.vitals?.hr ? `HR ${input.vitals.hr}` : "",
    input.vitals?.temp ? `Temp ${input.vitals.temp}` : "",
  ].filter(Boolean);

  const body = `
    <p class="brand">HealthEvidence AI · Visit summary</p>
    <h1>OPD / visit summary</h1>
    <div class="meta">
      <div><span>Facility</span><strong>${escapeHtml(input.facilityName)}</strong></div>
      <div><span>Visit #</span><strong>${escapeHtml(input.visitNumber)}</strong></div>
      <div><span>Patient ID</span><strong>${escapeHtml(input.patientId)}</strong></div>
      <div><span>Patient name</span><strong>${escapeHtml(input.patientName || "—")}</strong></div>
      <div><span>Sex / DOB</span><strong>${escapeHtml(input.sex || "—")} · ${escapeHtml(input.dob || "—")}</strong></div>
      <div><span>Department</span><strong>${escapeHtml(input.department)}</strong></div>
      <div><span>Doctor / desk</span><strong>${escapeHtml(input.doctorName)}</strong></div>
      <div><span>Signed-in role</span><strong>${escapeHtml(input.roleLabel)}</strong></div>
      ${input.caseId ? `<div><span>Case</span><strong>${escapeHtml(input.caseId)}</strong></div>` : ""}
      <div><span>Printed</span><strong>${escapeHtml(when)}</strong></div>
    </div>

    <h2>Chief complaint</h2>
    <div class="box">${linesToHtml(input.chiefComplaint || "—")}</div>

    ${
      input.hpi
        ? `<h2>History / note</h2><div class="box">${linesToHtml(input.hpi)}</div>`
        : ""
    }

    ${
      dx.length
        ? `<h2>Diagnoses / disorders</h2><ul>${dx
            .map(
              (d) =>
                `<li>${escapeHtml(d.display)}${
                  d.code ? ` <span>(${escapeHtml(d.code)})</span>` : ""
                }</li>`,
            )
            .join("")}</ul>`
        : ""
    }

    ${
      vitalsBits.length
        ? `<h2>Vitals</h2><p>${escapeHtml(vitalsBits.join(" · "))}</p>`
        : ""
    }

    ${
      input.labName
        ? `<h2>Lab</h2><p>${escapeHtml(input.labName)}${
            input.labValue
              ? `: ${escapeHtml(input.labValue)} ${escapeHtml(input.labUnit || "")}`
              : ""
          }</p>`
        : ""
    }

    ${
      input.medName
        ? `<h2>Medication noted</h2><p>${escapeHtml(input.medName)}</p>`
        : ""
    }

    ${
      input.assessmentPlan
        ? `<h2>Assessment / plan</h2><div class="box">${linesToHtml(input.assessmentPlan)}</div>`
        : ""
    }

    <div class="sig">
      <div class="line">Doctor / clinician · ${escapeHtml(input.doctorName)}</div>
      <div class="line">Patient / attendant (if needed)</div>
    </div>

    <p class="foot">
      Visit summary for chart continuity and desk handoff only.
      Not an OPD bill, invoice, receipt, prescription pad, or discharge summary.
      Not a medical device. Does not diagnose, approve, or deny care.
      HealthEvidence AI · printed ${escapeHtml(when)}
    </p>
  `;

  openPrintSheet(`Visit summary · ${input.patientId}`, body);
}

export type PacketPrintInput = {
  facilityLabel: string;
  doctorName: string;
  roleLabel: string;
  patientId: string;
  patientName?: string;
  caseId: string;
  policyTitle: string;
  procedure: string;
  readinessPercent: number;
  gapCount: number;
  humanReviewRequired: boolean;
  criteria: { plain_status: string; criterion: string }[];
  gaps: { label: string; action?: string }[];
  nextSteps?: string[];
  pathway?: { title: string; detail?: string }[];
  scorecardNote?: string;
  packetSummary?: string;
  disclaimer?: string;
  printedAt?: string;
};

export function printEvidencePacket(input: PacketPrintInput): void {
  const when = input.printedAt || new Date().toLocaleString();
  const body = `
    <p class="brand">HealthEvidence AI · Evidence pack</p>
    <h1>Evidence pack</h1>
    <p class="meta-note">Print or save as PDF from your browser print dialog.</p>
    <div class="meta">
      <div><span>Facility desk</span><strong>${escapeHtml(input.facilityLabel)}</strong></div>
      <div><span>Prepared by</span><strong>${escapeHtml(input.doctorName)}</strong></div>
      <div><span>Role</span><strong>${escapeHtml(input.roleLabel)}</strong></div>
      <div><span>Printed</span><strong>${escapeHtml(when)}</strong></div>
      <div><span>Patient ID</span><strong>${escapeHtml(input.patientId)}</strong></div>
      <div><span>Patient name</span><strong>${escapeHtml(input.patientName || "—")}</strong></div>
      <div><span>Case</span><strong>${escapeHtml(input.caseId)}</strong></div>
      <div><span>Procedure</span><strong>${escapeHtml(input.procedure)}</strong></div>
      <div><span>Policy checklist</span><strong>${escapeHtml(input.policyTitle)}</strong></div>
      <div><span>Checklist covered</span><strong>${escapeHtml(String(input.readinessPercent))}%</strong></div>
      <div><span>Open items</span><strong>${escapeHtml(String(input.gapCount))}</strong></div>
      <div><span>Senior review</span><strong>${
        input.humanReviewRequired ? "Needed" : "Not required by desk rules"
      }</strong></div>
    </div>

    ${
      input.scorecardNote
        ? `<h2>Ready to send?</h2><div class="box">${linesToHtml(input.scorecardNote)}</div>`
        : ""
    }

    <h2>Insurance checklist</h2>
    <ol>
      ${input.criteria
        .map(
          (c) =>
            `<li><strong>${escapeHtml(c.plain_status)}</strong> — ${escapeHtml(c.criterion)}</li>`,
        )
        .join("")}
    </ol>

    ${
      input.gaps.length
        ? `<h2>Open items</h2><ul>${input.gaps
            .map(
              (g) =>
                `<li>${escapeHtml(g.label)}${
                  g.action ? ` — ${escapeHtml(g.action)}` : ""
                }</li>`,
            )
            .join("")}</ul>`
        : "<h2>Open items</h2><p>None listed on this checklist.</p>"
    }

    ${
      input.pathway?.length
        ? `<h2>What to do next</h2><ol>${input.pathway
            .map(
              (s) =>
                `<li><strong>${escapeHtml(s.title)}</strong>${
                  s.detail ? ` — ${escapeHtml(s.detail)}` : ""
                }</li>`,
            )
            .join("")}</ol>`
        : ""
    }

    ${
      input.nextSteps?.length
        ? `<h2>Desk next steps</h2><ul>${input.nextSteps
            .map((s) => `<li>${escapeHtml(s)}</li>`)
            .join("")}</ul>`
        : ""
    }

    ${
      input.packetSummary
        ? `<h2>Evidence pack summary</h2><div class="box">${linesToHtml(input.packetSummary)}</div>`
        : ""
    }

    <div class="sig">
      <div class="line">Prepared by · ${escapeHtml(input.doctorName)}</div>
      <div class="line">Senior clinician (if reviewing)</div>
    </div>

    <p class="foot">
      ${escapeHtml(
        input.disclaimer ||
          "Documentation readiness only — not a coverage decision, approval, or denial.",
      )}
      Not an OPD bill, invoice, or receipt. Not a medical device.
      HealthEvidence AI · printed ${escapeHtml(when)}
    </p>
  `;

  openPrintSheet(`Evidence pack · ${input.patientId}`, body);
}
