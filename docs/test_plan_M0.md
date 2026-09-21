# M0 测试方案与脚本说明

> 配套对象：`docs/11_MVP分步实施计划.md` §3（M0 契约与骨架）。
> 本文只描述**当前 M0 成果**的测试方法与边界，不覆盖 M1–M6。
> 一键执行：`make verify`（= `make check` + `make falsify` + `make test`）。

---

## 1. 测试目标：可证伪，而非"看起来对"

`docs/07 §4.1` 把验收定义为**证伪测试**。M0 的测试同样遵循这一原则：
每条测试都对应一句可以被反驳的断言，而不是"跑通了"。

M0 要证明的只有四件事：

| # | 待证明命题 | 证伪方式 |
|---|---|---|
| 1 | 协议层是**真的被冻结**的，五条强制约束由代码保证而非靠约定 | 故意构造违规信封，必须抛异常 |
| 2 | 配置驱动：新增智能体/技能只改配置 | 故意写坏配置，必须拒绝启动并指出位置 |
| 3 | 注册表是**扫描加载**的，不是硬编码字典 | 改配置文件后注册结果必须跟着变 |
| 4 | 模型调用无旁路：业务代码不能直连模型 API | 请求未注册 provider 必须抛错 |

**M0 不测什么**（会变成假测试）：

- 不测"智能体是否聪明"——M0 没有任何智能体逻辑
- 不测"记忆是否有效"——M0 只建了表，没有读写流水线
- 不测"图生成是否正确"——M0 没有调度器
- 不测业务数值正确性——没有业务实现

> 上面四项都是正确的空白，不是缺口（`docs/11 §3.6` 禁止 M0 写任何业务逻辑）。

---

## 2. 测试分层

```
┌──────────────────────────────────────────────────────────────┐
│ L5  元测试层 tests/test_verify_m0_script.py    12 项          │
│     证明"证伪测试本身能失败" —— 防止假绿                        │
├──────────────────────────────────────────────────────────────┤
│ L4  验收层   tests/test_m0_acceptance.py       12 项          │
│     逐条对应 docs/11 §3.4 的五条验收标准                       │
├──────────────────────────────────────────────────────────────┤
│ L3  契约层   tests/test_contracts.py           27 项          │
│     对齐 docs/01§3 02§4 03§3 04§2 08§3.1 09§2/§7              │
├──────────────────────────────────────────────────────────────┤
│ L2  证伪层   scripts/verify_m0.py              35 项          │
│     破坏机制 → 必须立刻失败（docs/07 §4.1 的证伪测试）          │
├──────────────────────────────────────────────────────────────┤
│ L1  自检     scripts/check_registry.py + Makefile             │
│     加载 → 校验 → 建表 → 汇报，退出码可判定                     │
└──────────────────────────────────────────────────────────────┘
```

**为什么分五层**：

| 层 | 回答的问题 | 若缺失会怎样 |
|---|---|---|
| L1 自检 | 现在能不能跑起来？ | 无入口，靠手敲命令 |
| L2 证伪 | **机制是真的还是装饰的？** | 只能证明"跑通了"，不能证明"写成真的了" |
| L3 契约 | 结构符合文档吗？ | 文档与代码悄悄脱节 |
| L4 验收 | 里程碑标准被满足吗？ | 无法客观判定可否进入下一步 |
| L5 元测试 | **上面那些测试会失败吗？** | 断言恒真 → 假绿 → 最危险的失败模式 |

**L2 与 L5 是本方案的核心。** 普通测试只能证明"当前是对的"；
证伪测试证明"错了会被发现"；元测试证明"证伪测试真的会响"。
三者串起来，才能对"机制是真的"这句话负责。

---

## 3. L4 验收层映射表

