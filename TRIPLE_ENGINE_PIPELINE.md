# Triple-Engine Consensus Pipeline Architecture

## Overview
The Jury System is a resilient, multi-model consensus architecture designed to analyze conflict scenarios and provide unified, auditable verdicts. It evaluates documents by cross-referencing decisions from three primary AI engines working together through a structured vote. The system is designed to gracefully handle API quota limits and ensure maximum uptime.

## AI Models Used
The system provisions three primary top-tier models alongside a failover instance, standardizing access via Google Cloud Vertex AI:

1. **Anthropic Claude (Lead Juror):**
   - **Name:** Claude Opus 4.6 (referenced technically via Opus/Sonnet implementations).
   - **Role:** Primary analytical engine, functioning as the Lead.
   - **Routing:** Handled via the official `@anthropic-ai/vertex-sdk`. Utilizes the `global` region endpoint.
   - **Redundancy:** Configured with an explicit `europe-west1` regional failover node to bypass localized exhaustion.

2. **Google Gemini:**
   - **Name:** Gemini 3 Flash / Gemini 2.5 Flash.
   - **Role:** Independent Juror for diversity of thought.
   - **Routing:** Accessed directly via REST API endpoints (`us-east5` regional).

3. **Meta Llama:**
   - **Name:** Llama 4 Maverick.
   - **Role:** Independent Juror for diversity of thought.
   - **Routing:** Accessed directly via REST API endpoints (`us-east5` regional).

*All access is securely brokered utilizing `google-auth-library` and a centralized `service-account.json`, scoped to `https://www.googleapis.com/auth/cloud-platform`.*

---

## The Pipeline Workflow

The execution pipeline is mapped through the `JuryLogic` class and operates in four primary stages:

### Stage 1: Initialization and Health Checks (`runHealthCheck`)
Before requesting inferences, the system polls all jurors to verify availability.
- Pings each model linearly with a minimal test prompt.
- **Intelligent 429 Handling:** For Anthropic models, an HTTP 429 (Too Many Requests) is correctly flagged as "active" (meaning the authentication and networking are valid, but the quota limit was reached).
- Any juror failing validation is deactivated for the duration of the audit.

### Stage 2: Resilient Document Execution (`runConflictSimulation`)
The core processing algorithm utilizes a "Deep Economy with Polite Delays" execution style.
- **Sequential Execution:** Jurors process the simulation sequentially rather than strictly simultaneously.
- **Polite Delays:** The system enforces a **10-second stall** between each juror's turn (`await new Promise(resolve => setTimeout(resolve, 10000))`). This ensures quota buckets for models have time to replenish, mitigating concurrency limits.

### Stage 3: Extreme Resilience and Fallback Tactics
Inference calls (specifically to the Lead Juror) use layered defense mechanisms to prevent query failure:
- **Ultra-Minimal Prompts & Outputs:** The token budget is extremely constrained (`max_tokens: 50`, `budget_tokens: 32` for thinking), and the prompt is string-truncated to lower the processing payload.
- **Exponential Backoff:** If a standard 429 error is hit during analysis, the system loops through retries with an exponential wait timer (`1s`, `3s`, `10s`).
- **Cross-Region Failover:** If the primary Claude (Global) endpoint experiences a 429 drop on its very first attempt, traffic is instantly diverted to `analyzeWithEUFailover` targeting `europe-west1` to maintain throughput.

### Stage 4: Consensus Evaluation & Verdict
Every juror returns a strictly formatted JSON object containing:
- `verdict`: The outcome (e.g., `rotation_wins`, `override_wins`).
- `confidence`: Granular confidence level.
- `reasoning`: A brief explanation.
- `timeline`: A chronological breakdown of events.

The `calculateConsensus()` algorithm parses these results:
- Determines the `majority` via vote counting.
- Assesses the total confidence level based on agreement ratio (`maxCount / verdicts.length`).
- Establishes Pass/Fail parameters based on an arbitrary but highly secure **67% threshold** (e.g., minimum 2 out of 3 jurors must agree to stamp `✅ PASSED`).
