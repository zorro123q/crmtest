# 数据库清空操作文档

适用项目：`SalesPilot CRM`

适用目标：
- 清空会干扰登录、注册、仪表盘统计的旧业务数据
- 保留表结构
- 保留必要基础表
- 重建默认管理员账号 `admin / 123456`
- 当前版本要求 `users.password` 明文存储，不做加密

## 1. 会执行什么

本次清理会执行以下 SQL 脚本：

1. [01_reset_business_data.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/01_reset_business_data.sql)
2. [02_seed_default_admin.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/02_seed_default_admin.sql)
3. [03_optional_schema_patch.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/03_optional_schema_patch.sql)
4. [04_reset_users_plaintext.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/04_reset_users_plaintext.sql)

其中：

- `01_reset_business_data.sql`
  - 清空 `activities`
  - 清空 `opportunities`
  - 清空 `leads`
  - 清空 `contacts`
  - 清空 `accounts`
  - 清空旧演示/遗留统计表：
    - `customer_internal_info`
    - `opportunity_funnel`
    - `performance_overview`
  - 删除除 `admin` 之外的所有用户

- `02_seed_default_admin.sql`
  - 重新写入或覆盖默认管理员账号
  - 默认账号：
    - 用户名：`admin`
    - 密码：`123456`
  - `users.password` 直接写入明文 `123456`

- `03_optional_schema_patch.sql`
  - 当前版本只是占位说明
  - 现在不需要额外改表

- `04_reset_users_plaintext.sql`
  - 只重置 `users` 表
  - 会先把 `accounts / contacts / leads / opportunities / activities` 中的 `owner_id` 置空
  - 然后清空 `users`
  - 最后重建明文管理员账号 `admin / 123456`

## 2. 不会执行什么

本次操作不会：

- 不会 `DROP TABLE`
- 不会删除表结构
- 不会删除 `metadata_fields`
- 不会删除配置类基础表，例如：
  - `dict_items`
  - `grade_config`
  - `products`
  - `score_dimensions`
  - `score_weights`

## 3. 执行前准备

先确认数据库连接配置在 [backend/.env](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/.env) 中可用。

当前项目本地配置指向：

```env
DATABASE_SYNC_URL=mysql+pymysql://salespilot:***@127.0.0.1:3306/salespilot_db
```

建议执行前先备份：

```powershell
mysqldump -h 127.0.0.1 -P 3306 -u salespilot -p salespilot_db > backup_before_reset.sql
```

## 4. 执行方式

### 方式 A：使用 MySQL 命令行

进入项目根目录后，按顺序执行：

```powershell
Get-Content backend/sql/01_reset_business_data.sql | mysql -h 127.0.0.1 -P 3306 -u salespilot -p salespilot_db
Get-Content backend/sql/02_seed_default_admin.sql | mysql -h 127.0.0.1 -P 3306 -u salespilot -p salespilot_db
Get-Content backend/sql/03_optional_schema_patch.sql | mysql -h 127.0.0.1 -P 3306 -u salespilot -p salespilot_db
```

说明：

- 每条命令执行时会提示输入数据库密码
- 必须按顺序执行

### 方式 B：使用 Navicat / DBeaver / DataGrip

执行顺序同上：

1. 打开 [01_reset_business_data.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/01_reset_business_data.sql) 并执行
2. 打开 [02_seed_default_admin.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/02_seed_default_admin.sql) 并执行
3. 打开 [03_optional_schema_patch.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/03_optional_schema_patch.sql) 并执行

如果你只想重置 `users` 表，不清空其他业务数据，可单独执行：

1. 打开 [04_reset_users_plaintext.sql](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/sql/04_reset_users_plaintext.sql) 并执行

PowerShell 命令行写法：

```powershell
Get-Content backend/sql/04_reset_users_plaintext.sql | mysql -h 127.0.0.1 -P 3306 -u salespilot -p salespilot_db
```

## 5. 执行后校验

执行完成后，建议立即跑下面的校验 SQL：

```sql
SELECT COUNT(*) AS users_count FROM users;
SELECT username, password FROM users;

SELECT COUNT(*) AS accounts_count FROM accounts;
SELECT COUNT(*) AS contacts_count FROM contacts;
SELECT COUNT(*) AS leads_count FROM leads;
SELECT COUNT(*) AS opportunities_count FROM opportunities;
SELECT COUNT(*) AS activities_count FROM activities;

SELECT COUNT(*) AS customer_internal_info_count FROM customer_internal_info;
SELECT COUNT(*) AS opportunity_funnel_count FROM opportunity_funnel;
SELECT COUNT(*) AS performance_overview_count FROM performance_overview;
```

期望结果：

- `users` 只剩 1 条
- 用户名只剩 `admin`
- `password` 直接是明文 `123456`
- `accounts / contacts / leads / opportunities / activities` 全部为 `0`
- 三张旧统计表也为 `0`

再检查管理员账号：

```sql
SELECT id, username, password, created_at, updated_at
FROM users
WHERE username = 'admin';
```

期望结果：

- 能查到 `admin`
- `password = '123456'`

## 6. 登录验证

执行完 SQL 后：

1. 重启后端服务
2. 打开 [frontend/login.html](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/frontend/login.html)
3. 使用以下账号登录：

```text
username: admin
password: 123456
```

如果登录成功，说明：

- `users` 表已经切到明文密码模式
- 默认管理员账号可正常使用

## 7. 重置后的预期现象

重置后系统表现应为：

- `admin` 可以登录
- 新注册用户可以立即登录
- 管理员新增用户后，新用户可以立即登录
- 用户管理页初始只有 `admin`
- 仪表盘和漏斗页不再显示旧演示脏数据
- 因为业务数据被清空，统计页会显示 `0` 或空状态，直到录入新的 `leads` / `opportunities`

## 8. 如果执行失败

优先检查：

1. MySQL 服务是否启动
2. [backend/.env](/c:/Users/Administrator/Desktop/4月重点开发/V1/V3/backend/.env) 中数据库连接是否正确
3. 当前数据库是否就是 `salespilot_db`
4. 执行用户是否有 `DELETE` / `INSERT` 权限

如果需要回滚，使用备份文件：

```powershell
Get-Content backup_before_reset.sql | mysql -h 127.0.0.1 -P 3306 -u salespilot -p salespilot_db
```