| docs/11 §3.4 验收项 | 测试函数 | 断言要点 |
|---|---|---|
| 1 `make check` 可运行 | `test_acceptance_1_registry_loads_and_reports` | 数量为 2/3/1，汇报串含三段计数 |
| | `test_acceptance_1_min_tables_created` | 11 张表全部建立，关键表逐个点名 |
| 2 技能缺必填字段 | `test_acceptance_2_missing_required_field` | 异常串同时含**文件名**与**字段名** |
| | `test_acceptance_2_missing_skill_id` | 缺主键同样被拒 |
| | `test_acceptance_2_invalid_skill_id_pattern` | id 缺分组前缀被拒 |
| | `test_acceptance_2_nondeterministic_cache_rejected` | 非确定性技能开缓存被拒（docs/04 §6 陷阱 7） |
| | `test_acceptance_2_duplicate_skill_rejected` | id 重复被拒 |
| 3 模板引用不存在的能力 | `test_acceptance_3_unknown_capability_reference` | 报出 `quantum_forecast` 且定位到模板与 requires |
| | `test_acceptance_3_required_capability_without_provider` | required 能力无提供者 → 拒绝启动 |
| 4 Agent Card 引用未授权技能 | `test_acceptance_4_unauthorized_skill_reference` | 报出技能名 + 卡片文件名 + `agents.A01_supervisor.skills` |
| | `test_acceptance_4_skill_owner_must_be_registered` | 反向悬空（owner_agents 指向幽灵）被拒 |
| 5 `make test` 全部通过 | `test_acceptance_5_check_script_runs` | 以子进程真实执行自检脚本，断言退出码 0 |

### 3.1 关键设计：故意注入错误

所有"必须失败"的测试都通过 `tmp_config` 夹具完成：
把 `config/` 复制到临时目录 → 用 `yaml.safe_load` + 定点修改 → 写回 → 断言抛错。

```python
def test_acceptance_4_unauthorized_skill_reference(tmp_config: Path) -> None:
    agents_file = tmp_config / "agents" / "agents.yaml"

    def grant_unknown_skill(data: dict) -> None:
        data["agents"][0]["skills"].append("risk.calc_thermal_rating")

    _edit_yaml(agents_file, grant_unknown_skill)
    with pytest.raises(UnknownReferenceError) as excinfo:
        Registry.load(tmp_config)
```

**为什么不用 mock**：mock 掉的正是被测对象。这里改的是**真实配置文件**，
走的是**真实的加载路径**，因此能真正证明"配置坏 → 启动失败"。

**为什么不用造数脚本**：`tmp_config` 只做 `shutil.copytree` + 定点改写，
不生成任何业务数据，符合 `docs/11 §1` 的禁止项。

---

## 4. L3 契约层覆盖矩阵

| 契约 | 文档出处 | 覆盖的强制约束 |
|---|---|---|
| `Task` | docs/08 §3.1 | 12 字段齐全；`trigger` 仅供审计；拒绝未知字段 |
| `Scope` | docs/08 §3.1 | 空范围可判定 |
| `Envelope` 七段 | docs/03 §3 | 段落构成固定；13 个信封头字段 |
| 约束 1 因果树 | docs/03 §3.1 | `derive()` 继承 `trace_id`、设置 `parent_msg_id`、`seq` 递增 |
| 约束 2 记忆引用 | docs/03 §3.1 | `context_refs.memory_ids` 字段存在且随消息携带 |
| 约束 3 置信度 | docs/03 §3.1 | `result.confidence` 为 0~1 |
| 约束 4 遥测 | docs/03 §3.1 | `telemetry` 为强制段 |
| 约束 5 可溯源 | docs/03 §3.1 | **PROPOSE 无 evidence 直接抛错** |
| 协议纪律 | docs/03 §4 | REFUSE 必带理由；FAILURE 必带原因；响应集合成表 |
| 传输解耦 | docs/03 §9.1 | `to_wire()/from_wire()` 往返后 `model_dump()` 完全相等 |
| `SkillSpec` | docs/04 §2 | 14 字段；id 分组前缀；description 长度下限 |
| `AgentCard` | docs/01 §3 | 15 字段；至少 1 个能力；`max_retries ≤ 1`（docs/03 §7.2） |
| `Capability` | docs/09 §4.2/§5.1 | required 不得带 when；conditional 必须带 when；inputs/outputs 声明 |
| `ValidationResult` | docs/09 §7 | 拒绝必给原因；八条铁律对应 8 个枚举值 |
| `MemoryItem` | docs/02 §4.1 | **无 `source_ref` 不能落库**；user 作用域必带 `owner_user_id` |
| `PlanRejection` | docs/09 §8.2 | 记录违规引用，供观察幻觉 |

