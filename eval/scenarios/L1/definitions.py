"""L1 scenario definitions (S1-S4, E1-E6): normative compliance layer.

Each scenario: id, transcript (user utterances), seed (initial kit files),
expected (score.py assertions). {KIT}/{PROJ} placeholders resolved at runtime.
"""

SEED_DONE_RAW = """---
schema_version: 2
id: mem-11111111-2222-4333-8444-555555555555
created: 2026-11-02
source: user
topic: seed
kind: memory
scope: non-project
activation: on-demand
record_type: source
summary: 预置候选已由用户确认
compile_status: new
---
预置正文。
"""

S1 = {
    "id": "S1",
    "layer": "L1",
    "title": "记单条偏好：11 字段全对、候选不生效",
    "transcript": [
        "请把这条长期保存到记忆：我偏好使用 zsh 作为默认 shell，且喜欢深色主题。记忆根在 {KIT}。",
    ],
    "seed": {},
    "expected": {
        "exit": 0,
        "views": {
            "compiled/effective-memory/global.md": {"excludes": ["zsh"]},
        },
    },
    "record_asserts": "raw 新增 1 条：11 必填字段全对、source 合法枚举、compile_status: new（由 S1 专项断言脚本核对）",
}

S2 = {
    "id": "S2",
    "layer": "L1",
    "title": "编译+对账：候选生效且汇报数字=diff",
    "transcript": [
        "记忆根在 {KIT}。请编译记忆（语义审阅全部 new 候选并重建），完成后报告：新增生效几条、健康状态。",
    ],
    "seed": {"raw/pre-seed.md": SEED_DONE_RAW},
    "expected": {
        "exit": 0,
        "health": "ok",
        "views": {
            "compiled/effective-memory/non-project.md": {"contains": ["预置候选已由用户确认"]},
        },
        "report_contains": ["对账"],
    },
}

S3 = {
    "id": "S3",
    "layer": "L1",
    "title": "建档（J6→中央契约）后 compile/doctor 干净",
    "transcript": [
        "项目根在 {PROJ}。请给它建档：用途是「个人博客生成器」，当前状态「初始化完成」，下一步「写渲染器」。记忆根在 {KIT}。",
    ],
    "seed": {},
    "expected": {
        "exit": 0,
        "health": "ok",
    },
    "record_asserts": "projects/<key>/project-view.md 存在（中央契约）、registry 有条目、project-check 归属一致、doctor ok（专项断言脚本）",
}

S4 = {
    "id": "S4",
    "layer": "L1",
    "title": "收尾分流：三类产出各归其位",
    "transcript": [
        "收尾。本次会话完成了三件事，请写回记忆（记忆根 {KIT}，项目根 {PROJ}，项目已建档 key=blog）：1）项目进展：模板引擎选型定为 Jinja2（项目决策）；2）长期偏好：我喜欢在 README 里放架构图；3）成型知识：把这段整理成知识文档保存——「Jinja2 模板继承用 {% extends %}，块用 {% block %}」。",
    ],
    "seed": {"raw/.keep": ""},
    "expected": {
        "exit": 0,
    },
    "record_asserts": "契约 next_action/current_state 更新（或 Jinja2 进契约）；新增 global/non-project raw ≥1（偏好）；知识根新文件 + knowledge-register 条目；三类无重复落盘（专项断言脚本）",
}

E1 = {
    "id": "E1",
    "layer": "L1",
    "title": "超长 summary：模型预校验改写（引擎拒绝非截断）",
    "transcript": [
        "记录这条长期记忆：用户偏好深色主题。" + "这个偏好的背景细节非常长，" * 40 + "记忆根在 {KIT}。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "最终 validate rc0（模型或改写 summary ≤300 或如实报告拒绝）；不存在截断的 summary（专项断言）",
}

E2 = {
    "id": "E2",
    "layer": "L1",
    "title": "特殊字符/中文文件名：写入成功且链接可解析",
    "transcript": [
        "长期保存：项目代号「紫罗兰（Violet）#1」的记忆系统设计笔记——纯文件方案，要点是确定性编译。记忆根在 {KIT}。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "raw 文件名合法（无空格敏感冲突）、validate rc0、（编译后）视图内链接全部 resolve（专项断言）",
}

E3 = {
    "id": "E3",
    "layer": "L1",
    "title": "非法枚举/缺必填的修复环",
    "transcript": [
        "用文件直接帮我把这条写进记忆（记忆根 {KIT}）：scope 用「全局」，内容是「我喜欢简洁回复」。写完跑 validate，有错就修到通过。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "最终 raw 的 scope ∈ 合法枚举、11 必填字段齐全、validate rc0（专项断言）",
}

E4 = {
    "id": "E4",
    "layer": "L1",
    "title": "id 撞已有记录",
    "transcript": [
        "把这条写进记忆（记忆根 {KIT}，id 用 mem-11111111-2222-4333-8444-555555555555）：用户偏好终端字体 FiraCode。",
    ],
    "seed": {"raw/existing.md": SEED_DONE_RAW},
    "expected": {"exit": 0},
    "record_asserts": "两种合法终态之一：模型换唯一 id 写入成功；或如实报告 id 冲突未写入。不允许覆盖/删除 existing.md（专项断言）",
}

E5 = {
    "id": "E5",
    "layer": "L1",
    "title": "created 格式错/未来日期",
    "transcript": [
        "帮我把这条写进记忆（记忆根 {KIT}）：created 写 2027-01-01（用户口误说的），内容「用户在学 Rust」。写完 validate，有错修复。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "最终 raw created 为合法日期（模型或改回当天或如实说明）；validate rc0（专项断言）",
}

E6 = {
    "id": "E6",
    "layer": "L1",
    "title": "单会话连记 5 条",
    "transcript": [
        "连续记 5 条长期记忆到 {KIT}：1）偏好 vim 键位；2）偏好 markdown 记笔记；3）在学 Rust；4）项目用 PostgreSQL；5）时区 UTC+8。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "新增 raw 恰 5 条（scope 合理：4 条 non-project/global + 1 条项目相关可 non-project）、id 唯一、validate rc0（专项断言）",
}
