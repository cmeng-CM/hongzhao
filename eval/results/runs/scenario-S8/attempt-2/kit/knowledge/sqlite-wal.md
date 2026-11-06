# SQLite 的 WAL 模式要点

## 是什么

- WAL（Write-Ahead Logging）是 SQLite 的日志模式之一，通过 `PRAGMA journal_mode=WAL;` 开启。
- 开启后写操作不再写回主库文件，而是追加到旁路文件 `<db>-wal`；读取仍走主库 + WAL 中未合并页。
- WAL 是数据库级持久属性，写入数据库文件头，重启连接后依然生效（不必每次设置）。

## 核心收益

- 读写并发：读事务与写事务不再互相阻塞（rollback journal 模式下写会锁读）。
- 顺序写为主：写操作多为 WAL 文件追加，减少随机 I/O，大批量写入通常更快。
- 快照隔离：每个读事务看到打开时刻的一致性快照。

## 仍然成立的限制

- 同一时刻仍只有一个写者；写-写冲突依旧存在，需配合 `busy_timeout` 处理 `SQLITE_BUSY`。
- 所有访问进程必须位于同一主机（依赖 `-shm` 共享内存），网络文件系统（NFS/SMB）上不可用。
- 内存库、临时库不能使用 WAL。
- WAL 模式下不能直接改 `page_size`（需先切回其他 journal 模式或 VACUUM）。
- 纯读场景可能略慢：查询需要同时查主库与 WAL 索引。

## Checkpoint

- checkpoint 把 WAL 内容合并回主库；触发方式：自动（`wal_autocheckpoint`，默认 1000 页）、`PRAGMA wal_checkpoint(TRUNCATE|RESTART|FULL|PASSIVE)`、最后一个连接关闭时。
- 长连接 + 大 WAL 文件是常见问题来源，应关注 checkpoint 策略与 WAL 体积。

## 实践建议

- 开启 WAL 时同时设置 `PRAGMA busy_timeout`（如 5000ms），缓解并发写竞争。
- 评估是否需要调 `wal_autocheckpoint`，或在低峰期手动 `wal_checkpoint(TRUNCATE)`。
- 不要把 `-wal` / `-shm` 文件当作可随意搬动的独立文件，脱离主库无意义。
