# Gemify — Verification Engine Methodology & Execution Plan

**Scope of this document:** the exact schemas, rules, and decision rationale for the validation/anomaly layer we are adding, the API contract that connects the backend to the dashboard, and the rigid stage-by-stage plan for building Stages 1–6 in one day. Every design choice below states *what* it is and *why* it was chosen, so this file also functions as the project's decision log going forward. Append to it — don't replace it — as the day progresses.

---

## 1. Why this layer is being added

The dataset validated cleanly (referential integrity, reproducibility, PDF-CSV consistency) but had two structural gaps relative to what a compliance-verification engine needs to *demonstrate*:

1. **No real validation logic** — bidder GSTIN/PAN/Udyam fields were opaque placeholder strings (`SYN-GST-000001`), so there was nothing for a verification engine to actually *compute* against. A judge asking "show me it catching a fake GSTIN" had nothing to point at.
2. **Anomaly diversity was one-dimensional** — 10 cases, all `CROSS_BIDDER_DOCUMENT_NUMBER_REUSE`. A fraud-detection pitch needs to show breadth, not one trick repeated ten times.

Everything in Sections 2–4 exists to close those two gaps. Section 5 turns the closed gaps into a score. Section 6 exposes that score to a UI. Section 7 is the literal sequence for tomorrow.

---

## 2. Verification Schemas

These are the deterministic, explainable rules the Cross-Verification Engine (Member 4) runs. Each one is chosen because it is either (a) a real, publicly documented government ID algorithm, or (b) a structural rule that is defensible without needing live portal access.

### 2.1 GSTIN Validation Schema

**Why:** GSTIN is the one identifier in Indian government registration systems with a **public, documented checksum algorithm**. This is the strongest, most defensible piece of "real" validation logic the system can perform without a live API — use it as the flagship demo of Stage 3 (Cross-Verification).

**Structure (15 characters):**
```
Position:  1-2        3-12       13        14      15
Field:     State Code  PAN        Entity    "Z"     Checksum
                                   Code      (fixed) Digit
Example:   27          AAAAA0000A  1        Z       5
```

**Format regex (structural gate, run first — cheap, catches malformed input immediately):**
```regex
^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$
```

**Checksum algorithm (run second — only on structurally valid strings):**
```
CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"   # 36 chars, index = code point

def gstin_checksum_valid(gstin: str) -> bool:
    body = gstin[:14]              # first 14 characters
    declared_checksum = gstin[14]  # 15th character

    total = 0
    for i, ch in enumerate(body):
        weight = 1 if (i % 2 == 0) else 2       # position 1,3,5.. weight 1; 2,4,6.. weight 2
        codepoint = CHARSET.index(ch)
        product = codepoint * weight
        if product >= 36:
            product = (product // 36) + (product % 36)
        total += product

    checksum_codepoint = (36 - (total % 36)) % 36
    computed_checksum = CHARSET[checksum_codepoint]

    return computed_checksum == declared_checksum
```

**Caution (record this honestly in the pitch):** this is the standard published mod-36 algorithm used by most open-source GSTIN validators. Before treating it as a hard pass/fail gate, test it against a handful of *known-real* GSTINs (the PDF you have from YAMS BROS — `09BTIPS3536D1ZI` — is a good first test case) to confirm the implementation matches the live algorithm exactly. If it doesn't validate real known-good GSTINs, do not present it as authoritative — fall back to structural-only validation and say so.

### 2.2 PAN Validation Schema

**Why not a checksum:** unlike GSTIN, PAN's true check-digit algorithm is **not publicly documented or reliably reverse-engineered** — several open-source "PAN checksum" implementations in circulation are unverified. Claiming a checksum here that isn't real is a credibility risk if a judge checks. Instead, do **structural + semantic** validation, which is real and defensible.

**Structure (10 characters):** `AAAAA9999A`

```
Position 1-3: any alphabet series (no fixed meaning)
Position 4:   holder category (fixed meaning — see table)
Position 5:   first letter of surname (individual) or entity name
Position 6-9: sequential digits
Position 10:  alphabetic check character (algorithm not public — do not validate)
```

**4th-character category table (semantic validation — real, public):**
| Char | Holder type |
|---|---|
| P | Individual |
| C | Company |
| H | HUF (Hindu Undivided Family) |
| F | Firm |
| A | Association of Persons |
| T | Trust |
| B | Body of Individuals |
| L | Local Authority |
| J | Artificial Judicial Person |
| G | Government |

