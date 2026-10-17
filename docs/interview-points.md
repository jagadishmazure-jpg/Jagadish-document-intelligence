# Interview points

Short, honest talking points for Jagadish-document-intelligence. Every number quoted is from the
real run shown in the README.

- The risk in IDP is posting a wrong number, so posting is refused while any validation error remains.
- Real run: a vendor line extracted at confidence 0.60 is held until a reviewer corrects it, then it posts.
- Money cross-checks catch extraction and source errors: a total of 11,000.00 against a subtotal plus tax of 11,566.80 is held.
- The model-backed extractor is a stub that refuses without credentials, so the demo never fakes a model call.

## Likely follow-up questions

- How would you pick the confidence threshold? (Trade reviewer load against error rate on labelled data.)
- How do you avoid double posting? (Idempotency keys at the ERP gateway.)
- Where does an LLM help most? (Unstructured contracts, with the same review gate.)
