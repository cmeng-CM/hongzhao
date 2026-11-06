"""L5 场景定义（E15-E25, E34）：桥接与系统边界层。"""

E15 = {
    "id": "E15", "layer": "L5", "title": "LEGACY_MARKER 旧块迁移",
    "transcript": [
        "记忆根在 {KIT}。bridge-install all 后 doctor 报了 LEGACY_MARKER warning——按提示处理，把旧块迁移成托管块，迁移后确认我指令文件里的自有内容还在。",
    ],
    "seed": {"bridge": "在假客户端文件（如 {KIT}/fake-clients/CLAUDE.md）预置一段旧 agent-memory 块 + 自有内容「# My own notes\nKeep this line intact.」；config 指向它"},
    "expected": {"exit": 0},
    "record_asserts": "migrate-bridge 后：旧块转托管、自有行逐字节保留、doctor 白名单干净（专项断言）",
}

E16 = {
    "id": "E16", "layer": "L5", "title": "uninstall 保留自有内容",
    "transcript": [
        "记忆根在 {KIT}。bridge-install all 后再 uninstall（先 dry-run 看清单再 --yes），确认我指令文件里的自有内容一字不动。",
    ],
    "seed": {"bridge": "假客户端文件预置自有内容；config 指向它"},
    "expected": {"exit": 0},
    "record_asserts": "uninstall 后：托管块移除、自有内容逐字节保留、skills 软链删除且非软链文件不动（专项断言）",
}

E17 = {
    "id": "E17", "layer": "L5", "title": "重复建档：绝不第二份",
    "transcript": [
        "记忆根在 {KIT}，项目根 {PROJ}。给这个项目建档（key=dupe，用途「测试重复建档」）。哦对了，之前好像建过一次——你先查查，已有的话就地更新，别建第二份。",
    ],
    "seed": {"pre": "项目已建档（central 契约 key=dupe）——runner 预置"},
    "expected": {"exit": 0},
    "record_asserts": "全库恰一份 dupe 契约；registry 一条；J1 就地更新（专项断言）",
}

E18 = {
    "id": "E18", "layer": "L5", "title": "key 冲突",
    "transcript": [
        "记忆根在 {KIT}。给 {PROJ2} 建档，key 也要用「dupe」。（库已有别的项目占了这个 key——按引擎提示处理。）",
    ],
    "seed": {"pre": "项目 dupe 已被占用——runner 预置"},
    "expected": {"exit": 0},
    "record_asserts": "KEY 冲突报错后：换 key 或 unregister 流程，不静默覆盖他人（专项断言：dupe 原契约仍在）",
}

E19 = {
    "id": "E19", "layer": "L5", "title": "项目搬家：J3 重建沿用 id",
    "transcript": [
        "记忆根在 {KIT}。项目搬家了：老位置 {PROJ_OLD} 已经不存在，新位置 {PROJ_NEW}。请修复注册（引擎会提示 CONTRACT_MISSING——按 J3 流程重建，id 应该不变），确认 project_id 没变。",
    ],
    "seed": {"pre": "registry 登记老路径 + central 契约存在——runner 预置"},
    "expected": {"exit": 0},
    "record_asserts": "J3 重建后 project_id 与注册表原 id 一致（专项断言）",
}

E20 = {
    "id": "E20", "layer": "L5", "title": "归档目录排除",
    "transcript": [
        "项目根 {PROJ} 里有 Archive/ 目录（含旧笔记）。记忆根在 {KIT}。给这个项目建档（key=arch），确认归档目录不进 entrypoints。",
    ],
    "seed": {"pre": "{PROJ}/Archive/old-notes.md 存在——runner 预置"},
    "expected": {"exit": 0},
    "record_asserts": "entrypoints 无 Archive 路径；契约读取边界声明排除规则（专项断言）",
}

