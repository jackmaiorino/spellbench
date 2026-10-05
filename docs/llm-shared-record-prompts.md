# Optional shared-record prompts

`--prompt-format shared-records-v1` enables a lossless representation of the existing player-visible JSON prompt. The default remains `json-v1`. Hosted brokers forward the selected format to their child, and configuration logs record `spellbench-llm/shared-records-v1` and the actual system instruction hash.

Repeated identical dictionaries of at least 100 UTF-8 bytes appear once in `records`. An object containing only `$ref` expands to the indexed record. Definitions reference only earlier records. `$literal` escapes an immediate dictionary with a reserved marker key, preserving arbitrary data without interpreting it as a reference. Arrays, scalar types, null values, every field and all original integer candidate IDs are retained. `expand_payload` supports bounded offline reconstruction for audit.

Visibility checks run before encoding. Engine extensions and raw envelopes remain excluded. The complete encoded messages must still fit the configured byte cap; an oversized decision refuses without truncating candidates. The inner position retains the canonical v1 data schema. The outer prompt version identifies the representation supplied to the model.

Byte-cap refusals log `prompt_byte_cap_exceeded` and the actual/configured sizes before any provider request. Other observation or prompt validation failures retain their general error category. Logs do not include the refused position or arbitrary exception text.

Lossless representation can change model choices. Selecting this format changes an entrant's input identity and requires source review and a new compatible throughput qualification before rated use. It does not prove equivalent playing strength, token savings from provider accounting, or fewer model calls. A smaller byte count cannot resolve an independently exceeded request cap. The existing Pauper definition and active qualification continue using the default format.
