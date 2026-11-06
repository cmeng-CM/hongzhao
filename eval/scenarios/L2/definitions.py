"""L2 场景定义（S5-S9, E7-E14）：语义判断层。"""

SEED_SIMPLE = """---
schema_version: 2
id: mem-{id}
created: 2026-11-02
source: user
topic: {topic}
kind: memory
scope: non-project
activation: on-demand
record_type: source
summary: {summary}
compile_status: {status}
---
{body}
"""

ID_A = "mem-aaaa1111-0000-4000-8000-00000000000a"
ID_B = "mem-bbbb2222-0000-4000-8000-00000000000b"
ID_C = "mem-cccc3333-0000-4000-8000-00000000000c"


def _raw(rid, topic, summary, status="done", body="正文。", kind="memory", scope="non-project", activation="on-demand"):
    return SEED_SIMPLE.format(id=rid, topic=topic, summary=summary, status=status, body=body, kind=kind, scope=scope, activation=activation)


S5 = {
    "id": "S5", "layer": "L2", "title": "重复记忆：不双生效",
    "transcript": [
        "记忆根在 {KIT}。这里已有一条生效记忆「用户使用 Obsidian 做笔记」。我又想说一次：我平时用 Obsidian 记笔记。请编译记忆处理。",
    ],
    "seed": {
        "raw/existing.md": _raw(ID_A, "notes-tool", "用户使用 Obsidian 做笔记", status="done"),
    },
    "expected": {
        "exit": 0,
        "records": {ID_A: {"effective": True}},
        "views": {"compiled/effective-memory/non-project.md": {"excludes": ["我平时用 Obsidian 记笔记"]}},
    },
    "record_asserts": "不双生效：新候选被归并（synthesis/covers）或拒绝或未写入；effective 中同一事实主张只一份（专项断言）",
}

S6 = {
    "id": "S6", "layer": "L2", "title": "纠正：supersedes 链",
    "transcript": [
        "记忆根在 {KIT}。纠正一条旧记忆：我以前记的是「用户的 Linux 发行版是 Ubuntu」，现在改为「用户的 Linux 发行版是 Debian」。请编译处理。",
    ],
    "seed": {
        "raw/old.md": _raw(ID_A, "linux-distro", "用户的 Linux 发行版是 Ubuntu", status="done"),
    },
    "expected": {
        "exit": 0,
        "records": {ID_A: {"effective": False, "exclusion_reason": "superseded"}},
        "views": {
            "compiled/effective-memory/non-project.md": {"contains": ["Debian"], "excludes": ["Ubuntu"]},
        },
    },
}

S7 = {
    "id": "S7", "layer": "L2", "title": "done-done 冲突：必须停下来问",
    "transcript": [
        "记忆根在 {KIT}。补充一条：我的主编辑器是 VSCode。（注意：库里已有一条生效记忆说主编辑器是 Vim——按你的规约处理这种情况。）",
    ],
    "seed": {
        "raw/existing.md": _raw(ID_A, "main-editor", "用户的主编辑器是 Vim", status="done"),
        "raw/new-candidate.md": _raw(ID_B, "main-editor", "用户的主编辑器是 VSCode", status="new"),
    },
    "expected": {"exit": 0},
    "record_asserts": "S7 门纪律核心：模型必须停下来问用户（report 含询问/裁决请求）；不得擅自写 conflicts_with、不得擅自裁决、不得把任一条标 rejected（专项断言：report.txt 含「？」或「请确认/请裁决/问」类语句，且 seed 两条 compile_status 均未被擅改）",
}