---

## 5. L2 证伪层：八组 35 项

`scripts/verify_m0.py` 的做法是**主动破坏机制，然后看它是否报警**。
若破坏后仍"通过"，脚本判定 FAIL——那说明这个机制是装饰性的。

| 组 | 主题 | 项数 | 核心思路 |
|---|---|---|---|
| A | 配置驱动 | 3 | 只改 YAML，验证注册结果跟着变（证明不是硬编码） |
| B | 快速失败 | 9 | 写坏配置，验证拒绝启动且报出文件+字段 |
| C | 铁律二 · 信封 | 6 | 违规信封无法构造；合法信封可序列化往返 |
| D | 铁律三 · 技能 | 5 | 技能自带白名单/schema/描述约束，缺一即拒 |
| E | 记忆硬约束 | 4 | 无 `source_ref`、用户作用域无归属人、超长 → 构造失败 |
| F | 模型无旁路 | 4 | 未注册 provider 抛错；缺档位不静默换档 |
| G | 最小表集 | 2 | 11 张表建得出，且真的能写入读回 |
| H | 反证 | 2 | 合法配置/合法信封必须成功（证明不是无脑报错） |

**H 组为什么必要**：只有"破坏会失败"而没有"不破坏会成功"，
测试可能只是因为格式过严到任何输入都失败——那是另一种假绿。
H 组是判别力的另一半。

**B 组与 H 组构成双向对照**：

```
正常配置 ──► 加载成功   （H1 证明）
写坏配置 ──► 拒绝启动   （B1–B9 证明）
```

只有这两条同时成立，才能说"校验是真的在工作"。

---

## 6. L5 元测试层：证明"证伪测试会响"

`tests/test_verify_m0_script.py` 是整个方案里最容易被忽略、但最关键的一层。

它做的事：**把机制真的拆掉，确认对应的证伪测试会转为 FAIL。**

| 元测试 | 拆掉什么 | 期望 |
|---|---|---|
| `test_c1_detects_a_disabled_mechanism` | 信封构造改为不做校验 | C1 必须 FAIL |
| `test_c3_detects_a_disabled_mechanism` | 同上（REFUSE 场景） | C3 必须 FAIL |
| `test_b2_detects_a_disabled_mechanism` | 摘除 `Registry._validate` | B2 必须 FAIL |
| `test_e1_detects_a_disabled_mechanism` | `MemoryItem` 不做校验 | E1 必须 FAIL |
| `test_expect_raises_fails_when_nothing_is_raised` | 机制不报警 | 判 FAIL 且提示"可能是装饰性的" |
| `test_core_mechanics_*` 恢复后 | — | 必须重新 PASS（无状态污染） |

### 6.1 一个真实的坑：pydantic v2 无法从 Python 层关闭校验器

最初我尝试用 `monkeypatch` 替换 `Envelope.model_validate` 来"关掉校验"，
结果 C1 仍然是 PASS。原因：

> pydantic v2 把 `@model_validator` 编译进了 **Rust 核心 schema**，
> 替换 Python 层的方法名不影响实际执行路径。

这个发现本身有价值——它说明**约束是编译进核心的，不是 Python 层的装饰**。
元测试因此改为替换"被测代码所依赖的构造入口"（`mod.Envelope`），
这才是"约束未实装"的等价情形。

> 结论：如果元测试可以轻易关掉某个机制，那个机制可能就是软的。

---

## 7. 运行方式

```bash
make check      # L1 启动自检（快，看注册汇报）
make falsify    # L2 证伪测试（35 项）
make test       # L3+L4+L5 单元测试（51 项）
make verify     # 全量：check + falsify + test
```

细粒度执行：

```bash
PYTHONPATH=src python3 scripts/verify_m0.py --list    # 列出所有证伪项
PYTHONPATH=src python3 scripts/verify_m0.py -k B      # 只跑 B 组
PYTHONPATH=src python3 scripts/verify_m0.py -v        # 打印每步通过细节
PYTHONPATH=src python3 -m pytest tests -v
PYTHONPATH=src python3 -m pytest tests -k acceptance_3
PYTHONPATH=src python3 scripts/check_registry.py --config config --strict
```

