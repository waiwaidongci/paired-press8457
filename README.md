# 栖木印刷配对试验簿

同纸张两工艺成对色差→配对分析→试印复核；枚举n<=18，以上固定seed Monte Carlo加一校正。原生 HTML/CSS/JavaScript 多模块工作席，所有计算由 Python 完成。

## 模拟业务
栖木研究协作组，12名分析师与业务人员，日常使用 `paired-press-202611-1.csv` 手工抄表。当前三个痛点：观测与口径不可追溯、重算易出错、结果与复核割裂。上游提供独立合成业务观测；本应用接管数据登记、方法执行和输入冻结；下游负责人形成复测/预算方案，观察员获取复核后的CSV。

核心业务实体：PressStudy / MatchedPair / PairedRun / Review。源码 model/schema/service/controller/route 与前端 api/store/pages 完成链路，不依赖浏览器本地假数据。

## 功能与方法
- 试印研究、成对纸样录入/编辑/删除；重名记录与非法数值明确拒绝。
- 配对差均值与精确符号翻转置换检验。同一纸张上成对测量；小样本枚举全部符号，较大样本使用固定种子 Monte Carlo 与加一校正。
- 每次运行冻结参数、观测和SHA256。Redis任务由独立worker计算，写DB与共享产物卷；输入修改不会改写历史结果。
- 负责人复核不可覆盖；审计记录登录、数据改动、排队、复核与导出；240请求/分钟限流、全局可恢复错误。
- 名额派单回放：补录纸类、班次、到单时刻、读数可见时刻与成对读数（允许读数未齐），按到单顺序逐单回放当时该把新工艺名额给谁，并与全走原工艺的平均色差对比。

## 名额派单回放
场景：新工艺每班名额有限，需要试印记录回放“当时该把名额给谁”。

- **口径**：逐单按到单时刻排序，同刻按编号自然序（QM-2 在 QM-10 之前）再按记录 id。依据只取“当时已齐”的较早同类订单——同纸类、到单更早，且读数可见时刻不晚于本单到单时刻；同刻两单互为依据。平均改善 = 依据订单 (原工艺 ΔE − 新工艺 ΔE) 的均值。
- **派单**：依据平均改善严格大于门槛且本班尚有名额才选新工艺；无依据、未过门槛或名额用尽都走原工艺，并在逐单明细写明原因。
- **冻结**：一次回放在可重复读快照里同时读出冻结时刻前的订单与全部班次名额，请求里的门槛一并写入快照；冻结之后才可见的读数会以“未齐”入档，回放不会改用补录数据。快照记录 SHA256，可复现。
- **幂等**：每个回放请求带幂等键；相同键重试返回既有冻结结果、不新增记录，键已被不同研究或门槛使用时返回 409。
- **对比**：页面同时给出“按此派单”和“全走原工艺”在已可见成对读数上的平均色差及差额，并列出选中的订单、每班剩余名额与逐单依据。读数未齐（缺任一侧或可见时刻晚于冻结时刻）的订单两边都不计入平均；若它已按规则选中，仍占用并扣减本班名额。
- **时间口径**：所有时间按 UTC 规范化存储与比较；页面上的时间输入按 UTC 解释。回放只读冻结快照，不会反过来修改订单或名额。

合成样本 `backend/scripts/seed_demo.py` 在第一个试印研究中含 12 单，覆盖不同纸类、同刻抢最后一个名额（TRIAL-0004/0005）和读数后到（TRIAL-0006 到单 09:20、次日才可见；TRIAL-0012 读数未齐）。以冻结时刻 `2026-11-19T10:00:00Z`、门槛 `0.3` 回放，白班 3 个名额分别给 TRIAL-0002、TRIAL-0006（读数未齐，占名额）、TRIAL-0004；TRIAL-0005 与 TRIAL-0008 因名额用尽走原工艺。计入对比 7 单，派单平均 3.0714 ΔE，全原工艺 3.2857 ΔE，差额 −0.2143 ΔE。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18242 ，API http://localhost:19242/docs 。数据库映射 17742。无需Node构建。可以从中文和带空格目录启动。清理 `docker compose down -v --remove-orphans` 会删除本题演示数据卷。

|角色|账号|密码|权限与典型动作|
|---|---|---|---|
|admin 负责人|admin@demo.local|Research2026!|全部读写、批准复核、下载|
|analyst 分析师|analyst@demo.local|Research2026!|数据修改、创建任务、读取结果及下载；不能复核|
|viewer 观察员|viewer@demo.local|Research2026!|只读；仅可导出已复核结果|

## 一天的工作剧本
1. 09:00 admin登录，查“栖木·米白纸套印”。
2. 09:10 analyst核对 `paired-press-202611-1.csv` 的seed记录。
3. 09:15 来源录入页检查 `原工艺色差 ΔE` 等业务字段，必要时编辑。
4. 09:20 分析执行页保留默认参数 `{"resamples": 10000}`，命名本轮研究。
5. 09:21 冻结输入并排队，worker实算，结果页自动刷新。
6. 09:25 阅读核心数值、方法边界、明细与SHA256；发现失败先修数据重跑。
7. 09:35 admin打开业务复核，写明限制与下一步动作，归档后不可覆盖。
8. 09:40 viewer读取复核意见并下载CSV，在操作留痕页核对下载事件。

## 技术与目录
|部分|实现|
|---|---|
|前端|原生ES modules、HTML/CSS、Nginx1.27，无前端框架|
|API|Python3.11、FastAPI0.115、SQLAlchemy2、JWT、PBKDF2密码|
|计算|NumPy2.2、SciPy1.15，固定seed42|
|数据库|PostgreSQL16|
|任务|Redis7持久队列，Python独立worker，心跳healthcheck|

`frontend/src/`分api、stores、types、components/common、hooks、pages、router、utils、constants；`backend/src/`分config、models、schemas、services、controllers、routes、middlewares、utils、constants；`backend/scripts/seed_demo.py`自然键插入、重复不覆盖修改；`backend/migrations/README.md`说明schema版本。

环境变量 `.env.example`：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO。开发时在本地venv安装backend/requirements.txt，设置DATABASE_URL、REDIS_URL、JWT_SECRET再运行uvicorn；前端开发经Nginx代理 `/api/` 到不带前缀的API。

共享枚举：角色admin/analyst/viewer和队列queued/running/completed/failed；后端`src/constants/enums.py`、认证与worker使用相同值；前端`src/types/enums.js`、状态与角色界面使用相同值。Google Fonts：Noto Serif SC + IBM Plex Mono；断网使用serif/monospace回退。

## 算法输入、失败态与复现
输入为选定批次全部观测和参数，输出核心数值、明细、解释；参数经后端严格白名单和范围验证。同一纸张上成对测量；小样本枚举全部符号，较大样本使用固定种子 Monte Carlo 与加一校正。。空批次拒绝；不完整字段/非有限数/非法计数拒绝；常量相关列与不足样本使任务failed并保留错误。固定seed42、输入checksum相同可复现。独立oracle：小n穷举手算；交换两列统计量变号p相同；缺失配对拒绝。

已知边界：小型本地研究应用，使用合成数据，不含企业SSO与外发邮件；结果由人工复核，不自动执行业务决策；单worker恢复queued/running任务，数据库与Redis间未采用分布式事务。以当前测试目录TESTING.md记录实际验证结果。

MIT License。