**Validation logic:**
```
def pan_structurally_valid(pan: str) -> tuple[bool, str]:
    if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', pan):
        return False, "Structural format mismatch"
    if pan[3] not in "PCHFATBLJG":
        return False, f"4th character '{pan[3]}' is not a recognized holder-category code"
    return True, "Structurally valid (10th-char checksum not independently verifiable)"
```

Bidders whose declared entity type (e.g. `MANUFACTURER`, company) has a PAN 4th-character mismatch (e.g. `P` for individual on a company bid) should be flagged as `PAN_CATEGORY_MISMATCH`.

### 2.3 Udyam Registration Validation Schema

**Why:** same reasoning as PAN — Udyam has a published *format*, no published checksum.

**Structure:** `UDYAM-XX-00-0000000`
```
UDYAM-   fixed prefix
XX       2-letter state code (must be a valid Indian state/UT code)
00       2-digit district code
0000000  7-digit unique registration sequence
```

```regex
^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$
```
State code must additionally be checked against the real list of state abbreviations (e.g. `MH`, `UP`, `DL`...) — a structurally valid but nonexistent state code (e.g. `ZZ`) is a `UDYAM_INVALID_STATE_CODE` flag.

### 2.4 Document Expiry & Status Rules

**Why:** this is the cheapest, highest-signal check available — a date comparison — and it's already partially represented in the dataset's `EXPIRED` verification_status. Formalizing it as a rule makes it explainable rather than a raw label.

```
def expiry_check(issue_date, expiry_date, bid_opening_date) -> str:
    if expiry_date is None:
        return "NO_EXPIRY_APPLICABLE"
    if expiry_date < bid_opening_date:
        return "EXPIRED_BEFORE_BID_OPENING"     # hard fail
    if (expiry_date - bid_opening_date).days < 30:
        return "EXPIRING_SOON_WITHIN_30_DAYS"   # soft flag, REVIEW not FAIL
    return "VALID"
```

### 2.5 Cross-Field Consistency Rules

**Why:** these are the rules that catch inconsistency *between* documents rather than within one document — this is where most real-world procurement fraud actually shows up (per the corruption-pattern research discussed earlier), and it's the natural home for entity-name fuzzy matching.

| Rule ID | Checks | Method | Flag on failure |
|---|---|---|---|
| CFR-01 | Entity name consistency across PAN, GSTIN, Udyam, cover letter | RapidFuzz token_sort_ratio, threshold 85% | `ENTITY_NAME_MISMATCH_ACROSS_DOCUMENTS` |
| CFR-02 | Declared turnover (bid form) vs. turnover evidence document | Exact / ±2% tolerance for rounding | `TURNOVER_DECLARATION_MISMATCH` |
| CFR-03 | GSTIN state code (first 2 digits) vs. registered address state | Lookup match | `GSTIN_ADDRESS_STATE_MISMATCH` |
| CFR-04 | OEM authorization present when bidder_role ≠ `MANUFACTURER`/`OEM` | Presence check | `OEM_AUTHORIZATION_CHAIN_BROKEN` |
| CFR-05 | Identical/near-identical `quoted_price` or `bidder_turnover` across ≥2 bidders on same tender | Exact match or <0.5% variance | `SUSPICIOUS_FINANCIAL_DUPLICATION` (collusion signal) |

---

## 3. Expanded Anomaly Taxonomy

**Why the current taxonomy is insufficient:** one anomaly type across 10 cases cannot demonstrate detection *breadth*. The table below adds 8 new types, each mapped to a schema rule from Section 2 or a new field from Section 4, with a target injection rate calibrated to stay realistic (real-world anomaly rates are low — flooding the dataset with fraud would itself look unrealistic to a judge).

