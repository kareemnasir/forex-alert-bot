# Marketaux API contract for issue #28

Checked against the [official Marketaux API documentation](https://www.marketaux.com/documentation) on 2026-08-13.

## Request contract

- Endpoint: `GET https://api.marketaux.com/v1/news/all`. Marketaux documents this Finance & Market News endpoint as available on all plans.
- Authentication: required GET query parameter `api_token`. The documentation does not describe bearer-token or header authentication.
- `search`: optional full-text search over the article title and body. It supports `+` (AND), `|` (OR), unary `-`, quoted phrases, suffix `*`, and parentheses. Reserved characters must be escaped, and Marketaux says GET parameters must be URL-encoded.
- `language`: optional comma-separated language codes; the default is all languages. `language=en` requests English results.
- `limit`: optional requested article count. Its default and maximum depend on the account plan, so the client should send the configured small limit without assuming a fixed free-tier maximum.
- `published_after`: optional exclusive lower publication-time bound. Documented forms include `YYYY-MM-DDTHH:MM:SS`, `YYYY-MM-DDTHH:MM`, `YYYY-MM-DDTHH`, `YYYY-MM-DD`, `YYYY-MM`, and `YYYY`.

A suitable single-request shape for this project is:

```text
GET https://api.marketaux.com/v1/news/all
    ?api_token=<NEWS_API_KEY>
    &search=<URL-encoded explicit OR expression>
    &language=en
    &limit=<NEWS_MAX_ITEMS>
    &published_after=<UTC YYYY-MM-DDTHH:MM:SS>
```

Using one explicit OR expression for all configured currency, country, and central-bank terms keeps request volume bounded. Marketaux does not define how bare multiword searches combine, so explicit operators are less ambiguous. In particular, encode `|` and encode a literal AND operator `+` as `%2B` rather than sending a raw plus sign.

## Date semantics

Marketaux states that all dates are UTC (GMT). Its `published_after` examples omit a zone suffix, while response examples use UTC `Z` timestamps such as `2024-11-08T01:24:00.000000Z`. Format the request cutoff from a UTC-aware datetime using the documented suffix-free form, then parse `published_at` (including fractional seconds and `Z`) into a UTC-aware internal datetime. See [Getting Started and Finance & Market News](https://www.marketaux.com/documentation).

## Response contract

The response envelope is:

```json
{
  "meta": {
    "found": 123,
    "returned": 10,
    "limit": 10,
    "page": 1
  },
  "data": []
}
```

Marketaux says an empty result has an empty `data` array. Each article may include:

- `title`: article title
- `source`: source domain, not necessarily a display-friendly publisher name
- `published_at`: publication datetime
- `url`: article URL
- `description`: article meta description
- `snippet`: short snippet of the article body
- other fields including `uuid`, `keywords`, `image_url`, `language`, `relevance_score`, `entities`, and `similar`

There is no separate `summary` field. A normalized item can prefer `snippet` and fall back to `description`. The official page describes fields but does not provide a required/nullability schema, so normalization should tolerate null optional text fields and skip records missing required internal fields. See the official [response object definitions and example response](https://www.marketaux.com/documentation).

## Errors and implementation cautions

The official error section documents JSON errors shaped like `{"error":{"code":"...","message":"..."}}`, including malformed parameters, invalid tokens, exhausted usage, plan restrictions, rate limiting, and server/unavailable failures. The fetcher should therefore treat non-success HTTP responses, invalid JSON, and unexpected envelopes as recoverable provider failures.

Two documentation ambiguities should not leak into the internal provider contract:

1. Request date formats omit `Z`/offsets despite the global UTC statement. Use a UTC value rendered in the documented suffix-free request form, and always produce UTC-aware normalized values.
2. With `search`, the documented default ordering changes to relevance. The `sort` description inconsistently names `published_on` while also discussing `published_at`; do not depend on that discrepancy. Apply the cutoff, relevance checks, item cap, and deterministic ordering locally.

Source: [Marketaux official API documentation](https://www.marketaux.com/documentation).
