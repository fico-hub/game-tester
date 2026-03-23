# CLI SLG — Bug 纪要与修复建议

**测试日期**: 2026-03-23
**测试员**: bug_hunter_001 / bug_hunter_002
**服务器**: https://clislg.filo.ai (Season s1_foundation, Turn ~2800)
**测试范围**: 10 轮巡检，覆盖注册登录、边界值、竞态、权限、漏洞模式

---

## 汇总

| 严重等级 | 数量 |
|---------|------|
| 🔴 Critical | 3 |
| 🟠 High | 3 |
| 🟡 Medium | 3 |
| 🔵 Low | 2 |
| **合计** | **11** |

---

## 🔴 Critical

### BUG-001: 征兵接受浮点数，产生非整数兵力

- **端点**: `army.conscript`
- **复现**:
  ```json
  {"type":"army.conscript","payload":{"armyId":"...","slot":0,"unitType":"infantry","count":1.5}}
  ```
- **现象**: 服务器返回 `accepted: true`，军队实际产生 1.5 个步兵，morale 也变成 1.5
- **验证**: `count: 0.001` 同样被接受，军队出现 51.501 兵力
- **影响**:
  - 战斗计算可能出现精度问题
  - 玩家可以用极小浮点数（如 0.001）无限试探征兵，几乎不消耗资源
  - 可能导致战斗系统中的除法/取整异常
- **修复建议**:
  ```javascript
  // 在命令验证层添加整数检查
  if (!Number.isInteger(payload.count) || payload.count < 1) {
    return reject('征兵数量必须为正整数');
  }
  ```

### BUG-002: Spectate/Leaderboard 完整暴露所有玩家数据

- **端点**: `GET /api/v3/spectate`, `GET /api/leaderboard`
- **无需认证**即可获取所有 26 名玩家的：
  - 精确资源数量（grain, wood, iron, gold）
  - 城市坐标（q, r, s）
  - 将领名称、品质、等级、兵力
  - 军队状态、行军路径
  - 击杀/阵亡统计
- **影响**: 这是完美的战场情报——攻击者可以精确知道谁最弱、谁的城在哪、谁的军队正在外面行军
- **修复建议**:
  - 方案 A（推荐）: Spectate 只暴露聚合数据（总玩家数、排行榜分数），不暴露精确资源和坐标
  - 方案 B: Spectate 需要认证，且只显示地图可见范围内的信息
  - 方案 C: 至少隐藏精确资源值和军队行军路径

### BUG-003: 空密码可以注册账号

- **端点**: `POST /api/v3/auth/register`
- **复现**: `{"username":"test_empty_pass","password":""}`
- **现象**: 注册成功，返回 token
- **影响**: 用户可能误设空密码，账号安全性为零
- **修复建议**:
  ```javascript
  if (!password || password.length < 6) {
    return error('密码长度至少 6 位');
  }
  ```

---

## 🟠 High

### BUG-004: 未知命令类型被接受（含 SQL 注入字符串）

- **端点**: `POST /api/v3/commands`
- **复现**:
  ```json
  {"type":"city.build; DROP TABLE players;--","payload":{}}
  ```
- **现象**: 返回 `accepted: true, status: completed, result: {ok: true}`
- **影响**:
  - 命令路由没有白名单校验，任意字符串都进入处理队列
  - 虽然 SQL 注入可能不直接生效（取决于后端实现），但这表明输入验证不足
  - 可能被用于 DoS（大量无效命令堆积队列）
- **修复建议**:
  ```javascript
  const VALID_COMMANDS = ['season.join', 'city.build', 'city.upgrade', 'army.create', ...];
  if (!VALID_COMMANDS.includes(payload.type)) {
    return reject(`未知命令: ${payload.type}`);
  }
  ```

### BUG-005: IDOR — army.disband 提交层未校验所有权

- **端点**: `army.disband`
- **复现**: Player B 用自己的 token，对 Player A 的 armyId 执行 disband
- **现象**: 提交层返回 `accepted: true`，命令进入队列。执行层返回 `ok: true` 但实际未生效
- **影响**:
  - 提交层和执行层的权限检查不一致
  - 虽然最终未真正解散，但返回 `ok: true` 会误导调用方
  - 其他命令（如 army.march）可能存在相同问题但实际执行
- **修复建议**:
  - 在提交层（command router）即校验 armyId 归属
  - 执行失败时返回 `ok: false` 而非 `ok: true`