| New `anomaly_type` | Source rule | Target count (of 1000 bidders) | Severity |
|---|---|---|---|
| `GSTIN_CHECKSUM_INVALID` | §2.1 | 15 | HIGH |
| `PAN_CATEGORY_MISMATCH` | §2.2 | 10 | MEDIUM |
| `UDYAM_INVALID_STATE_CODE` | §2.3 | 8 | MEDIUM |
| `ENTITY_NAME_MISMATCH_ACROSS_DOCUMENTS` | §2.5 CFR-01 | 20 | HIGH |
| `TURNOVER_DECLARATION_MISMATCH` | §2.5 CFR-02 | 15 | HIGH |
| `SUSPICIOUS_FINANCIAL_DUPLICATION` | §2.5 CFR-05 | 12 (6 pairs) | HIGH |
| `BLACKLIST_DEBARMENT_HIT` | new field, §4 | 8 | CRITICAL (hard-fail regardless of score) |
| `EPFO_ESIC_NONCOMPLIANT` | new field, §4 | 12 | MEDIUM |
| `CROSS_BIDDER_DOCUMENT_NUMBER_REUSE` *(existing)* | — | keep at 10 | MEDIUM |

**Total anomaly cases after expansion: ~110** (up from 10), against 1,000 bidders → **~11% anomaly rate**. This is deliberately generous relative to real-world fraud rates (which are far lower) — the justification to state openly in the pitch is that a demo needs enough positive cases to be visibly, repeatedly catchable within a short live demonstration; production calibration would use a much lower injection rate matched to real historical data.

---

## 4. Dataset Schema Changes

**Why:** Sections 2 and 3 introduce fields that don't exist in the current CSVs yet. This section is the literal diff to apply to the generator script.

### `bidders.csv` — new columns
```
blacklist_status          ENUM(CLEAR, DEBARRED)
epfo_registration_number  STRING (format: EPFO-XX-0000000-000, nullable if not applicable)
epfo_status                ENUM(COMPLIANT, NON_COMPLIANT, NOT_APPLICABLE)
esic_registration_number  STRING (nullable)
esic_status                ENUM(COMPLIANT, NON_COMPLIANT, NOT_APPLICABLE)
startup_india_number       STRING (nullable, format: DIPP0000)
nsic_registration_number  STRING (nullable)
```

### `documents.csv` — new `document_type` values
```
EPFO_REGISTRATION
ESIC_REGISTRATION
STARTUP_INDIA_CERTIFICATE
NSIC_REGISTRATION
BLACKLIST_DECLARATION   (a self-declaration doc, cross-checked against blacklist_status)
```

### `anomaly_cases.csv` — schema unchanged, `anomaly_type` enum extended per Section 3 table.

**Regeneration approach:** re-run `scripts/generate_dataset.py` with the same seed (42) plus the new field generators appended — this preserves reproducibility (byte-identical structured output for everything except the new fields) while extending coverage. Do **not** hand-edit the CSVs directly; any manual edit breaks the "two isolated runs produce identical output" reproducibility claim, which is one of the dataset's strongest credibility points.

---

## 5. Scoring & Risk Rubric

**Why explainable-rubric over ML score:** stated in earlier project discussion — a judge asking "why did bidder X get 72%?" needs a traceable answer. A weighted rubric gives that; an opaque model doesn't, without added SHAP infrastructure we don't have time to build by tomorrow.

```
Category weights (sum to 100):
  Statutory identity validity (GSTIN/PAN/Udyam format+checksum):  25
  Financial eligibility (turnover, EMD):                          20
  Experience & past performance:                                  20
  Document completeness & validity (expiry, presence):            15
  Cross-field consistency (CFR-01 through CFR-05):                 15
  MII/MSE preference compliance:                                   5

Hard-fail conditions (override score to CRITICAL regardless of total):
  - blacklist_status == DEBARRED
  - GSTIN_CHECKSUM_INVALID on the primary GSTIN document
  - Any mandatory document missing entirely

Risk bands:
  90-100  →  LOW
  70-89   →  MEDIUM
  40-69   →  HIGH
  0-39    →  CRITICAL
```

---

## 6. Frontend Integration — API Contract

**Why this shape:** the dashboard (Member 5) needs to render without knowing anything about how scoring was computed — it consumes one report object per bidder-tender pair. This keeps backend and frontend fully decoupled, so both can be built in parallel tomorrow without blocking each other (this is the single most important scheduling decision in Section 7).

### 6.1 Endpoints
```
GET  /api/tenders/{tender_id}                       → tender detail + requirement list
GET  /api/tenders/{tender_id}/bidders                → list of bidders with summary score/risk
GET  /api/bidders/{bidder_id}/compliance-report       → full ComplianceReport (below)
GET  /api/bidders/{bidder_id}/documents               → document list with verification_status
POST /api/bidders/{bidder_id}/officer-decision        → { decision, justification, officer_id }
GET  /api/audit-trail/{bidder_id}                     → immutable log of all checks + decisions
```

