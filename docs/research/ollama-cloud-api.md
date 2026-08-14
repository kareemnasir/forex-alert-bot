# Ollama Cloud API notes

Verified against official Ollama documentation on 2026-08-14. This is a narrow API-contract note for issue #29, not a model recommendation.

## Remote host and authentication

- The native Ollama API base URL for cloud models is `https://ollama.com/api`. A direct non-streaming chat request is therefore `POST https://ollama.com/api/chat`. The official SDK examples configure the host as `https://ollama.com`, because the SDK appends `/api/...`. ([API introduction](https://docs.ollama.com/api/introduction), [Cloud API access](https://docs.ollama.com/cloud))
- Direct access requires an API key sent as `Authorization: Bearer $OLLAMA_API_KEY`. Ollama says API keys currently do not expire, but can be revoked. The key must remain runtime configuration, not repository content. ([Authentication](https://docs.ollama.com/api/authentication))
- The cloud API can list models available to the account with `GET https://ollama.com/api/tags`. Ollama's direct-cloud examples use a configurable model value and may name it differently from a local Ollama client proxying a `:cloud` model, so the application should not hardcode a model name. ([Cloud API access](https://docs.ollama.com/cloud))

## Chat request and response envelope

For this short structured task, use the native chat endpoint with a body shaped like:

```json
{
  "model": "<configured model>",
  "messages": [
    {"role": "system", "content": "<guardrails and output contract>"},
    {"role": "user", "content": "<bounded news input>"}
  ],
  "stream": false
}
```

`model` and `messages` are required. REST streaming defaults to `true`; setting `stream: false` returns one `application/json` document and is explicitly described as simpler and better suited to short or structured responses. ([Chat endpoint](https://docs.ollama.com/api/chat), [Streaming](https://docs.ollama.com/api/streaming))

On success, the chat response contains the assistant output in `message.content`, alongside fields such as `model`, `created_at`, `done`, `done_reason`, and usage/timing metrics. The sentiment parser should parse only `message.content` as the model-produced JSON, while safe response metadata may be retained for diagnostics. ([Chat endpoint](https://docs.ollama.com/api/chat), [Usage metrics](https://docs.ollama.com/api/usage))

## JSON and schema enforcement

The general Ollama chat API documents a `format` field that can be `"json"` or a JSON schema. Its structured-output guidance recommends also including the schema in the prompt and demonstrates validating the returned content with Pydantic. However, the same official page currently states: **“Ollama’s Cloud currently does not support structured outputs.”** ([Structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [Chat endpoint](https://docs.ollama.com/api/chat))

Consequences for issue #29:

- Do not depend on Cloud enforcing `format` or a schema.
- Put the required JSON shape and behavioral guardrails in the prompt.
- Parse `message.content` as JSON and validate it against the application's strict Pydantic model.
- Treat malformed JSON, missing fields, out-of-range values, or extra disallowed structure as unavailable; client-side validation remains required even if Cloud later supports `format`.

## Errors, timeout, and retry boundary

Ollama documents JSON errors as `{"error": "..."}` and lists common HTTP statuses: `400` (bad request), `404` (not found/model missing), `429` (too many requests), `500` (internal server error), and `502` (bad gateway/cloud model unreachable). ([Errors](https://docs.ollama.com/api/errors))

The official API pages reviewed here do not define a Cloud request timeout, a `Retry-After` guarantee, or a prescribed retry/backoff policy. Therefore the caller should set its own finite HTTP timeout. A single bounded retry for connection/timeout failures, `429`, `500`, or `502` is a reasonable application policy inferred from the documented meanings; `400` and `404` should normally fail closed without retry because they indicate request/configuration errors. After the retry budget is exhausted, return sentiment as unavailable rather than allowing the scheduler to fail.