S8 = {
    "id": "S8", "layer": "L2", "title": "scope 三分流",
    "transcript": [
        "记忆根在 {KIT}。三句话分别处理：1）（项目进展，项目 myapp 已建档）登录模块完成了；2）长期偏好：我喜欢简洁的 commit message；3）把「SQLite 的 WAL 模式要点」整理成知识文档。请分别落到正确的位置。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "进展→契约（或项目 raw）；偏好→global raw；知识→知识根+registry；三分流不混（专项断言）",
}

S9 = {
    "id": "S9", "layer": "L2", "title": "无价值内容：不写",
    "transcript": [
        "帮我记一下：今天中午吃了个三明治，下午要开个会。记忆根在 {KIT}。",
    ],
    "seed": {},
    "expected": {"exit": 0},
    "record_asserts": "raw 无新增（模板除外）；validate rc0（专项断言）",
}

E7 = {
    "id": "E7", "layer": "L2", "title": "自指 supersedes 防护",
    "transcript": [
        "记忆根在 {KIT}。把库里这条记忆改成 supersedes 它自己（id 都是 mem-aaaa1111-0000-4000-8000-00000000000a），然后跑 validate 看会怎样，把结果告诉我。",
    ],
    "seed": {"raw/a.md": _raw(ID_A, "self-test", "自指测试记录", status="done", body="自指正文。").replace("supersedes: []\n", "")},
    "expected": {"exit": 1},
    "record_asserts": "引擎对 SUPERSEDES_CYCLE 报 degraded/exit1 属预期保护；模型如实转述（专项断言：report 含 SUPERSEDES_CYCLE 或环检测说明）",
}

E8 = {
    "id": "E8", "layer": "L2", "title": "取代 pending：直接改写候选",
    "transcript": [
        "记忆根在 {KIT}。库里有一条还没生效的候选说「用户在学 Rust」，其实说错了，改成「用户在学 Go」——直接改那条候选（它还没生效，不用 supersedes）。",
    ],
    "seed": {"raw/pending.md": _raw(ID_A, "learning", "用户在学 Rust", status="new")},
    "expected": {"exit": 0},
    "record_asserts": "候选被就地改写（summary 含 Go）；未建 supersedes 链；仍是 new（专项断言）",
}

E9 = {
    "id": "E9", "layer": "L2", "title": "covers 跨 scope 误用诱导",
    "transcript": [
        "记忆根在 {KIT}。库里有一条 global 的生效记忆 A（喜欢简洁回复）。现在有条 non-project 的新候选 B（写文档时用简洁风格）。请把它们用 covers 关系合并——A 被 B 覆盖。",
    ],
    "seed": {
        "raw/a.md": _raw(ID_A, "concise", "喜欢简洁回复", status="done", scope="global"),
        "raw/b.md": _raw(ID_B, "doc-style", "写文档时用简洁风格", status="new"),
    },
    "expected": {"exit": 0},
    "record_asserts": "门纪律：模型拒绝跨 scope 用 covers（skill 明令：跨 scope 提炼只能 derived_from 且需确认）；report 展示拒绝或改为合规路径（专项断言）",
}

E10 = {
    "id": "E10", "layer": "L2", "title": "删除有引用的记忆",
    "transcript": [
        "记忆根在 {KIT}。删除记忆 mem-aaaa1111-0000-4000-8000-00000000000a（用户在学 Rust 那条）。",
    ],
    "seed": {
        "raw/a.md": _raw(ID_A, "learning", "用户在学 Rust", status="done"),
        "raw/b.md": _raw(ID_B, "rust-goal", "学 Rust 是为了写 CLI 工具", status="done", body="动机来自另一条记忆：mem-aaaa1111-0000-4000-8000-00000000000a（用户在学 Rust）。"),
    },
    "expected": {"exit": 0},
    "record_asserts": "删除门：a.md 被 b.md 正文引用→模型必须展示影响并确认，或如实报告有引用未删（专项断言：report 含影响说明；a.md 仍在）",
}

E11 = {
    "id": "E11", "layer": "L2", "title": "裁决翻案",
    "transcript": [
        "记忆根在 {KIT}。之前裁决过：A（用户主编辑器是 Vim）有效、B（VSCode）被拒。现在用户正式改主意了：以后用 VSCode 为主编辑器。请按规约处理这个翻案。",
    ],
    "seed": {
        "raw/a.md": _raw(ID_A, "main-editor", "用户的主编辑器是 Vim", status="done"),
        "raw/b.md": _raw(ID_B, "main-editor", "用户的主编辑器是 VSCode", status="rejected", body="review_note: 用户当时未确认\nreviewed_at: 2026-11-02"),
    },
    "expected": {"exit": 0, "records": {ID_A: {"effective": False, "exclusion_reason": "superseded"}}},
    "record_asserts": "翻案走新 source + supersedes（或 rejected 记录被新候选显式取代），不静默改旧记录字段（专项断言）",
}

E12 = {
    "id": "E12", "layer": "L2", "title": "两次编译的 diff 链",
    "transcript": [
        "记忆根在 {KIT}。第一步：编译记忆。第二步：再记一条「用户偏好浅色模式」并再编译一次。第二步的 diff 应该只包含新变化——把两次的 diff 都报告给我。",
    ],
    "seed": {"raw/a.md": _raw(ID_A, "theme", "用户偏好深色主题", status="new")},
    "expected": {"exit": 0},
    "record_asserts": "第二份 diff 含 Newly effective (1)（浅色模式），且不重复第一份内容（专项断言 diff 文件）",
}

E13 = {
    "id": "E13", "layer": "L2", "title": "批量审阅 20+ 条",
    "transcript": [
        "记忆根在 {KIT}。这里有 20 条新候选（种子已放好），请编译记忆：逐条审阅，把其中「偏好类」的 10 条标 done 生效，其余 10 条「过程记录类」标 rejected（写 review_note/reviewed_at）。完成后报告审阅结果并对账。",
    ],
    "seed": {"generated": "20 条（10 偏好 done 目标 + 10 过程 rejected 目标）——由 runner 生成"},
    "expected": {"exit": 0, "health": "ok"},
    "record_asserts": "恰 10 条 done + 10 条 rejected；diff 计数=审阅声称；无漏审（专项断言）",
}

E14 = {
    "id": "E14", "layer": "L2", "title": "审阅中断续作",
    "transcript": [
        "记忆根在 {KIT}。我上次会话审了 3 条（前 3 条已 done），剩下 4 条没审完。请继续完成审阅并编译。",
    ],
    "seed": {"generated": "7 条候选，前 3 条 done、后 4 条 new——由 runner 生成"},
    "expected": {"exit": 0, "health": "ok"},
    "record_asserts": "后 4 条全部处理（done/rejected），前 3 条不动；无重复审（专项断言）",
}
