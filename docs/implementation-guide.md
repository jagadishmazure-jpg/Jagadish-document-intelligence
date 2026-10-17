# Implementation guide: from offline build to Azure

> Status: **planned**. Nothing here has been deployed. The offline build in this
> repository is what exists today; this guide is how it would be taken to a
> real Azure environment.

## Azure service mapping

| Offline component | Azure service (planned) | Notes |
|---|---|---|
| Document intake | Azure Blob Storage with Event Grid trigger | Private endpoint |
| `Extractor` | Azure AI Document Intelligence prebuilt invoice, receipt and contract models | Keep the confidence contract |
| Pipeline runtime | Azure Functions (Durable) or Container Apps job | Managed identity |
| Review queue | Power Apps or a small web app with Entra ID sign-in | Reviewer identity on every correction |
| ERP posting | Logic Apps or API Management to the ERP API | Idempotency keys |
| Ledger | Immutable blob storage | Lineage for audit |

## Steps

1. Land documents in Blob Storage and trigger the pipeline from Event Grid.
2. Implement `LLMExtractor` on Document Intelligence and map its confidences to the same field contract.
3. Keep validation and the 0.8 threshold; tune the threshold on a labelled sample.
4. Build the reviewer UI and record every correction with the reviewer's identity.
5. Post to the ERP through an integration gateway with idempotency keys; keep posting refused on errors.
6. Measure field-level precision/recall and straight-through rate before widening scope.

## Guardrails to keep when going live

- Posting is refused while any validation error remains (`PostingRefused`).
- Fields under the 0.8 confidence threshold always go to a human.
- Money must reconcile within 1% before posting.
- `LLMExtractor` will not run without credentials, so nothing silently fakes a model call.
- Every stage, including held outcomes, is on a hash-chained ledger.

## What to measure before calling it production-ready

- Field-level precision and recall on a labelled set.
- Straight-through-processing rate and post-posting correction rate.
- Reviewer minutes per held document.
