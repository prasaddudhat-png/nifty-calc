# 📖 Template: New API Integration

**Date:** {{date}}
**Author:** AI/User

## Purpose
Describe what this new API endpoint does and why it is needed.
*Example: Adding a new endpoint to fetch historical IV data.*

## Endpoints
- `GET /api/v1/iv_data`
- `POST /api/v1/scan`

## Rate Limiting Rules
Describe the specific rate limits from the broker (e.g., Angel One allows 3 requests per second).
- [ ] Has a `time.sleep()` been added?
- [ ] Is it wrapped in the global `api_lock`?

## Related Documents
- [[AI_BRAIN]]
- [[Angel_One_API_Reference]]
