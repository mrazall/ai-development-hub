# Knowledge ACL envelope

Knowledge does not accept project ACL decisions from `/search` query parameters. The
control-plane sends `X-AIHub-Principal` with the value
`v1.<base64url(JSON payload)>.<base64url(HMAC-SHA256)>`.

The signed JSON payload is:

```json
{"project_ids":["project-a"],"role":"viewer","user_id":"user-123"}
```

The signature covers the exact base64url payload string and uses the shared
`AIHUB_INTERNAL_SECRET`. The service rejects missing, malformed, or invalidly signed
headers with HTTP 401. `role: admin` bypasses project filtering. Other principals can
read `shared`/`public` documents and private documents only when their signed
`project_ids` contains the document project. A private document without a project is
not readable by a non-admin principal.

The header is an internal service-to-service envelope, not a user-controlled token;
the control-plane is responsible for authenticating the user and issuing it.
