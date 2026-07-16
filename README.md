<p align="center">
  <img src="logo.png" width="300" alt="PocketVectorDB Logo"/>
</p>

   # PocketVectorDB  

A lightweight, fast, offline-ready vector database for Python and mobile/edge environments

PocketVectorDB is a complete vector database solution for:

- **Local development**: Offline AI agents, Termux (Android), edge devices
- **Production deployments**: Tier-based pricing, REST API, cloud backups
- **Small to medium businesses**: Complete monetization system with Stripe integration
- **Individual developers**: Simple local storage + optional cloud features

Built for simplicity and speed, PocketVectorDB provides:
- SQLite backend with unlimited storage (no RAM limits)
- REST API for remote queries
- User authentication and API key management
- Monthly billing with tier enforcement
- Admin dashboard for platform monitoring
- Complete deployment guides (Docker, Heroku, AWS)

======================================================================
#  🚀 Features
======================================================================

- Ultra-lightweight: no server, no heavy frameworks  
- Fast cosine similarity search via optimized matrix operations  
- Persistent storage using `embeddings.npy` and `metadata.json`  
- Batch insert operations  
- Metadata filtering (`where={...}`)  
- Full CRUD operations  
- Zero external dependencies except NumPy (local version)
- Works on Termux, Linux, macOS, and Windows  
- Perfect for small AI agents and local LLM memory
- **NEW**: Production-ready with cloud features:
  - SQLite backend for unlimited storage
  - REST API with rate limiting
  - User authentication and tier management
  - Stripe payment integration
  - Complete admin dashboard
  - Email notifications
  - Docker deployment ready

======================================================================
# 📦 Installation
======================================================================

### Python  
```bash
pip install pocketvectordb
```

### Termux  
Install from a local wheel:
```bash
pip install pocketvectordb-1.0.0-py3-none-any.whl
```

======================================================================
# 🚀 Production Deployment
======================================================================

### Local + Cloud Hybrid

Start locally, scale to production:

**Local Development (Free)**
```bash
pip install pocketvectordb
# Use locally with zero dependencies
```

**Production with Cloud Features ($2.99-$29.99/month)**
```bash
# Deploy with Docker
docker-compose up -d

# All services start automatically:
# - API Server (http://localhost:5000)
# - User Dashboard (http://localhost:5001)
# - Admin Panel (http://localhost:5002)
```

### Three-Service Architecture

1. **API Server** - Vector database queries and management
   - Rate limiting per tier
   - Usage tracking
   - Authentication with API keys

2. **User Dashboard** - Customer portal
   - Account management
   - Subscription upgrades
   - Usage monitoring
   - Invoice history

3. **Admin Panel** - Business metrics
   - Revenue tracking (MRR, ARR)
   - User growth analytics
   - Cohort analysis
   - Churn monitoring

### Deployment Options

- **Local**: `python app.py`
- **Docker**: `docker-compose up -d`
- **Heroku**: `git push heroku main`
- **AWS EC2**: See DEPLOYMENT.md

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete setup guides.

### Tier System

| Feature | Free | Pro | Team |
|---------|------|-----|------|
| **Price** | Free | $9.99/mo | $29.99/mo |
| **Storage** | 500 MB | 10 GB | Unlimited |
| **Queries/mo** | 100K | 10M | 1B |
| **Documents** | 10K | 1M | 100M |
| **API Access** | ❌ | ✅ | ✅ |
| **Support** | Community | Email (24h) | Priority (1h) |

======================================================================
# 🧠 Quick Start
======================================================================

```python
from pocketvectordb import VectorDB
import numpy as np

db = VectorDB("./my_vectordb", dimension=384)

embedding = np.random.randn(384).astype(np.float32)

doc_id = db.add(
    embedding,
    text="Hello world!",
    metadata={"tag": "greeting"}
)

query = np.random.randn(384).astype(np.float32)
results = db.query(query, n_results=3)

print(results["documents"])
```

======================================================================
# 🔍 Similarity Search
======================================================================

```python
results = db.query(query_embedding, n_results=5)
```

Returns:  
- `ids`  
- `documents`  
- `distances`  
- `metadatas`

======================================================================
# 🗂️ Metadata Filtering
======================================================================

```python
results = db.query(
    query_embedding,
    n_results=3,
    where={"category": "science"}
)
```

======================================================================
#  ✏️ Updating Documents
======================================================================

```python
db.update(
    doc_id,
    text="Updated content",
    metadata={"updated": True}
)
```

======================================================================
#  🗑️ Delete Matching Documents
======================================================================

```python
deleted_count = db.delete(where={"category": "tech"})
```

======================================================================
#  💾 Persistence
======================================================================

Every write updates:

- `embeddings.npy`  
- `metadata.json`  

Reloading is automatic:

```python
db = VectorDB("./my_vectordb")
print(db.count())
```

========================================================================
#   📊 Performance
========================================================================

Benchmarks on Android (Termux):

| Documents | Insert Time | Query Time |
|----------|-------------|------------|
| 100      | 0.017s      | 0.14 ms    |
| 500      | 0.39s       | 0.31 ms    |
| 1000     | 1.56s       | 0.53 ms    |

