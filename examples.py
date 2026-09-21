"""Example usage and initialization of Agentic Memory MCP."""
from database import get_db
from memory_store import MemoryStore


def load_example_data():
    """Load example data into memory store."""
    db = get_db()
    store = MemoryStore(db)

    # Example Durable Knowledge (stored as markdown files)
    okf_docs = [
        {
            "title": "Architecture: User Authentication",
            "content": """# User Authentication Architecture

## Overview
JWT-based authentication system using bcrypt for password hashing.

## Key Rules
- Access tokens expire after 1 hour
- Refresh tokens expire after 30 days
- Passwords must be at least 8 characters
- Use salt rounds = 12 for bcrypt

## Endpoints
- POST /auth/register
- POST /auth/login
- POST /auth/refresh
- POST /auth/logout

## Error Codes
- 401: Unauthorized (invalid token)
- 403: Forbidden (expired token)
- 409: Conflict (email already registered)
""",
            "category": "architecture"
        },
        {
            "title": "API Standards: REST Conventions",
            "content": """# REST API Standards

## Naming Conventions
- Use kebab-case for URL paths
- Use camelCase for JSON properties
- Resources are nouns (users, posts, comments)

## HTTP Methods
- GET: Retrieve resource
- POST: Create resource
- PUT: Replace resource
- PATCH: Partial update
- DELETE: Remove resource

## Status Codes
- 200: OK
- 201: Created
- 400: Bad Request
- 401: Unauthorized
- 404: Not Found
- 500: Internal Server Error

## Response Format
```json
{
  "success": true,
  "data": {...},
  "timestamp": "2026-09-13T08:40:00Z"
}
```
""",
            "category": "api"
        }
    ]

    for doc in okf_docs:
        store.store_okf(doc["title"], doc["content"], doc["category"])
        print(f"[STORED] OKF: {doc['title']}")

    # Example Short-Lived Context (stored in DB, expires after 30 days)
    context_notes = [
        {
            "title": "Bug Fix: JWT Token Validation",
            "content": "Fixed issue where expired tokens were not properly rejected. Added explicit check in middleware.",
            "lesson": "Always validate token expiry before processing request"
        },
        {
            "title": "Performance Optimization: Database Indexing",
            "content": "Added indexes on user_id and created_at columns. Query performance improved by 40%.",
            "lesson": "Profile database queries before adding indexes"
        }
    ]

    for note in context_notes:
        store.store_context(note["title"], note["content"], note["lesson"])
        print(f"[STORED] Context: {note['title']}")

    # Example Task Skills (stored as markdown files)
    skills = [
        {
            "name": "Deploy to Production",
            "steps": """# Production Deployment Workflow

## Steps
1. Run full test suite: `npm test`
2. Build release bundle: `npm run build`
3. Tag release: `git tag -a v1.0.0 -m "Release v1.0.0"`
4. Push to repository: `git push origin main --tags`
5. Deploy to production: `npm run deploy:prod`
6. Verify deployment: `curl https://api.example.com/health`
7. Monitor logs for errors: `tail -f /var/log/app.log`

## Rollback (if needed)
1. Identify last stable tag
2. Checkout previous version
3. Deploy previous version
4. Test thoroughly before re-deploying new version
""",
            "tags": "deployment,production,release"
        },
        {
            "name": "Setup Development Environment",
            "steps": """# Local Development Setup

## Prerequisites
- Node.js >= 18.0.0
- npm >= 9.0.0
- SQLite >= 3.35.0

## Steps
1. Clone repository: `git clone <repo-url>`
2. Install dependencies: `npm install`
3. Copy env template: `cp .env.example .env`
4. Initialize database: `npm run db:init`
5. Seed test data: `npm run db:seed`
6. Start development server: `npm run dev`
7. Open browser to http://localhost:3000

## Verify Setup
- Run tests: `npm test`
- Check health endpoint: `curl http://localhost:3000/health`
""",
            "tags": "setup,development,onboarding"
        }
    ]

    for skill in skills:
        store.store_skill(skill["name"], skill["steps"], skill["tags"])
        print(f"[STORED] Skill: {skill['name']}")

    db.close()
    print("\n[DONE] Example data loaded successfully")


if __name__ == "__main__":
    load_example_data()
