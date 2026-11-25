# ContextMesh

**团队里的 AI 助手，共用一份有出处、分人群的项目决定。** 成员 A 确认需求，成员 B 在另一个会话检索。两人的项目凭据不同，查询的是同一个服务；换机器无需复制决定文件。

## 看它解决哪一次返工

最初所有用户都用短信登录。产品经理后来只把企业试点改成邮箱。测试人员接手前，两条验收用例都引用初版决定。用 ContextMesh 核对引用，会得到两个不同的结果：

| 用例 | 适用对象 | 服务返回 | 接手者看到的当前依据 |
|---|---|---|---|
| T-17 | 企业试点 | needs_review | 查到邮箱规则和新评审来源 |
| T-18 | 公众注册 | current | 初版短信规则仍有效 |

### 本机运行真实双人演示

在仓库根目录使用 Python 3.10+。以下是 macOS / Linux 命令，Windows 可将 .venv/bin/python 替换为 .venv/Scripts/python.exe。

~~~sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python examples/demo.py
~~~

演示使用临时 SQLite 库、真实 HTTP MCP 服务和两位成员的独立客户端连接。它会先发布旧版本，再只修改一个人群，最后打印两条用例的核对结果。运行结束即清理演示数据。服务端无需模型 API Key。

## 给团队开一个持久项目

在同一目录运行以下命令。首次授权时创建项目。每条 grant 输出一枚成员专属 token，在客户端的凭据配置中使用。对同名成员再次 grant 会轮换 token；revoke 会使该身份的凭据失效。

~~~sh
.venv/bin/python contextmesh.py grant login alice
.venv/bin/python contextmesh.py grant login bob
.venv/bin/python contextmesh.py serve
~~~

默认地址为 http://127.0.0.1:8787/mcp ，数据保存在当前目录的 contextmesh.sqlite3。可以在子命令前用 --db 指定持久文件路径。所有进程使用同一个数据库文件。另一台电脑可通过 SSH 端口转发访问同一服务（在成员电脑执行，替换 team-host 为实际 SSH 主机）：

~~~sh
ssh -N -L 8787:127.0.0.1:8787 team-host
~~~

也可以在服务前配置带 TLS 的反向代理，转发至回环地址并传递认证头；若使用 SDK 的本地主机校验，转发给后端的 Host 设为 127.0.0.1:8787。团队成员通过 HTTPS 端点连接。项目成员可以发布和更新本项目的共享结论，只有发布者可以撤回自己的记录；撤回从生效查询剔除，项目历史保留。

## 接入 WorkBuddy

1. 在两位成员的客户端安装 [WorkBuddy Skill](dist/contextmesh-decisions.zip)，为普通任务提供何时查、何时写、如何引用的说明。
2. 在「专家·技能·连接器 → 连接器 → 自定义连接器」添加 Streamable HTTP MCP 服务。按 [配置示例](integrations/workbuddy/mcp.example.json) 填写端点和各自的 Authorization 头，在任务中启用该连接器。配置中的地址适合服务同机运行或已建立上述隧道的桌面端；云端执行需使用可达的 HTTPS 地址。[WorkBuddy 官方连接器说明](https://open.workbuddy.cn/docs/connector)
3. A 在自己的会话中输入：“发布到 login 项目：登录验证，企业试点和公众注册均使用短信验证码，来源是初版评审。” 核对共享摘要后确认，再输入：“企业试点改邮箱，公众不变，来源是周三评审。”
4. B 新建会话输入：“按项目决定，分别给企业试点和公众注册写登录验收用例，附当前决定 ID 和出处。” 想检查旧用例时给出原决定 ID 和人群即可。自然触发依赖客户端；也可显式选中技能和连接器。

本版验证了官方 MCP Python SDK 客户端的端到端读写，WorkBuddy 桌面客户端尚待真人联调。原来的[本地清单示例](dist/contextmesh-demo.zip)仍可在无连接器时作为文件模式试用；文件模式使用各自已有的文件权限。

## 已实现的 MCP 工具

| 工具 | 行为 |
|---|---|
| publish_context | 发布确认的主题、结论、来源和明确的人群；替代时携带旧 ID，只更新指定人群。与现行版本不符时拒绝覆盖。 |
| search_context | 按子串和可选的人群过滤当前决定。每项的 active_audience 表示当前生效人群；audiences 记录发布时范围。 |
| check_reference | 按旧 ID 和人群判定当前、待复核、人群不符、无当前规则或未知引用。 |
| recent_context | 分页读取项目历史、发布人、替代关系、撤回标记及当前有效人群。 |
| withdraw_context | 撤回自己的一条决定。旧版不会自动复活。 |

每枚 token 只绑定一位成员及一个项目，数据库只保存 token 摘要。人群标签是业务规则的适用范围；项目成员均能读取项目内的共享记录。首版采用发布即生效、精确人群标签和文本检索。跨项目搜索、后台订阅通知、语义搜索与自主任务分派属于后续设计。

## 验证与设计

~~~sh
.venv/bin/python -m unittest discover -s tests -v
~~~

测试覆盖跨身份读写、项目隔离、并发替代冲突、重启恢复、引用失效、撤回及成员撤权。

[图解产品提案](docs/proposal.html) · [Skill 源码](skills/contextmesh-decisions/SKILL.md) · [Apache-2.0 许可证](LICENSE)
