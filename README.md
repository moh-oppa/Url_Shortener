# URL Shortener with Analytics

A URL shortener with per-link click analytics (country, referrer, daily totals), built with
**FastAPI, PostgreSQL and Redis**.

The aim was to design it the way a real service would be built. A redirect should take a single
Redis lookup. Analytics writes should never slow down a redirect. The stats endpoint should not
slow down as click history grows.

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy 2 (async) + asyncpg · Alembic · Pydantic v2 · Redis 7 (cache and Str
eams) ·
PostgreSQL 16 · GeoIP2 · Docker Compose · pytest · Ruff · GitHub Actions

## Roadmap

- [ ] Per-IP rate limiting on link creation (settings and error type exist, but it isn't enforced yet)
- [ ] Frontend dashboard for stats
- [ ] Load test of the redirect path (e.g. with k6) and results published here
- [ ] Public deployment
