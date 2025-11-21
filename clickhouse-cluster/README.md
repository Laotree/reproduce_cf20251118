# Build a ClickHouse Distributed Cluster

```bash
docker-compose -f clickhouse-cluster/docker-compose.yml up -d
```

Expected result:
> clickhouse-node3
> clickhouse-node2
> clickhouse-node1
> zookeeper

## Verify Cluster Creation

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "SELECT cluster,shard_num,host_name FROM system.clusters WHERE cluster='cluster_3shards_1replicas'"
```

Expected result:
> cluster_3shards_1replicas       1       clickhouse-node1
> cluster_3shards_1replicas       2       clickhouse-node2
> cluster_3shards_1replicas       3       clickhouse-node3

# Create Database

## Create r0 Database

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "CREATE DATABASE IF NOT EXISTS r0 ON CLUSTER cluster_3shards_1replicas"
```

## Create Local Table

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "CREATE TABLE r0.http_requests_features ON CLUSTER cluster_3shards_1replicas
(
    event_date Date,
    request_id UInt64,
    feature_1  String,
    feature_2  Float64
)
ENGINE = MergeTree()
ORDER BY request_id"
```

## Create Distributed Table

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "CREATE TABLE default.http_requests_features ON CLUSTER cluster_3shards_1replicas
(
    event_date Date,
    request_id UInt64,
    feature_1  String,
    feature_2  Float64
)
ENGINE = Distributed(
    'cluster_3shards_1replicas',
    r0,                   
    http_requests_features,      
    rand()   
)"
```

## Create Test User and Grant Implicit Permission (Before Change)

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "CREATE USER test_user IDENTIFIED WITH plaintext_password BY 'test';"

docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "GRANT SELECT ON default.http_requests_features TO test_user;"
```

## Open Another Terminal and Query with Test User

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 --user test_user --password test -q "SELECT name, type FROM system.columns WHERE table = 'http_requests_features' ORDER BY name"
```

Expected result:
> event_date      Date  
> feature_1       String  
> feature_2       Float64  
> request_id      UInt64  

## Explicit Permission (ROOT CAUSE)

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "GRANT SELECT ON r0.* TO test_user"
```

## Open Another Terminal and Query with Test User

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 --user test_user --password test -q "SELECT name, type FROM system.columns WHERE table = 'http_requests_features' ORDER BY name"
```

Expected result:
> event_date      Date  
> event_date      Date  
> feature_1       String  
> feature_1       String  
> feature_2       Float64  
> feature_2       Float64  
> request_id      UInt64  
> request_id      UInt64


## Revoke Permission

```bash
docker exec -it clickhouse-node1 clickhouse client -h 127.0.0.1 --port 9000 -q "REVOKE SELECT ON r0.* TO test_user"
```