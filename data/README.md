# 运行数据目录

此目录只存放 Web 注册服务产生的本地数据，不存放前端或后端源码。

- `accounts/`：账号文件、邮箱凭证、SSO 待处理文件和 SQLite 结果库。
- `cpa_auth/`：CPA 授权 JSON。
- `grok2api_auth/`：Grok2API 授权 JSON。
- `web_auth.json`：Web 唯一管理员的哈希认证信息。
- `.next_action_id.cache`：授权流程的本地运行缓存。
- `browser-cache/`：低流量模式缓存的 grok.com / accounts.x.ai 静态资源。
- 其他子目录：历史备份或运行缓存。

除本说明文件外，`data/` 内容均已由 `.gitignore` 忽略。
