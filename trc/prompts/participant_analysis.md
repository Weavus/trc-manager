---
description: "Analyzes a single participant's dialogue to infer their role."
model_id_ref: "google/gemini-2.5-flash"
force_json_output: true
parameters:
  temperature: 0.2
  max_tokens: 4096
---

You are an AI expert in analyzing meeting transcripts. Your task is to analyze the provided dialogue from a single participant and assign their most probable roles based on the provided role taxonomy.

### INSTRUCTIONS
1.  **Analyze Dialogue:** Review the `participant_dialogue` to understand the speaker's contributions.
2.  **Infer Roles:** Identify up to 3 potential roles from the `role_taxonomy` that best match the participant's dialogue. Check both primary roles and aliases.
3.  **Filter by Quality:** Only include a role if you have high confidence in the match. As a guideline, only return roles where you would assign a `confidence_score` of 7 or higher. If no roles meet this quality bar, return an empty array `[]`.
4.  **Provide Confidence & Reasoning:** For each role, provide a `confidence_score` (1-10) and a brief `reasoning` (max 50 words) explaining your choice based on the dialogue.
5.  **Format Output:** The entire response **MUST** be a single JSON array of objects. Do not include any text outside the JSON.

### OUTPUT FORMAT
```json
[
  {
    "name": "{{participant_name}}",
    "inferred_role": "Taxonomy Role 1",
    "confidence_score": 9,
    "reasoning": "Brief justification for role 1 (max 50 words)."
  },
  {
    "name": "{{participant_name}}",
    "inferred_role": "Taxonomy Role 2",
    "confidence_score": 8,
    "reasoning": "Brief justification for role 2 (max 50 words)."
  }
]
```

### INPUTS

**Participant Name:**
{{participant_name}}

**Role Taxonomy:**
{{role_taxonomy}}

**Participant Dialogue:**
{{participant_dialogue}}

**JSON OUTPUT:**