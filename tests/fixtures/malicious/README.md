# malicious fixture）

四类恶意输入由 tests/unit/test_fields.py 内联构造：
① summary 含换行 ② 行首 `@`（import 指令注入面）③ `hongzhao:end` 标记注入 ④ 超 300 字符。
断言三件事：validate 拒绝并给出对应错误码（FIELD_NOT_SINGLE_LINE / FIELD_CONTROL_CHAR /
FIELD_TOO_LONG）；渲染层对行首 @ 与托管标记做转义（escape_render_text）；输出无内容丢失。