### BUG-006: 超长用户名（10000 字符）可注册

- **端点**: `POST /api/v3/auth/register`
- **复现**: 发送 10000 个字符的用户名
- **现象**: 注册成功，返回超大的 JWT token（username 被完整编入 token）
- **影响**:
  - 数据库存储异常大的用户名
  - JWT token 体积膨胀，增加每次请求的带宽开销
  - 可能导致 UI 显示异常
- **修复建议**:
  ```javascript
  if (username.length < 3 || username.length > 32) {
    return error('用户名长度 3-32 字符');
  }
  ```

---

## 🟡 Medium

### BUG-007: 并发命令防护不完整（3/5 命中）

- **端点**: `POST /api/v3/commands`（并发测试）
- **复现**: 同时发 5 个 `army.conscript` 请求
- **现象**: 3 个被接受，2 个被拒绝（"命令已在队列中"）
- **影响**: 队列去重机制有效但不够严格，某些并发窗口下仍可多次入队
- **修复建议**: 使用原子操作（如 Redis SETNX）确保同一玩家同一类型命令在队列中唯一

### BUG-008: 超大 Payload 被接受（100KB+）

- **端点**: `POST /api/v3/commands`
- **复现**: 发送包含 1000 个 junk 字段的 payload
- **现象**: `accepted: true`
- **影响**: 可用于内存 DoS 攻击，大量超大 payload 可能耗尽服务器内存
- **修复建议**:
  - 设置请求体大小限制（如 10KB）
  - 服务端只提取已知字段，忽略未知字段

### BUG-009: 地图边界外坐标进入执行层

- **端点**: `army.march`
- **复现**: `target: {q: 9999, r: -9999, s: 0}`（地图仅 120x120）
- **现象**: 提交层 `accepted: true`，执行层 `failed`
- **影响**: 浮点坐标 `{q:1.5, r:-1.5, s:0}` 也进入了执行层
- **修复建议**:
  ```javascript
  // 提交层即校验坐标范围
  const MAP_RADIUS = 60;
  if (Math.abs(q) > MAP_RADIUS || Math.abs(r) > MAP_RADIUS) {
    return reject('目标坐标超出地图范围');
  }
  if (!Number.isInteger(q) || !Number.isInteger(r) || !Number.isInteger(s)) {
    return reject('坐标必须为整数');
  }
  ```

---

## 🔵 Low

### BUG-010: season.join 可重复调用

- **端点**: `season.join`
- **复现**: 已加入赛季后再次调用
- **现象**: 返回 `joined: true, created: false`（幂等）
- **影响**: 功能正常但返回值可能误导，且每次调用都消耗服务器资源
- **修复建议**: 返回 `{alreadyJoined: true}` 或 HTTP 409 Conflict

### BUG-011: 无速率限制

- **端点**: 所有认证端点
- **复现**: 并发 50 个 GET /city 请求
- **现象**: 全部 200 OK，无 429 响应
- **影响**: 可被用于暴力枚举、DDoS
- **修复建议**: 添加基于 token 的速率限制（如 60 req/min/user）

---

## 值得肯定的防御

| 测试项 | 结果 |
|-------|------|
| 负数征兵（count: -1） | ✅ 正确拒绝 |
| 无效兵种（dragon） | ✅ 正确拒绝，有清晰提示 |
| 无效建筑类型 | ✅ 正确拒绝，列出合法选项 |
| 无 token 访问 | ✅ 正确返回 401 |
| 篡改 token | ✅ 正确返回 401 |
| 无效 cube 坐标（q+r+s≠0） | ✅ 正确拒绝 |
| 重复用户名注册 | ✅ 正确拒绝 |
| IDOR army.conscript | ✅ 正确检查所有权 |
| 并发命令队列去重 | ✅ 部分有效 |

---

## 修复优先级建议

1. **P0 (立即)**: BUG-001 浮点数兵力、BUG-003 空密码注册
2. **P1 (本周)**: BUG-004 命令白名单、BUG-005 IDOR 一致性、BUG-006 用户名长度限制
3. **P2 (下周)**: BUG-002 数据暴露、BUG-007 并发防护加固、BUG-008 Payload 大小限制
4. **P3 (后续)**: BUG-009 坐标前置校验、BUG-010 幂等返回值、BUG-011 速率限制