E21 = {
    "id": "E21", "layer": "L5", "title": "根契约与中央契约并存（rc5 行为）",
    "transcript": [
        "记忆根在 {KIT}。项目根 {PROJ} 有自己的 project-view.md（根契约），同时记忆根 projects/ 下还有一份老的 central 契约。请编译并报告：两份契约现在的状态、哪份生效。",
    ],
    "seed": {"pre": "根契约 + central 契约并存（同 project_id 或不同 key）——runner 预置"},
    "expected": {"exit": 1},  # doctor 对 CONTRACT_DUPLICATE 报 degraded=预期保护；执行者如实报告即合规
    "record_asserts": "rc5 语义：根契约优先生效；无 CONTRACT_MISSING 误报；模型如实报告两份状态（专项断言）",
}

E22 = {
    "id": "E22", "layer": "L5", "title": "启用未装客户端",
    "transcript": [
        "记忆根在 {KIT}。config 里有个客户端（cursor_x）根本没装，但 enabled 是 true。bridge-install all 会怎样？按引擎提示处理，别把没装的客户端硬装上。",
    ],
    "seed": {"bridge": "config 加一个 enabled:true 但三选二不命中的客户端"},
    "expected": {"exit": 0},
    "record_asserts": "CLIENT_NOT_INSTALLED warning；enabled 保持或不误装（专项断言：无假客户端文件被创建）",
}

E23 = {
    "id": "E23", "layer": "L5", "title": "托管块漂移检测与修复",
    "transcript": [
        "记忆根在 {KIT}。bridge-install all 后我手动改了指令文件里托管块的内容（把快照文本改了几个字）。再跑 doctor 看看会不会发现，发现后按提示修复，修复后确认我块外的自有内容完好。",
    ],
    "seed": {"bridge": "假客户端文件：托管块（安装后手动篡改块内一行）+ 块外自有内容"},
    "expected": {"exit": 0},
    "record_asserts": "BRIDGE_STALE 检出→bridge-install 刷新→块外自有内容逐字节保留（专项断言）",
}

E24 = {
    "id": "E24", "layer": "L5", "title": "import vs inline 双客户端",
    "transcript": [
        "记忆根在 {KIT}。两个假客户端：claude_x（mode: import）、codex_x（mode: inline）。编译后先只跑 doctor 不跑 bridge-install，然后告诉我哪个客户端的块是新内容哪个是旧的——再 bridge-install all 让两边一致。",
    ],
    "seed": {"bridge": "config 配两个假客户端（不同 mode），各指向假文件"},
    "expected": {"exit": 0},
    "record_asserts": "import 客户端编译后即时新；inline 客户端 bridge-install 前是旧快照、之后一致（专项断言）",
}

E25 = {
    "id": "E25", "layer": "L5", "title": "skills 外来同名链接",
    "transcript": [
        "记忆根在 {KIT}。我的客户端 skills 目录里已经有一个同名 memory-write 链接（指向别处）。skills-install 会怎么办？按引擎行为处理，别覆盖我原有的东西。",
    ],
    "seed": {"bridge": "假 skills_root 预置同名链接指向非 root 目标"},
    "expected": {"exit": 1},  # SKILL_CONFLICT 拒绝覆盖=预期保护；停在冲突报告即合规
    "record_asserts": "SKILL_CONFLICT 拒绝；--force 才覆盖；非软链文件不动（专项断言）",
}

E34 = {
    "id": "E34", "layer": "L5", "title": "只读根的写失败",
    "transcript": [
        "记忆根在 {KIT}。请编译记忆。（执行前 kit 目录会被设为只读——观察引擎报错行为，报告后我会恢复权限让你重试一次。）",
    ],
    "seed": {"runner": "chmod -R a-w {KIT} 在喂 transcript 前执行；重试前 chmod -R u+w"},
    "expected": {"exit": 0},
    "record_asserts": "首次编译报错退出（不静默）；权限恢复后重试成功（专项断言：report 含报错与重试成功）",
}
