# High-Scale Onboarding Engine

A robust, production-ready Python application for automated account onboarding workflows with proxy management, CAPTCHA solving, and encrypted data persistence.

## Overview

This project implements an asynchronous onboarding engine designed to handle large-scale account creation scenarios. It features:

- **Concurrent Account Registration**: Process multiple account creations simultaneously using asyncio
- **Proxy Rotation**: Intelligent proxy management with automatic validation and failure tracking
- **CAPTCHA Integration**: Support for multiple CAPTCHA solving services (2captcha, Anti-Captcha)
- **Encrypted Storage**: SQLite-backed persistence with Fernet encryption for sensitive data
- **Browser Automation**: Playwright-based form filling and interaction

## Architecture

```
high_scale_onboarding/
├── config.py           # Configuration management with environment variables
├── engine.py           # Core onboarding orchestration logic
├── proxy_manager.py    # Proxy pool management and validation
├── captcha_solver.py   # CAPTCHA solving service integration
├── persistence.py      # Encrypted database operations
└── __init__.py         # Package exports
```

### Component Breakdown

**Engine** (`engine.py`)
- Manages concurrent job scheduling with semaphores
- Orchestrates browser navigation and form submission
- Coordinates proxy and CAPTCHA interactions
- Tracks completion statistics

**ProxyManager** (`proxy_manager.py`)
- Loads and validates proxy lists from files or remote sources
- Implements round-robin proxy selection
- Tracks proxy health with configurable failure thresholds
- Auto-refreshes proxies when validity drops below threshold

**CaptchaSolver** (`captcha_solver.py`)
- Supports multiple solving providers (2captcha, Anti-Captcha)
- Fallback mock solver for testing
- Async polling with configurable timeout
- Error recovery with detailed logging

**PersistenceStore** (`persistence.py`)
- SQLite database for structured data storage
- Fernet-based encryption for all sensitive records
- Automatic table schema creation
- Atomic record operations

**Configuration** (`config.py`)
- Environment-based settings (12+ parameters)
- Type-safe path handling with pathlib
- Sensible defaults for all settings

## Installation

### Prerequisites
- Python 3.9+
- pip or conda package manager

### Setup

1. Clone or extract the project:
```bash
cd folder
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

4. Create a proxies file (if using proxies):
```bash
# proxies.txt format: one proxy per line
# Examples:
# 192.168.1.1:8080
# user:pass@proxy.example.com:3128
# http://10.0.0.1:9090
```

## Configuration

Configure behavior via environment variables. Common settings:

```bash
# CAPTCHA Service
export CAPTCHA_PROVIDER=2captcha      # Options: 2captcha, anti-captcha, sandbox
export CAPTCHA_API_KEY=your_api_key

# Concurrency Settings
export MAX_CONCURRENT_TASKS=10        # Parallel browser instances
export TOTAL_SIMULATION_JOBS=100      # Total accounts to create

# Proxy Configuration
export USE_PROXY=True                 # Enable/disable proxy usage
export PROXY_MAX_FAILURES=4           # Failures before proxy blacklist
export REQUEST_TIMEOUT_SECONDS=60

# Target Configuration
export ONBOARDING_TARGET_URL=https://www.instagram.com/accounts/emailsignup/
export SITE_VERIFY_URL=https://www.instagram.com

# Encryption
export FERNET_KEY=optional_key_string
```

Or create a `.env` file and load with python-dotenv:

```bash
pip install python-dotenv
```

```python
from dotenv import load_dotenv
load_dotenv()
```

## Usage

### Basic Execution

Run the main simulation:

```bash
python run_simulation.py
```

This will:
1. Initialize encryption key (auto-generated if missing)
2. Load and validate proxy list
3. Launch the onboarding engine
4. Create accounts with configured concurrency
5. Save results to encrypted database
6. Display sample records

### Advanced Usage

```python
import asyncio
from high_scale_onboarding import (
    OnboardingEngine,
    ProxyManager,
    CaptchaSolver,
    PersistenceStore,
)

