# Pre-visit LLM prompts

Patients must submit symptoms before `POST /api/appointments/confirm`. CareConnect stores the original text, then asks Gemini for a pre-visit summary. The summary is assistive only and is not a medical diagnosis.

## Prompt

The backend sends this prompt exactly, with the submitted symptoms substituted:

```
Analyse these symptoms and return:
urgency level (Low / Medium / High),
chief complaint,
and three suggested questions for the doctor.

Symptoms:
<symptoms>
```

The template lives in `backend/app/services/previsit.py` as `PREVISIT_PROMPT_TEMPLATE`. Appointment booking code does not call Gemini. It uses the `LLMClient` protocol in `backend/app/integrations/llm.py`. The Gemini adapter is `backend/app/integrations/gemini.py`.

## Expected model output

The response is accepted only when all of the following parse and validate:

| Field | Rule |
| --- | --- |
| urgency level | Exactly `Low`, `Medium`, or `High` |
| chief complaint | Non-empty string |
| suggested questions | Exactly three non-empty strings |

JSON is preferred (`urgency_level`, `chief_complaint`, `suggested_questions`). Plain text in the same shape is also accepted. Anything else is a generation failure.

## Stored fields

On confirm, in the same booking transaction:

1. Insert the appointment (`confirmed`).
2. Insert `symptom_submissions` with the original symptoms and `submitted_at`.
3. Insert `ai_symptom_summaries` with `status = pending`.
4. Convert the slot hold.
5. `COMMIT`

After commit, Gemini runs. The summary row is then updated with:

- `urgency_level`
- `chief_complaint`
- `suggested_questions`
- `raw_response` (the unmodified model text, when any text was returned)
- `status` (`succeeded` or `failed`)
- `error_message` (on failure)
- `generated_at`

## Failure handling

Gemini failure must never break appointment booking.

- The Gemini adapter uses a **30 second** request timeout (`GEMINI_TIMEOUT_SECONDS` in `backend/app/integrations/gemini.py`). Timeouts, missing API key, network errors, empty responses, and invalid output are stored as `status = failed` with `error_message` (timeouts use `Gemini request timed out`).
- The appointment row and original symptoms stay saved.
- `POST /api/appointments/{appointment_id}/previsit-summary/retry` regenerates from the stored symptoms.
- `GET /api/appointments/{appointment_id}/previsit-summary` returns the original symptoms to the patient, the assigned doctor, and admins even when AI generation failed. Doctors and admins also see `raw_response` when present.

If the LLM call raises after the booking transaction has committed, the HTTP confirm response is still `201`. Retry can run later.

## Post-visit prompt

After the assigned doctor submits clinical notes (and optional prescription and follow-up instructions), CareConnect asks Gemini for a patient-friendly summary. The backend sends this prompt exactly, with a notes block substituted:

```
Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps:

<notes>
```

`<notes>` is built from the saved clinical notes, each prescribed medicine (name, dosage, frequency, duration, instructions), and follow-up instructions. The model is not given extra medical facts, so it must not invent medication or follow-up details.

The template lives in `backend/app/services/visit.py` as `VISIT_SUMMARY_PROMPT_TEMPLATE`. Visit submit does not import Gemini. It uses the same `LLMClient` protocol.

## Post-visit expected output

The summary is accepted only when all of the following hold:

- the text is non-empty
- every prescribed medicine name appears in the summary
- follow-up instructions, when the doctor entered any, are reflected (the summary must include follow-up)
- the stored summary is labeled **AI-generated** and states that it is assistive only, not a medical diagnosis

CareConnect adds the AI-generated label if the model omits it. The labeled text is stored on `visit_notes.patient_friendly_summary`.

## Post-visit stored fields

On `POST /api/appointments/{appointment_id}/visit`, in one transaction:

1. Insert `visit_notes` with clinical notes, follow-up instructions, and `summary_status = pending`.
2. Insert `prescriptions` and `prescription_medications` when medicines were provided.
3. Mark the appointment `completed`.
4. `COMMIT`

After commit, Gemini runs. The visit note is then updated with:

- `patient_friendly_summary`
- `summary_raw_response`
- `summary_status` (`succeeded` or `failed`)
- `summary_error` (on failure)
- `summary_generated_at`

## Post-visit failure handling

Gemini failure must never roll back clinical notes or the prescription.

- Missing API key, network errors, empty responses, and summaries that drop prescribed medicines are stored as `summary_status = failed`.
- `POST /api/appointments/{appointment_id}/visit/summary/retry` regenerates from the stored notes and medicines. Only the assigned doctor may retry.
- `GET /api/appointments/{appointment_id}/visit` returns the appointment, original symptoms, pre-visit urgency and suggested questions, prescription, and (for the doctor) clinical notes even when AI generation failed.

Only the assigned doctor may submit visit notes. Patients and other doctors receive HTTP 403.

