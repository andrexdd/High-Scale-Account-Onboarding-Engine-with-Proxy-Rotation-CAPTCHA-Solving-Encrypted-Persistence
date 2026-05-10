# Proxy Management Guide

## Overview

The `ProxyManager` component handles proxy lifecycle including loading, validation, rotation, and health tracking. This guide covers common proxy configurations and troubleshooting.

## Proxy Format

Proxies are loaded from a plaintext file (`proxies.txt`). Supported formats:

### Format 1: IP:Port (HTTP)
```
192.168.1.100:8080
10.0.0.50:3128
203.0.113.45:9090
```

### Format 2: Scheme://IP:Port
```
http://192.168.1.100:8080
https://10.0.0.50:3128
socks5://203.0.113.45:1080
```

### Format 3: Authentication
```
user:password@192.168.1.100:8080
admin:secret123@proxy.company.com:3128
```

### Format 4: Full URL
```
http://user:password@192.168.1.100:8080
https://admin:secret@proxy.example.com:443
```

### Mixed File Example (proxies.txt)
```
# Comment lines are ignored
192.168.1.100:8080
http://10.0.0.50:3128
user:pass@203.0.113.45:9090
socks5://auth:password@proxy.api.com:1080
```

## Creating a Proxy File

### Option 1: Manual Entry
```bash
cat > proxies.txt << EOF
192.168.1.100:8080
10.0.0.50:3128
203.0.113.45:9090
EOF
```

### Option 2: Download from Service
Many proxy providers offer direct download. Examples:

```bash
# ProxyScrape public proxies
curl "https://api.proxyscrape.com/v2/?request=displayproxies&format=textplain&ssl=all" \
  > proxies.txt

# Free-Proxy-List format conversion
curl https://free-proxy-list.net/ 2>/dev/null | grep -oE '\b[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b:[0-9]+' > proxies.txt
```

### Option 3: Premium Provider Integration
Modify `proxy_manager.py` to fetch from your premium provider's API:

```python
# Example: Bright Data API integration
async def fetch_proxies_from_brightdata(api_token):
    url = "https://api.brightdata.com/proxies"
    headers = {"Authorization": f"Bearer {api_token}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            return [ProxyEntry(server=p['ip_port']) for p in data['proxies']]
```

## Proxy Validation

On startup, ProxyManager validates proxies by making HTTP requests to a test URL (default: Instagram). This ensures:

1. **Connectivity**: Proxy is reachable and responsive
2. **Status**: Returns HTTP 2xx-3xx response codes
3. **Speed**: Response completes within timeout (5 seconds default)

Validation behavior:

```python
# Validation happens automatically on load_from_file()
proxy_mgr = await ProxyManager.load_from_file(
    "proxies.txt",
    min_valid_ratio=0.5  # At least 50% must be valid
)

# If validity falls below threshold, proxies are auto-refreshed
# Set min_valid_ratio=1.0 for strict validation (all proxies must be valid)
```

Starting with 100 proxies, ~50 must be valid by default. If not, the system attempts to fetch fresh proxies from ProxyScrape.

## Proxy Rotation

ProxyManager uses **round-robin selection** with **failure tracking**:

```
Availability:
┌─────────────────────────────────────────┐
│ Proxy 1 (fail_count: 0) - HEALTHY      │
│ Proxy 2 (fail_count: 1) - HEALTHY      │
│ Proxy 3 (fail_count: 4) - BLACKLISTED  │ <- Skipped in selection
│ Proxy 4 (fail_count: 0) - HEALTHY      │
└─────────────────────────────────────────┘
Selection: 1 → 2 → 4 → 1 → 2 → 4 → ... (3 is skipped)
```

Configuration:

```python
# Proxy blacklist threshold
PROXY_MAX_FAILURES = 4

# After 4 consecutive failures, proxy is excluded from rotation
# Excluded proxies can be restored once they succeed
```

## Health Tracking

Each proxy tracks consecutive failures. Operations update the status:

```python
# Request succeeds → decrease fail_count (helps recovery)
proxy_mgr.mark_proxy_success(proxy)  # fail_count: 2 → 1

# Request fails → increase fail_count
proxy_mgr.mark_proxy_failed(proxy)   # fail_count: 1 → 2

# Check overall health
stats = proxy_mgr.stats()
# {'total_proxies': 100, 'healthy_proxies': 87}
```

## Auto-Refresh Strategy

When all healthy proxies are exhausted:

```python
# Original: 100 proxies, 50 healthy, 50 blacklisted
# If all 50 healthy fail, system:
#   1. Resets all fail_counts to 0
#   2. Re-adds blacklisted proxies to pool
#   3. Logs warning message

await engine.run(total_jobs=1000)  # May hit full reset if all fail
```

This prevents complete locking but adds recovery time. Optimal setup:

- **50+% of proxies high-quality** (1-3 failures per 1000 requests)
- **Min 20 healthy proxies** to absorb temporary failures  
- **Refresh daily** if using free lists (they degrade over time)

## Premium Proxy Recommendations

For production:

| Provider | Cost | Speed | Geo Coverage | Notes |
|----------|------|-------|--------------|-------|
| Bright Data | $$$ | Fast | Global | Best for Instagram, auth headers, ISP proxies |
| Smartproxy | $$ | Fast | Global | Good rotation, affordable |
| Residential Proxy.io | $$$ | Medium | Global | Real residential IPs |
| Oxylabs | $$$ | Fast | Global | Enterprise-grade, highest success rate |
| Proxy-Seller | $ | Varies | Limited | Budget option, lower reliability |

Most providers offer payment upon success, making them suitable for scaling.

## Troubleshooting

### Issue: "No proxies available after refresh"

```
Error: ValueError: No proxies available after refresh for proxies.txt
```

**Solutions**:
1. Verify proxies.txt exists and contains valid proxy entries
2. Check network connectivity (`ping proxy.example.com`)
3. Reduce validation timeout if proxies are slow:
   ```python
   PROXY_VALIDATION_TIMEOUT = 10  # Increase from 5
   ```
4. Disable strict validation temporarily:
   ```python
   proxy_mgr = await ProxyManager.load_from_file(
       "proxies.txt",
       min_valid_ratio=0.1  # Accept if 10% are valid
   )
   ```

### Issue: Proxies work but requests failing

**Possible causes**:
- **Authentication failure**: Verify credentials in proxy URL
- **IP blocking**: Target site blocking proxy IP ranges
- **Wrong proxy type**: SOCKS5 proxies won't work with HTTP requests

**Check format**:
```python
from high_scale_onboarding.proxy_manager import ProxyManager

proxy = ProxyManager.parse_proxy_line("user:pass@192.168.1.100:8080")
print(proxy.playwight_proxy())
# Output: {'server': 'http://192.168.1.100:8080', 'username': 'user', 'password': 'pass'}
```

### Issue: All proxies marked as failed

**Check logs**:
```python
# Enable debug logging
import logging
logging.getLogger('high_scale_onboarding.proxy_manager').setLevel(logging.DEBUG)

# Look for messages like:
# Proxy http://192.168.1.100:8080 failed (1/4)
# All proxies were marked failed. Resetting failure counts.
```

**Remediate**:
1. Check if target site is blocking proxies temporarily
2. Wait 5-10 minutes before retrying
3. Update proxy list with fresh proxies
4. Lower failure threshold:
   ```bash
   export PROXY_MAX_FAILURES=8
   ```

### Issue: Slow proxy validation on startup

**Optimize**:
```python
# Reduce validation batch size (default: 20)
# Lower memory usage, slower validation
PROXY_VALIDATION_BATCH = 5

# Reduce timeout if network is fast
PROXY_VALIDATION_TIMEOUT = 3  # Default: 5

# Skip validation entirely (NOT recommended for production)
proxy_mgr = ProxyManager([
    ProxyEntry(server="192.168.1.100:8080"),
    ProxyEntry(server="10.0.0.50:3128"),
])
```

## Advanced: Custom Proxy Source

Replace default ProxyScrape with custom source:

```python
# high_scale_onboarding/proxy_manager.py

@classmethod
async def fetch_proxies_from_source(cls, source_url=None):
    # Custom implementation
    def custom_fetch():
        # Connect to internal proxy database
        import redis
        r = redis.Redis(host='proxy-db', port=6379)
        proxies_json = r.get('active_proxies')
        return json.loads(proxies_json)
    
    proxies = custom_fetch()
    return [cls.parse_proxy_line(p) for p in proxies]

# Usage
proxy_mgr = await ProxyManager.load_from_file("proxies.txt")
```

## Best Practices

1. **Rotate proxy sources** weekly to avoid detection
2. **Monitor proxy costs** if using paid services
3. **Keep fail_count low** by using quality proxies
4. **Test proxies externally** before adding to pool:
   ```bash
   curl -x http://proxy:port http://www.instagram.com -I
   ```
5. **Use authentication** when available (harder to detect)
6. **Implement IP rotation** at application level, not proxy level alone
7. **Log failed proxies** for analysis and blocking