async def custom_workflow():
    # Load proxies
    proxy_mgr = await ProxyManager.load_from_file("proxies.txt")
    
    # Initialize CAPTCHA solver
    captcha = CaptchaSolver(
        api_key="your_api_key",
        provider="2captcha",
        timeout=120
    )
    
    # Setup database
    encryption_key = PersistenceStore.generate_key()
    db = PersistenceStore.from_config("database.db", encryption_key.decode())
    
    # Create engine
    engine = OnboardingEngine(
        proxy_manager=proxy_mgr,
        captcha_solver=captcha,
        persistence=db,
        max_concurrent=20,
        request_timeout=60
    )
    
    # Run jobs
    await engine.run(total_jobs=50)
    
    # Retrieve results
    records = db.load_records(limit=5)
    for rec in records:
        print(f"User: {rec['user_id']}, Created: {rec['created_at']}")

# Execute
asyncio.run(custom_workflow())
```

## Logging

Logging is configured to INFO level by default. Adjust in `run_simulation.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for verbose output
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
```

Log output includes:
- Job progress and completion
- Proxy selection and failure events
- CAPTCHA submission and polling
- Database operations
- Browser navigation events

## Data Persistence

Results are encrypted using Fernet (AES-128) and stored in SQLite:

```
onboarding_results table:
├── id                    (Primary Key)
├── user_id              (Account username)
├── created_at           (ISO 8601 timestamp)
└── encrypted_payload    (Fernet-encrypted JSON)
```

Access stored records:

```python
from high_scale_onboarding import PersistenceStore

db = PersistenceStore.from_config("onboarding_results.db", "your_encryption_key")
records = db.load_records(limit=100)
for record in records:
    print(record['payload'])
```

## Error Handling

The engine implements resilient error handling:

- **Proxy Failures**: Tracks failures per proxy, automatically rotates when threshold exceeded
- **Browser Crashes**: Catches exceptions and marks job as failed with detailed logging
- **CAPTCHA Timeouts**: Retries with exponential backoff (configurable timeout)
- **Network Issues**: Async operations with timeouts prevent hanging

Failed jobs are logged but don't stop the engine; it continues with remaining jobs.

## Performance Tuning

For optimal performance:

1. **Concurrency**: Start at 10, increase in increments of 5 while monitoring resource usage
2. **Proxy Quality**: Use only high-uptime proxies; use validation to filter at startup
3. **CAPTCHA Service**: Choose provider based on accuracy/cost trade-off
4. **Timeouts**: Increase for slower networks; decrease for faster ones

```bash
# Example: 50 concurrent jobs with refined settings
export MAX_CONCURRENT_TASKS=50
export REQUEST_TIMEOUT_SECONDS=120
export PROXY_MAX_FAILURES=3
python run_simulation.py
```

## Troubleshooting

### Issue: ImportError for playwright
**Solution**: Install Playwright and browsers
```bash
pip install -r requirements.txt
playwright install chromium
```

### Issue: All proxies failing
**Solution**: Check proxy format and network connectivity
```bash
# Test a single proxy
curl -x http://proxy:port http://www.instagram.com
```

### Issue: CAPTCHA solver timeout
**Solution**: Increase timeout and verify API key
```bash
export CAPTCHA_API_KEY=valid_key
export REQUEST_TIMEOUT_SECONDS=180
```

### Issue: Database locked
**Solution**: Ensure no other processes access the database; consider using WAL mode
```python
self._conn.execute("PRAGMA journal_mode=WAL")
```

## Security Considerations

- **Encryption Key**: Store encryption keys securely; never commit to version control
- **API Credentials**: Use environment variables; never hardcode sensitive values
- **Proxy Credentials**: Supported via authentication in proxy URLs
- **Database Access**: Use file permissions to restrict database access

## Requirements

See `requirements.txt`:
```
aiohttp>=3.8          # Async HTTP client for proxy validation
cryptography>=41.0    # Fernet encryption
playwright>=1.44      # Browser automation
pydantic>=2.0         # Data validation (optional, for custom extensions)
```

## Testing

For local testing without external services:

```bash
export CAPTCHA_PROVIDER=sandbox       # Uses mock solver
export USE_PROXY=False                # Disables proxy usage
export TOTAL_SIMULATION_JOBS=2        # Small test run
python run_simulation.py
```

## Contributing

Contributions welcome. Follow PEP 8 style guide and include type hints.

## License

Proprietary - All rights reserved

## Support

For issues or questions, review logs and verify:
1. Python version (3.9+)
2. All dependencies installed
3. Environment variables configured
4. Proxy list format correct
5. Network connectivity to target site