### 6.2 `ComplianceReport` response schema
```json
{
  "bidder_id": "BIDDER-000001",
  "tender_id": "TENDER-0001",
  "overall_score": 82,
  "risk_level": "MEDIUM",
  "hard_fail": false,
  "category_scores": {
    "statutory_identity": 25,
    "financial_eligibility": 18,
    "experience_performance": 20,
    "document_completeness": 12,
    "cross_field_consistency": 7,
    "mii_mse_compliance": 5
  },
  "flags": [
    {
      "rule_id": "CFR-01",
      "anomaly_type": "ENTITY_NAME_MISMATCH_ACROSS_DOCUMENTS",
      "severity": "HIGH",
      "description": "Entity name on GSTIN differs from PAN by 22% (below 85% match threshold).",
      "evidence_document_ids": ["DOC-000002", "DOC-000001"]
    }
  ],
  "ai_recommendation": "Bidder shows a name-consistency flag between GSTIN and PAN filings. Financial and experience criteria are met. Recommend conditional qualification pending clarification.",
  "generated_at": "2026-09-22T09:00:00+05:30"
}
```

### 6.3 Data flow (textual)
```
Backend (FastAPI, Member 3)
   → runs Sections 2 & 2.5 rules on ingestion (Member 2's extracted fields)
   → produces ComplianceReport JSON (Section 6.2), Member 4's scoring logic
   → LLM layer (Member 6) reads the JSON's flags[] array only, writes ai_recommendation string
   → Dashboard (Member 5) polls GET /compliance-report, renders score/risk/flags/evidence
   → Officer action → POST /officer-decision → written to audit trail (immutable append-only)
```

**Why polling, not WebSockets:** verification is not a streaming/real-time process for the demo (documents are pre-loaded, not live-uploaded during the pitch) — a simple GET-on-load is faster to build and has zero moving parts to debug under time pressure. WebSockets would be the right call as a scaling/production concern, not a hackathon-day concern.

---

## 7. Tomorrow's Execution Plan — Stage 1 through 6

**Rigidity note:** the times below assume a ~10-hour build day. Each stage has a **hard checkpoint** — if a stage isn't checkpoint-complete by its end time, the team drops scope (see Section 8) rather than letting the stage bleed into the next one. This exists specifically because Stage 4 (scoring) and Stage 6 (dashboard) both depend on Stage 3 (verification) — a late Stage 3 delays everyone.

| Time | Stage | Owner | Task | Checkpoint (must be true to proceed) |
|---|---|---|---|---|
| 09:00–09:30 | 0 | All | Standup: confirm dataset regeneration (Section 4) is done and validated | New CSVs pass the same validation script used before; anomaly count ≈110 |
| 09:30–11:30 | 1 (Ingestion & OCR) | Member 2 | Wire extraction pipeline to read the regenerated `documents.csv`-referenced PDFs; output structured fields with confidence scores | Can extract GSTIN/PAN/dates from ≥95% of sample PDFs without manual correction |
| 09:30–11:30 | 2 (Portal layer) | Member 3 | Build `PortalConnector` adapters; since real bidder data is synthetic, this stage is a **pass-through mock layer** that simulates GST-sandbox-style responses for demo purposes | Adapter returns a consistent, schema-valid mock response for any bidder_id |
| 11:30–14:00 | 3 (Cross-Verification) | Member 4 | Implement Sections 2.1–2.5 exactly as specified — GSTIN checksum, PAN structural, Udyam structural, expiry, CFR-01 to CFR-05 | Running against the full 1,000-bidder set reproduces the anomaly counts from Section 3's table within ±10% |
| 14:00–15:30 | 4 (Scoring & Risk) | Member 4 (+ Member 6 assist) | Implement Section 5 rubric; output `ComplianceReport` JSON per Section 6.2 | 5 known-good and 5 known-anomalous bidders score correctly on manual spot-check |
| 14:00–17:00 | 5 (Dashboard) | Member 5 | Build against the Section 6.2 schema using **mocked JSON**, not waiting on Member 4's live output | Dashboard renders a hardcoded sample ComplianceReport correctly before 15:30, then swaps to live API |
| 15:30–17:00 | 5b (LLM Recommendation) | Member 6 | Prompt template that ingests `flags[]` only (never raw documents) and produces `ai_recommendation` string; add hallucination guardrail (reject output that mentions a document_id not in the input) | 10 sample reports produce recommendations with zero fabricated document references |
| 17:00–18:00 | 6 (Integration) | All | Wire Member 5's dashboard to the real backend (drop the mock JSON); wire officer-decision POST → audit trail | Full path bidder-list → click bidder → see score/flags/recommendation → officer decision → audit log entry, works end-to-end for at least 3 bidders |
| 18:00–19:00 | — | All | Bug bash against the 8 new anomaly types specifically — confirm each type is visibly catchable in the UI, not just present in the JSON | Each of the 8 new anomaly types has at least one bidder where it is visibly flagged in the dashboard |
| 19:00+ | — | Member 6 | Update demo script to reference the new anomaly types by name | Demo script walks through ≥4 distinct anomaly types, not just the original one |

