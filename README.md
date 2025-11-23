# Attempt to reproduce the Cloudflare 2025-11-18 outage.

reference [Cloudflare outage on November 18, 2025](https://blog.cloudflare.com/18-november-2025-outage/)

## Prerequisites
- docker and docker-compose
```bash my env
docker --version
Docker version 28.3.3, build 980b856

docker-compose --version
Docker Compose version 2.40.3
```
- network
```bash 
docker network create -d bridge cf-20251118
```
## Implementation plan
1. [Simulate running a ClickHouse cluster storing feature sets](clickhouse-cluster/README.md)
2. [Simulate KV workers that distribute configuration](kv-workers/README.md)
3. [Simulate proxy engines with and without using feature sets](proxy-engines/README.md)
4. [Simulate the analytics service returning 500 statuses as the failure evolves](customer-visits/README.md)