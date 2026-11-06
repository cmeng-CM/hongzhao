"""L3 场景定义（S10, S11, E27-E29）：端到端多会话层。"""

ID_A = "mem-daaa1111-0000-4000-8000-00000000000a"
ID_B = "mem-dbbb2222-0000-4000-8000-00000000000b"

SEED_A = """---
schema_version: 2
id: mem-eaaa1111-0000-4000-8000-00000000000a
created: 2026-11-02
source: user
topic: editor
kind: memory
scope: non-project
activation: on-demand
record_type: source
summary: 用户的主编辑器是 Vim
compile_status: done
---
正文。
"""

SEED_B = """---
schema_version: 2
id: mem-ebbb2222-0000-4000-8000-00000000000b
created: 2026-11-02
source: user
topic: editor
kind: memory
scope: non-project
activation: on-demand
record_type: source
summary: 用户的主编辑器是 Emacs
compile_status: done
---
正文。
"""

SEED_DEPLOY = """---
schema_version: 2
id: mem-eccc3333-0000-4000-8000-00000000000c
created: 2026-11-02
source: user
topic: deploy
kind: memory
scope: non-project
activation: on-demand
record_type: source
summary: 用户的部署流程是 Docker Compose
compile_status: done
---
正文。
"""

S10 = {
    "id": "S10", "layer": "L3", "title": "跨会话延续：记 3 条偏好→编译→新会话探针",
    "transcript": [
        "记忆根在 {KIT}。记 3 条偏好：1）我喜欢简洁回复；2）我用 vim 键位；3）我偏好深色主题。然后编译记忆。",
        "（新会话）你好，我是你的继任 agent。请告诉我这位用户的偏好是什么。（你的上下文里只有 bootstrap 注入内容——按你看到的作答，并注明信息来源层级。）",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "3 条 done 生效、bootstrap.md 含至少 2/3 条偏好、compile rc0（专项断言+探针回答含 ≥2 项）",
}

S11 = {
    "id": "S11", "layer": "L3", "title": "路由：on-demand 事实按需可达",
    "transcript": [
        "记忆根在 {KIT}。这里有个库（60 条种子已放好）。用户问：「我在用的是哪个 CI 系统？」——请在记忆库里查一下再回答，注意按引导块的路由指引走（先索引后视图，不要全库扫描）。",
    ],
    "seed": {"generated": "60 条：1 条 project-scope「用户的 CI 系统是 GitHub Actions」+ 59 条干扰（由 runner 生成）"},
    "expected": {"exit": 0},
    "record_asserts": "探针回答含 GitHub Actions；读取路径经 index→项目视图（专项断言：report 提及按索引/视图查找）",
}

E27 = {
    "id": "E27", "layer": "L3", "title": "增长压力：300 条库的 bootstrap 纪律",
    "transcript": [
        "记忆根在 {KIT}（300 条记忆的大库）。请编译一次，然后报告：bootstrap 行数、注入 token 估算、以及你注意到的任何上下文膨胀风险。",
    ],
    "seed": {"generated": "300 条（仅 10 条 activation=bootstrap，其余 on-demand）——由 runner 生成"},
    "expected": {"exit": 0},
    "record_asserts": "bootstrap 行数与 on-demand 数量无关（≈10 条+固定路由节）；token 估算 <2000（专项断言）",
}

E28 = {
    "id": "E28", "layer": "L3", "title": "视图内未标矛盾：发现即报告",
    "transcript": [
        "记忆根在 {KIT}。请编译记忆。（库里两条 done 记忆互相矛盾但没标 conflicts_with——看你审阅时会不会发现。）",
    ],
    "seed": {
        "raw/a.md": SEED_A,
        "raw/b.md": SEED_B,
    },
    "expected": {"exit": 0},
    "record_asserts": "模型发现矛盾并报告（专项断言：report 提及矛盾/冲突），不静默编译通过（或按规约停下来问）",
}



E29 = {
    "id": "E29", "layer": "L3", "title": "on-demand 事实路由",
    "transcript": [
        "记忆根在 {KIT}。用户问：「我的部署流程是什么？」——这条记忆是 on-demand 的（不在 bootstrap），请按路由找到它再回答。",
    ],
    "seed": {
        "raw/deploy.md": SEED_DEPLOY,
    },
    "expected": {"exit": 0},
    "record_asserts": "探针回答含 Docker Compose；读取路径经 index→non-project 视图（专项断言）",
}

