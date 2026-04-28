# 长期记忆

## CRM 项目关键信息

### 导入功能设计要点（2026-04-27 更新）

**负责人未注册导入逻辑**：
- 负责人姓名保存到 `custom_fields.business_owner`（线索）或 `custom_fields.owner_name_display`（商机）
- 如果负责人已注册系统用户，`owner_id` 绑定到该用户
- 如果负责人未注册，`owner_id` 设为 `None`，不替换成当前登录用户
- 审计信息保存：`custom_fields.import_user_id` 和 `custom_fields.import_username`

**前端负责人显示优先级**：
- 线索：`custom.business_owner || item.owner_username || (item.owner && item.owner.username) || '未分配'`
- 商机：`custom.owner_name_display || item.owner_username || (item.owner && item.owner.username) || '未分配'`

**重复表头处理**：
- 新增 `_map_row_by_headers()` 函数支持按列位置顺序映射
- Excel 中多个"初审是否通过"列会依次映射到 first_review_pass, second_review_pass, third_review_pass

### 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `backend/app/services/table_import_service.py` | 更新导入列顺序，新增 `_map_row_by_headers` 函数支持重复表头 |
| `backend/app/api/routes/leads.py` | 添加 `_resolve_owner_id_by_name`，修改导入逻辑支持未注册负责人 |
| `backend/app/api/routes/opportunities.py` | 同上 |
| `backend/app/api/routes/analytics.py` | owner_ranking 优先使用 `custom_fields.owner_name_display` |
| `frontend/page-leads.html` | 负责人显示优先使用 `custom.business_owner` |
| `frontend/page-opportunities.html` | 负责人显示优先使用 `custom.owner_name_display` |
