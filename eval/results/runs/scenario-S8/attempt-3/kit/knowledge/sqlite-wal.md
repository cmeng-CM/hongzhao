# SQLite 的 WAL 模式要点

## 机制概述

- 以 `PRAGMA journal_mode=WAL;` 开启；写操作追加到旁路文件 `<db>-wal`，读取走主库加 WAL 中未合并页。
- WAL 是数据库文件的持久属性（记在文件头），连接重开后无需重复设置。

## 主要收益

- 读写不互斥：读事务与写事务可并发执行（传统 rollback journal 下写锁会挡住读）。
- 写入以 WAL 追加为主，随机 I/O 少，批量写入一般更快。
- 读事务获得快照隔离，各自看到打开时的一致性视图。

## 边界与限制

- 仍是单写者模型：并发写会撞 `SQLITE_BUSY`，需要设置 `PRAGMA busy_timeout` 兜底。
- 依赖 `-shm` 共享内存，所有访问进程必须在同一主机；NFS 等网络文件系统上不可用。
- 内存库、临时数据库不支持 WAL。
- WAL 模式下无法直接修改 `page_size`。
- 纯读负载可能略慢（需同时检索主库与 WAL 索引）。

## Checkpoint 要点

- checkpoint 将 WAL 合并回主库：自动触发（`wal_autocheckpoint`，默认 1000 页）、手动 `PRAGMA wal_checkpoint(PASSIVE|FULL|RESTART|TRUNCATE)`、最后一个连接关闭时。
- 长驻连接导致 WAL 膨胀是常见故障来源，需规划 checkpoint 策略。

## 实践建议

- 开 WAL 同时设 `busy_timeout`（例如 5000ms）。
- 按负载调整 `wal_autocheckpoint` 或低峰期手动 TRUNCATE。
- 备份、搬库时以主库为准，`-wal`/`-shm` 不能单独使用。
