# SQLite WAL 模式要点

## 是什么

- WAL（Write-Ahead Logging）：写操作先追加到 `-wal` 文件，主数据库文件在 checkpoint 时才合并更新；区别于默认的回滚日志模式（`journal_mode=DELETE`）。

## 启用与常用配置

```sql
PRAGMA journal_mode = WAL;          -- WAL 模式对数据库文件持久生效，重连后仍保持
PRAGMA synchronous = NORMAL;        -- WAL 下的推荐档位，兼顾安全与性能
PRAGMA wal_autocheckpoint;          -- 默认 1000 页，自动触发 checkpoint
PRAGMA wal_checkpoint(TRUNCATE);    -- 主动收缩 -wal 文件
```

## 收益

- 读写不互斥：读不阻塞写、写不阻塞读，适合"单写多读"场景。
- 提交更快：只需顺序追加 `-wal`，减少对主库文件的 fsync。
- 崩溃恢复更快：只需处理较短的 WAL 尾部。

## 局限与注意

- 所有访问进程必须在同一台主机：不支持网络文件系统（如 NFS）上的并发访问。
- `-wal` 与 `-shm` 伴生文件需要 checkpoint 维护，长事务会阻碍收缩。
- 仍是单写者：并发写会报 `SQLITE_BUSY`，需配合 `busy_timeout`。
- WAL 模式下不能修改 `page_size`；只读介质上无法使用（读也需要可写的 `-shm`/`-wal`）。

## 选用判断

高并发读、写延迟敏感的本地单机场景选 WAL；嵌入式只读介质、网络盘、多进程跨主机共享数据库文件的场景不适用。
