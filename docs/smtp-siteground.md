# SiteGround SMTP Setup (AlumCasting)

Production email delivery for the Lead Hunter outreach pipeline goes through
the **AlumCasting** mailbox on SiteGround.

## Confirmed provider settings

| Setting          | Value                       |
| ---------------- | --------------------------- |
| Account          | `sales@alumcasting.com`     |
| SMTP Host        | `sgp14.siteground.asia`     |
| Port             | `465`                       |
| Security         | **SSL/TLS (implicit SSL)**  |
| Authentication   | Required                    |
| Username         | `sales@alumcasting.com`     |
| Password         | the mailbox account password |

## .env configuration

```env
SMTP_HOST=sgp14.siteground.asia
SMTP_PORT=465
SMTP_USERNAME=sales@alumcasting.com
SMTP_PASSWORD=<mailbox password>
SMTP_FROM_EMAIL=sales@alumcasting.com
SMTP_USE_TLS=true
```

> `SMTP_USE_TLS` is kept for STARTTLS-capable providers (e.g. Gmail on 587).
> On port **465** the sender always uses implicit SSL (`smtplib.SMTP_SSL`)
> and never issues STARTTLS — this is handled automatically from the port.

## Important notes

- **Port 465 = implicit SSL.** The connection is TLS-encrypted from the very
  first byte; a plain `SMTP` + `STARTTLS` handshake fails on this port.
  `app/outreach/sender.py` selects `SMTP_SSL` whenever `SMTP_PORT=465` and
  keeps STARTTLS for ports 25 / 587.
- **Do not commit the password.** `.env` is git-ignored; `.env.example` ships
  with an empty `SMTP_PASSWORD=`.
- **Dry-run fallback.** If any of host / username / password is missing, the
  app falls back to the in-memory mock provider — sends are recorded locally
  and reported as success (dry-run), so the whole pipeline works without
  credentials. `GET /outreach/email-status` reports `configured: false` in
  that case.
- **Verify connectivity** with `POST /outreach/email-test` (optionally with
  a `recipient`; defaults to `SMTP_FROM_EMAIL`). It performs a real
  authentication + delivery and returns `{success, provider, configured,
  dry_run, recipient, sent_at, error}` without touching the outreach
  workflow. The password is never exposed by any endpoint.