`check_registry.py --strict`：把"能力缺口"这类 WARN 提升为失败退出码。
当前 M0 会因 `confidence_review / history_retrieval / memory_retrieval`
无提供者而非零退出——这是**预期行为**，M2 补齐 8 智能体后应转为全绿。

---

## 8. 当前结果

| 层 | 用例数 | 结果 | 命令 |
|---|---|---|---|
| L1 自检 | 1（含 4 项 OK 汇报） | 通过 | `make check` |
| L2 证伪 | 35 | 35/35 通过 | `make falsify` |
| L3 契约 | 27 | 通过 | `make test` |
| L4 验收 | 12 | 通过 | `make test` |
| L5 元测试 | 12 | 通过 | `make test` |
| **合计** | **51 项测试 + 1 个自检脚本** | **全绿** | `make verify` |

自检输出：

```
[OK] 已注册 2 个智能体 / 3 个技能 / 1 个能力模板（能力定义 8 个）
[OK] ModelRouter profiles=['hybrid', 'stub'] providers=['stub'] default=hybrid
[OK] 最小表集 11 张：task, task_step, memory_item, memory_edge, memory_access_log,
     message_log, skill_call_log, trace_snapshot, plan_record, replan_record, plan_rejection
[WARN] 无智能体提供的能力：confidence_review, history_retrieval, memory_retrieval
```

---

## 9. 已知测试盲区（主动声明）

这些是 M0 阶段**无法**测试的内容，不是遗漏：

| 盲区 | 原因 | 将在哪个里程碑覆盖 |
|---|---|---|
| 消息经总线投递而非直接调用（铁律二） | M0 只有信封结构，没有 bus 实现 | M1（`src/runtime/bus/`） |
| 执行图来自模板推导（铁律一） | M0 没有调度器 | M1 最小图，M2 完整图 |
| 技能越权调用被拒（铁律三的运行期部分） | M0 只做了加载期白名单校验 | M1（权限异常 + 审计留痕） |
| 记忆检索真的起作用 | M0 只有表结构 | M1（写入后立即可检索） |
| 事件流与 trace 重建 | M0 没有运行时 | M1 / M6 |
| 并发、限流、缓存、降级 | 属技能治理 | M5 |

**结论**：M0 的测试只能证明"契约与骨架是真的"。
三条铁律的**运行期**验证要在 M1 起才可能成立——
到那时 `test_contracts.py` 与 `test_m0_acceptance.py` 必须仍然全绿（无回归）。

---

## 10. 后续里程碑的测试策略（预留）

每进入一个新里程碑，**不新建测试体系**，而是：

1. 新增 `tests/test_m{n}_acceptance.py`，逐条映射该里程碑验收标准；
2. 新增 `scripts/verify_m{n}.py` 做证伪测试（沿用本文件 A–H 的分组思路）；
3. `make falsify` 逐步合并为 `verify_m0 ... verify_m6`；`make verify` 全量串起；
4. **上一里程碑的测试文件一字不改**，作为回归网。

这样到 M6 时，`docs/07 §4.1` 的 15 条证伪测试自然成为既有测试的超集，
而不是重写一遍。

### 10.1 每个里程碑必须新增的证伪项（预留清单）

| 里程碑 | 必须新增的证伪测试 |
|---|---|
| M1 | 把总线改为直接函数调用 → 测试必须失败；关掉记忆检索 → 断言必须失败 |
| M2 | 同一意图三个深度的图必须能 diff 出差异；模板写死时测试必须失败 |
| M3 | 把某条记忆的最近访问时间前调 180 天 → 排序必须下降 |
| M4 | 制造三元组往返 3 次 → 必须被强制中断 |
| M5 | 相同入参调两次 → 第二次必须缓存命中 |
| M6 | 合并 15 条，`make verify` 一键全绿 |

**共同要求**：每条都要问一句"如果这个机制是假的，这条测试会不会失败？"
答不上来，它就不是证伪测试。