---

## 8. Cross-Verification of This Plan & Optimization for the Deadline

Self-review of the schema and schedule above, and where it should be *cut*, not just followed, if time runs short.

### 8.1 Risks in this plan as written
1. **Stage 3 is the critical path and the highest-risk stage.** Five distinct rule types (GSTIN checksum, PAN structural, Udyam structural, expiry, 5 cross-field rules) in 2.5 hours is tight. If Member 4 is not comfortable with RapidFuzz already, CFR-01 (fuzzy name matching) is the most likely rule to slip.
2. **Dataset regeneration (Section 4) is a hard blocker for everyone** and isn't on the timeline above — it must happen *before* 09:00, ideally tonight, or the whole day shifts right. This is the single most important instruction in this document: **do not start tomorrow's schedule until the regenerated dataset has passed validation.**
3. **LLM recommendation guardrails (5b) are easy to under-scope.** "Reject output that mentions a document_id not in the input" is a real engineering task (string-matching validation on the LLM's output), not just a prompt — budget real time for it, not an afterthought.

### 8.2 Optimized / faster path, without losing demo strength
If Stage 3 is behind schedule by 14:00, cut in this exact order (each cut preserves demo credibility better than the next):
1. **Cut CFR-03 (GSTIN-address state match) and CFR-04 (OEM chain) first.** These are the least visually dramatic in a live demo — a judge won't miss them if the other three are shown.
2. **Cut PAN category mismatch and Udyam state-code checks second.** Keep GSTIN checksum (it's the flagship, real-algorithm check) and CFR-01/CFR-02/CFR-05 (name mismatch, turnover mismatch, financial duplication) — these three tell the most compelling fraud story visually.
3. **Never cut the GSTIN checksum implementation.** It is the one piece of "real government algorithm" validation in the whole system and is worth protecting over everything else in Stage 3 if forced to choose.
4. **If Stage 5b (LLM guardrails) is at risk, ship without the document-id validation guardrail but disclose this explicitly in the pitch** ("grounding is enforced through structured-input-only prompting; output validation is a planned next step") rather than silently shipping an unguarded LLM call. An honest gap is safer than an undisclosed one if a judge tests it live.
5. **Dashboard (Stage 5) should never be blocked waiting for backend** — this is why it's scheduled to start at 14:00 against mocked JSON regardless of Stage 3/4 progress. This is the biggest schedule-derisking decision in the whole plan: **frontend and backend proceed in parallel from 14:00, full stop, even if backend is behind.**

### 8.3 What NOT to add, even if time permits
- Do not add more anomaly types beyond the 8 in Section 3 tomorrow — breadth is already sufficient to answer "does it only catch one thing," and additional types add regeneration + testing time without proportional demo value the day before presentation.
- Do not attempt live GST sandbox integration tomorrow if it isn't already working — Section 7's Portal layer is explicitly scoped as mock-only for tomorrow; live integration is a stretch goal for a later day, not part of this rigid plan.

---

## 9. Change Log

| Date | Change | Reason |
|---|---|---|
| (today) | Authored this methodology; scoped Sections 2–8 | Dataset review surfaced two gaps: no real checksum validation, anomaly taxonomy too narrow (see Section 1) |
| (tomorrow, fill in as executed) | | |