PocketVectorDB is optimized for fast local lookups without GPU or FAISS.


========================================================================
#  🛠️ Why PocketVectorDB?
========================================================================

Most vector databases are:  
- too heavy  
- server-based  
- cloud-locked  
- not optimized for mobile  
- overkill for small agents  

PocketVectorDB is a pure-Python, offline-first, minimalist vector engine.

Perfect for:  
- LLM memory systems  
- Personal agents  
- Offline chatbots  
- IoT classification  
- Fast lookup systems  
- Mobile AI experiments  
- Students & researchers  


========================================================================
#   📚 Documentation
========================================================================

- **[Quick Start](README.md#-quick-start)** - Local usage basics
- **[API Reference](api_server.py)** - REST API endpoints
- **[Deployment Guide](DEPLOYMENT.md)** - Production setup
- **[Configuration](DEPLOYMENT.md#configuration)** - Environment variables
- **[Billing System](billing.py)** - Subscription and pricing

### API Endpoints

**Authentication**
- `POST /api/v1/auth/generate-key` - Create API key
- `POST /api/auth/login` - Dashboard login

**Queries**
- `POST /api/v1/query` - Search vectors
- `POST /api/v1/add` - Add documents
- `GET /api/v1/stats` - Database statistics

**Dashboard**
- `GET /dashboard` - User dashboard
- `GET /api/dashboard/summary` - Billing summary
- `POST /api/auth/logout` - Logout

**Admin**
- `GET /admin` - Admin panel
- `GET /api/admin/stats` - Platform statistics
- `GET /api/admin/forecast` - Revenue forecast
- `GET /api/admin/cohorts` - Cohort analysis

### Examples

**Using the REST API**
```bash
# Get API key
curl -X POST http://localhost:5000/api/v1/auth/generate-key \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_123", "tier": "pro"}'

# Query database
curl -X POST http://localhost:5000/api/v1/query \
  -H "X-API-Key: pk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "database_id": "db_123",
    "embedding": [0.1, 0.2, ...],
    "n_results": 5
  }'

# Add document
curl -X POST http://localhost:5000/api/v1/add \
  -H "X-API-Key: pk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "database_id": "db_123",
    "embedding": [0.1, 0.2, ...],
    "text": "Hello world",
    "metadata": {"category": "greeting"}
  }'
```

**Using Python Client**
```python
import requests

api_key = "pk_..."
response = requests.post(
    "http://localhost:5000/api/v1/query",
    headers={"X-API-Key": api_key},
    json={
        "database_id": "db_123",
        "embedding": embedding.tolist(),
        "n_results": 5
    }
)

results = response.json()
print(results["results"]["documents"])
```

========================================================================
#   💰 Monetization
========================================================================

Complete billing system included:

- **Stripe Integration**: Full payment processing
- **Tier Enforcement**: Limits enforced at database level
- **Usage Tracking**: Automatic query and storage counting
- **Prorated Upgrades**: Fair billing for mid-cycle changes
- **Invoice Generation**: Professional invoices with due dates
- **Email Notifications**: Alerts for quota warnings

Revenue Projection (with 500+ users):
- **MRR**: $5K-$10K
- **ARR**: $60K-$120K
- **Margin**: 90%+ (storage costs minimal)

See [MONETIZATION_STRATEGY.md](MONETIZATION_STRATEGY.md) for complete plan.

========================================================================
#   🔒 Security
========================================================================

- API keys with per-tier rate limiting
- HTTPS/TLS support
- Password hashing (PBKDF2)
- Session management with httponly cookies
- SQL injection protection (parameterized queries)
- CSRF protection
- Tier-based access control

### Production Security Checklist

- [ ] Enable HTTPS/TLS certificates
- [ ] Set strong session secret keys
- [ ] Configure CORS properly
- [ ] Enable rate limiting
- [ ] Set up firewall rules
- [ ] Monitor for suspicious API usage
- [ ] Regular security audits
- [ ] Backup encryption enabled

========================================================================
#   🧪 Testing
========================================================================

Run tests:
```bash
python -m pytest test_pocketvectordb.py -v
```

Performance benchmarks:
```bash
python pocketvectordb.py --benchmark
```

Database migration test:
```bash
python migrations.py test_old_database/ test_new_database/
```

========================================================================
#   🤝 Contributing
========================================================================

Contributions welcome! Areas for improvement:

- Hybrid local/cloud sync
- PostgreSQL backend option
- GraphQL API
- WebSocket support for real-time queries
- Advanced analytics features
- Mobile SDKs (iOS/Android)
- Performance optimizations
- Documentation improvements

See issues on GitHub for current priorities.

========================================================================
#   📄 License
========================================================================

MIT License - See LICENSE file

========================================================================
#   ❤️ Author
========================================================================

Built by ThatFkrDurk561

PocketVectorDB is designed for developers who want:
- ✅ Speed without compromise
- ✅ Simplicity without complexity
- ✅ Monetization without friction
- ✅ Scalability without cloud lock-in

Questions? Issues? Ideas?
- 📧 support@pocketvectordb.com
- 🐛 GitHub Issues
- 💬 Discussions
